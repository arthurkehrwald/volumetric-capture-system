"""
Automatically focus a camera lens.
At least one printed fiducial marker (marker.pdf) must be visible to the camera
without any obstruction at the distance that should be in focus.
The closest marker is recognized using the Aruco markers located at each corner
and cropped out. The sharpness is rated using the Laplacian variance of that
cropped image. The optimization process consists of two stages. First, an upper
and lower bound for the lens position is established by identifying the two
sharpest pictures in a focus sequence of five pictures with a focal distance
between 50cm and infinity. Second, A binary search between the the two
corresponding lens positions (hopefully) converges to the optimum.
"""

from flask import Flask, jsonify
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


def wait_for_lens_pos(lens_pos: float, running_picam: Picamera2, timeout: float):
    start_time = time.time()
    while start_time - time.time() < timeout:
        metadata = Metadata(
            running_picam.capture_metadata()
        )  # Blocks until frame arrives
        if abs(metadata.LensPosition - lens_pos) < 0.01:
            return


def take_photo(running_picam: Picamera2, lens_pos: float) -> np.ndarray:
    with running_picam.controls as ctrl:
        ctrl.AfMode = controls.AfModeEnum.Manual
        ctrl.LensPosition = lens_pos
    wait_for_lens_pos(lens_pos, running_picam, timeout=1.5)
    array = running_picam.capture_array("main")
    return array


class FocusImg(typing.NamedTuple):
    photo: np.ndarray
    biggest_marker_detected: MarkerDetection
    lens_pos: float
    rating: float


def try_out_lens_pos(lens_pos: float, running_picam: Picamera2) -> FocusImg:
    photo = take_photo(running_picam, lens_pos)
    marker = find_best_test_marker(photo)
    if marker is not None:
        crop = crop_out_marker(photo, marker)
        rating = rate_marker_sharpness(crop)
    else:
        rating = 0
    return FocusImg(photo, marker, lens_pos, rating)


def find_ideal_lens_pos(
    running_picam: Picamera2,
    lower_bound: FocusImg,
    upper_bound: FocusImg,
    iterations: int,
) -> float:
    if lower_bound.rating == upper_bound.rating:
        raise ValueError(
            "Ratings for upper and lower bound lens positions cannot be the same."
        )
    for _ in range(iterations):
        mid_lens_pos = (lower_bound.lens_pos + upper_bound.lens_pos) / 2
        mid = try_out_lens_pos(mid_lens_pos, running_picam)

        if lower_bound.rating > upper_bound.rating:
            upper_bound = mid
        else:
            lower_bound = mid

    return mid_lens_pos


def find_lens_pos_bounds(
    running_picam: Picamera2, num_photos: int
) -> typing.Tuple[FocusImg, FocusImg]:
    seq = []
    for i in range(num_photos):
        MAX_LENS_POS = 2  # 50cm focus dist
        lens_pos = MAX_LENS_POS * i / (num_photos - 1)
        candidate = try_out_lens_pos(lens_pos, running_picam)
        seq.append(candidate)
    seq.sort(key=lambda x: x.rating, reverse=True)
    return seq[0], seq[1]


app = Flask(__name__)


@app.route("/autofocus", methods=["GET"])
def autofocus():
    with Picamera2() as picam:
        picam.configure(picam.create_still_configuration())
        picam.start()
        lower, upper = find_lens_pos_bounds(picam, num_photos=5)
        ideal = find_ideal_lens_pos(picam, lower, upper, iterations=5)
    return jsonify({"lens_position", ideal}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False, use_reloader=False)
