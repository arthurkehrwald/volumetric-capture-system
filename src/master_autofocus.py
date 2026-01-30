from dataclasses import dataclass
import time
import typing
import requests
from utils import launcher
import json
from utils import config
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
        self.cam_info: list[PerCamInfo] = self.read_cam_info(config.CAMERA_LIST_FILE)

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
        self.update_autofocus_table_loop(table)

    def update_autofocus_table_loop(self, table: ttk.Treeview):
        for i in range(len(self.cam_info)):
            self.update_table_row(table, self.cam_info[i], i)
        table.after(500, self.update_autofocus_table_loop, table)

    def get_table_values(self, info: PerCamInfo) -> typing.Tuple[str]:
        return (
            info.name,
            "Online" if info.online else "Offline",
            str(info.focus_rating),
            str(info.prev_rating),
            f"{(1 / info.lens_pos):.2f}" if info.lens_pos > .1 else "∞",
            f"{info.prev_distance:.2f}",
            "Click!",
            "Click!",
        )

    def update_table_row(self, table: ttk.Treeview, info: PerCamInfo, index: int):
        item = table.get_children()[index]
        table.item(item, values=self.get_table_values(info))


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
