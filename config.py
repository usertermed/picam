"""Configuration loader and validator.

Stores settings in JSON file and provides typed accessors.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict

LOG = logging.getLogger("security_camera.config")

DEFAULTS = {
    "camera": {
        "device": "/dev/video0",
        "width": 640,
        "height": 480,
        "fps": 10,
        "jpeg_quality": 80,
    },
    "motion": {
        "enabled": True,
        "sensitivity": 25,  # threshold for binarization
        "min_area": 500,  # pixels changed
        "cooldown_seconds": 10,
        "downscale": 2,
    },
    "storage": {
        "snapshot_directory": "data/snapshots",
        "max_snapshots": 5000,
        "max_storage_mb": 0,  # 0 means disabled
        "snapshot_jpeg_quality": 80,
    },
    "discord": {
        "enabled": False,
        "webhook_url": "",
        "cooldown_seconds": 30,
    },
    "web": {
        "host": "0.0.0.0",
        "port": 8080
    },
    "logging": {
        "level": "INFO"
    }
}


@dataclass
class Config:
    path: str
    _data: Dict[str, Any] = field(default_factory=dict)

    def load(self) -> None:
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as fh:
                self._data = json.load(fh)
        else:
            self._data = DEFAULTS.copy()
            self.save()
        LOG.debug("Config loaded: %s", self._data)

    def save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=4)
        LOG.info("Config saved to %s", self.path)

    def as_dict(self) -> Dict[str, Any]:
        return self._data

    def update_from_dict(self, d: Dict[str, Any]) -> None:
        # Merge top-level keys
        for k, v in d.items():
            if k in self._data and isinstance(self._data[k], dict) and isinstance(v, dict):
                self._data[k].update(v)
            else:
                self._data[k] = v
        self.validate()

    def validate(self) -> None:
        # Ensure sensible types and bounds
        try:
            cam = self._data.get("camera", {})
            cam["width"] = int(cam.get("width", 640))
            cam["height"] = int(cam.get("height", 480))
            cam["fps"] = max(1, int(cam.get("fps", 10)))
            cam["jpeg_quality"] = max(10, min(95, int(cam.get("jpeg_quality", 80))))

            motion = self._data.get("motion", {})
            motion["sensitivity"] = max(1, int(motion.get("sensitivity", 25)))
            motion["min_area"] = max(1, int(motion.get("min_area", 500)))
            motion["cooldown_seconds"] = max(0, int(motion.get("cooldown_seconds", 10)))
            motion["downscale"] = max(1, int(motion.get("downscale", 2)))

            storage = self._data.get("storage", {})
            storage["snapshot_directory"] = storage.get("snapshot_directory", "data/snapshots")
            storage["max_snapshots"] = int(storage.get("max_snapshots", 5000))
            storage["max_storage_mb"] = int(storage.get("max_storage_mb", 0))
            storage["snapshot_jpeg_quality"] = max(10, min(95, int(storage.get("snapshot_jpeg_quality", 80))))

            discord = self._data.get("discord", {})
            discord["enabled"] = bool(discord.get("enabled", False))
            discord["webhook_url"] = str(discord.get("webhook_url", ""))
            discord["cooldown_seconds"] = max(0, int(discord.get("cooldown_seconds", 30)))

            web = self._data.get("web", {})
            web["host"] = str(web.get("host", "0.0.0.0"))
            web["port"] = int(web.get("port", 8080))

            log = self._data.get("logging", {})
            log["level"] = str(log.get("level", "INFO"))
        except Exception as e:
            LOG.exception("Invalid config: %s", e)
            raise

    # convenience accessors
    def camera_device(self) -> str:
        return self._data.get("camera", {}).get("device", DEFAULTS["camera"]["device"])

    def camera_width(self) -> int:
        return int(self._data.get("camera", {}).get("width", DEFAULTS["camera"]["width"]))

    def camera_height(self) -> int:
        return int(self._data.get("camera", {}).get("height", DEFAULTS["camera"]["height"]))

    def camera_fps(self) -> int:
        return int(self._data.get("camera", {}).get("fps", DEFAULTS["camera"]["fps"]))

    def camera_jpeg_quality(self) -> int:
        return int(self._data.get("camera", {}).get("jpeg_quality", DEFAULTS["camera"]["jpeg_quality"]))

    def motion_enabled(self) -> bool:
        return bool(self._data.get("motion", {}).get("enabled", DEFAULTS["motion"]["enabled"]))

    def web_host(self) -> str:
        return str(self._data.get("web", {}).get("host", DEFAULTS["web"]["host"]))

    def web_port(self) -> int:
        return int(self._data.get("web", {}).get("port", DEFAULTS["web"]["port"]))

    def discord_enabled(self) -> bool:
        return bool(self._data.get("discord", {}).get("enabled", False))

    def log_level(self) -> int:
        lvl = self._data.get("logging", {}).get("level", "INFO")
        return getattr(logging, lvl.upper(), logging.INFO)
