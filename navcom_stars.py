"""Bounded living-expertise candidates from existing Hermes metadata.

This adapter never contacts a service, starts an agent, evaluates a Dockerfile,
or submits work. Native inventories inspect bounded metadata copies, and every
runtime remains unobserved. Candidate identity is not a promotion to a star.
"""
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

from navcom_ship_inspection import _text, commission_tools

COMPOSE_NAMES = {"compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml"}
METADATA_NAMES = COMPOSE_NAMES | {"Dockerfile", "SOUL.md", "profile.yaml", "distribution.yaml"}
SKIP_DIRS = {"node_modules", "vendor", "venv", "__pycache__", "dist", "build", "evidence", "runs", "models", "secrets", "credentials"}
OCI_KEYS = ("org.opencontainers.image.title", "org.opencontainers.image.description", "org.opencontainers.image.source")
PROVIDER_IMAGE = re.compile(r"^(?:(?:docker\.io|ghcr\.io)/)?nousresearch/hermes-agent(?::[^\s]+|@[^\s]+)?$")


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _public_reference(value):
    value = _text(value, 500)
    if value.startswith(("http://", "https://")):
        value = re.sub(r"^(https?://)[^/\s@]*@", r"\1", value)
        try:
            parsed = urlsplit(value)
            return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
        except ValueError:
            return ""
    return value


def _safe(path, root):
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return not any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1))


def _metadata(roots, profile_home, max_dirs, max_files, max_bytes, seconds):
    """Copy only named metadata; never open env/config/auth/runtime stores."""
    payload = {}; coverage = dict(directories=0, files=0, bytes=0, depth_omitted=0, policy_omitted=0, complete=True, skipped=[])
    projects = []; profile_folders = []; deadline = time.monotonic() + seconds
    def add(path, root):
        if not _safe(path, root) or not path.is_file():
            coverage["skipped"].append(dict(path=str(path), reason="missing, linked or unsupported metadata")); return
        size = path.stat().st_size
        if size > 256 * 1024 or len(payload) >= max_files or coverage["bytes"] + size > max_bytes:
            coverage["complete"] = False
            coverage["skipped"].append(dict(path=str(path), reason="metadata budget")); return
        with path.open("rb") as handle:
            data = handle.read(min(256 * 1024, max_bytes - coverage["bytes"]) + 1)
        if len(data) > min(256 * 1024, max_bytes - coverage["bytes"]):
            coverage["complete"] = False
            coverage["skipped"].append(dict(path=str(path), reason="metadata changed beyond byte budget")); return
        payload[str(path)] = data
        coverage["files"] += 1; coverage["bytes"] += len(data)
    for item in roots:
        if time.monotonic() > deadline:
            coverage["complete"] = False
            coverage["skipped"].append(dict(reason="metadata time budget")); break
        info = item if isinstance(item, dict) else dict(root=str(item))
        original = Path(info["root"]).expanduser()
        if original.is_symlink() or not original.is_dir() or any(part in {".private", ".aws", ".ssh", ".gnupg", "secrets", "credentials"} for part in original.parts):
            coverage["skipped"].append(dict(path=str(original), reason="missing or linked project root")); coverage["complete"] = False; continue
        root = original.resolve()
        projects.append(dict(root=str(root), source_id=info.get("id")))
        pending = [(root, 0)]
        while pending:
            folder, depth = pending.pop()
            if time.monotonic() > deadline:
                coverage["complete"] = False
                coverage["skipped"].append(dict(path=str(folder), reason="metadata time budget")); break
            if coverage["directories"] >= max_dirs:
                coverage["complete"] = False
                coverage["skipped"].append(dict(path=str(folder), reason="directory budget")); break
            coverage["directories"] += 1
            try:
                entries = list(itertools.islice(folder.iterdir(), 1001))
            except OSError:
                coverage["complete"] = False; continue
            if len(entries) > 1000:
                coverage["complete"] = False
                coverage["skipped"].append(dict(path=str(folder), reason="directory fanout budget"))
            for path in sorted(entries[:1000], reverse=True):
                if path.is_symlink() or path.name.startswith(".") or path.name in SKIP_DIRS:
                    coverage["policy_omitted"] += 1
                    continue
                if path.is_dir():
                    if depth < 3:
                        pending.append((path, depth + 1))
                    else:
                        coverage["complete"] = False
                        coverage["depth_omitted"] += 1
                elif path.name in METADATA_NAMES:
                    add(path, root)
    home = None
    if profile_home:
        candidate = Path(profile_home).expanduser()
        if candidate.is_symlink() or not candidate.is_dir():
            coverage["complete"] = False
            coverage["skipped"].append(dict(path=str(candidate), reason="native profile home unavailable or linked"))
        else:
            home = candidate.resolve()
            folders = [home]
            if (home / "profiles").is_dir() and not (home / "profiles").is_symlink():
                children = list(itertools.islice((home / "profiles").iterdir(), 101))
                if len(children) > 100:
                    coverage["complete"] = False
                    coverage["skipped"].append(dict(path=str(home / "profiles"), reason="profile count budget"))
                folders.extend(p for p in sorted(children[:100]) if p.is_dir() and not p.is_symlink() and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", p.name))
            for folder in folders:
                if time.monotonic() > deadline:
                    coverage["complete"] = False
                    coverage["skipped"].append(dict(path=str(folder), reason="metadata time budget")); break
                profile_folders.append(str(folder))
                for name in ("profile.yaml", "distribution.yaml", "SOUL.md"):
                    path = folder / name
                    if path.exists() or path.is_symlink():
                        add(path, home)
    return projects, home, profile_folders, payload, coverage


def _build_tools(tool_root):
    """Use Starship's existing borrowed Starforge detectors; no algorithm copy."""
    root = Path(tool_root or commission_tools(borrowed=True)).expanduser().resolve()
    modules = {}; signatures = {}
    for name in ("build_systems", "config_files"):
        path = root / (name + ".py")
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 256 * 1024:
            return {}, {}, "Installed Starship build/config detectors are unavailable"
        signatures[str(path)] = _hash(path.read_bytes())
        spec = importlib.util.spec_from_file_location("_navcom_star_" + name, path)
        module = importlib.util.module_from_spec(spec)
        # exec_module may write bytecode; compile into the isolated module instead.
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
        modules[name] = module
    return modules, signatures, None


def _dockerfile(raw, target=""):
    """Only literal FROM ancestry and standard OCI labels; never evaluate code."""
    labels = {}; aliases = {}; hermes = False; stage = None
    text = raw.decode("utf-8", "replace").replace("\\\n", " ")
    for line in text.splitlines():
        try:
            words = shlex.split(line, comments=True)
        except ValueError:
            continue
        if not words:
            continue
        if words[0].upper() == "FROM":
            if stage:
                aliases[stage] = (hermes, dict(labels))
            tokens = [w for w in words[1:] if not w.startswith("--")]
            if tokens:
                hermes, labels = aliases.get(tokens[0], (bool(PROVIDER_IMAGE.fullmatch(tokens[0])), {}))
                labels = dict(labels)
                stage = tokens[2] if len(tokens) >= 3 and tokens[1].upper() == "AS" else None
        elif words[0].upper() == "LABEL":
            for word in words[1:]:
                key, sep, value = word.partition("=")
                if sep and key in OCI_KEYS and "$" not in value:
                    labels[key] = _text(value, 500)
    if stage:
        aliases[stage] = (hermes, labels)
    return aliases.get(target, (False, {})) if target else (hermes, labels)


# Runs in an explicitly selected installed runtime, never from a project cwd.
# Hermes receives only copied profile/distribution metadata, not credentials,
# config, sessions, skills, process state or real wrappers. Its own list_profiles
# still decides profile IDs and metadata. Gateway availability is intentionally
# not copied into the resulting DTO.
NATIVE_SCRIPT = r'''
import json,sys,os
from pathlib import Path
request=json.loads(sys.stdin.read())
try:
 import yaml
except ImportError:
 print(json.dumps({'error':'PyYAML is unavailable in the selected optional metadata runtime'}));sys.exit(0)
out={'compose':{},'profiles':[],'errors':[]}
for name,filename in request['compose'].items():
 try:
  data=yaml.safe_load(Path(filename).read_text()) or {}
  if not isinstance(data,dict):raise ValueError('Compose root must be a mapping')
  services=data.get('services') or {}
  if not isinstance(services,dict) or len(services)>100:raise ValueError('Compose services exceed metadata bounds')
  result={}
  def string(v):return v[:2000] if isinstance(v,str) else ''
  for key,service in services.items():
   if not isinstance(key,str) or not isinstance(service,dict):continue
   build=service.get('build')
   if isinstance(build,str):build={'context':build}
   if not isinstance(build,dict):build={}
   labels=service.get('labels') or {}
   if isinstance(labels,list):labels=dict(v.split('=',1) for v in labels if isinstance(v,str) and '=' in v)
   if not isinstance(labels,dict):labels={}
   command=service.get('command')
   result[key[:128]]={'image':string(service.get('image')),'container_name':string(service.get('container_name')),
    'command':[string(v) for v in command[:20]] if isinstance(command,list) else string(command),
    'build':{k:string(build.get(k)) for k in ('context','dockerfile','target')},
    'labels':{k:string(labels.get(k)) for k in request['oci_keys']},
    'ports_declared':bool(service.get('ports')),'entrypoint_override':bool(service.get('entrypoint'))}
  out['compose'][name]=result
 except Exception as exc:out['errors'].append({'path':name,'reason':type(exc).__name__+': metadata could not be parsed within its bounds'})
if request.get('profile_mirror'):
 try:
  for path in Path(request['profile_mirror']).rglob('*.yaml'):
   try:
    data=yaml.safe_load(path.read_text()) or {}
    if not isinstance(data,dict):raise ValueError('Metadata must be a mapping')
    names=('description','description_auto') if path.name=='profile.yaml' else ('name','version','source')
    clean={}
    for key in names:
     if key not in data:continue
     value=data[key]
     if key=='description_auto':
      if not isinstance(value,bool):raise ValueError('Description confirmation must be boolean')
      clean[key]=value
     else:
      if not isinstance(value,str):raise ValueError('Metadata text must be scalar strings')
      clean[key]=value[:2000]
    path.write_text(yaml.safe_dump(clean))
   except Exception:
    path.unlink()
    out['errors'].append({'provider':'hermes-profile','path':str(path.relative_to(request['profile_mirror'])),'reason':'Non-scalar or malformed profile metadata was excluded before native inventory'})
  sys.path.insert(0,request['hermes_source'])
  os.environ['HERMES_HOME']=request['profile_mirror']
  import hermes_cli.profiles as profiles
  if Path(profiles.__file__).resolve()!=Path(request['hermes_source']).resolve()/'hermes_cli/profiles.py':raise ValueError('Unexpected Hermes module')
  profiles._get_wrapper_dir=lambda:Path(request['empty_wrappers'])
  for profile in profiles.list_profiles():
   def text(v):return v[:2000] if isinstance(v,str) else ''
   out['profiles'].append({'name':text(profile.name),'path':str(profile.path),'description':text(profile.description),
    'description_auto':bool(profile.description_auto),'distribution_name':text(profile.distribution_name),
    'distribution_version':text(profile.distribution_version),'distribution_source':text(profile.distribution_source)})
 except Exception as exc:out['errors'].append({'provider':'hermes-profile','reason':type(exc).__name__+': native inventory could not read the bounded metadata copy'})
print(json.dumps(out))
'''


def _candidate(provider, identity, name, description, evidence, charters, binding, source_id=None, auto=False):
    gaps = ["Runtime and callable capability have not been observed", "Stewardship must be checked in the referenced charter; no structured owner was inferred"]
    if not charters:
        gaps.append("No bounded charter metadata was found")
    if not description.strip():
        gaps.append("No provider-authored expertise description was found")
    if auto:
        gaps.append("Provider description was auto-generated and is not confirmed")
    return dict(id="star-candidate:" + _hash(identity.encode())[:20], kind="star_candidate", provider=provider,
                provider_identity=identity, name=_text(name, 160), description=_text(description, 500),
                description_auto=auto, qualification="incomplete" if not charters or not description.strip() else "unconfirmed" if auto else "declared_candidate",
                evidence=evidence, charter_refs=charters, steward_refs=charters,
                physical_binding=binding, source_ids=[source_id] if source_id else [],
                availability=dict(state="unknown", checked_at=None, reason="Discovery reads metadata only"),
                interfaces=[dict(effect="inspect", transport="metadata", references=evidence + charters, support="available_metadata")], gaps=gaps)


def discover(roots=(), cache_path=None, *, profile_home=None, hermes_source=None, hermes_python=None,
             tool_root=None, max_roots=100, max_dirs=300, max_files=1000, max_bytes=4 * 1024 * 1024, seconds=3, native_seconds=15):
    """Return cached candidate DTOs from provided inventory roots/native profiles.

    roots may contain paths or existing source records with root/id. No registry
    is created and no callable interface is executed. This is not a health check.
    """
    if any(not isinstance(n,int) or n < 1 for n in (max_roots,max_dirs,max_files,max_bytes)):
        raise ValueError("Discovery budgets must be positive integers")
    if not isinstance(seconds, (int,float)) or not 0 < seconds <= 60:
        raise ValueError("Metadata time budget must be positive and at most 60 seconds")
    if not isinstance(native_seconds, (int,float)) or not 0 < native_seconds <= 15:
        raise ValueError("Native metadata time budget must be positive and at most 15 seconds")
    roots = list(roots)
    omitted = max(0, len(roots)-max_roots)
    projects, home, profile_folders, payload, coverage = _metadata(roots[:max_roots], profile_home, max_dirs, max_files, max_bytes, seconds)
    coverage.update(roots_requested=len(roots), roots_inspected=len(projects), roots_omitted=omitted)
    coverage["bounds"] = dict(max_roots=max_roots,max_dirs=max_dirs,max_depth=3,max_files=max_files,max_bytes=max_bytes,seconds=seconds,native_seconds=native_seconds)
    coverage["complete"] = coverage["complete"] and not omitted
    native_root = Path(hermes_source or Path.home()/".hermes/hermes-agent").expanduser().resolve()
    if any(native_root.is_relative_to(Path(p["root"])) for p in projects) or (home and native_root.is_relative_to(home) and native_root != Path.home()/".hermes/hermes-agent"):
        raise ValueError("Use the installed Hermes provider, never code inside an inspected project or custom profile")
    interpreter = str(hermes_python or native_root/"venv/bin/python")
    selected_tools = Path(tool_root or commission_tools(borrowed=True)).expanduser().resolve()
    if any(selected_tools.is_relative_to(Path(p["root"])) for p in projects):
        raise ValueError("Use installed build/config detectors, never code inside an inspected project")
    tools, tool_signatures, tool_gap = _build_tools(tool_root)
    signatures = {path:_hash(raw) for path,raw in sorted(payload.items())}
    for path in (native_root/"hermes_cli/profiles.py", native_root/"hermes_constants.py", native_root/"agent/skill_utils.py"):
        if path.is_file() and path.stat().st_size < 1024*1024:
            signatures[str(path)] = _hash(path.read_bytes())
    runtime_file = Path(interpreter)
    runtime_identity = dict(path=interpreter, available=runtime_file.is_file())
    if runtime_file.is_file():
        stat=runtime_file.stat();runtime_identity.update(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
    launcher=str(native_root/"venv/bin/hermes") if (native_root/"venv/bin/hermes").is_file() else shutil.which("hermes")
    launcher_identity = dict(path=launcher)
    if launcher:
        try:
            stat=Path(launcher).stat();launcher_identity.update(size=stat.st_size,mtime_ns=stat.st_mtime_ns)
        except OSError:
            launcher=None;launcher_identity["available"]=False
    fingerprint = _hash(json.dumps([_hash(Path(__file__).read_bytes()),projects,str(home),profile_folders,signatures,tool_signatures,runtime_identity,launcher_identity,coverage],sort_keys=True).encode())
    cache = Path(cache_path).expanduser().resolve() if cache_path else None
    if cache:
        if any(cache.is_relative_to(Path(p["root"])) for p in projects) or (home and cache.is_relative_to(home)):
            raise ValueError("Keep the metadata cache outside inspected roots")
        publication = cache/(fingerprint+".json")
        if publication.is_file():
            if publication.stat().st_size > 4*1024*1024:
                raise ValueError("Candidate cache exceeds its size limit")
            return dict(json.loads(publication.read_text()),cache_hit=True)
    result = dict(schema_version=1,engine="Hermes native profile inventory + Starship/Starforge build/config detectors + Compose/OCI metadata",
                  fingerprint=fingerprint,observed_at=time.time(),cache_hit=False,candidates=[],excluded=[],gaps=[],coverage=coverage)
    if tool_gap:
        result["gaps"].append(tool_gap)
        result["coverage"]["complete"]=False
    with tempfile.TemporaryDirectory(prefix="navcom-star-metadata-") as temporary:
        temp=Path(temporary);copies={}
        for index,project in enumerate(projects):
            root=Path(project["root"]);mirror=temp/("project-"+str(index));mirror.mkdir()
            for filename,raw in payload.items():
                source=Path(filename)
                if source.is_relative_to(root):
                    destination=mirror/source.relative_to(root);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw);copies[filename]=destination
        profile_mirror=None
        if home:
            profile_mirror=temp/"profiles-home";profile_mirror.mkdir()
            for folder in profile_folders:
                (profile_mirror/Path(folder).relative_to(home)).mkdir(parents=True,exist_ok=True)
            for filename,raw in payload.items():
                path=Path(filename)
                if path.is_relative_to(home) and path.name in {"profile.yaml","distribution.yaml"}:
                    destination=profile_mirror/path.relative_to(home);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
        compose={}
        for filename,copy in copies.items():
            if Path(filename).name not in COMPOSE_NAMES:continue
            if tools:
                builds=tools["build_systems"].detect_build_systems(copy.parent)
                configs=tools["config_files"].detect_config_files(copy.parent)
                if not any(b["name"]=="docker-compose" for b in builds):continue
                result.setdefault("inspection",[]).append(dict(path=str(Path(filename).parent),build_systems=builds,
                    config_files=configs,engine="installed Starship borrowed Starforge detectors"))
            else:
                # No replacement detector: report the unavailable provider.
                continue
            compose[filename]=str(copy)
        (temp/"empty-wrappers").mkdir()
        request=dict(compose=compose,profile_mirror=str(profile_mirror) if profile_mirror else None,
                     hermes_source=str(native_root),empty_wrappers=str(temp/"empty-wrappers"),oci_keys=OCI_KEYS)
        native_ok = True
        try:
            completed=subprocess.run([interpreter,"-I","-B","-c",NATIVE_SCRIPT],input=json.dumps(request),
                                     capture_output=True,text=True,timeout=native_seconds,cwd=temp)
            if completed.returncode or len(completed.stdout)>2*1024*1024:
                raise ValueError("Optional metadata runtime failed or exceeded output bounds")
            native=json.loads(completed.stdout)
            if native.get("error"):raise ValueError(native["error"])
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            result["gaps"].append("Metadata runtime unavailable: "+str(exc));native=dict(compose={},profiles=[],errors=[]);native_ok=False
            result["coverage"]["complete"]=False
        result["gaps"].extend(native.get("errors",[]))
        if native.get("errors"):
            result["coverage"]["complete"]=False
        for row in native.get("profiles",[]):
            original=home/Path(row["path"]).relative_to(profile_mirror)
            charter=str(original/"SOUL.md")
            charters=[charter] if charter in payload else []
            if not row.get("description") and not charters:
                result["excluded"].append(dict(provider="hermes-profile",path=str(original),reason="No declared expertise description or charter"));continue
            evidence=[p for p in (str(original/"profile.yaml"),str(original/"distribution.yaml")) if p in payload]
            candidate=_candidate("hermes-profile",str(original),row.get("distribution_name") or row["name"],row.get("description",""),evidence,charters,
                dict(kind="local_profile",path=str(original),profile=row["name"],hermes_home=str(home)),auto=row.get("description_auto",False))
            candidate["version_evidence"]=dict(distribution_version=_text(row.get("distribution_version"),80),distribution_source=_public_reference(row.get("distribution_source")))
            if launcher:
                prefix=[launcher]+(["-p",row["name"]] if row["name"]!="default" else [])
                candidate["interfaces"].extend([
                    dict(effect="observe_status",transport="argv_template",argv=prefix+["gateway","status"],environment={"HERMES_HOME":str(home)},support="provider_declared"),
                    dict(effect="ask_agent",transport="argv_template",argv=prefix+["chat","-q","{question}"],environment={"HERMES_HOME":str(home)},support="provider_declared")])
            else:
                candidate["gaps"].append("Hermes launcher is unavailable; no callable route exposed")
            result["candidates"].append(candidate)
        for filename,services in native.get("compose",{}).items():
            file=Path(filename);project=max((p for p in projects if file.is_relative_to(Path(p["root"]))),key=lambda p:len(p["root"]))
            root=Path(project["root"])
            for service,data in services.items():
                context=data["build"].get("context") or ".";docker_name=data["build"].get("dockerfile") or "Dockerfile"
                dockerfile=Path(os.path.abspath(file.parent/context/docker_name))
                target=data["build"].get("target", "")
                built,labels=_dockerfile(payload[str(dockerfile)],target) if str(dockerfile) in payload and dockerfile.is_relative_to(root) else (False,{})
                provider=built if target else bool(PROVIDER_IMAGE.fullmatch(data["image"])) or built
                if not provider:
                    result["excluded"].append(dict(path=filename,service=service,reason="No supported Hermes image or final build-stage identity"));continue
                labels.update({k:_text(v,500) for k,v in data["labels"].items() if v})
                charter_paths=[str(file.parent/"home/SOUL.md"),str(file.parent/"SOUL.md")]
                charters=[p for p in charter_paths if p in payload]
                evidence=[filename]+([str(dockerfile)] if str(dockerfile) in payload else [])
                binding=dict(kind="compose_service",repository=str(root),compose=filename,service=service,
                             container_name=_text(data["container_name"],128),image=_text(data["image"],200),ports_declared=data["ports_declared"])
                candidate=_candidate("hermes-compose",filename+"#"+service,labels.get(OCI_KEYS[0]) or service,
                    labels.get(OCI_KEYS[1],""),evidence,charters,binding,project.get("source_id"))
                candidate["version_evidence"]=dict(image=binding["image"],source=_public_reference(labels.get(OCI_KEYS[2])))
                candidate["gaps"].append("Adjacent source charter is not proof of the current container's loaded home")
                container=data["container_name"]
                if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}",container) and not data["entrypoint_override"]:
                    candidate["interfaces"].extend([
                        dict(effect="observe_status",transport="argv_template",argv=["docker","inspect","--format","{{json .State}}",container],support="provider_declared"),
                        dict(effect="ask_agent",transport="argv_template",argv=["docker","exec",container,"hermes","chat","-q","{question}"],support="provider_declared")])
                else:
                    candidate["gaps"].append("Container binding is absent/dynamic or entrypoint overridden; no callable route exposed")
                candidate["gaps"].append("No structured submit-work interface was discovered; arbitrary README commands and HTTP routes were not inferred")
                result["candidates"].append(candidate)
    result["candidates"].sort(key=lambda c:c["id"])
    if cache and native_ok and not native.get("errors"):
        cache.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd,name=tempfile.mkstemp(prefix=".stars-",dir=cache)
        try:
            with os.fdopen(fd,"w") as handle:json.dump(result,handle,ensure_ascii=False)
            os.replace(name,publication)
        finally:
            if os.path.exists(name):os.unlink(name)
    return result
