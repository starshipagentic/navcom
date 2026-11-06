"""Read native Starforge project inventory without harvesting or modifying its DB."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time

from navcom_space import kill_group

ENGINE = 'starforge.catalog.Catalog.list_projects'
MAX_PROJECTS = 2000
MAX_CATALOG_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_ERRORS_BYTES = 64 * 1024


def _unavailable(reason):
    return dict(nodes=[], coverage=dict(available=False, engine=ENGINE, complete=False,
                                       truncated=False, limitations=[reason]))


def _native_inventory(limit):
    """Run in Starforge's runtime; only storage access changes, not catalog ordering."""
    from functools import partial
    from unittest.mock import patch
    from tinydb import TinyDB
    from tinydb.storages import Storage
    import starforge.catalog as native
    from starforge.utils import get_global_dir

    # The provider's location resolver normally mkdirs. Keep its exact environment
    # semantics, but an optional inventory read must never create its directory.
    def existing_directory(directory, *args, **kwargs):
        if not directory.is_dir():
            raise FileNotFoundError('Native Starforge directory is unavailable.')

    with patch.object(Path, 'mkdir', existing_directory):
        catalog_path = get_global_dir() / 'catalog.json'

    class ReadOnlySnapshot(Storage):
        def __init__(self, path, **kwargs):
            flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
            descriptor = os.open(path, flags)
            with os.fdopen(descriptor, 'rb') as stream:
                metadata = os.fstat(stream.fileno())
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError('Native Starforge catalog must be a regular file.')
                if metadata.st_size > MAX_CATALOG_BYTES:
                    raise ValueError('Native Starforge catalog exceeds the 32 MiB read budget.')
                raw = stream.read(MAX_CATALOG_BYTES + 1)
            if len(raw) > MAX_CATALOG_BYTES:
                raise ValueError('Native Starforge catalog exceeds the 32 MiB read budget.')
            self.data = json.loads(raw)
            if not isinstance(self.data, dict) or not isinstance(self.data.get('projects', {}), dict):
                raise ValueError('Native Starforge catalog has an invalid project table.')
            rows = self.data.get('projects', {}).values()
            if any(not isinstance(row, dict) or not isinstance(row.get('name', ''), str) for row in rows):
                raise ValueError('Native Starforge catalog has an invalid project record.')
            self.fingerprint = hashlib.sha256(raw).hexdigest()
            self.byte_count = len(raw)

        def read(self):
            return self.data

        def write(self, data):
            raise PermissionError('Native inventory storage is read-only.')

        def close(self):
            pass

    # Catalog exposes no storage argument. Inject TinyDB's standard storage
    # interface just for construction; its native list_projects method is reused.
    with patch.object(native, 'TinyDB', partial(TinyDB, storage=ReadOnlySnapshot)):
        catalog = native.Catalog(catalog_path)
    try:
        total = catalog.project_count()
        rows = catalog.list_projects(limit=limit)
        nodes, invalid, duplicates, missing, not_directories = [], 0, 0, 0, 0
        paths = set()
        for row in rows:
            value = row.get('path')
            if (not isinstance(value, str) or not value or len(value) > 4096
                    or any(ord(character) < 32 for character in value) or not Path(value).is_absolute()):
                invalid += 1
                continue
            # No cwd rebasing, ownership inference or cache-directory scan.
            if value in paths:
                duplicates += 1
                continue
            paths.add(value)
            path = Path(value)
            try:
                status = 'directory' if path.is_dir() else 'not_directory' if path.exists() else 'missing'
            except OSError:
                status = 'unavailable'
            missing += status in ('missing', 'unavailable')
            not_directories += status == 'not_directory'
            origin = dict(kind='starforge', catalog=str(catalog_path), root_status=status)
            for key in ('name', 'galaxy', 'last_scan'):
                field = row.get(key, '')
                origin[key] = field[:512] if isinstance(field, str) else ''
            nodes.append(dict(label=value, collection=None, source_origin=origin))
        limitations = []
        if total > limit:
            limitations.append('Native project inventory limited to the first ' + str(limit) + ' native-sorted records.')
        if invalid:
            limitations.append(str(invalid) + ' records omitted because their project paths are not valid absolute paths.')
        if missing or not_directories:
            limitations.append('Missing or non-directory project roots are retained for intake to report; no clone or repair was attempted.')
        return dict(nodes=nodes, coverage=dict(available=True, engine=ENGINE,
                    catalog=str(catalog_path), catalog_fingerprint=catalog._db.storage.fingerprint,
                    catalog_bytes=catalog._db.storage.byte_count, total_projects=total,
                    considered_projects=len(rows), returned_projects=len(nodes), invalid_paths=invalid,
                    duplicate_paths=duplicates, missing_roots=missing, non_directory_roots=not_directories,
                    truncated=total > limit, complete=total <= limit and not invalid and not missing and not not_directories,
                    limitations=limitations))
    finally:
        catalog._db.close()


NATIVE = '''import json,sys
sys.path.insert(0,sys.argv[1])
import navcom_starforge_inventory as inventory
try:
    result=inventory._native_inventory(int(sys.argv[2]))
except FileNotFoundError:
    result=inventory._unavailable('Native Starforge catalog is not present; no catalog was created.')
except (OSError,ValueError,TypeError,KeyError,RecursionError) as exc:
    result=inventory._unavailable('Native Starforge catalog could not be read ('+type(exc).__name__+').')
print(json.dumps(result))
'''
BOOTSTRAP = '''import os,sys
sys.path.insert(0,sys.argv[1])
os.environ['PYTHONDONTWRITEBYTECODE']='1'
from navcom_sources import runtime
python=runtime()
os.execv(python,[python,'-I','-B','-c',sys.argv[2],sys.argv[1],sys.argv[3]])
'''


def inventory(limit=MAX_PROJECTS, seconds=5):
    """Optional native inventory, including runtime resolution within one deadline."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PROJECTS:
        raise ValueError('Native project inventory limit must be between 1 and 2000.')
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 < seconds <= 15:
        raise ValueError('Native project inventory deadline must be within 15 seconds.')
    started = time.monotonic()
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = None
        try:
            process = subprocess.Popen([sys.executable, '-I', '-B', '-c', BOOTSTRAP,
                str(Path(__file__).parent), NATIVE, str(limit)], stdin=subprocess.DEVNULL,
                stdout=output, stderr=errors, start_new_session=True)
            while process.poll() is None:
                if time.monotonic() - started >= seconds:
                    raise TimeoutError('Native inventory deadline exceeded.')
                if os.fstat(output.fileno()).st_size > MAX_OUTPUT_BYTES or os.fstat(errors.fileno()).st_size > MAX_ERRORS_BYTES:
                    raise ValueError('Native inventory output budget exceeded.')
                time.sleep(min(.025, max(.001, seconds - (time.monotonic() - started))))
            if process.returncode:
                return _unavailable('Native Starforge runtime unavailable; existing indexed project intake remains available.')
            if os.fstat(output.fileno()).st_size > MAX_OUTPUT_BYTES or os.fstat(errors.fileno()).st_size > MAX_ERRORS_BYTES:
                raise ValueError('Native inventory output budget exceeded.')
            output.seek(0)
            result = json.loads(output.read(MAX_OUTPUT_BYTES + 1))
            if not isinstance(result, dict) or not isinstance(result.get('nodes'), list) or len(result['nodes']) > limit or not isinstance(result.get('coverage'), dict):
                raise ValueError('Native inventory returned an invalid result.')
            return result
        except (OSError, ValueError, TimeoutError) as exc:
            return _unavailable('Native Starforge inventory unavailable (' + type(exc).__name__ + '); existing indexed project intake remains available.')
        finally:
            if process:
                kill_group(process)
