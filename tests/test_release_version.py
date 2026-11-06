"""The user's version command must identify the release being built."""
from pathlib import Path
import re
import subprocess
import sys


def test_cli_version_matches_distribution():
    root = Path(__file__).resolve().parents[1]
    version = re.search(r'^version = "([^"]+)"',
                        (root / 'pyproject.toml').read_text(), re.M)[1]
    result = subprocess.run([sys.executable, str(root / 'navcom.py'), '--version'],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'navcom ' + version
