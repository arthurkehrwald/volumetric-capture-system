import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
import typing
import weakref
import aiohttp
import requests
import json
from utils import config
import tkinter as tk
from tkinter import ttk


@dataclass
class PerCamInfo:
    name: str
    ip: str
    online: bool
    focus_rating: int
    prev_rating: int
    lens_pos: float
    prev_distance: float


class Autofocus:
    def __init__(self):
        self.cam_info_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        with self.cam_info_lock:
            self.cam_info: list[PerCamInfo] = self.read_cam_info(
                config.CAMERA_LIST_FILE
            )
        self.check_cams_online_thread = threading.Thread(
            target=lambda: asyncio.run(self.check_cams_online_loop()), daemon=True
        )
        self.check_cams_online_thread.start()
        self._finalizer = weakref.finalize(
            self,
            self.cleanup,
            self.shutdown_event,
            self.check_cams_online_thread,
        )

    @staticmethod
    def cleanup(
        shutdown_event: threading.Event,
        check_cams_thread: threading.Thread,
    ):
        shutdown_event.set()
        check_cams_thread.join()

    def read_cam_info(self, file: str) -> typing.List[PerCamInfo]:
        with open(file, "r") as f:
            cams: list[dict] = json.load(f)
        return [
            PerCamInfo(
                name=cam["name"],
                ip=cam["ip"],
                online=False,
                focus_rating=0,
                prev_rating=0,
                lens_pos=cam["lens_position"],
                prev_distance=0.0,
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
        )
        table = ttk.Treeview(widget, columns=columns, show="headings")
        for col in columns:
            table.heading(col, text=col)
        table.tag_configure("offline", foreground="gray")
        table.grid(row=0, column=0, sticky="nsew")
        widget.rowconfigure(0, weight=1)
        widget.columnconfigure(0, weight=1)
        for info in self.cam_info:
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
            for i in range(len(self.cam_info)):
                self.update_table_row(table, self.cam_info[i], i)
        table.after(500, self.update_autofocus_table_loop, table)

    def get_table_values(self, info: PerCamInfo) -> typing.Tuple[str]:
        return (
            info.name,
            "Online" if info.online else "Offline",
            str(info.focus_rating),
            str(info.prev_rating),
            f"{(1 / info.lens_pos):.2f}" if info.lens_pos > 0.1 else "∞",
            f"{info.prev_distance:.2f}",
            "Click!",
            "Click!",
        )

    def update_table_row(self, table: ttk.Treeview, info: PerCamInfo, index: int):
        item = table.get_children()[index]
        table.item(
            item,
            values=self.get_table_values(info),
            tags=() if info.online else ("offline",),
        )

    def on_focus_all_clicked(self, table: ttk.Treeview):
        """Callback when Focus All button is clicked"""
        print("focus all clicked")

    def on_focus_selected_clicked(self, table: ttk.Treeview):
        """Callback when Focus Selected button is clicked"""
        print("Focus selected clicked")

    def on_verify_selected_clicked(self):
        """Callback when Verify button is clicked"""
        print("Verify clicked")

    def get_selected_cams(self, table: ttk.Treeview) -> typing.List[PerCamInfo]:
        selected_items = table.selection()
        selected_ips = [table.item(item)["values"][0] for item in selected_items]
        with self.cam_info_lock:
            return [cam for cam in self.cam_info if cam.name in selected_ips]

    def get_endpoint(self, ip: str, route: str) -> str:
        return f"http://{ip}:5000/{route}"

    async def check_cam_online(self, session: aiohttp.ClientSession, ip: str) -> bool:
        endpoint = self.get_endpoint(ip, "ping")
        try:
            async with session.get(endpoint, timeout=1) as response:
                return response.ok
        except TimeoutError:
            return False

    async def check_cams_online_loop(self):
        async with aiohttp.ClientSession() as session:
            while not self.shutdown_event.is_set():
                async with asyncio.TaskGroup() as tg:
                    tasks = [
                        (cam, tg.create_task(self.check_cam_online(session, cam.ip)))
                        for cam in self.cam_info
                    ]

                with self.cam_info_lock:
                    for cam, task in tasks:
                        cam.online = task.result()

    def autofocus(self, camera: PerCamInfo):
        endpoint = self.get_endpoint(camera.ip, "autofocus")
        try:
            response = requests.get(endpoint, timeout=20)
            json = response.json()
            lens_pos = json["lens_pos"]
            rating = json["rating"]
            with self.cam_info_lock:
                camera.focus_rating = rating
                camera.lens_pos = lens_pos
            store_lens_pos(camera.ip, lens_pos)
        except requests.exceptions.Timeout:
            return  # TODO


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
