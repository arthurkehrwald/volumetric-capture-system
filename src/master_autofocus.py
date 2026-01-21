import time
import requests
from utils import launcher
import json
from utils import config

if __name__ == "__main__":
    IP = "10.50.100.116"
    SCRIPT = "remote_autofocus.py"
    launcher.upload_script(IP, f"src/remote/{SCRIPT}")
    time.sleep(1)
    launcher.start_script(IP, SCRIPT)
    time.sleep(1)
    response = requests.get(f"http://{IP}:5000/autofocus", timeout=30)
    lens_pos = response.json()["lens_position"]

    # Load camera list and update the entry with matching IP
    with open("src/config/camera_list.json", "r") as f:
        cam_list = json.load(f)

    # Find and update the camera with the matching IP
    for camera in cam_list:
        if camera["ip"] == IP:
            camera["lens_position"] = lens_pos
            break

    # Write updated camera list back to file
    with open("src/config/camera_list.json", "w") as f:
        json.dump(cam_list, f, indent=4)

    launcher.stop_script(IP, SCRIPT)
