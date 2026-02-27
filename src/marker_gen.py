import cv2
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PIL import Image
import math


def generate_siemens_star(size_px):
    """
    Generate a Siemens star image with black and white circular sectors.

    :param size_px: Size of the image in pixels (width and height).
    :return: A numpy array representing the Siemens star.
    """
    star = (
        np.ones((size_px, size_px), dtype=np.uint8) * 255
    )  # Start with a white canvas
    center = size_px // 2
    radius = int(center * math.sqrt(2))  # Adjust radius to fill the marker
    num_sectors = 48

    for i in range(num_sectors):
        start_angle = int(360 * i / num_sectors)
        end_angle = int(360 * (i + 1) / num_sectors)
        color = 0 if i % 2 == 0 else 255
        cv2.ellipse(
            star,
            (center, center),
            (radius, radius),
            0,  # Rotation angle
            start_angle,
            end_angle,
            color,
            -1,  # Fill the sector
        )

    return star


def generate_aruco_marker(dictionary, id, size_px):
    """
    Generate an ArUco marker image.

    :param dictionary: The ArUco dictionary to use.
    :param id: The ID of the marker.
    :param size_px: The size of the marker in pixels.
    :return: A numpy array representing the ArUco marker.
    """
    marker = np.zeros((size_px, size_px), dtype=np.uint8)
    marker = cv2.aruco.generateImageMarker(dictionary, id, size_px)
    return marker


def create_marker_pdf(aruco_id, marker_size_cm, dpi=300):
    """
    Create a PDF file containing the marker.

    :param output_path: Path to save the PDF file.
    :param marker_size_cm: Size of the marker in centimeters.
    :param dpi: Dots per inch for the PDF.
    """
    # Convert marker size to pixels
    cm_to_inch = 0.393701
    marker_size_in = marker_size_cm * cm_to_inch
    marker_size_px = int(marker_size_in * dpi)

    # Create the Siemens star
    siemens_star = generate_siemens_star(marker_size_px)

    # Create the ArUco markers
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250)
    aruco_size_px = (
        marker_size_px // 5
    )  # ArUco markers are 1/5th the size of the marker
    marker = generate_aruco_marker(aruco_dict, aruco_id, aruco_size_px)
    aruco_markers = [marker for i in range(4)]

    # Create a blank marker canvas
    marker = np.ones((marker_size_px, marker_size_px), dtype=np.uint8)

    # Overlay the Siemens star
    marker = cv2.addWeighted(marker, 0, siemens_star, 1, 0)

    # Overlay the ArUco markers in the corners
    positions = [
        (0, 0),
        (0, marker_size_px - aruco_size_px),
        (marker_size_px - aruco_size_px, 0),
        (marker_size_px - aruco_size_px, marker_size_px - aruco_size_px),
    ]

    for i, (pos, aruco) in enumerate(zip(positions, aruco_markers)):
        x, y = pos
        if i == 1:  # Rotate 90 degrees for the top-right corner
            aruco = cv2.rotate(aruco, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif i == 2:  # Rotate 180 degrees for the bottom-right corner
            aruco = cv2.rotate(aruco, cv2.ROTATE_90_CLOCKWISE)
        elif i == 3:  # Rotate 270 degrees for the bottom-left corner
            aruco = cv2.rotate(aruco, cv2.ROTATE_180)

        # Add white border to inward-facing sides
        border_thickness = aruco_size_px // 20
        if i == 0:  # Top-left corner
            aruco = cv2.copyMakeBorder(
                aruco,
                0,
                border_thickness,
                0,
                border_thickness,
                cv2.BORDER_CONSTANT,
                value=255,
            )
        elif i == 1:  # Top-right corner
            aruco = cv2.copyMakeBorder(
                aruco,
                border_thickness,
                0,
                0,
                border_thickness,
                0,
                cv2.BORDER_CONSTANT,
                value=255,
            )
        elif i == 2:  # Bottom-left corner
            aruco = cv2.copyMakeBorder(
                aruco,
                0,
                border_thickness,
                border_thickness,
                0,
                cv2.BORDER_CONSTANT,
                value=255,
            )
        elif i == 3:  # Bottom-right corner
            aruco = cv2.copyMakeBorder(
                aruco,
                border_thickness,
                0,
                border_thickness,
                0,
                cv2.BORDER_CONSTANT,
                value=255,
            )

        # Resize back to original size
        aruco = cv2.resize(
            aruco, (aruco_size_px, aruco_size_px), interpolation=cv2.INTER_AREA
        )

        marker[y : y + aruco_size_px, x : x + aruco_size_px] = aruco

    # Save the marker as a PDF
    marker_image = Image.fromarray(marker)
    marker_image.save("temp_marker.png")

    pdf = canvas.Canvas(f"marker_{aruco_id}.pdf", pagesize=A4)
    page_width, page_height = A4
    x_center = (page_width - marker_size_in * 72) / 2
    y_center = (page_height - marker_size_in * 72) / 2

    pdf.drawImage(
        "temp_marker.png",
        x=x_center,  # Center horizontally
        y=y_center,  # Center vertically
        width=marker_size_in * 72,
        height=marker_size_in * 72,
    )
    pdf.save()


if __name__ == "__main__":
    create_marker_pdf(aruco_id=102, marker_size_cm=18.5)
