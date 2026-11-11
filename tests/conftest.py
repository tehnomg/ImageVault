import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from fastapi.testclient import TestClient
from app import create_app
from config import Config
from tests.make_test_data import build_sample_tree

def make_cfg(data_dir: Path, **kw) -> Config:
    c = Config(data_dir=data_dir, **kw)
    for p in (c.data_dir, c.thumbs_dir, c.logs_dir, c.backups_dir):
        p.mkdir(parents=True, exist_ok=True)
    return c

@pytest.fixture
def cfg(tmp_path):
    return make_cfg(tmp_path / "data")

@pytest.fixture
def client(cfg):
    with TestClient(create_app(cfg)) as c:
        yield c

@pytest.fixture
def sample(tmp_path):
    return build_sample_tree(tmp_path / "library")