"""Camera capture abstraction.

Attempts to use OpenCV (cv2). If not available, provides a mock camera for testing.

Provides a single capture loop that populates latest frame buffers used by the streamer
and motion detector.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional
import io

import numpy as np

LOG = logging.getLogger("security_camera.camera")

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - cv2 may be unavailable on test systems
    cv2 = None


class Camera:
    """Camera wrapper that continuously captures frames in a background thread.

    Attributes:
        latest_frame_np: latest BGR numpy array (or None)
        latest_jpeg: latest encoded JPEG bytes (or None)
    """

    def __init__(self, device: str = "/dev/video0", width: int = 640, height: int = 480, fps: int = 10, jpeg_quality: int = 80):
        self.device = device
        self.width = width
        self.height = height
        self.fps = max(1, fps)
        self.jpeg_quality = jpeg_quality

        self.latest_frame_np: Optional[np.ndarray] = None
        self.latest_jpeg: Optional[bytes] = None

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="CameraCapture")
        self._thread.start()
        LOG.info("Camera thread started for %s", self.device)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
        LOG.info("Camera stopped")

    def is_open(self) -> bool:
        return self._cap is not None and getattr(self._cap, "isOpened", lambda: True)()

    def update_settings(self, width: int, height: int, fps: int, jpeg_quality: int) -> None:
        LOG.info("Updating camera settings: %dx%d @%dfps q=%d", width, height, fps, jpeg_quality)
        self.width = width
        self.height = height
        self.fps = max(1, fps)
        self.jpeg_quality = jpeg_quality
        # Reopen capture to apply settings
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def get_jpeg(self) -> Optional[bytes]:
        return self.latest_jpeg

    def _open_capture(self):
        if cv2 is None:
            LOG.warning("cv2 not available, using mock frames")
            return None
        try:
            cap = cv2.VideoCapture(self.device)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.width))
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.height))
            cap.set(cv2.CAP_PROP_FPS, int(self.fps))
            # Some drivers need a short warmup
            time.sleep(0.1)
            if not cap.isOpened():
                LOG.error("Failed to open camera device %s", self.device)
                return None
            LOG.info("Opened camera %s (requested %dx%d @%dfps)", self.device, self.width, self.height, self.fps)
            return cap
        except Exception:
            LOG.exception("Error opening camera")
            return None

    def _run(self) -> None:
        frame_interval = 1.0 / max(1, self.fps)
        last_time = 0.0
        while not self._stop_event.is_set():
            start = time.time()
            if self._cap is None:
                self._cap = self._open_capture()
                if self._cap is None:
                    # Sleep and retry
                    time.sleep(2.0)
                    continue
            frame = None
            try:
                if cv2 is not None:
                    ret, f = self._cap.read()
                    if not ret or f is None:
                        LOG.warning("Camera read failed, reopening")
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                        self._cap = None
                        time.sleep(1.0)
                        continue
                    # f is BGR numpy array
                    frame = f
                else:
                    # Create mock frame (placeholder)
                    frame = self._mock_frame()
                # store latest_frame_np
                self.latest_frame_np = frame
                # encode JPEG
                if cv2 is not None:
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpeg_quality)]
                    _, jpg = cv2.imencode('.jpg', frame, encode_param)
                    self.latest_jpeg = jpg.tobytes()
                else:
                    # simple PNG from numpy using pillow
                    from PIL import Image
                    img = Image.fromarray(frame[:, :, ::-1])
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG', quality=self.jpeg_quality)
                    self.latest_jpeg = buf.getvalue()
            except Exception:
                LOG.exception("Error capturing frame")
                self.latest_frame_np = None
                self.latest_jpeg = None
                try:
                    if self._cap:
                        self._cap.release()
                except Exception:
                    pass
                self._cap = None
                time.sleep(1.0)

            elapsed = time.time() - start
            to_sleep = frame_interval - elapsed
            if to_sleep > 0:
                time.sleep(to_sleep)

    def _mock_frame(self):
        # Return a small gray image for unit tests or environments without cv2
        h = int(self.height)
        w = int(self.width)
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        # draw timestamp
        import datetime
        txt = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            from PIL import Image, ImageDraw, ImageFont
            im = Image.fromarray(arr)
            draw = ImageDraw.Draw(im)
            draw.text((10, 10), txt, fill=(255, 255, 255))
            return np.array(im)
        except Exception:
            return arr
