import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
import random
import threading
import typing
import weakref
import aiohttp
import json
from utils import config
import tkinter as tk
from tkinter import ttk

FOCUS_RATING_FOR_MAX_SCORE = 14000


@dataclass
class CamInfo:
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
        self.cam_info_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        with self.cam_info_lock:
            self.cameras: list[CamInfo] = self.read_cam_info(config.CAMERA_LIST_FILE)
        self.check_cams_online_thread = threading.Thread(
            target=lambda: asyncio.run(self.check_cams_connection()), daemon=True
        )
        self.check_cams_online_thread.start()
        self.thread_pool = ThreadPoolExecutor()
        self._finalizer = weakref.finalize(
            self,
            self.cleanup,
            self.shutdown_event,
            self.check_cams_online_thread,
            self.thread_pool,
        )
        self.thread_pool.submit(
            lambda: asyncio.run(
                self.request_from_cameras(
                    self.cameras,
                    self.build_rate_lens_pos_response,
                    self.handle_rate_lens_pos_response,
                    "Focus rating",
                )
            )
        )

    @staticmethod
    def cleanup(
        shutdown_event: threading.Event,
        check_cams_thread: threading.Thread,
        thread_pool: ThreadPoolExecutor,
    ):
        shutdown_event.set()
        check_cams_thread.join()
        thread_pool.shutdown()

    def read_cam_info(self, file: str) -> typing.List[CamInfo]:
        with open(file, "r") as f:
            cams: list[dict] = json.load(f)
        return [
            CamInfo(
                name=cam["name"],
                ip=cam["ip"],
                connected=False,
                focus_rating=random.random() * FOCUS_RATING_FOR_MAX_SCORE,
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
            "Focus Rating",
            "Prev. Focus Rating",
            "Focus Distance (m)",
            "Prev. Focus Distance (m)",
            "Message",
        )
        table = ttk.Treeview(widget, columns=columns, show="headings")
        for col in columns:
            table.heading(col, text=col)
        table.column(2, anchor="e")
        table.column(3, anchor="e")
        table.column(4, anchor="e")
        table.column(5, anchor="e")
        table.tag_configure("offline", foreground="gray")
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

        bottom_btns = tk.Frame(widget)
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
        focus_all_btn.pack(side="left", fill="both", expand=True, padx=2)
        focus_selected_btn.pack(side="left", fill="both", expand=True, padx=2)
        verify_selected_btn.pack(side="left", fill="both", expand=True, padx=2)

        self.update_autofocus_table_loop(table)

    def update_autofocus_table_loop(self, table: ttk.Treeview):
        if self.shutdown_event.is_set():
            return
        with self.cam_info_lock:
            for i in range(len(self.cameras)):
                self.update_table_row(table, self.cameras[i], i)
        table.after(500, self.update_autofocus_table_loop, table)

    def lens_pos_to_focus_dist_str(self, lens_pos: float) -> str:
        return f"{(1 / lens_pos):.2f}" if lens_pos > 0.1 else "∞"

    def focus_rating_to_display_value(self, rating: int) -> str:
        return str(math.ceil(rating / FOCUS_RATING_FOR_MAX_SCORE * 10))

    def update_table_row(self, table: ttk.Treeview, cam: CamInfo, index: int):
        item = table.get_children()[index]
        table.item(
            item,
            values=self.get_table_values(cam),
            tags=() if cam.connected else ("offline",),
        )

    def get_table_values(self, cam: CamInfo) -> typing.Tuple[str]:
        return (
            cam.name,
            "Connected" if cam.connected else "Not Connected",
            self.focus_rating_to_display_value(cam.focus_rating),
            self.focus_rating_to_display_value(cam.prev_rating),
            self.lens_pos_to_focus_dist_str(cam.lens_pos),
            self.lens_pos_to_focus_dist_str(cam.prev_lens_pos),
            cam.message,
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
                )
            )
        )

    def on_verify_selected_clicked(self):
        """Callback when Verify button is clicked"""
        print("Verify clicked")

    def get_selected_cams(self, table: ttk.Treeview) -> typing.List[CamInfo]:
        selected_items = table.selection()
        selected_ips = [table.item(item)["values"][0] for item in selected_items]
        with self.cam_info_lock:
            return [cam for cam in self.cameras if cam.name in selected_ips]

    def get_endpoint(
        self, ip: str, route: str, variable: typing.Optional[str] = None
    ) -> str:
        endpoint = f"http://{ip}:5000/{route}"
        return endpoint if variable is None else endpoint + "/" + variable

    async def check_cam_connection(
        self, session: aiohttp.ClientSession, ip: str
    ) -> bool:
        endpoint = self.get_endpoint(ip, "ping")
        try:
            async with session.get(endpoint, timeout=1) as response:
                return response.ok
        except TimeoutError:
            return False
        except Exception as e:
            print(f"Unknown exception while pinging camera: {e}")
            return False

    async def check_cams_connection(self):
        async with aiohttp.ClientSession() as session:
            while not self.shutdown_event.is_set():
                async with asyncio.TaskGroup() as tg:
                    tasks = [
                        (
                            cam,
                            tg.create_task(self.check_cam_connection(session, cam.ip)),
                        )
                        for cam in self.cameras
                    ]

                with self.cam_info_lock:
                    for cam, task in tasks:
                        cam.connected = task.result()

    async def request_from_cameras(
        self,
        cams: typing.List[CamInfo],
        url_builder: typing.Callable[[CamInfo], str],
        response_handler: typing.Callable[[typing.Dict, CamInfo], None],
        action_name: str,
    ):
        async with aiohttp.ClientSession() as session:
            async with asyncio.TaskGroup() as tg:
                for cam in cams:
                    tg.create_task(
                        self.request_from_camera(
                            session, cam, url_builder, response_handler, action_name
                        )
                    )

    async def request_from_camera(
        self,
        session: aiohttp.ClientSession,
        cam: CamInfo,
        url_builder: typing.Callable[[CamInfo], str],
        response_handler: typing.Callable[[typing.Dict, CamInfo], None],
        action_name: str,
    ):
        with self.cam_info_lock:
            cam.message = f"{action_name} in progress..."
        endpoint = url_builder(cam)
        try:
            async with session.get(endpoint, timeout=10) as response:
                json = await response.json()
                response_handler(json, cam)
        except TimeoutError:
            with self.cam_info_lock:
                cam.message = f"{action_name} failed: No connection"
        except aiohttp.ClientConnectionError:
            with self.cam_info_lock:
                cam.message = f"{action_name} failed: Remote script not running"
        except (aiohttp.ContentTypeError, KeyError):
            with self.cam_info_lock:
                cam.message = (
                    f"{action_name} failed: Malformed response (Version mismatch?)"
                )
        except Exception as ex:
            print(f"Unknown exception during {action_name}: {ex}")
            with self.cam_info_lock:
                cam.message = f"{action_name} failed: Unknown reason"

    def build_autofocus_url(self, cam: CamInfo) -> str:
        return self.get_endpoint(cam.ip, "autofocus")

    def build_rate_lens_pos_response(self, cam: CamInfo) -> str:
        return self.get_endpoint(cam.ip, "rate-lens-pos", str(cam.lens_pos))

    def handle_autofocus_response(self, response: typing.Dict, cam: CamInfo):
        lens_pos = response["lens_pos"]
        rating = response["rating"]
        with self.cam_info_lock:
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
        with self.cam_info_lock:
            cam.focus_rating = rating
            cam.message = (
                "Focus rating completed successfully."
                if rating != 0
                else "Focus rating failed: No markers recognized"
            )


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
