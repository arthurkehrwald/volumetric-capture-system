**EN** | [DE](/README.de.md)

<p align="center">
  <img src="https://github.com/VolumanXR/.github/blob/main/docs/assets/Logo_VCS.png" alt="Volumetric Capture System Logo" width="400"/>
</p>

# VolumanXR – Volumetric Capture System

This module is part of the **VolumanXR** project and implements a complete **synchronized volumetric video capture system** using Raspberry Pis and the Raspberry Pi Camera Module V3. The system enables real-time, multi-camera video acquisition for 4D Gaussian Splatting.
<p align="center">
  <img src="https://github.com/VolumanXR/.github/blob/main/docs/assets/VCR_Scanresult.gif" alt="Animated results of a scan" width="100%"/>
</p>

It includes:
- A scalable and customizable camera rig
- A decentralized control system with synchronized recording
- GUI tools for capture, calibration, and download
- Automation scripts and config management

> **Maintenance Notice**\
>This repository primarily serves as a documentation and reference space for the Volumetric Capture System of the VolumanXR research project. Further development occurs on an occasional basis and is not continuous. Repositories may receive updates from time to time, but regular maintenance and long-term support should not be assumed.

### Usage

The autofocus feature is part of the 

## 📦 Repository Structure
```text
volumetric-capture-system/
├── readme.md
├── requirements.txt
├── cad/                           # 3D-printable camera holder models
├── src/
│   ├── master_camera_controller.py
│   ├── master_capture_controller.py
│   ├── master_download_manager.py
│   ├── config/                    # Device settings and camera parameters
│   ├── lib/                       # Shared configuration and SSH utilities
│   ├── remote/                    # Scripts executed on Raspberry Pis
│   ├── res/                       # Icons and sound files used by GUI tools
│   └── utils/                     # Utility scripts for setup and control
```

---

## 🔧 Hardware Context
<p align="center">
  <img src="https://github.com/VolumanXR/.github/blob/main/docs/assets/VCS_teaser_image.png" alt="Volumetric Capture System Overview Image" width="100%"/>
</p>

- **Camera Rig**: Custom-built frame using aluminum extrusion profiles (not included in repo).
- **Cameras**: Raspberry Pi 4B (1GB) + Camera Module V3
- **Devices**: approx. 70 Raspberry Pi units
- **Mounts**: 3D-printable camera holders (provided in `cad/`)
- **Trigger**: Software-synchronized using NTP + ZeroMQ

> *The structural skeleton is specific to our use case and therefore excluded to encourage custom modifications. It is based on standard 20×20mm aluminum extrusions, and the included 3D-printable camera holders are fully compatible with this profile size. A full parts list for the frame construction can be provided upon request.*

---

## 🚀 Core Functionality

### 🎚️ Master Camera Controller (`master_camera_controller.py`)
- GUI tool for live preview and global camera calibration
- Modify ISO, shutter speed, white balance, resolution
- Automatically focus the cameras using fiducial markers (Added in this fork)
- Save unified settings to `camera_settings.json`

### 📸 Master Capture Controller (`master_capture_controller.py`)
- GUI-based tool to control still or video capture
- Synchronizes all agents to a single start time
- Frame drop detection and timestamp logging
- Uses `camera_list.json` to identify and manage all configured camera devices on the network

### 🔄 Master Download Manager (`master_download_manager.py`)
- GUI tool to download sessions from all Pis
- Organizes files, checks completeness, enables conversion
- Supports offline mode for post-capture frame extraction

---

## 🧠 Remote Agents (Running on Raspberry Pis)

Remote-side scripts are located in `src/remote/` and are triggered via SSH by the master control GUIs. Each script is responsible for a core function during capture, calibration, or data transfer.

### Main Remote Modules

- `remote_camera_controller.py`  
  Handles calibration commands from the Master Camera Controller (`master_camera_controller.py`), such as adjusting focus or setting exposure.

- `remote_capture_controller.py`  
  Receives synchronized recording instructions from the Master Capture Controller (`master_capture_controller.py`), executes the capture locally, and logs metadata.

- `remote_download_manager.py`  
  Runs a simple file server on each Pi to make captured sessions available for download, coordinated by the Master Download Manager (`master_download_manager.py`).

### Remote Utilities (`src/remote/utils/`)

- `remote_set_cam_number.py` — Sets a unique hostname, ID (e.g. `CAM00`) and fixed IP  
- `remote_test_camera_settings.py` — Applies a series of camera configurations and captures test images for validation

---

## This fork

This fork adds an autofocus feature that allows calibrating the lens positions of all cameras automatically using fiducial markers. The markers can be generated using the `marker_gen.py` script. We have glued 16 of these markers to boxes and mounted those boxes on a pole to make them visible to all cameras simultaneously.

<p align="center">
<img width="300" alt="marker-pole" src="https://github.com/user-attachments/assets/2cf943e4-d71d-4357-ac86-24479aae1269"/>
</p>

### Motivation

The Raspberry Pi Cameras have built in autofocus, but this proved unreliable during video recordings. Since the subject is typically in the center of the rig, a fixed focus distance for all cameras would work theoretically, but in practice each camera is different. Initially, the lens positions / focus distances of all cameras were calibrated manually with the expectation of never having to do it again. A few months later, the cameras were no longer focused with these same settings. This fork was made because it is not practical to manually focus all cameras every few weeks.

### Usage

<img width="1920" height="1032" alt="image" src="https://github.com/user-attachments/assets/45cda43c-f7c6-4ebe-b899-e479e044c373" />

The autofocus feature is integrated into the master camera controller as an additional tab in the user interface. There is a table of all connected cameras showing their focus distances and a 1-5 star rating of the resulting sharpness. Using the buttons at the bottom of the window, it is possible to:

- Focus all the cameras at once
- Focus the selected camera(s)
- Retake photos and recalculate the ratings
- Compare cropped markers from photos taken with the previous and current focus distances to see if the focus procedure actually worked
- Look at an uncropped photo taken with the current focus distance
- Save the changes to focus distances

### Known issues

- Since there is no fixed association between cameras and markers to allow users to place the pole with arbitrary orientation, the remote script may occasionally choose different markers to calculate the sharpness, leading to inconsistent results. This happens because the marker with the biggest surface area in the image is chosen if more than one is recognized. If two markers are close to the same size, this method is not deterministic across multiple photos. An additional criterion such as distance from image center should be introduced.
- The star ratings are not comparable between different cameras, lighting situations and marker orientations. The scale is also inconsistent. An improvement from one to two stars may in some cases be subjectively substantial. In other cases, moving from one to five stars barely makes a noticeable difference in the before / after pictures.
- The commits added in this fork were initially made in another repository and later rebased. Commits between  [95b90a9](https://github.com/arthurkehrwald/volumetric-capture-system/commit/95b90a9aa31db57e923792dedfe57f567d3182ee) and [de93045](https://github.com/arthurkehrwald/volumetric-capture-system/commit/de93045b82592e102d226466fa78ed6aa0c74317) were not tested and may be broken.

## 🧰 General Utilities

Located in `src/utils/`, these tools support discovery, setup, and remote control:

- `launcher.py`  
  CLI for development, debugging, and deployment. Supports multithreaded SSH to start/stop/update remote scripts on all Pis.

- `search_devices.py`  
  Scans the local subnet using multithreaded pings to identify active devices. Attempts to resolve hostnames for each responsive IP.

- `set_up_chrony_via_ssh.py`  
  Configures time synchronization on all Pis using Chrony for frame-accurate triggering.

- `master_set_cam_number.py`  
  Assigns camera numbers and hostnames from the master side during setup.

- `build.py`
  Preconfigured build script for all three main programs

---

## ⚙️ Configuration Files

- `camera_list.json` — List of camera hostnames, IPs, and their custom focus offsets
- `camera_settings.json` — Default global exposure settings (shutter, ISO, etc.)

Each Pi is matched via hostname (e.g. `CAM00`, `CAM01`, ...) and receives a fixed IP address in the `10.x.x.x` range.  
The **last octet of the IP corresponds to the camera number**, starting at `.100` — for example:
- `CAM00` → `10.x.x.100`
- `CAM01` → `10.x.x.101`

---
## 🗂 File Naming Convention

Captured videos and still images follow the pattern:
```
<session_name>_<ip_suffix>.<extension>
```

Examples:
- `DanceA_103.mp4` — video from device with IP `10.x.x.103`
- `PoseTest_115.jpg` — still image from device with IP `10.x.x.115`

This format ensures files can easily be traced to their originating capture device.

---

## 🎛 Dependencies

Install dependencies for local tools:

```bash
pip install -r requirements.txt
```
Recommended environment:
- Python 3.10+
- Works on Windows/macOS (for GUI tools) and Raspberry Pi OS (for remote agents)

---

## 👥 Contributions
### Code Contributors

- **Kai Altwicker** — Rig design, synchronization, master control architecture  
- **Dennis Amuser** — Remote agent design, firmware imaging, network & automation

### Publications
- **[IEEE VR26 Poster](https://doi.org/10.13140/RG.2.2.16244.62083) (Preprint)**\
[Steffen Stein](https://www.linkedin.com/in/steffen-sascha-stein/), [Dennis Amuser](https://github.com/dooonnis), [Kai Altwicker](https://github.com/tallAldi), David Mertens, Matthias Bullert Alisa Rüge, David Martin Karf, Kristoffer Waldow, [Arnulph Fuhrmann](https://www.linkedin.com/in/arnulph-fuhrmann-291420279/)
```bibtex
@misc{stein2026scalable,
  author       = {Steffen-Sascha Stein and Dennis Amuser and Kai Altwicker and  David Mertens and Matthias Bullert and Alisa Ruge and David Martin Karg and Kristoffer Waldow and Arnulph Fuhrmann},
  title        = {A Scalable and Cost-Effective Multi-View Capture System for Photorealistic Dynamic Human Reconstruction},
  year         = {2026},
  month        = {February},
  note         = {Preprint. To appear in IEEE VR 2026 Poster Track},
  doi          = {10.13140/RG.2.2.16244.62083},
  url          = {https://doi.org/10.13140/RG.2.2.16244.62083}
}
```

### Acknowledgements
- Prof. Dr.-Ing. Fuhrmann
- GatewayTHK
- Makerspace TH Köln 
- Zentralwerkstatt Elektrotechnik, 

---

## 📄 License
 
Please refer to the [`LICENSE`](/LICENSE) file for full terms.

Third-party license notices are provided in [`THIRD_PARTY_NOTICES.md`](/NOTICE-THIRD-PARTY.md).


---

> ℹ️ This repository is part of the VolumanXR project. \
> For full project context, visit the [VolumanXR](https://github.com/VolumanXR) page.





