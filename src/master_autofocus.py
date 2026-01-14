import time
import requests
from utils import launcher

if __name__ == '__main__':
    IP = "10.50.100.116"
    SCRIPT = "remote_autofocus.py"
    launcher.upload_script(IP, f"src/remote/{SCRIPT}")
    time.sleep(1)
    launcher.start_script(IP, SCRIPT)
    time.sleep(1)
    response = requests.get(f"http://{IP}:5000/", timeout=5)
    print(response.content)
    launcher.stop_script(IP, SCRIPT)
