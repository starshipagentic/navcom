"""The published wheel and sdist allowlists stay complete and anchored."""
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib")
ROOT = Path(__file__).resolve().parents[1]


def _targets():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"]["targets"]


def test_every_runtime_file_ships_in_wheel_and_sdist():
    targets = _targets()
    wheel, sdist = targets["wheel"]["only-include"], targets["sdist"]["include"]
    runtime = sorted(p.name for p in ROOT.glob("navcom*") if p.suffix in {".py", ".js", ".css", ".html"})
    assert [name for name in runtime if name not in wheel] == []
    assert "assets/starship" in wheel
    assert [entry for entry in wheel if "/" + entry not in sdist] == []


def test_sdist_is_anchored_and_excludes_internal_material():
    sdist = _targets()["sdist"]["include"]
    # Unanchored names such as "README.md" also match LABS/**/private copies.
    assert [entry for entry in sdist if not entry.startswith("/")] == []
    assert [entry for entry in sdist if entry.startswith(("/LABS", "/diary")) or entry == "/docs"] == []
