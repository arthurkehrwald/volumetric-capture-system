from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time
import typing
import requests
from utils import launcher
import json
from utils import config
from tkinter import ttk
import tkinter as tk


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
        self.thread_pool = ThreadPoolExecutor()
        with self.cam_info_lock:
            self.cam_info: list[PerCamInfo] = self.read_cam_info(
                config.CAMERA_LIST_FILE
            )

    def on_closing(self):
        self.shutdown_event.set()
        self.thread_pool.shutdown()

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
            "Focus",
            "Verify",
        )
        table = ttk.Treeview(widget, columns=columns, show="headings")
        for col in columns:
            table.heading(col, text=col)

        # Configure tags for status colors
        table.tag_configure("offline", foreground="gray")

        scrollbar = ttk.Scrollbar(widget, orient="vertical", command=table.yview)
        table.configure(yscroll=scrollbar.set)
        focus_all_btn = ttk.Button(widget, text="Focus All")
        table.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        focus_all_btn.grid(row=1, column=0, columnspan=2, sticky="ew")
        widget.rowconfigure(0, weight=1)
        widget.columnconfigure(0, weight=1)
        for info in self.cam_info:
            table.insert(
                parent="",
                index="end",
                values=self.get_table_values(info),
            )
        
        # Bind click events for Focus and Verify columns
        table.bind("<Button-1>", lambda e: self.on_table_click(table, e, columns))
        
        self.update_autofocus_table_loop(table)

    def update_autofocus_table_loop(self, table: ttk.Treeview):
        if self.shutdown_event.is_set():
            return
        with self.cam_info_lock:
            for i in range(len(self.cam_info)):
                self.update_table_row(table, self.cam_info[i], i)
            for info in self.cam_info:
                future = self.thread_pool.submit(self.check_cam_online, info.ip)
                future.add_done_callback(self.check_cam_online_callback)
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

    def on_table_click(self, table: ttk.Treeview, event, columns: tuple):
        """Handle clicks on table cells"""
        region = table.identify_region(event.x, event.y)
        if region != "cell":
            return
        
        row = table.identify_row(event.y)
        col = table.identify_column(event.x)
        
        if not row or not col:
            return
        
        col_index = int(col[1:]) - 1
        col_name = columns[col_index] if col_index < len(columns) else None
        row_index = int(row[1:]) - 1  # Convert from '#1' format to 0-based index
        
        if col_name == "Focus":
            with self.cam_info_lock:
                if row_index < len(self.cam_info):
                    camera_info = self.cam_info[row_index]
                    self.on_focus_clicked(camera_info)
        elif col_name == "Verify":
            with self.cam_info_lock:
                if row_index < len(self.cam_info):
                    camera_info = self.cam_info[row_index]
                    self.on_verify_clicked(camera_info)

    def on_focus_clicked(self, camera: PerCamInfo):
        """Callback when Focus button is clicked"""
        print(f"Focus clicked for camera: {camera.name} (IP: {camera.ip})")
        # TODO: Implement focus functionality

    def on_verify_clicked(self, camera: PerCamInfo):
        """Callback when Verify button is clicked"""
        print(f"Verify clicked for camera: {camera.name} (IP: {camera.ip})")
        # TODO: Implement verify functionality

    def check_cam_online(self, ip: str) -> typing.Tuple[str, bool]:
        endpoint = self.get_endpoint(ip, "ping")
        try:
            response = requests.get(endpoint, timeout=0.5)
        except requests.exceptions.Timeout:
            return ip, False
        return ip, response.status_code == 200

    def get_endpoint(self, ip: str, route: str) -> str:
        return f"http://{ip}:5000/{route}"

    def check_cam_online_callback(self, status_future: Future[typing.Tuple[str, bool]]):
        ip, online = status_future.result()
        with self.cam_info_lock:
            next(cam for cam in self.cam_info if cam.ip == ip).online = online


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
    IP = "10.50.100.116"
    SCRIPT = "remote_autofocus.py"
    launcher.upload_script(IP, f"src/remote/{SCRIPT}")
    time.sleep(1)
    launcher.start_script(IP, SCRIPT)
    try:
        time.sleep(1)
        response = requests.get(
            f"http://{IP}:5000/autofocus",
            timeout=30,
        )
        print(response.json())
        lens_pos = response.json()["lens_pos"]
        store_lens_pos(IP, lens_pos)
    finally:
        launcher.stop_script(IP, SCRIPT)
