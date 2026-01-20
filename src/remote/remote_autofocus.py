"""
Finds the sharpest image in a list of images to help automatically focus camera
lenses. At least one printed fiducial marker (marker.pdf) must be visible in
each image without any obstruction at the distance that should be in focus.
The largest marker is recognized using the Aruco markers located at each corner
and cropped out. The sharpness is rated using the Laplacian variance of that
cropped image.
"""

from flask import Flask
from picamera2 import Picamera2
import time
import numpy as np
import typing
import cv2 as cv


class Point(typing.NamedTuple):
    x: int
    y: int


class MarkerDetection(typing.NamedTuple):
    marker_id: int
    corners: typing.List[Point]


def find_aruco_markers(img: np.ndarray) -> typing.List[MarkerDetection]:
    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_4X4_250)
    gray = cv.cvtColor(img, cv.COLOR_BGR2GRAY)
    corners_list, ids, _ = cv.aruco.detectMarkers(gray, dictionary)
    if ids is None:
        return []
    return [
        MarkerDetection(
            marker_id=int(ids[i][0]),
            corners=[Point(int(c[0]), int(c[1])) for c in corners_list[i][0]],
        )
        for i in range(len(ids))
    ]


def find_test_markers(img: np.ndarray) -> typing.List[MarkerDetection]:
    corner_markers = find_aruco_markers(img)
    test_markers = {}
    for marker in corner_markers:
        if marker.marker_id not in test_markers:
            test_markers[marker.marker_id] = []
        test_markers[marker.marker_id].append(marker.corners[0])

    return [
        MarkerDetection(marker_id=mid, corners=corners)
        for mid, corners in test_markers.items()
        if len(corners) == 4
    ]


def calc_area(marker: MarkerDetection) -> float:
    # Calculate area using the shoelace formula for a polygon
    corners = marker.corners
    n = len(corners)
    area = 0.0
    for i in range(n):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def find_best_test_marker(img: np.ndarray) -> MarkerDetection:
    markers = find_test_markers(img)
    if not markers:
        return None
    best_marker = max(markers, key=calc_area)
    return best_marker


def crop_out_marker(img: np.ndarray, marker: MarkerDetection) -> np.ndarray:
    x_coords = [point.x for point in marker.corners]
    y_coords = [point.y for point in marker.corners]
    x_min, x_max = min(x_coords), max(x_coords)
    y_min, y_max = min(y_coords), max(y_coords)
    return img[y_min:y_max, x_min:x_max]


def rate_marker_sharpness(marker_img: np.ndarray) -> int:
    gray = cv.cvtColor(marker_img, cv.COLOR_BGR2GRAY)
    laplacian = cv.Laplacian(gray, cv.CV_64F)
    sharpness = int(laplacian.var())
    return sharpness


def rate_image_focus(img: np.ndarray) -> int:
    marker = find_best_test_marker(img)
    if marker is None:
        return 0
    crop = crop_out_marker(img, marker)
    return rate_marker_sharpness(crop)


def take_photo() -> np.ndarray:
    picam2 = Picamera2()
    picam2.configure(picam2.create_still_configuration())
    picam2.start()
    try:
        time.sleep(1)
        array = picam2.capture_array("main")
        return array
    finally:
        picam2.stop()


app = Flask(__name__)


@app.route("/rate-sharpness", methods=["GET"])
def rate_sharpness_route():
    photo = take_photo()
    focus = rate_image_focus(photo)
    return str(focus)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False, use_reloader=False)
