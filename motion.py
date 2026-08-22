"""Motion detection using frame differencing and cooldown logic."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

import numpy as np

from config import Config
from snapshots import Snapshots
from database import Database
from discord_notify import DiscordNotifier
from camera import Camera

LOG = logging.getLogger("security_camera.motion")


class MotionDetector:
    def __init__(self, camera: Camera, snapshots: Snapshots, db: Database, notifier: DiscordNotifier, config: Config):
        self.camera = camera
        self.snapshots = snapshots
        self.db = db
        self.notifier = notifier
        self.config = config

        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_event_time = 0.0
        self._bg_frame: Optional[np.ndarray] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="MotionDetector")
        self._thread.start()
        LOG.info("Motion detector started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def update_config(self) -> None:
        LOG.info("Motion detector config updated")

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.config.motion_enabled():
                time.sleep(1.0)
                continue
            frame = self.camera.latest_frame_np
            if frame is None:
                time.sleep(0.1)
                continue
            try:
                down = int(self.config.as_dict().get("motion", {}).get("downscale", 2))
                gray = _to_grayscale(frame)
                if down > 1:
                    gray = gray[::down, ::down]
                if self._bg_frame is None:
                    self._bg_frame = gray
                    time.sleep(0.1)
                    continue
                # compute diff
                diff = np.abs(gray.astype(int) - self._bg_frame.astype(int)).astype(np.uint8)
                # threshold using sensitivity
                thresh_val = int(self.config.as_dict().get("motion", {}).get("sensitivity", 25))
                mask = diff > thresh_val
                changed = int(mask.sum())
                min_area = int(self.config.as_dict().get("motion", {}).get("min_area", 500))
                now = time.time()
                cooldown = int(self.config.as_dict().get("motion", {}).get("cooldown_seconds", 10))
                if changed >= min_area and (now - self._last_event_time) >= cooldown:
                    # motion event
                    LOG.info("Motion detected: changed=%d >= min_area=%d", changed, min_area)
                    # save snapshot
                    jpeg = self.camera.get_jpeg()
                    timestamp = datetime.utcnow()
                    path = self.snapshots.save_snapshot(jpeg_bytes=jpeg, timestamp=timestamp)
                    # record in db
                    self.db.insert_event(timestamp=timestamp, snapshot_path=path, motion_score=changed)
                    # send discord (non-blocking)
                    try:
                        if self.config.discord_enabled():
                            self.notifier.notify(timestamp=timestamp, image_bytes=jpeg)
                    except Exception:
                        LOG.exception("Discord notify failed")
                    self._last_event_time = now
                # update background slowly: running average
                alpha = 0.2
                self._bg_frame = (self._bg_frame.astype(float) * (1 - alpha) + gray.astype(float) * alpha).astype(np.uint8)
            except Exception:
                LOG.exception("Error during motion detection")
            time.sleep(0.05)


def _to_grayscale(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        # BGR to gray
        return (0.2989 * frame[:, :, 2] + 0.5870 * frame[:, :, 1] + 0.1140 * frame[:, :, 0]).astype(np.uint8)
    return frame.astype(np.uint8)
