#!/usr/bin/env python3
"""Flask web application entrypoint for Raspberry Pi Zero 2 W security camera.
"""
from __future__ import annotations

import io
import logging
import os
import threading
import time
from datetime import datetime
from typing import Iterator

from flask import (Flask, Response, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)

from config import Config
from camera import Camera
from motion import MotionDetector
from snapshots import Snapshots
from database import Database
from discord_notify import DiscordNotifier

LOG = logging.getLogger("security_camera")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECURITY_CAMERA_SECRET") or "dev-secret"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
SNAPSHOT_DIR = os.path.join(DATA_DIR, "snapshots")
DB_PATH = os.path.join(BASE_DIR, "events.db")

config = Config(CONFIG_PATH)
config.load()

db = Database(DB_PATH)
db.initialize()

snapshots = Snapshots(snap_dir=SNAPSHOT_DIR, db=db, config=config)

camera = Camera(device=config.camera_device(), width=config.camera_width(), height=config.camera_height(), fps=config.camera_fps(), jpeg_quality=config.camera_jpeg_quality())

discord = DiscordNotifier(config)

motion_detector = MotionDetector(camera=camera, snapshots=snapshots, db=db, notifier=discord, config=config)

# Start background threads
camera.start()
motion_detector.start()


@app.route("/")
def index():
    status = {
        "camera_online": camera.is_open(),
        "motion_enabled": config.motion_enabled(),
        "snapshot_count": snapshots.count_snapshots(),
        "recent_events": db.get_recent_events(10),
    }
    return render_template("index.html", config=config.as_dict(), status=status)


def mjpeg_stream() -> Iterator[bytes]:
    """Yield multipart JPEG frames from camera.latest_jpeg buffer."""
    LOG.debug("Starting MJPEG stream generator")
    while True:
        frame = camera.get_jpeg()
        if frame is None:
            # Send a small placeholder frame or sleep
            time.sleep(0.1)
            continue
        yield (b"--frame\r\n"
               b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        # rate limiting handled by camera capture fps


@app.route("/stream")
def stream():
    return Response(mjpeg_stream(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/snapshots")
def snapshots_page():
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 40))
    snaps, total = snapshots.list_snapshots(page=page, per_page=per_page)
    return render_template("snapshots.html", snapshots=snaps, page=page, per_page=per_page, total=total)


@app.route("/snapshot/<path:relpath>")
def serve_snapshot(relpath: str):
    # Prevent directory traversal by disallowing .. and ensuring path under snap dir
    if ".." in relpath or relpath.startswith("/"):
        return "Invalid path", 400
    full = snapshots.resolve_snapshot_path(relpath)
    if not full or not os.path.exists(full):
        return "Not found", 404
    return send_file(full)


@app.route("/api/delete_snapshot", methods=["POST"])
def api_delete_snapshot():
    relpath = request.form.get("path")
    if not relpath:
        return jsonify({"error": "path required"}), 400
    ok = snapshots.delete_snapshot(relpath)
    return jsonify({"deleted": ok})


@app.route("/api/delete_all", methods=["POST"])
def api_delete_all():
    snapshots.delete_all_snapshots()
    return jsonify({"deleted_all": True})


@app.route("/settings", methods=["GET"])
def settings_page():
    return render_template("settings.html", config=config.as_dict())


@app.route("/api/save_settings", methods=["POST"])
def api_save_settings():
    # Accept either JSON or form data. Form keys may be like camera[width]; convert to nested dict
    raw = request.json
    if raw is None:
        raw = {}
        for k, v in request.form.items():
            if "[" in k and k.endswith("]"):
                base, rest = k.split("[", 1)
                inner = rest[:-1]
                raw.setdefault(base, {})[inner] = _coerce_value(v)
            else:
                raw[k] = _coerce_value(v)
    try:
        config.update_from_dict(raw)
        config.save()
        flash("Settings saved", "success")
        # Apply some settings live
        camera.update_settings(width=config.camera_width(), height=config.camera_height(), fps=config.camera_fps(), jpeg_quality=config.camera_jpeg_quality())
        motion_detector.update_config()
        snapshots.update_config()
        return jsonify({"ok": True})
    except Exception as e:
        LOG.exception("Failed to save settings")
        return jsonify({"ok": False, "error": str(e)}), 400


def _coerce_value(v: str):
    # try to coerce numeric and boolean-like strings
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        if "." in v:
            return float(v)
        return int(v)
    except Exception:
        return v


@app.route("/api/test_discord", methods=["POST"])
def api_test_discord():
    if not config.discord_enabled():
        return jsonify({"ok": False, "error": "Discord disabled"}), 400
    try:
        # Use latest frame
        jpg = camera.get_jpeg()
        discord.test_webhook(jpg_bytes=jpg)
        return jsonify({"ok": True})
    except Exception as e:
        LOG.exception("Discord test failed")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/stats")
def api_stats():
    return jsonify({
        "camera_open": camera.is_open(),
        "snapshot_count": snapshots.count_snapshots(),
        "recent_events": db.get_recent_events(5),
    })


def shutdown():
    LOG.info("Shutting down...")
    motion_detector.stop()
    camera.stop()
    db.close()


if __name__ == "__main__":
    logging.basicConfig(level=config.log_level())
    try:
        app.run(host=config.web_host(), port=config.web_port(), threaded=True)
    except KeyboardInterrupt:
        shutdown()
