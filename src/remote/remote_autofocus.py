from flask import Flask, Response
from picamera2 import Picamera2
import time
import numpy as np

app = Flask(__name__)

def take_photo() -> np.ndarray:
    picam2 = Picamera2()
    picam2.configure(picam2.create_still_configuration())
    picam2.start()
    time.sleep(1)
    array = picam2.capture_array("main")
    picam2.stop()
    return array

@app.route("/rate-sharpness", methods=["GET"])
def rate_sharpness_route():
    photo = take_photo()
    return f"{photo.shape}"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False, use_reloader=False)
