from config import Config
import os
import tempfile


def test_config_load_save(tmp_path):
    p = tmp_path / "cfg.json"
    cfg = Config(str(p))
    cfg.load()
    orig = cfg.as_dict()
    assert "camera" in orig
    cfg._data["camera"]["width"] = 320
    cfg.save()
    cfg2 = Config(str(p))
    cfg2.load()
    assert cfg2.camera_width() == 320
