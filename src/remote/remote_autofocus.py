from flask import Flask, Response
from picamera2 import Picamera2
import time

app = Flask(__name__)


@app.route("/rate-sharpness", methods=["GET"])
def rate_sharpness_route():
    try:
        picam2 = Picamera2()
        picam2.configure(picam2.create_still_configuration())
        picam2.start()
        time.sleep(1)
        array = picam2.capture_array("main")
        return f"{array.shape}"
    except Exception as e:
        return e


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False, use_reloader=False)
