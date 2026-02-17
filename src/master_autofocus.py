import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import threading
import typing
import weakref
import aiohttp
import json
from utils import config
import tkinter as tk
from tkinter import ttk

FOCUS_RATING_FOR_MAX_SCORE = 14000
MAX_NUM_STARS = 5

BLACK_FG_TAG = "black_fg"
GREY_FG_TAG = "grey_fg"
RED_FG_TAG = "dark_red_bg"
WHITE_BG_TAG = "white_bg"
GREY_BG_TAG = "grey_bg"


@dataclass
class CamInfo:
    lock: threading.Lock
    name: str
    ip: str
    connected: bool
    focus_rating: int
    prev_rating: int
    lens_pos: float
    prev_lens_pos: float
    message: str


class Autofocus:
    def __init__(self):
        self.all_cameras_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        with self.all_cameras_lock:
            self.cameras: list[CamInfo] = self.read_cam_info(config.CAMERA_LIST_FILE)
        self.ping_cams_thread = threading.Thread(
            target=lambda: asyncio.run(self.check_cams_connection()), daemon=True
        )
        self.ping_cams_thread.start()
        self.thread_pool = ThreadPoolExecutor()
        self._finalizer = weakref.finalize(
            self,
            self.cleanup,
            self.shutdown_event,
            self.ping_cams_thread,
            self.thread_pool,
        )
        self.thread_pool.submit(
            lambda: asyncio.run(
                self.request_from_cameras(
                    self.cameras,
                    self.build_rate_lens_pos_url,
                    self.handle_rate_lens_pos_response,
                    "Focus rating",
                    timeout=3,
                    set_cam_message=True,
                    delay=5,
                )
            )
        )

    @staticmethod
    def cleanup(
        shutdown_event: threading.Event,
        ping_cams_thread: threading.Thread,
        thread_pool: ThreadPoolExecutor,
    ):
        shutdown_event.set()
        ping_cams_thread.join()
        thread_pool.shutdown()

    def read_cam_info(self, file: str) -> typing.List[CamInfo]:
        with open(file, "r") as f:
            cams: list[dict] = json.load(f)
        return [
            CamInfo(
                lock=threading.Lock(),
                name=cam["name"],
                ip=cam["ip"],
                connected=False,
                focus_rating=0,
                prev_rating=0,
                lens_pos=cam["lens_position"],
                prev_lens_pos=0.0,
                message="",
            )
            for cam in cams
        ]

    def create_gui(self, widget: ttk.Widget):
        columns = (
            "Camera",
            "Status",
            "Message",
            "Focus Rating",
            "Prev. Focus Rating",
            "Focus Distance (m)",
            "Prev. Focus Distance (m)",
        )
        table_style = ttk.Style()
        table_style_name = "Edge.Treeview"
        table_style.layout(
            table_style_name,
            [("Edge.Treeview.treearea", {"sticky": "nsew"})],
        )
        table_style.configure(table_style_name, highlightthickness=0, bd=0)
        table = ttk.Treeview(
            widget, columns=columns, show="headings", style="Edge.Treeview"
        )
        for col in columns:
            table.heading(col, text=col)
        table.column(5, anchor="e")
        table.column(6, anchor="e")
        table.tag_configure(BLACK_FG_TAG, foreground="#000000")
        table.tag_configure(GREY_FG_TAG, foreground="#8B8B8B")
        table.tag_configure(RED_FG_TAG, foreground="#e90f0f")
        table.tag_configure(WHITE_BG_TAG, background="#ffffff")
        table.tag_configure(GREY_BG_TAG, background="#e8e8e8")
        table.grid(row=0, column=0, sticky="nsew")
        widget.rowconfigure(0, weight=1)
        widget.columnconfigure(0, weight=1)
        for info in self.cameras:
            table.insert(
                parent="",
                index="end",
                values=self.get_table_values(info),
            )

        scrollbar = ttk.Scrollbar(
            widget,
            orient="vertical",
            command=table.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        table.configure(yscroll=scrollbar.set)

        bottom_btns = tk.Frame(widget, bg="#ebebeb")
        focus_all_btn = ttk.Button(
            bottom_btns,
            text="Focus All",
            command=lambda: self.on_focus_all_clicked(table),
        )
        focus_selected_btn = ttk.Button(
            bottom_btns,
            text="Focus Selected",
            command=lambda: self.on_focus_selected_clicked(table),
        )
        verify_selected_btn = ttk.Button(
            bottom_btns,
            text="Verify Selected",
            command=lambda: self.on_verify_selected_clicked(table),
        )
        bottom_btns.grid(row=1, column=0, columnspan=2, sticky="ew")
        padding = 4
        focus_all_btn.pack(side="left", fill="both", expand=True, padx=(0, padding))
        focus_selected_btn.pack(side="left", fill="both", expand=True, padx=padding)
        verify_selected_btn.pack(
            side="left", fill="both", expand=True, padx=(padding, 0)
        )
        self.update_autofocus_table_loop(table)

    def update_autofocus_table_loop(self, table: ttk.Treeview):
        if self.shutdown_event.is_set():
            return
        for i in range(len(self.cameras)):
            with self.cameras[i].lock:
                self.update_table_row(table, self.cameras[i], i)
        table.after(500, self.update_autofocus_table_loop, table)

    def lens_pos_to_focus_dist_str(self, lens_pos: float) -> str:
        return f"{(1 / lens_pos):.2f}" if lens_pos > 0.1 else "∞"

    def focus_rating_to_display_value(self, rating: int) -> str:
        if rating == 0:
            return "None"
        num_stars = self.get_star_rating(rating)
        display_value = ""
        for i in range(num_stars):
            display_value += "★"
        for i in range(MAX_NUM_STARS - num_stars):
            display_value += "☆"
        return display_value

    def get_star_rating(self, rating: int) -> int:
        return math.ceil(rating / float(FOCUS_RATING_FOR_MAX_SCORE) * MAX_NUM_STARS)

    def get_fg_tag(self, rating: int, is_connected: bool) -> str:
        if not is_connected:
            return GREY_FG_TAG
        is_ok_rating = self.get_star_rating(rating) / MAX_NUM_STARS >= 0.5
        return BLACK_FG_TAG if is_ok_rating else RED_FG_TAG

    def update_table_row(self, table: ttk.Treeview, cam: CamInfo, index: int):
        item = table.get_children()[index]
        is_even_row = index % 2 == 0
        table.item(
            item,
            values=self.get_table_values(cam),
            tags=(
                WHITE_BG_TAG if is_even_row else GREY_BG_TAG,
                self.get_fg_tag(cam.focus_rating, cam.connected),
            ),
        )

    def get_table_values(self, cam: CamInfo) -> typing.Tuple[str]:
        return (
            cam.name,
            "Connected" if cam.connected else "Not Connected",
            cam.message,
            self.focus_rating_to_display_value(cam.focus_rating),
            self.focus_rating_to_display_value(cam.prev_rating),
            self.lens_pos_to_focus_dist_str(cam.lens_pos),
            self.lens_pos_to_focus_dist_str(cam.prev_lens_pos),
        )

    def on_focus_all_clicked(self, table: ttk.Treeview):
        """Callback when Focus All button is clicked"""
        print("focus all clicked")

    def on_focus_selected_clicked(self, table: ttk.Treeview):
        """Callback when Focus Selected button is clicked"""
        selected = self.get_selected_cams(table)
        self.thread_pool.submit(
            lambda: asyncio.run(
                self.request_from_cameras(
                    selected,
                    self.build_autofocus_url,
                    self.handle_autofocus_response,
                    "Autofocus",
                    timeout=10,
                    set_cam_message=True,
                )
            )
        )

    def on_verify_selected_clicked(self):
        """Callback when Verify button is clicked"""
        print("Verify clicked")

    def get_selected_cams(self, table: ttk.Treeview) -> typing.List[CamInfo]:
        selected_items = table.selection()
        selected_ips = [table.item(item)["values"][0] for item in selected_items]
        with self.all_cameras_lock:
            return [cam for cam in self.cameras if cam.name in selected_ips]

    def get_endpoint(
        self, ip: str, route: str, variable: typing.Optional[str] = None
    ) -> str:
        endpoint = f"http://{ip}:5000/{route}"
        return endpoint if variable is None else endpoint + "/" + variable

    async def check_cams_connection(self):
        async with aiohttp.ClientSession() as session:
            while not self.shutdown_event.is_set():
                async with asyncio.TaskGroup() as tg:
                    for cam in self.cameras:
                        tg.create_task(
                            self.request_from_camera(
                                session,
                                cam,
                                self.build_ping_url,
                                self.handle_ping_response,
                                "Ping",
                                timeout=1,
                                set_cam_message=False,
                            )
                        )

    async def request_from_cameras(
        self,
        cams: typing.List[CamInfo],
        url_builder: typing.Callable[[CamInfo], str],
        response_handler: typing.Callable[[typing.Dict, CamInfo], None],
        action_name: str,
        timeout: float,
        set_cam_message: bool,
        delay: float | None = 0.0,
    ):
        await asyncio.sleep(delay)
        async with aiohttp.ClientSession() as session:
            async with asyncio.TaskGroup() as tg:
                for cam in cams:
                    tg.create_task(
                        self.request_from_camera(
                            session,
                            cam,
                            url_builder,
                            response_handler,
                            action_name,
                            timeout,
                            set_cam_message,
                        )
                    )

    async def request_from_camera(
        self,
        session: aiohttp.ClientSession,
        cam: CamInfo,
        url_builder: typing.Callable[[CamInfo], str],
        response_handler: typing.Callable[[typing.Dict, CamInfo], None],
        action_name: str,
        timeout: float,
        set_cam_message: bool,
    ):
        if set_cam_message:
            with cam.lock:
                cam.message = f"{action_name} in progress..."
        endpoint = url_builder(cam)
        error_msg = None
        try:
            async with session.get(endpoint, timeout=timeout) as response:
                json = await response.json()
                response_handler(json, cam)
        except TimeoutError:
            error_msg = f"{action_name} failed: No connection"
        except aiohttp.ClientConnectionError:
            error_msg = f"{action_name} failed: Remote script not running"
        except (aiohttp.ContentTypeError, KeyError):
            error_msg = f"{action_name} failed: Malformed response (Version mismatch?)"
        except Exception as ex:
            # Can't throw here because that would cancel running requests to all other cameras
            # Just print instead
            print(f"Unknown exception during {action_name}: {ex}")
            error_msg = f"{action_name} failed: Unknown reason"
        if set_cam_message and error_msg is not None:
            with cam.lock:
                cam.message = error_msg

    def build_autofocus_url(self, cam: CamInfo) -> str:
        with cam.lock:
            ip = cam.ip
        return self.get_endpoint(ip, "autofocus")

    def build_rate_lens_pos_url(self, cam: CamInfo) -> str:
        with cam.lock:
            ip = cam.ip
        return self.get_endpoint(ip, "rate-lens-pos", str(cam.lens_pos))

    def build_ping_url(self, cam: CamInfo) -> str:
        with cam.lock:
            ip = cam.ip
        return self.get_endpoint(ip, "ping")

    def handle_autofocus_response(self, response: typing.Dict, cam: CamInfo):
        lens_pos = response["lens_pos"]
        rating = response["rating"]
        with cam.lock:
            cam.prev_rating = cam.focus_rating
            cam.prev_lens_pos = cam.lens_pos
            cam.focus_rating = rating
            cam.lens_pos = lens_pos
            cam.message = (
                "Autofocus completed successfully."
                if rating != 0
                else "Autofocus failed: No markers recognized"
            )

    def handle_rate_lens_pos_response(self, response: typing.Dict, cam: CamInfo):
        rating = response["rating"]
        with cam.lock:
            cam.focus_rating = rating
            cam.message = (
                "Focus rating completed successfully."
                if rating != 0
                else "Focus rating failed: No markers recognized"
            )

    def handle_ping_response(self, response: typing.Dict, cam: CamInfo):
        ok = response["status"] == "ok"
        with cam.lock:
            cam.connected = ok


def store_lens_pos(ip: str, lens_pos: float):
    with open(config.CAMERA_LIST_FILE, "r") as f:
        cam_list = json.load(f)

    for camera in cam_list:
        if camera["ip"] == ip:
            camera["lens_position"] = lens_pos
            break

    with open(config.CAMERA_LIST_FILE, "w") as f:
        json.dump(cam_list, f, indent=4)


def get_stored_lens_pos(ip: str) -> float:
    with open(config.CAMERA_LIST_FILE, "r") as f:
        cam_list = json.load(f)

    for camera in cam_list:
        if camera["ip"] == ip:
            return camera["lens_position"]


if __name__ == "__main__":
    autofocus = Autofocus()
    root = tk.Tk()
    autofocus.create_gui(root)
    root.mainloop()
