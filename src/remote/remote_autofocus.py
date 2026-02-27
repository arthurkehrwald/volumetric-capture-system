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

import io
import flask
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


class FocusRating(typing.NamedTuple):
    lens_pos: float
    rating: float

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, FocusRating)
            and self.lens_pos == other.lens_pos
            and self.rating == other.rating
        )


def rate_focus(photo: np.ndarray) -> int:
    marker = find_best_test_marker(photo)
    if marker is not None:
        crop = crop_out_marker(photo, marker)
        rating = rate_marker_sharpness(crop)
    else:
        rating = 0
    return rating


def find_ideal_lens_pos(
    running_picam: Picamera2,
    lower_bound: FocusRating,
    upper_bound: FocusRating,
    iterations: int,
) -> FocusRating:
    for _ in range(iterations):
        mid_lens_pos = (lower_bound.lens_pos + upper_bound.lens_pos) / 2
        photo = take_photo(running_picam, mid_lens_pos)
        mid_rating = rate_focus(photo)
        mid = FocusRating(mid_lens_pos, mid_rating)

        if lower_bound.rating > upper_bound.rating:
            upper_bound = mid
        else:
            lower_bound = mid

    return mid


def find_lens_pos_bounds(
    running_picam: Picamera2, num_photos: int
) -> typing.Tuple[FocusRating, FocusRating]:
    seq = []
    for i in range(num_photos):
        MAX_LENS_POS = 2  # 50cm focus dist
        lens_pos = MAX_LENS_POS * i / (num_photos - 1)
        photo = take_photo(running_picam, lens_pos)
        rating = rate_focus(photo)
        seq.append(FocusRating(lens_pos, rating))
    seq.sort(key=lambda x: x.rating, reverse=True)
    return seq[0], seq[1]


def try_encode_photo(photo: np.ndarray) -> typing.Tuple[bool, io.BytesIO | None]:
    success, buffer = cv.imencode(".jpg", photo)
    if not success:
        return False, None
    bytes = io.BytesIO(buffer.tobytes())
    bytes.seek(0)
    return success, bytes


autofocus_blueprint = flask.Blueprint("autofocus", __name__)


@autofocus_blueprint.route("/rate-lens-pos/<float:lens_pos>")
def rate_lens_pos_route(lens_pos: float):
    photo = take_photo(flask.current_app.picam, lens_pos)
    rating = rate_focus(photo)
    return flask.jsonify({"rating": rating})


@autofocus_blueprint.route("/autofocus")
def autofocus_route():
    lower, upper = find_lens_pos_bounds(flask.current_app.picam, num_photos=5)
    ideal = find_ideal_lens_pos(flask.current_app.picam, lower, upper, iterations=5)
    return flask.jsonify(
        {
            "lens_pos": ideal.lens_pos,
            "rating": ideal.rating,
        }
    )


@autofocus_blueprint.route("/photo/<float:lens_pos>")
def send_photo_route(lens_pos: float):
    photo = take_photo(flask.current_app.picam, lens_pos)
    success, bytes = try_encode_photo(photo)
    if not success:
        flask.current_app.logger.error("Failed to encode photo.")
        return flask.jsonify({"error": "Failed to encode photo"}), 500
    return flask.send_file(bytes, mimetype="image/jpeg")


@autofocus_blueprint.route("/marker-photo/<float:lens_pos>")
def send_marker_photo_route(lens_pos: float):
    photo = take_photo(flask.current_app.picam, lens_pos)
    marker = find_best_test_marker(photo)
    if marker is not None:
        photo = crop_out_marker(photo, marker)
    success, bytes = try_encode_photo(photo)
    if not success:
        flask.current_app.logger.error("Failed to encode photo.")
        return flask.jsonify({"error": "Failed to encode photo"}), 500
    return flask.send_file(bytes, mimetype="image/jpeg")


@autofocus_blueprint.route("/ping")
def ping_route():
    return flask.jsonify({"status": "ok"})
