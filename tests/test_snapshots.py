from snapshots import Snapshots
from database import Database
from config import Config
import tempfile
from datetime import datetime


def test_snapshot_filename_and_retention(tmp_path):
    db = Database(str(tmp_path / "ev.db"))
    db.initialize()
    cfg_path = tmp_path / "cfg.json"
    cfg = Config(str(cfg_path))
    cfg.load()
    cfg._data["storage"]["max_snapshots"] = 2
    snaps = Snapshots(str(tmp_path / "snaps"), db, cfg)
    # save three snapshots
    for i in range(3):
        ts = datetime.utcnow()
        snaps.save_snapshot(b"\xff\xd8\xff\xd9", ts)
    assert snaps.count_snapshots() <= 2
