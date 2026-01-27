import time
import requests
from utils import launcher
import json
from utils import config


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
