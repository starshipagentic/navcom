"""Reviewable native expert handoffs, never an embedded agent executor.

Hermes chat may run tools, hooks, network requests and writes. Preparation only
reads provider metadata; confirmation revalidates that metadata and, for Docker,
the existing container binding. Neither operation sends a question to an agent.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

from navcom_space import kill_group


class StarChatError(ValueError):
    pass


EFFECTS = [
    "Opening the command sends this question to the selected Hermes expert.",
    "Hermes uses its configured model, credentials, context, tools and hooks; it may contact remote services, change files or submit work.",
    "Hermes may save the conversation and update its native session or skill files.",
    "NavCom does not enforce time or output limits after the command opens in a native terminal; use that terminal to interrupt it.",
]
PREPARE_SECONDS = 15  # Metadata preparation budget; reported as preparation_bounds.seconds.

# The installed Python entry point, with its import location pinned before any
# Hermes module loads. -I ignores ambient PYTHONPATH/PYTHONHOME and user sites.
# This constant is owned by NavCom, never read from a profile or project.
ENTRYPOINT = "import sys; sys.path.insert(0, sys.argv.pop(1)); from hermes_cli.main import main; main()"
PROFILE_DESTINATION = "import os,sys,json; sys.path.insert(0,sys.argv[1]); os.environ['HERMES_HOME']=sys.argv[2]; from hermes_cli.profiles import resolve_profile_env; print(json.dumps(resolve_profile_env(sys.argv[3])))"


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _identity(path, *, contents=False, maximum=2 * 1024 * 1024):
    path = Path(path)
    try:
        stat = path.stat()
        if not path.is_file():
            raise OSError()
        result = dict(path=str(path), resolved=str(path.resolve()), device=stat.st_dev,
                      inode=stat.st_ino, size=stat.st_size, modified_ns=stat.st_mtime_ns)
        if contents:
            if stat.st_size > maximum:
                raise StarChatError("Installed provider source exceeds the inspection budget")
            with path.open("rb") as stream:
                data = stream.read(maximum + 1)
            if len(data) > maximum:
                raise StarChatError("Installed provider source exceeds the inspection budget")
            result["sha256"] = hashlib.sha256(data).hexdigest()
        return result
    except OSError as exc:
        raise StarChatError("The selected installed provider is unavailable") from exc


def _installed():
    return Path.home() / ".hermes/hermes-agent"


def _local_provider():
    """Read the installed parser as syntax; never import chat startup code."""
    root = _installed()
    parser = root / "hermes_cli/_parser.py"
    identity = {str(path.relative_to(root)): _identity(path, contents=True)
                for path in (parser, root / "hermes_cli/main.py", root / "hermes_cli/profiles.py",
                             root / "hermes_constants.py", root / "toolsets.py", root / "hermes_cli/oneshot.py")}
    launcher = root / "venv/bin/hermes"
    identity["launcher"] = _identity(launcher, contents=True, maximum=65536)
    identity["interpreter"] = _identity(root / "venv/bin/python")
    if not os.access(launcher, os.X_OK):
        raise StarChatError("The installed Hermes launcher is not executable")
    try:
        with parser.open("rb") as stream:
            parser_bytes = stream.read(2 * 1024 * 1024 + 1)
        with launcher.open("rb") as stream:
            launcher_bytes = stream.read(65537)
        if len(parser_bytes) > 2 * 1024 * 1024 or len(launcher_bytes) > 65536:
            raise StarChatError("Installed provider source exceeds the inspection budget")
        tree = ast.parse(parser_bytes)
        options = {value.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                   and ((isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument")
                        or (isinstance(node.func, ast.Name) and node.func.id == "_inherited_flag"))
                   for value in node.args if isinstance(value, ast.Constant) and isinstance(value.value, str)}
        pre_flags = next((ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.AnnAssign)
                          and isinstance(node.target, ast.Name) and node.target.id == "PRE_ARGPARSE_INHERITED_FLAGS"), [])
        launcher_tree = ast.parse(launcher_bytes)
    except (OSError, ValueError, SyntaxError) as exc:
        raise StarChatError("Installed Hermes CLI metadata could not be verified") from exc
    if "--query" not in options or ("--profile", True) not in pre_flags or not any(isinstance(n, ast.ImportFrom) and n.module == "hermes_cli.main" for n in ast.walk(launcher_tree)):
        raise StarChatError("Installed Hermes does not expose the verified native chat entry point")
    return dict(launcher=str(launcher), interpreter=str(root / "venv/bin/python"), root=str(root),
                identity=identity, options=sorted(options))


def _literal_path(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise StarChatError("Invalid provider location")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise StarChatError("Provider locations must be absolute literal paths")
    return path


def _profile_destination(runtime, home, profile):
    """Resolve using native path rules without importing chat or reading config."""
    try:
        result = subprocess.run([runtime["interpreter"], "-I", "-B", "-c", PROFILE_DESTINATION,
            runtime["root"], str(home), profile], capture_output=True, timeout=3, cwd=runtime["root"])
        if result.returncode or len(result.stdout) > 8192 or len(result.stderr) > 65536:
            raise StarChatError("Native Hermes could not verify the selected profile destination")
        destination = json.loads(result.stdout)
        if not isinstance(destination, str):
            raise ValueError()
        return destination
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise StarChatError("Native Hermes could not verify the selected profile destination") from exc


def _worker(request):
    """Reuse the existing native inventory; all subprocess work stays metadata-only."""
    import navcom_stars
    import navcom_star_inspection

    selected = request["candidate"]
    binding = selected.get("physical_binding", {})
    provider = selected.get("provider")
    options = dict(max_roots=1, max_dirs=150, max_files=250, max_bytes=1024 * 1024,
                   seconds=min(2, request["seconds"]), native_seconds=min(12, request["seconds"]))
    if provider == "hermes-profile":
        home = _literal_path(binding.get("hermes_home"))
        profile = binding.get("profile", "")
        if not isinstance(profile, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile):
            raise StarChatError("Invalid native profile identity")
        expected = home if profile == "default" else home / "profiles" / profile
        if str(expected) != binding.get("path") or any(p.is_symlink() for p in (expected, *expected.parents)):
            raise StarChatError("The native profile location changed or traverses a link")
        found = navcom_stars.discover([], request["cache"] + "/discovery", profile_home=home, **options)
        runtime = _local_provider()
        if _profile_destination(runtime, home, profile) != str(expected):
            raise StarChatError("Native Hermes resolves this profile to a different home; refresh discovery with the provider's root home")
        argv = [runtime["interpreter"], "-I", "-B", "-c", ENTRYPOINT, runtime["root"], "--profile=" + profile, "chat"]
        if "--cli" in runtime["options"]:
            argv.append("--cli")
        cwd, environment = str(expected), {"HERMES_HOME": str(home)}
        runtime_identity = runtime["identity"]
        observation = None
    elif provider == "hermes-compose":
        root = _literal_path(binding.get("repository"))
        compose = _literal_path(binding.get("compose"))
        if not compose.is_relative_to(root):
            raise StarChatError("The Compose declaration is outside its recorded repository")
        # A catalog batch may have first found this declaration under a broad
        # inventory parent. Reuse native Git discovery to refresh its repository
        # directly; otherwise unrelated sibling projects can exhaust the budget.
        from navcom_source_discovery import _git_root
        discovery_root = _git_root(compose.parent)
        if not discovery_root.is_relative_to(root.resolve()):
            raise StarChatError("The selected declaration resolved outside its recorded inventory root")
        if not (discovery_root / ".git").exists():
            discovery_root = root
        found = navcom_stars.discover([dict(root=str(discovery_root), id=next(iter(selected.get("source_ids", [])), None))],
                                     request["cache"] + "/discovery", **options)
        found["coverage"] = dict(found["coverage"], selected_root=str(discovery_root), recorded_inventory_root=str(root))
        executable = shutil.which("docker")
        if not executable or Path(executable).resolve().is_relative_to(root):
            raise StarChatError("An installed Docker executable outside the project is required")
        container = binding.get("container_name", "")
        if not isinstance(container, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", container):
            raise StarChatError("A literal container identity is required")
        # A bare docker command can be redirected to a different daemon. This
        # first adapter supports a named context only, never secret-bearing host
        # overrides or an unpinned inherited environment.
        if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT"):
            raise StarChatError("Select a named Docker context before preparing this native handoff; DOCKER_HOST override is not supported")
        runtime_identity = dict(executable=_identity(executable), context=navcom_star_inspection._runtime_identity(selected))
        observation = navcom_star_inspection.observe(selected) if request["observe"] else None
        if observation is not None and (observation.get("state") != "container_running" or not observation.get("binding_matches")):
            raise StarChatError("The running container does not match the declared image and Compose binding")
        context = observation.get("runtime", {}).get("context") if observation else None
        if observation is not None and (not isinstance(context, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", context)):
            raise StarChatError("The Docker context could not be pinned for this handoff")
        if runtime_identity["context"] != navcom_star_inspection._runtime_identity(selected):
            raise StarChatError("Docker runtime selection changed during preparation")
        argv = [executable] + (["--context", context] if context else []) + ["exec", container, "hermes", "chat"]
        cwd, environment = str(compose.parent), {"DOCKER_CONFIG": str(Path(os.environ.get("DOCKER_CONFIG") or Path.home() / ".docker").expanduser().resolve())}
    else:
        raise StarChatError("No verified native handoff exists for this provider")
    fresh = next((row for row in found["candidates"] if row["id"] == selected.get("id")), None)
    if fresh is None or fresh.get("provider") != provider or fresh.get("provider_identity") != selected.get("provider_identity"):
        raise StarChatError("The selected expert declaration is no longer discoverable; refresh the chart")
    if provider == "hermes-compose" and fresh.get("physical_binding", {}).get("repository") == str(discovery_root):
        # Repository is the inventory scope supplied to discovery, not the
        # provider identity (which is the exact Compose path + service).
        fresh = dict(fresh, physical_binding=dict(fresh["physical_binding"], repository=str(root)))
    if fresh.get("physical_binding") != binding:
        raise StarChatError("The expert's physical binding changed; refresh the chart before asking")
    if fresh.get("qualification") == "incomplete" or not any(i.get("effect") == "ask_agent" for i in fresh.get("interfaces", [])):
        raise StarChatError("The selected expert has no complete native ask declaration")
    argv.append("--query=" + request["question"])
    return dict(candidate=fresh, argv=argv, cwd=cwd, environment=environment,
                runtime_identity=runtime_identity, observation=observation,
                metadata_fingerprint=found["fingerprint"], metadata_observed_at=found["observed_at"], coverage=found["coverage"])


SCRIPT = """import json,sys
sys.path.insert(0,sys.argv[1])
import navcom_star_chat as chat
try:
 result={'ok':True,'value':chat._worker(json.load(sys.stdin))}
except chat.StarChatError as exc:
 result={'ok':False,'error':str(exc)}
except Exception:
 result={'ok':False,'error':'Native metadata preparation failed; no question was sent'}
print(json.dumps(result))
"""


def _run(request, seconds):
    """Bound metadata and status children together, never run a chat command."""
    with tempfile.TemporaryDirectory(prefix="navcom-ask-review-") as cwd:
        with tempfile.TemporaryFile() as input_file, tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
            input_file.write(json.dumps(request).encode()); input_file.seek(0)
            process = subprocess.Popen([sys.executable, "-I", "-B", "-c", SCRIPT, str(Path(__file__).parent)],
                stdin=input_file, stdout=output, stderr=errors, cwd=cwd, start_new_session=True)
            deadline = time.monotonic() + seconds
            try:
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        raise StarChatError("Expert preparation time budget reached; no question was sent")
                    if os.fstat(output.fileno()).st_size > 2 * 1024 * 1024 or os.fstat(errors.fileno()).st_size > 65536:
                        raise StarChatError("Expert preparation output budget reached; no question was sent")
                    try:
                        process.wait(timeout=.025)
                    except subprocess.TimeoutExpired:
                        continue
                if process.returncode or os.fstat(output.fileno()).st_size > 2 * 1024 * 1024 or os.fstat(errors.fileno()).st_size > 65536:
                    raise StarChatError("Expert preparation failed or exceeded its output budget; no question was sent")
                output.seek(0)
                result = json.load(output)
                if not result.get("ok"):
                    raise StarChatError(result.get("error", "Expert preparation failed"))
                return result["value"]
            finally:
                kill_group(process)


def _prepare(center, question, cache_path, *, observe):
    if not isinstance(question, str) or not question.strip() or len(question) > 4000 or any((ord(c) < 32 and c not in "\n\t") or 127 <= ord(c) <= 159 for c in question):
        raise StarChatError("Supply a question of 1–4,000 characters without terminal control characters")
    candidate = center.get("star")
    if center.get("kind") != "star" or not isinstance(candidate, dict) or center.get("id") != candidate.get("id"):
        raise StarChatError("Select one star with recorded provider identity")
    if len(json.dumps(candidate)) > 256 * 1024:
        raise StarChatError("Selected expert metadata exceeds the review budget")
    cache = str(Path(cache_path).expanduser().resolve())
    result = _run(dict(candidate=candidate, question=question, cache=cache, seconds=PREPARE_SECONDS, observe=observe), PREPARE_SECONDS)
    fresh = result["candidate"]
    # Observed runtime state and clock times are not part of consent identity;
    # metadata, configured runtime, exact question and local provider bytes are.
    review_token = _digest([1, _identity(Path(__file__), contents=True)["sha256"], fresh,
                            result["runtime_identity"], result["metadata_fingerprint"], question])
    environment = result["environment"]
    command = "cd " + shlex.quote(result["cwd"]) + " && " + shlex.join(
        (["env"] + [key + "=" + value for key, value in sorted(environment.items())] if environment else []) + result["argv"])
    return dict(schema_version=1, action="ask_agent", mode="native_handoff", state="review_required",
                star_id=center["id"], provider=fresh["provider"], provider_identity=fresh["provider_identity"],
                label=fresh["name"], description=fresh["description"], qualification=fresh["qualification"],
                question=question, review_token=review_token, handoff=dict(argv=result["argv"], cwd=result["cwd"], env=environment, command=command),
                effects=EFFECTS, execution=dict(question_sent=False, agent_started=False, navcom_executes_chat=False,
                    tools_disabled=False, inference_only_verified=False, native_time_limit=None, native_output_limit=None),
                readiness="unverified", observation=result["observation"], metadata_observed_at=result["metadata_observed_at"],
                metadata_fingerprint=result["metadata_fingerprint"], coverage=result["coverage"],
                preparation_bounds=dict(seconds=PREPARE_SECONDS, output_bytes=2 * 1024 * 1024),
                gaps=["Native chat is agentic; no supported inference-only CLI contract was verified",
                      "Container Hermes flags and loaded context have not been inspected" if fresh["provider"] == "hermes-compose" else "The installed provider reads its own private configuration when launched"])


def prepare(center, question, cache_path):
    """Build a review without contacting Docker, a gateway or any model."""
    return _prepare(center, question, cache_path, observe=False)


def handoff(center, question, cache_path, *, review_token):
    """Revalidate an explicitly reviewed handoff; return it without launching it.

    A review token detects stale inputs; it is not an authorization credential.
    The caller must obtain the user's explicit Open in Hermes action separately.
    """
    if not isinstance(review_token, str) or not re.fullmatch(r"[a-f0-9]{64}", review_token):
        raise StarChatError("Review this question and expert before opening Hermes")
    result = _prepare(center, question, cache_path, observe=True)
    if result["review_token"] != review_token:
        raise StarChatError("The question, expert metadata or runtime changed; review the handoff again")
    return dict(result, state="ready_for_native_handoff")
