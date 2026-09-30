import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "support"))
import fake_home  # noqa: E402


def before_scenario(context, scenario):
    context.tmp = Path(tempfile.mkdtemp(prefix="navcom-bdd-"))
    context.home = context.tmp / "home"
    context.sessions, context.workdir = fake_home.build(context.home)
    context.env = fake_home.env_for(context.home)
    context.navcom = str(Path(__file__).resolve().parent.parent / "navcom.py")


def after_scenario(context, scenario):
    shutil.rmtree(context.tmp, ignore_errors=True)
