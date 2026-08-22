"""Snapshot storage and retention management."""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from config import Config
from database import Database

LOG = logging.getLogger("security_camera.snapshots")


class Snapshots:
    def __init__(self, snap_dir: str, db: Database, config: Config):
        self.snap_dir = os.path.abspath(snap_dir)
        self.db = db
        self.config = config
        os.makedirs(self.snap_dir, exist_ok=True)

    def update_config(self) -> None:
        os.makedirs(self.snap_dir, exist_ok=True)

    def _ensure_dir_for(self, timestamp: datetime) -> str:
        y = timestamp.strftime("%Y")
        m = timestamp.strftime("%m")
        d = timestamp.strftime("%d")
        out = os.path.join(self.snap_dir, y, m, d)
        os.makedirs(out, exist_ok=True)
        return out

    def save_snapshot(self, jpeg_bytes: Optional[bytes], timestamp: datetime) -> Optional[str]:
        if jpeg_bytes is None:
            LOG.error("No jpeg bytes provided to save_snapshot")
            return None
        subdir = self._ensure_dir_for(timestamp)
        name = timestamp.strftime("%Y-%m-%d_%H-%M-%S") + ".jpg"
        # safe filename
        name = name.replace("..", "")
        path = os.path.join(subdir, name)
        try:
            with open(path, "wb") as fh:
                fh.write(jpeg_bytes)
            LOG.info("Saved snapshot %s", path)
            # cleanup if needed
            self._enforce_retention()
            # return path relative to snap_dir
            rel = os.path.relpath(path, self.snap_dir)
            return rel
        except Exception:
            LOG.exception("Failed to write snapshot to %s", path)
            return None

    def list_snapshots(self, page: int = 1, per_page: int = 40) -> Tuple[List[dict], int]:
        # List files sorted desc
        files = []
        for root, _, filenames in os.walk(self.snap_dir):
            for fn in filenames:
                if fn.lower().endswith(('.jpg', '.jpeg', '.png')):
                    full = os.path.join(root, fn)
                    stat = os.stat(full)
                    files.append((full, stat.st_mtime))
        files.sort(key=lambda x: x[1], reverse=True)
        total = len(files)
        start = (page - 1) * per_page
        slice_ = files[start:start + per_page]
        out = []
        for full, mtime in slice_:
            rel = os.path.relpath(full, self.snap_dir)
            out.append({
                "path": rel,
                "mtime": mtime,
            })
        return out, total

    def resolve_snapshot_path(self, relpath: str) -> Optional[str]:
        candidate = os.path.abspath(os.path.join(self.snap_dir, relpath))
        if not candidate.startswith(self.snap_dir):
            return None
        return candidate

    def delete_snapshot(self, relpath: str) -> bool:
        p = self.resolve_snapshot_path(relpath)
        if not p or not os.path.exists(p):
            return False
        try:
            os.remove(p)
            LOG.info("Deleted snapshot %s", p)
            return True
        except Exception:
            LOG.exception("Failed to delete %s", p)
            return False

    def delete_all_snapshots(self) -> None:
        try:
            # be careful: only delete inside snap_dir
            for child in Path(self.snap_dir).glob("**/*"):
                try:
                    if child.is_file():
                        child.unlink()
                except Exception:
                    LOG.exception("Failed to delete %s", child)
            LOG.info("Deleted all snapshots under %s", self.snap_dir)
        except Exception:
            LOG.exception("Failed to delete all snapshots")

    def count_snapshots(self) -> int:
        n = 0
        for _, _, filenames in os.walk(self.snap_dir):
            for fn in filenames:
                if fn.lower().endswith(('.jpg', '.jpeg', '.png')):
                    n += 1
        return n

    def _enforce_retention(self) -> None:
        cfg = self.config.as_dict().get("storage", {})
        max_snapshots = int(cfg.get("max_snapshots", 5000))
        max_storage_mb = int(cfg.get("max_storage_mb", 0))
        # Delete old files if count exceeds
        files = []
        for root, _, filenames in os.walk(self.snap_dir):
            for fn in filenames:
                if fn.lower().endswith(('.jpg', '.jpeg', '.png')):
                    full = os.path.join(root, fn)
                    try:
                        stat = os.stat(full)
                        files.append((full, stat.st_mtime, stat.st_size))
                    except Exception:
                        continue
        files.sort(key=lambda x: x[1])  # oldest first
        # by count
        while max_snapshots > 0 and len(files) > max_snapshots:
            f, _, _ = files.pop(0)
            try:
                os.remove(f)
                LOG.info("Pruned old snapshot %s", f)
            except Exception:
                LOG.exception("Failed to prune %s", f)
        # by storage
        if max_storage_mb > 0:
            total = sum(sz for _, _, sz in files)
            max_bytes = max_storage_mb * 1024 * 1024
            while files and total > max_bytes:
                f, _, sz = files.pop(0)
                try:
                    os.remove(f)
                    total -= sz
                    LOG.info("Pruned %s to reduce storage", f)
                except Exception:
                    LOG.exception("Failed to prune %s", f)
