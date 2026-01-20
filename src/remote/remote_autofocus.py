"""
Finds the sharpest image in a list of images to help automatically focus camera
lenses. At least one printed fiducial marker (marker.pdf) must be visible in
each image without any obstruction at the distance that should be in focus.
The largest marker is recognized using the Aruco markers located at each corner
and cropped out. The sharpness is rated using the Laplacian variance of that
cropped image.
"""

from flask import Flask
from picamera2 import Picamera2, Metadata
import time
import numpy as np
import typing
import cv2 as cv
from libcamera import controls


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


def wait_for_lens_pos(
    lens_pos: float, running_picam: Picamera2, timeout_time: None | float
):
    while not timed_out(timeout_time):
        metadata = Metadata(
            running_picam.capture_metadata()
        )  # Blocks until frame arrives
        print(abs(metadata.LensPosition - lens_pos))
        if abs(metadata.LensPosition - lens_pos) < 0.01:
            return
    raise TimeoutError()


def timed_out(timeout_time: float | None) -> bool:
    return timeout_time is not None and time.time() > timeout_time


def take_photo(
    running_picam: Picamera2, lens_pos: float, timeout_time: float | None
) -> np.ndarray:
    with running_picam.controls as ctrl:
        ctrl.AfMode = controls.AfModeEnum.Manual
        ctrl.LensPosition = lens_pos
    wait_for_lens_pos(lens_pos, running_picam, timeout_time)
    array = running_picam.capture_array("main")
    return array


class FocusImg(typing.NamedTuple):
    image: np.ndarray
    lens_pos: float


def record_focus_series(
    num_photos: int, timeout_time: float | None
) -> typing.List[FocusImg]:
    """
    Takes a specified number of photos with different lens positions.

    :param num_photos: Number of photos
    :type num_photos: int
    :param timeout_time: Optional timestamp in seconds since epoch until function must finish
    :type timeout_time: float | None
    :return: List of images with associated lens positions
    :rtype: List[FocusImg]
    """
    with Picamera2() as picam:
        picam.configure(picam.create_still_configuration())
        picam.start()
        seq = []
        for i in range(num_photos):
            MAX_LENS_POS = 2  # 50cm focus dist
            lens_pos = MAX_LENS_POS * i / (num_photos - 1)
            photo = take_photo(picam, lens_pos, timeout_time)
            seq.append(FocusImg(photo, lens_pos))


app = Flask(__name__)


@app.route("/autofocus", methods=["GET"])
def autofocus():
    start_time = time.time()
    try:
        seq = record_focus_series(20, time.time() + 5)
    except Exception as e:
        return str(e)
    passed = time.time() - start_time
    return str(passed)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False, use_reloader=False)
