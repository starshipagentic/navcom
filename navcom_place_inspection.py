"""Bounded, cached observations of a place's physical checkouts using native Git.

Conceptual membership comes from the chart. This observer establishes only where
that recorded code is stored and which Git checkout was observed there. It does
not scan source, fetch, choose a preferred copy, or establish application runtime.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time

from navcom_space import _atomic, _writer

VERSION = 1
MAX_LOCATIONS = 24
SECONDS = 12


def _text(value):
    return re.sub(r'[\x00-\x1f\x7f]', '', str(value or ''))[:4096]


def _git(root, args, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Location observation reached its time budget.')
    # A caller's Git directory/index/worktree overrides must not redirect the
    # selected location. These commands read refs/paths and never run hooks.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_TERMINAL_PROMPT='0', LC_ALL='C')
    try:
        result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *args],
                                env=env, capture_output=True, text=True, timeout=min(2, remaining))
    except subprocess.TimeoutExpired:
        raise TimeoutError('Native Git did not finish within the observation budget.') from None
    except OSError:
        raise ValueError('Native Git is unavailable; filesystem location remains observable.') from None
    if len(result.stdout) > 32768:
        raise ValueError('Native Git metadata exceeded the output limit.')
    return result.returncode, result.stdout.strip()


def _observe(location, host, deadline):
    value = location.get('path') if isinstance(location, dict) else location
    item = dict(path=_text(value), availability='unobserved', observed_at=time.time(), git=None)
    recorded_host = location.get('host') if isinstance(location, dict) else None
    if recorded_host and recorded_host not in (host, 'localhost', '127.0.0.1'):
        item.update(host=_text(recorded_host), gap='Recorded host differs from this observer; no remote path was opened.')
        return item
    item['host'] = host
    if not isinstance(value, str) or '\x00' in value or not Path(value).is_absolute() or '..' in Path(value).parts:
        item['gap'] = 'An exact absolute location is required.'
        return item
    root = Path(value)
    try:
        root.stat()
        if not root.is_dir():
            item['availability'] = 'not-directory'
            return item
        item.update(availability='present', resolved_path=str(root.resolve()))
        status, raw = _git(root, ['rev-parse', '--path-format=absolute', '--show-toplevel', '--git-common-dir', '--git-dir'], deadline)
        if status:
            item['gap'] = 'Git checkout metadata is unavailable at this location.'
            return item
        paths = raw.splitlines()
        if len(paths) != 3 or not all(Path(p).is_absolute() for p in paths):
            item['gap'] = 'Native Git did not return an unambiguous checkout binding.'
            return item
        top, common, gitdir = [str(Path(p).resolve()) for p in paths]
        if not root.resolve().is_relative_to(Path(top)):
            item['gap'] = 'Git root does not contain the recorded location.'
            return item
        item['git'] = dict(root=top, common_dir=common, git_dir=gitdir, commit=None, branch=None, head_state='unknown')
        status, commit = _git(root, ['rev-parse', '--verify', 'HEAD'], deadline)
        if status == 0 and re.fullmatch(r'[0-9a-f]{40,64}', commit):
            item['git']['commit'] = commit
        status, branch = _git(root, ['symbolic-ref', '--quiet', '--short', 'HEAD'], deadline)
        if status == 0 and branch:
            item['git'].update(branch=_text(branch), head_state='branch' if item['git']['commit'] else 'unborn')
        elif status == 1 and item['git']['commit']:
            item['git']['head_state'] = 'detached'
    except FileNotFoundError:
        item['availability'] = 'missing'
    except (OSError, ValueError, TimeoutError) as exc:
        item['gap'] = _text(exc)
    return item


def _relationships(locations):
    result = []
    for i, left in enumerate(locations):
        if not left.get('git'):
            continue
        for right in locations[i + 1:]:
            if not right.get('git'):
                continue
            a, b = left['git'], right['git']
            if a['common_dir'] != b['common_dir']:
                kind, basis = 'independent_repositories', 'Different native Git common directories.'
            elif a['root'] == b['root']:
                kind, basis = 'same_checkout', 'The recorded paths resolve inside the same checkout.'
            else:
                kind, basis = 'linked_worktrees', 'Distinct checkout roots share a native Git common directory.'
            result.append(dict(left=left['path'], right=right['path'], kind=kind, basis=basis,
                               same_commit=bool(a['commit'] and b['commit'] and a['commit'] == b['commit'])))
    return result


def inspect_place(entity, cache_path, *, refresh=False):
    if entity.get('kind') not in ('planet', 'moon', 'district') or not entity.get('id'):
        raise ValueError('Choose a product, experiment or district for location inspection.')
    host = socket.gethostname()
    locations = entity.get('locations', [])
    if not isinstance(locations, list):
        locations = []
    unique = {}
    for value in locations:
        item = value if isinstance(value, dict) else dict(path=value)
        if isinstance(item.get('path'), str):
            unique[(item.get('host'), item['path'])] = dict(path=item['path'], host=item.get('host'))
    identity = dict(version=VERSION, place=entity['id'], host=host, locations=list(unique.values()))
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    cache = Path(cache_path) / (fingerprint + '.json')
    if not refresh:
        try:
            saved = json.loads(cache.read_text())
            if saved.get('fingerprint') == fingerprint and saved.get('schema_version') == VERSION:
                return dict(saved, cached=True)
        except (OSError, ValueError):
            pass
    with _writer(cache):
        deadline = time.monotonic() + SECONDS
        observed = []
        for item in list(unique.values())[:MAX_LOCATIONS]:
            if time.monotonic() >= deadline:
                break
            observed.append(_observe(item, host, deadline))
        omitted = len(unique) - len(observed)
        gaps = [entry['path'] + ': ' + entry['gap'] for entry in observed if entry.get('gap')]
        if omitted:
            gaps.append(str(omitted) + ' locations remain unobserved because of the location or time bound.')
        if not unique:
            gaps.append('No physical code locations are recorded for this destination.')
        result = dict(schema_version=VERSION, type='place', place_id=entity['id'], fingerprint=fingerprint,
                      observed_at=time.time(), cached=False, observer_host=host, locations=observed,
                      relationships=_relationships(observed), gaps=gaps,
                      coverage=dict(recorded=len(unique), observed=len(observed), omitted=omitted),
                      policy='Dated local filesystem and native Git observations. Cached until refreshed; '
                             'working changes, runtime, access and preferred copy are not determined.')
        _atomic(cache, result)
    return result
