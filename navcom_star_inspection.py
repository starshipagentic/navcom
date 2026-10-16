"""Living-expertise dossiers and explicit, bounded provider status observations.

Metadata is not a readiness claim. Only installed provider status code or Docker's
inspect operation runs; no project commands, gateways, inference or models start.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from navcom_ship_inspection import _text

VERSION = 2
PROFILE_STATUS = r'''
import json,sys
from pathlib import Path
request=json.load(sys.stdin)
sys.path.insert(0,request['provider_root'])
from hermes_cli.profiles import _check_gateway_running
print(json.dumps({'gateway_running':bool(_check_gateway_running(Path(request['profile_home'])))}))
'''
DOCKER_FORMAT = ('{"running":{{.State.Running}},"status":{{json .State.Status}},'
                 '"image":{{json .Config.Image}},'
                 '"compose_directory":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}},'
                 '"compose_files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}},'
                 '"compose_service":{{json (index .Config.Labels "com.docker.compose.service")}}}')
DOCKER_CONTEXT_FORMAT = '{"name":{{json .Name}},"host":{{json .Endpoints.docker.Host}}}'


def _runtime_identity(candidate):
    """Invalidate status on a daemon/context switch without reading Docker auth."""
    if candidate.get('provider') != 'hermes-compose':
        return None
    executable = shutil.which('docker')
    config = Path(os.environ.get('DOCKER_CONFIG') or str(Path.home()/'.docker'))/'config.json'
    def stamp(path):
        try:
            info = Path(path).stat()
            return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        except (OSError, TypeError):
            return None
    value = [executable, stamp(executable), str(config), stamp(config),
             {key: os.environ.get(key) for key in ('DOCKER_CONTEXT', 'DOCKER_HOST',
                 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'DOCKER_CONFIG')}]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _endpoint(value):
    """Show runtime location without userinfo, passwords, query or fragments."""
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        url = urlsplit(value)
        if url.scheme in ('unix', 'npipe'):
            return _text(url.scheme+'://'+url.path, 200)
        if url.scheme and url.hostname:
            host = '['+url.hostname+']' if ':' in url.hostname else url.hostname
            return _text(url.scheme+'://'+host+(':'+str(url.port) if url.port else ''), 200)
    except ValueError:
        pass
    return None


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.observation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:json.dump(value, stream)
        os.replace(name, path)
    finally:
        if Path(name).exists():Path(name).unlink()


def _run_json(argv, request=None):
    # Fixed provider operations only. File-backed output bounds memory as well
    # as avoiding untrusted console text in a browser response.
    with tempfile.TemporaryDirectory(prefix='navcom-star-status-') as directory:
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            try:
                result = subprocess.run(argv, input=json.dumps(request).encode() if request else None,
                    stdout=output, stderr=errors, cwd=directory, timeout=10)
            except (OSError, subprocess.SubprocessError):
                return None
            if result.returncode or output.tell() > 65536:
                return None
            output.seek(0)
            try:
                value = json.load(output)
                return value if isinstance(value, dict) else None
            except (ValueError, UnicodeError):
                return None


def observe(candidate):
    """Observe one native process binding; never infer expert/model readiness."""
    binding = candidate.get('physical_binding', {})
    result = dict(observed_at=time.time(), state='unknown', model_readiness='unverified',
                  effect='observe_status', started_services=False)
    if candidate.get('provider') == 'hermes-profile':
        provider = Path.home()/'.hermes/hermes-agent'
        interpreter = provider/'venv/bin/python'
        home = Path(binding.get('hermes_home', ''))
        profile = binding.get('profile', '')
        if not home.is_absolute() or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', profile):
            return dict(result, reason='Invalid native profile binding')
        expected = home if profile == 'default' else home/'profiles'/profile
        if str(expected) != binding.get('path') or any(p.is_symlink() for p in [expected, *expected.parents]):
            return dict(result, reason='Profile binding changed or traverses a link')
        if not expected.is_dir() or not interpreter.is_file():
            return dict(result, reason='Profile or installed Hermes runtime is unavailable')
        data = _run_json([str(interpreter), '-I', '-B', '-c', PROFILE_STATUS],
                         dict(provider_root=str(provider), profile_home=str(expected)))
        if data is None or not isinstance(data.get('gateway_running'), bool):
            return dict(result, reason='Native Hermes status could not be observed')
        return dict(result, state='gateway_running' if data['gateway_running'] else 'gateway_not_running',
                    gateway_running=data['gateway_running'], provider='Hermes native gateway status',
                    reason='Process observation only; no question was sent to the expert')
    if candidate.get('provider') == 'hermes-compose':
        container = binding.get('container_name', '')
        executable = shutil.which('docker')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', container) or not executable:
            return dict(result, reason='Docker or the declared container binding is unavailable')
        identity = _runtime_identity(candidate)
        context = _run_json([executable, 'context', 'inspect', '--format', DOCKER_CONTEXT_FORMAT]) or {}
        host_override = os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None
        runtime = dict(fingerprint=identity, context=_text(context.get('name'), 120),
                       endpoint=_endpoint(host_override or context.get('host')),
                       selection='DOCKER_HOST' if host_override else 'Docker context')
        result['runtime'] = runtime
        data = _run_json([executable, 'inspect', '--type', 'container', '--format', DOCKER_FORMAT, container])
        if identity != _runtime_identity(candidate):
            return dict(result, reason='Docker context changed during observation; observe again')
        if data is None or not isinstance(data.get('running'), bool):
            return dict(result, reason='The declared container could not be observed in the configured Docker context')
        expected_directory = str(Path(binding.get('compose', '')).parent)
        config_files=data.get('compose_files') or ''
        declared_files=[]
        if isinstance(config_files,str) and len(config_files)<16384:
            declared_files=[os.path.normpath(str(Path(expected_directory)/p)) for p in config_files.split(',')[:16] if p]
        selected_file=os.path.normpath(binding.get('compose',''))
        image_evidence='matches' if binding.get('image') and data.get('image')==binding['image'] else 'undeclared' if not binding.get('image') else 'mismatch'
        binding_matches = (image_evidence=='matches' and
                           data.get('compose_service') == binding.get('service') and
                           data.get('compose_directory') == expected_directory and selected_file in declared_files)
        return dict(result, state=('container_running' if data['running'] else 'container_stopped') if binding_matches else 'binding_unverified',
                    container_running=data['running'], binding_matches=binding_matches,image_evidence=image_evidence,
                    container_status=_text(data.get('status'), 80), provider='Docker inspect',
                    reason='Container identity and process observation only; model and expert readiness remain unverified')
    return dict(result, reason='No supported status observer for this provider')


def inspect_star(center, cache_path, *, refresh=False, observe_status=False):
    import navcom_stars
    candidate = center.get('star')
    if center.get('kind') != 'star' or not isinstance(candidate, dict):
        raise ValueError('Select a star destination with recorded provider metadata')
    gaps = list(candidate.get('gaps', []))
    metadata_at = center.get('observed_at') or center.get('provenance', {}).get('observed_at')
    cache_path = Path(cache_path)
    center_fingerprint=hashlib.sha256(json.dumps(candidate,sort_keys=True).encode()).hexdigest()
    metadata_path=cache_path/(hashlib.sha256(center['id'].encode()).hexdigest()+'.metadata.json')
    metadata_cached=True
    if metadata_path.is_file() and metadata_path.stat().st_size<2*1024*1024:
        try:
            saved=json.loads(metadata_path.read_text())
            if saved.get('center_fingerprint')==center_fingerprint and saved.get('candidate',{}).get('id')==candidate['id']:
                candidate=saved['candidate'];metadata_at=saved['observed_at'];gaps=list(saved['gaps'])
        except (OSError,ValueError,KeyError,TypeError):pass
    if refresh:
        binding = candidate.get('physical_binding', {})
        if candidate.get('provider') == 'hermes-profile':
            discovered = navcom_stars.discover([], cache_path/'discovery', profile_home=binding.get('hermes_home'))
        elif candidate.get('provider') == 'hermes-compose':
            discovered = navcom_stars.discover([dict(root=binding['repository'], id=next(iter(candidate.get('source_ids', [])), None))], cache_path/'discovery')
        else:
            raise ValueError('No metadata refresher for this star provider')
        fresh = next((item for item in discovered['candidates'] if item['id'] == candidate['id']), None)
        if fresh is None:
            raise ValueError('This star declaration is no longer discoverable; refresh the chart')
        candidate = fresh
        metadata_at = discovered['observed_at']
        gaps = list(candidate.get('gaps', [])) + discovered.get('gaps', [])
        _atomic_json(metadata_path,dict(center_fingerprint=center_fingerprint,candidate=candidate,observed_at=metadata_at,gaps=gaps))
        metadata_cached=False
    fingerprint = hashlib.sha256(json.dumps([VERSION, candidate, _runtime_identity(candidate)], sort_keys=True).encode()).hexdigest()
    path = cache_path/(fingerprint+'.json')
    observation = None
    cached = False
    if path.is_file() and path.stat().st_size < 65536:
        try:
            observation = json.loads(path.read_text())
            cached = True
        except (ValueError, OSError):
            pass
    # An explicit Observe is a fresh process check. Ordinary dossier browsing
    # reuses the dated observation and its recorded runtime location.
    if observe_status:
        observation = observe(candidate)
        _atomic_json(path,observation)
        cached = False
    return dict(schema_version=1, type='star', star_id=center['id'], label=candidate.get('name', center['label']),
        qualification=candidate.get('qualification', 'unconfirmed'), provider=candidate.get('provider'),
        description=candidate.get('description', ''), description_auto=candidate.get('description_auto', False),
        metadata_observed_at=metadata_at, metadata_cached=metadata_cached,cached=cached, observation=observation,
        availability=candidate.get('availability', {'state':'unknown'}),
        physical=candidate.get('physical_binding', {}), charter_refs=candidate.get('charter_refs', []),
        steward_refs=candidate.get('steward_refs', []), interfaces=candidate.get('interfaces', []),
        version_evidence=candidate.get('version_evidence', {}), evidence=candidate.get('evidence', []), gaps=gaps,
        capabilities_policy='Inspect reads cached metadata. Observe checks an existing process. Asking the agent is a separate action that may use its configured model and tools.')
