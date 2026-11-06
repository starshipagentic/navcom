import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "features" / "support"))


@pytest.fixture(autouse=True)
def isolated_starforge_inventory(tmp_path, monkeypatch):
    """Tests may use native analysis, never the owner's real harvested inventory."""
    monkeypatch.setenv("STARFORGE_GLOBAL_DIR", str(tmp_path / "starforge-home"))


@pytest.fixture(scope="session")
def navcom():
    spec = importlib.util.spec_from_file_location("navcom_under_test", ROOT / "navcom.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
