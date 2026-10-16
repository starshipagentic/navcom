"""Bounded native Starforge version-family input adapter, shared by intake/views."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

ENGINE = 'starforge.lineage.LineageDetector.detect_repo_lineages'
MAX_DIRECTORIES = 2000
MAX_FAMILIES = 128
MAX_BYTES = 512 * 1024


def detect(directories, label):
    """Adapt real sibling paths to Starforge, without redefining its matching."""
    from starforge.lineage import LineageDetector, _normalize_name
    if not isinstance(label, str) or len(label) > 4096 or len(directories) > MAX_DIRECTORIES:
        raise ValueError('Native family input exceeds its label/directory budget.')
    paths = []
    for value in directories:
        if not isinstance(value, str) or not value or len(value) > 4096:
            raise ValueError('Native family paths must be bounded relative paths.')
        path = Path(value)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Native family paths must stay inside the source.')
        if str(path) != '.':
            paths.append(path)
    siblings = defaultdict(list)
    for path in sorted(set(paths)):
        siblings[path.parent].append(path)

    class CatalogView:
        def __init__(self, rows): self.rows = rows
        def list_projects(self, limit=500): return self.rows[:limit]

    result, omitted = [], []
    for parent, paths in sorted(siblings.items()):
        if len(paths) < 2:
            continue
        if len(paths) > 500:
            omitted.append('Native catalog limit: sibling group omitted at ' + str(parent))
            continue
        rows = []
        for path in paths:
            original = path.name
            contextual = not _normalize_name(original) and LineageDetector._extract_version(original) > 0
            name = str(path) if contextual and str(parent) != '.' else label + '/' + original if contextual else original
            rows.append(dict(name=name, path=str(path), original_name=original, contextual_name=contextual))
        for family in LineageDetector(CatalogView(rows)).detect_repo_lineages():
            numbered = {LineageDetector._extract_version(member['original_name']) for member in family['repos']}
            numbered.discard(0)
            if len(numbered) < 2:
                continue
            if len(result) >= MAX_FAMILIES:
                return dict(families=result, omitted=omitted + ['Native family result budget reached.'])
            result.append(dict(parent_path=str(parent), label=parent.name if str(parent) != '.' else label,
                native_name=family['name'], native_score=family['score'], engine=ENGINE,
                members=[dict(label=member['original_name'], path=member['path'], native_input=member['name'],
                              contextual_name=member['contextual_name']) for member in family['repos']]))
    return dict(families=result, omitted=omitted)


def signature():
    import starforge.lineage
    return hashlib.sha256(Path(__file__).read_bytes() + Path(starforge.lineage.__file__).read_bytes()
                          + sys.version.encode()).hexdigest()


def _cached(request):
    key = hashlib.sha256(json.dumps([request['directories'], request['label'], signature()], sort_keys=True).encode()).hexdigest()
    cache = Path(request['cache']) if request.get('cache') else None
    memo = cache / (key + '.json') if cache else None
    if memo and memo.is_file() and memo.stat().st_size <= MAX_BYTES * 4:
        return dict(json.loads(memo.read_text()), cached=True)
    data = dict(detect(request['directories'], request['label']), status='available', engine=ENGINE,
                fingerprint=key, cached=False)
    if memo:
        cache.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode='w', dir=cache, prefix='.families-', delete=False) as handle:
            json.dump(data, handle, sort_keys=True)
            temporary = Path(handle.name)
        os.replace(temporary, memo)
    return data


NATIVE = '''import json,sys
sys.path.insert(0,sys.argv[1])
import navcom_native_families as families
print(json.dumps(families._cached(json.load(sys.stdin))))
'''
BOOTSTRAP = '''import os,sys
sys.path.insert(0,sys.argv[1])
os.environ['PYTHONDONTWRITEBYTECODE']='1'
from navcom_sources import runtime
python=runtime()
os.execv(python,[python,'-I','-B','-c',sys.argv[2],sys.argv[1]])
'''


def analyze(directories, label, cache_path=None, seconds=3):
    """Bound the complete optional runtime/cache operation, not only inference."""
    request = dict(directories=sorted(set(str(path) for path in directories)), label=label,
                   cache=str(Path(cache_path).resolve()) if cache_path else None)
    payload = json.dumps(request).encode()
    if len(payload) > MAX_BYTES or len(request['directories']) > MAX_DIRECTORIES:
        return dict(status='unavailable', engine=ENGINE, families=[], omitted=['Native family input budget exceeded.'])
    if not 0 < seconds <= 5:
        raise ValueError('Native family analysis deadline must be within 5 seconds.')
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = None
        try:
            process = subprocess.Popen([sys.executable, '-I', '-B', '-c', BOOTSTRAP, str(Path(__file__).parent), NATIVE],
                stdin=subprocess.PIPE, stdout=output, stderr=errors, start_new_session=True)
            process.communicate(payload, timeout=seconds)
            if process.returncode or output.tell() > MAX_BYTES * 4 or errors.tell() > 65536:
                raise ValueError('Native runtime failed or exceeded its output budget.')
            output.seek(0)
            return json.loads(output.read())
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return dict(status='unavailable', engine=ENGINE, families=[],
                        omitted=['Native version-family sampling unavailable: ' + type(exc).__name__ + '. Existing app sampling retained.'])
        finally:
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
