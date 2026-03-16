import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import enum
import math
import threading
import typing
import weakref
import aiohttp
import json
from utils import config
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
import io

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


class RemoteError(enum.Enum):
    NoError = 0
    NoMarkerFound = 1
    EncodeFail = 2


class PhotoType(enum.Enum):
    FullFrame = 0
    MarkerCrop = 1


def get_error_msg(error: RemoteError) -> str:
    if error == RemoteError.NoError:
        return "No error."
    elif error == RemoteError.NoMarkerFound:
        return "No marker found."
    elif error == RemoteError.EncodeFail:
        return "Failed to encode image."


def handle_request_errors(action_name: str, set_cam_message: bool = True):
    def decorator[T, **P](
        f: typing.Callable[
            typing.Concatenate[typing.Any, CamInfo, P], typing.Awaitable[T]
        ],
    ) -> typing.Callable[
        typing.Concatenate[typing.Any, CamInfo, P], typing.Awaitable[T]
    ]:
        async def inner(
            self: typing.Any, cam: CamInfo, *args: P.args, **kwargs: P.kwargs
        ) -> T:
            if set_cam_message:
                with cam.lock:
                    cam.message = f"{action_name} in progress..."
            error_msg = None
            try:
                return await f(self, cam, *args, **kwargs)
            except TimeoutError:
                error_msg = f"{action_name} failed: No connection"
            except aiohttp.ClientConnectionError:
                error_msg = f"{action_name} failed: Remote script not running"
            except (aiohttp.ContentTypeError, KeyError):
                error_msg = (
                    f"{action_name} failed: Malformed response (Version mismatch?)"
                )
            except Exception as ex:
                # Can't throw here because that would cancel running requests to all other cameras
                # Just print instead
                print(f"Unknown exception during {action_name}: {ex}")
                error_msg = f"{action_name} failed: Unknown reason"
            if set_cam_message and error_msg is not None:
                with cam.lock:
                    cam.message = error_msg

        return inner

    return decorator


class Autofocus:
    def __init__(self):
        self.shutdown_event = threading.Event()
        self.cameras: list[CamInfo] = self.read_cam_info(config.CAMERA_LIST_FILE)
        self.has_unsaved_changes = False
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
                self.request_from_cameras(self.cameras, self.rate_lens_pos, delay=5)
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

    def on_window_close(self) -> bool:
        if self.has_unsaved_changes:
            return self.show_save_popup()
        return True

    def show_save_popup(self) -> bool:
        """
        Show a popup asking whether to save changes.
        Blocks until the user makes a choice.
        Returns True if user wants to save or discard (proceed with close).
        Returns False if user cancels (don't close).
        """
        result = messagebox.askyesnocancel(
            "Unsaved Changes",
            "You have unsaved focus settings. Do you want to save them?",
        )

        if result is None:  # Cancel button
            return False
        elif result is True:  # Yes button - Save
            self.write_all_lens_positions()
            return True
        else:  # No button - Discard
            return True

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
                prev_lens_pos=-1,
                message="",
            )
            for cam in cams
        ]

    def write_all_lens_positions(self):
        with open(config.CAMERA_LIST_FILE, "r") as f:
            cameras_json_list = json.load(f)

        for cam in self.cameras:
            with cam.lock:
                for camera_json_dict in cameras_json_list:
                    if camera_json_dict["ip"] == cam.ip:
                        camera_json_dict["lens_position"] = cam.lens_pos
                        break

        with open(config.CAMERA_LIST_FILE, "w") as f:
            json.dump(cameras_json_list, f, indent=4)

        self.set_has_unsaved_changes(False)

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
        table.column(2, width=400)
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
        self.focus_selected_btn = ttk.Button(
            bottom_btns,
            text="Focus Selected",
            command=lambda: self.on_focus_selected_clicked(table),
            state="disabled",
        )
        self.rate_lens_pos_btn = ttk.Button(
            bottom_btns,
            text="Rate current lens pos",
            command=lambda: self.on_rate_lens_pos_clicked(table),
            state="disabled",
        )
        self.compare_before_after_btn = ttk.Button(
            bottom_btns,
            text="Compare Before/After Pictures",
            command=lambda: self.on_before_after_clicked(table),
            state="disabled",
        )
        self.show_photo_btn = ttk.Button(
            bottom_btns,
            text="Show Photo",
            command=lambda: self.on_show_photo_btn_clicked(table),
            state="disabled",
        )
        self.save_btn = ttk.Button(
            bottom_btns, text="Save", command=self.on_save_clicked, state="disabled"
        )
        bottom_btns.grid(row=1, column=0, columnspan=2, sticky="ew")
        padding = 4
        focus_all_btn.pack(side="left", fill="both", expand=True, padx=(0, padding))
        self.focus_selected_btn.pack(
            side="left", fill="both", expand=True, padx=padding
        )
        self.rate_lens_pos_btn.pack(side="left", fill="both", expand=True, padx=padding)
        self.compare_before_after_btn.pack(
            side="left", fill="both", expand=True, padx=padding
        )
        self.show_photo_btn.pack(side="left", fill="both", expand=True, padx=padding)
        self.save_btn.pack(side="left", fill="both", expand=True, padx=(padding, 0))

        # Bind selection change event to update button states
        table.bind("<<Change>>", lambda e: self.on_table_selection(table))

        self.update_autofocus_table_loop(table)

    def update_autofocus_table_loop(self, table: ttk.Treeview):
        if self.shutdown_event.is_set():
            return
        for i in range(len(self.cameras)):
            with self.cameras[i].lock:
                self.update_table_row(table, self.cameras[i], i)
        table.after(500, self.update_autofocus_table_loop, table)

    def lens_pos_to_focus_dist_str(self, lens_pos: float) -> str:
        if lens_pos < 0:
            return "-"
        if lens_pos < 0.05:
            return "∞"
        return f"{(1 / lens_pos):.2f}"

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
        return min(
            MAX_NUM_STARS,
            math.ceil(rating / float(FOCUS_RATING_FOR_MAX_SCORE) * MAX_NUM_STARS),
        )

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
        # Update button states if selection changed
        self.on_table_selection(table)

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
        self.thread_pool.submit(
            lambda: asyncio.run(self.request_from_cameras(self.cameras, self.autofocus))
        )

    def on_focus_selected_clicked(self, table: ttk.Treeview):
        """Callback when Focus Selected button is clicked"""
        selected = self.get_selected_cams(table)
        self.thread_pool.submit(
            lambda: asyncio.run(self.request_from_cameras(selected, self.autofocus))
        )

    def on_table_selection(self, table: ttk.Treeview):
        """Enable or disable buttons based on table selection."""
        selected_cams = self.get_selected_cams(table)
        self.focus_selected_btn.config(
            state="normal" if len(selected_cams) > 0 else "disabled"
        )
        self.rate_lens_pos_btn.config(
            state="normal" if len(selected_cams) > 0 else "disabled"
        )
        can_compare_before_after = (
            len(selected_cams) == 1
            and selected_cams[0].prev_lens_pos > 0
            and selected_cams[0].lens_pos > 0
        )
        self.compare_before_after_btn.config(
            state="normal" if can_compare_before_after else "disabled"
        )
        self.show_photo_btn.config(
            state="normal" if len(selected_cams) == 1 else "disabled"
        )

    def on_before_after_clicked(self, table: ttk.Treeview):
        """Callback when Verify button is clicked"""
        selected = self.get_selected_cams(table)
        if not selected:
            return
        cam = selected[0]
        with cam.lock:
            if cam.prev_lens_pos < 0 or cam.lens_pos < 0:
                return
        self.thread_pool.submit(lambda: asyncio.run(self.compare_before_after(cam)))

    def on_rate_lens_pos_clicked(self, table: ttk.Treeview):
        selected = self.get_selected_cams(table)
        self.thread_pool.submit(
            lambda: asyncio.run(self.request_from_cameras(selected, self.rate_lens_pos))
        )

    def on_show_photo_btn_clicked(self, table: ttk.Treeview):
        selected = self.get_selected_cams(table)
        if not selected:
            return
        cam = selected[0]
        self.thread_pool.submit(lambda: asyncio.run(self.take_photo(cam)))

    def on_save_clicked(self):
        self.write_all_lens_positions()

    def set_has_unsaved_changes(self, value: bool):
        self.has_unsaved_changes = value
        self.save_btn.configure(
            state="normal" if self.has_unsaved_changes else "disabled"
        )

    def get_selected_cams(self, table: ttk.Treeview) -> typing.List[CamInfo]:
        selected_items = table.selection()
        selected_ips = [table.item(item)["values"][0] for item in selected_items]
        return [cam for cam in self.cameras if cam.name in selected_ips]

    def lens_pos_to_url_param(self, lens_pos: float) -> str:
        return str(round(max(0, min(100, lens_pos)), 3))

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
                        tg.create_task(self.ping(cam, session))

    async def request_from_cameras(
        self,
        cams: typing.List[CamInfo],
        request_func: typing.Callable[
            [CamInfo, aiohttp.ClientSession], typing.Awaitable
        ],
        delay: float | None = 0.0,
    ):
        await asyncio.sleep(delay)
        async with aiohttp.ClientSession() as session:
            async with asyncio.TaskGroup() as tg:
                for cam in cams:
                    tg.create_task(request_func(cam, session))

    @handle_request_errors("Before/after photos")
    async def compare_before_after(self, cam: CamInfo):
        with cam.lock:
            ip = cam.ip
            before_pos = cam.prev_lens_pos
            after_pos = cam.lens_pos
        async with aiohttp.ClientSession() as session:
            before_err, before_pic = await self.try_get_photo(
                session, ip, PhotoType.MarkerCrop, before_pos, resize_to=(640, 640)
            )
            after_err, after_pic = await self.try_get_photo(
                session, ip, PhotoType.MarkerCrop, after_pos, resize_to=(640, 640)
            )
        if before_err != RemoteError.NoError or after_err != RemoteError.NoError:
            err = before_err if before_err != RemoteError.NoError else after_err
            with cam.lock:
                cam.message = f"Before/after comparison failed: {get_error_msg(err)}"
            return
        with cam.lock:
            cam.message = "Before/after comparison completed successfully"
        self.compare_before_after_btn.after(
            0, self.show_before_after_popup, before_pic, after_pic, cam
        )

    async def try_get_photo(
        self,
        session: aiohttp.ClientSession,
        ip: str,
        type: PhotoType,
        lens_pos: float,
        resize_to: typing.Tuple[int, int],
    ) -> typing.Tuple[RemoteError, ImageTk.PhotoImage | None]:
        endpoint = self.get_endpoint(
            ip,
            "marker-photo" if type == PhotoType.MarkerCrop else "photo",
            self.lens_pos_to_url_param(lens_pos),
        )
        async with session.get(endpoint, timeout=2.0) as response:
            content_type = response.content_type
            if content_type and "image" in content_type:
                image_bytes = await response.read()
                image = Image.open(io.BytesIO(image_bytes))
            elif content_type and "json" in content_type:
                response_json = await response.json()
                error = RemoteError(response_json["error_code"])
                return error, None
            else:
                raise aiohttp.ContentTypeError(response.request_info, (response))
        image = image.resize(resize_to)
        photo_image = ImageTk.PhotoImage(image)
        return RemoteError.NoError, photo_image

    def show_before_after_popup(
        self, before: ImageTk.PhotoImage, after: ImageTk.PhotoImage, cam: CamInfo
    ):
        popup = tk.Toplevel()
        popup.title(f"Photo - {cam.name}")
        popup.geometry("800x800")

        notebook = ttk.Notebook(popup)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Before tab
        before_frame = tk.Frame(notebook)
        before_label = tk.Label(before_frame, image=before)
        before_label.image = before  # Prevent garbage collection
        before_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        notebook.add(before_frame, text="Before")

        # After tab
        after_frame = tk.Frame(notebook)
        after_label = tk.Label(after_frame, image=after)
        after_label.image = after  # Prevent garbage collection
        after_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        notebook.add(after_frame, text="After")

    @handle_request_errors("Autofocus")
    async def autofocus(self, cam: CamInfo, session: aiohttp.ClientSession):
        endpoint = self.get_endpoint(cam.ip, "autofocus")
        async with session.get(endpoint, timeout=10) as response:
            response_json = await response.json()
        lens_pos = response_json["lens_pos"]
        rating = response_json["rating"]
        error = RemoteError(response_json["error_code"])
        if error == RemoteError.NoError:
            with cam.lock:
                cam.prev_rating = cam.focus_rating
                cam.prev_lens_pos = cam.lens_pos
                cam.focus_rating = rating
                cam.lens_pos = lens_pos
                cam.message = "Autofocus completed successfully."
            self.set_has_unsaved_changes(True)
        else:
            with cam.lock:
                cam.message = f"Autofocus failed: {get_error_msg(error)}"

    @handle_request_errors("Rate lens pos")
    async def rate_lens_pos(self, cam: CamInfo, session: aiohttp.ClientSession):
        endpoint = self.get_endpoint(
            cam.ip, "rate-lens-pos", self.lens_pos_to_url_param(cam.lens_pos)
        )
        async with session.get(endpoint, timeout=3) as response:
            response_json = await response.json()
        rating = response_json["rating"]
        error = RemoteError(response_json["error_code"])
        with cam.lock:
            cam.focus_rating = rating
            cam.message = (
                "Focus rating completed successfully."
                if error == RemoteError.NoError
                else f"Focus rating failed: {get_error_msg(error)}"
            )

    @handle_request_errors("Ping", False)
    async def ping(self, cam: CamInfo, session: aiohttp.ClientSession):
        endpoint = self.get_endpoint(cam.ip, "ping")
        async with session.get(endpoint, timeout=1) as response:
            response_json = await response.json()
        ok = RemoteError(response_json["error_code"]) == RemoteError.NoError
        with cam.lock:
            cam.connected = ok

    @handle_request_errors("Take photo")
    async def take_photo(self, cam: CamInfo):
        """Display the photo in a tkinter popup window"""
        with cam.lock:
            ip = cam.ip
            lens_pos = cam.lens_pos
        async with aiohttp.ClientSession() as session:
            error, pic = await self.try_get_photo(
                session, ip, PhotoType.FullFrame, lens_pos, resize_to=(1280, 720)
            )
        if error != RemoteError.NoError:
            with cam.lock:
                cam.message = f"Photo failed: {get_error_msg(error)}"
            return
        with cam.lock:
            cam.message = "Photo completed successfully."
        self.show_photo_btn.after(0, self.show_photo_popup, pic, cam)

    def show_photo_popup(self, photo: ImageTk.PhotoImage, cam: CamInfo):
        # Create popup window
        popup = tk.Toplevel()
        popup.title(f"Photo - {cam.name}")
        popup.geometry("1280x720")
        # Create label with image
        label = tk.Label(popup, image=photo)
        label.image = photo  # Keep a reference to prevent garbage collection
        label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)


if __name__ == "__main__":
    autofocus = Autofocus()
    root = tk.Tk()
    autofocus.create_gui(root)
    root.mainloop()
