picam - Security Camera project for Pi Zero 2 W
=====================================

Overview
--------
A lightweight Python-based security camera server optimized for Raspberry Pi Zero 2 W using a USB UVC webcam such as the Logitech C270.

Features
- Local web UI (Flask)
- Live MJPEG stream optimized for low CPU usage
- Motion detection via frame differencing
- Snapshot storage with folder-by-date layout
- Automatic retention by count or storage size
- Optional Discord webhook notifications with attached snapshot
- SQLite event log

Important notes
- Do **not** expose the web UI to the public internet; this is intended for trusted local networks.


Install via Script (Raspberry Pi OS / Raspbian)
--------------------------------------

1. Clone repository
   `git clone http://GitHub.com/usertermed/picam.git`
2. Run the script (may ask for password at some point, due to the fact it installs packages)
   ```
   cd picam
   chmod +rwx ./install.sh
   ./install.sh
   ```
3. Service should automatically start, check the web portal at http://<raspberry-pi-ip>:3000


Do-It-Yourself Install (Not Recommended) (Debian-based)
--------------------------------------

Note: these instructions aren't really kept up with the rest of the project's dependencies. Only use these if you expect issues and have a reason to.
1. Update system:

    `sudo apt update && sudo apt upgrade -y`

2. Install OS packages (minimal):

    `sudo apt install -y python3-venv python3-dev build-essential libatlas-base-dev libjpeg-dev ffmpeg v4l-utils`

3. Create project folder and virtualenv (example):

    `git clone <this-repo> ~/security-camera
    cd ~/security-camera
    python3 -m venv venv
    . venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt`

4. Verify webcam is detected:

    `v4l2-ctl --list-devices
    ls -l /dev/video*`

If multiple /dev/video devices exist, set the correct device in config.json.

5. Copy config.example.json to config.json and edit as needed.

    `cp config.example.json config.json
    nano config.json`

6. Start for testing:

    `source ./venv/bin/activate
    python app.py`

7. Access web UI on another machine: http://<raspberry-pi-ip>:8080/

Systemd
-------
Copy systemd/security-camera.service to /etc/systemd/system/security-camera.service and edit paths (WorkingDirectory and ExecStart) to match installation. Then enable and start:

    sudo systemctl daemon-reload
    sudo systemctl enable security-camera
    sudo systemctl start security-camera

Troubleshooting
- If the camera is not detected, check dmesg and v4l2-ctl.
- If OpenCV install fails, consider using system packages or skip OpenCV and use the mock for development.

Security
- Do not commit config.json with secrets (Discord webhook URL).
- Restrict filesystem permissions for config.json if it contains a webhook.

Tests
-----
Run pytest in the project directory to execute basic unit tests.

