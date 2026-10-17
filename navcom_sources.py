"""CLI orchestration for optional Starforge source harvesting and cached search."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys


def parser():
    p = argparse.ArgumentParser(
        prog="navcom sources",
        description="Harvest local code and docs with Starforge; search cached snapshots without a model.",
        epilog="Starforge must be installed for harvest/search. Set NAVCOM_STARFORGE_PYTHON to its Python interpreter if it is not on PATH. No Starship dependency.",
    )
    subs = p.add_subparsers(dest="action")
    for name, description in [
        ("harvest", "Add/update a local source and its explicit scope."),
        ("discover", "Discover indexed repositories and bounded code/document scopes; optionally harvest them."),
        ("refresh", "Check all registered sources; analyze only changed contents."),
        ("list", "Show harvested sources, scope and coverage."),
        ("search", "Search Starforge concepts and literal code/document text."),
        ("read", "Read a bounded window of an exact harvested code/document file."),
    ]:
        s = subs.add_parser(name, help=description, description=description)
        s.add_argument(
            "--cache",
            type=Path,
            help="Private source cache; default NAVCOM_SOURCES_CACHE or sources beside the conversation index.",
        )
        s.add_argument(
            "--json",
            action="store_true",
            help="Structured output; progress/errors go to stderr.",
        )
        if name == "discover":
            s.add_argument("--index",type=Path,help="Conversation index used for discovery.")
            s.add_argument("--within",help="Existing Atlas collection to inspect.")
            s.add_argument("--limit",type=int,default=200,help="Indexed projects per page (default 200).")
            s.add_argument("--offset",type=int,default=0)
            s.add_argument("--harvest",action="store_true",help="Run existing Starforge harvest on these discovered scopes.")
        if name == "read":
            s.add_argument("source",help="Exact source ID, unique label or root from sources list/search.")
            s.add_argument("path",help="File path from a source hit, or a relative path inside that source snapshot.")
            s.add_argument("--line",type=int,default=1,help="First line to read (default 1).")
            s.add_argument("--limit",type=int,default=80,help="Maximum lines, 1–200 (default 80); byte limits also apply.")
            s.add_argument("--snapshot",default="",help="Pin the artifact key returned by a previous read.")
            s.add_argument("--published",type=float,help="Require matching publication unless --snapshot pins the same currently published artifact.")
            s.add_argument("--history",default="",help="Pinned history receipt ID returned by history explore.")
            s.add_argument("--history-cache",type=Path,help="Historical snapshot cache; default NAVCOM_HISTORY_CACHE or beside the index.")
            s.add_argument("--index",type=Path,help="Determine default cache locations; no conversations are read.")
        if name == "harvest":
            s.add_argument(
                "root",
                type=Path,
                help="Local project directory. Original files are read only.",
            )
            s.add_argument(
                "--include",
                action="append",
                help="Relative file/directory; repeat for multiple scopes. Default: entire root, with exclusions.",
            )
            s.add_argument(
                "--index",
                type=Path,
                help="Conversation index used to discover the exact project handoff.",
            )
            s.add_argument(
                "--max-files",
                type=int,
                default=10000,
                help="Abort rather than truncate above this count (default 10000).",
            )
            s.add_argument(
                "--max-bytes",
                type=int,
                default=64 * 1024 * 1024,
                help="Abort above total snapshot bytes (default 64 MiB).",
            )
            s.add_argument(
                "--max-file-bytes",
                type=int,
                default=2 * 1024 * 1024,
                help="Abort above individual file bytes (default 2 MiB).",
            )
        if name == "search":
            s.add_argument("--path",action="append",default=[],help="Relative file/directory within --within; repeat to search a district. Applies to both paths.")
            s.add_argument("words", nargs="+")
            s.add_argument(
                "--within",
                help="Exact source ID, unique label, or absolute root from sources list.",
            )
            s.add_argument(
                "--mode",
                choices=["both", "concept", "text"],
                default="both",
                help="Default both: ranked gems plus literal phrase matches across code/docs.",
            )
            s.add_argument(
                "--regex",
                action="store_true",
                help="Treat text query as a regex, instead of a literal phrase (text path only).",
            )
            s.add_argument(
                "--ext", help="Text path only: restrict extension, e.g. md or .ts."
            )
            s.add_argument(
                "--limit",
                type=int,
                default=20,
                help="Maximum hits per search path (1–200; default 20).",
            )
    return p


WORKER = Path(__file__).with_name("navcom_sources_worker.py")


def source_id(root):
    """Stable source identity for one resolved root (explicit or discovered harvest)."""
    return hashlib.sha256(str(root).encode()).hexdigest()[:16]


def worker_argv(interpreter=None):
    """Run the harvest/search worker in the Starforge runtime; callers own stdio and timeouts."""
    return [interpreter or runtime(), str(WORKER)]


def runtime():
    override = os.environ.get("NAVCOM_STARFORGE_PYTHON")
    if override:
        interpreter = shutil.which(override) or str(Path(override).expanduser())
    else:
        executable = shutil.which("starforge")
        interpreter = None
        if executable:
            try:
                line = Path(executable).read_text().splitlines()[0]
                if line.startswith("#!"):
                    parts = shlex.split(line[2:])
                    if len(parts) == 1:
                        interpreter = parts[0]
                    elif len(parts) == 2 and Path(parts[0]).name == "env":
                        interpreter = shutil.which(parts[1])
            except (OSError, UnicodeError):
                pass
        if not interpreter:
            interpreter = sys.executable
    check = subprocess.run(
        [interpreter, "-c", "import starforge.catalog, starforge.cli_reporting"],
        capture_output=True,
        text=True,
    )
    if check.returncode:
        raise ValueError(
            "Starforge runtime unavailable. Install Starforge, or set NAVCOM_STARFORGE_PYTHON to the Python interpreter where it is installed."
        )
    return interpreter


class WorkerError(ValueError):
    """The Starforge worker refused or failed; its own reason went to stderr, or is this message."""

    def __init__(self, returncode, reason=""):
        super().__init__(reason or f"Starforge worker stopped (exit {returncode})")
        self.returncode = returncode


def sources_list(cache):
    """Harvested sources with their scope and coverage (`navcom sources list`)."""
    state = Path(cache) / "current.json"
    if not state.exists():
        return dict(schema_version=1, sources=[], published=None)
    return dict(schema_version=1, **json.loads(state.read_text()))


def search(cache, query, *, within=None, paths=(), mode="both", regex=False, ext=None, limit=20, progress=None):
    """Search harvested sources: ranked Starforge concepts plus literal code/document text
    (`navcom sources search`). With progress (a terminal), progress(message) hears the start and
    the worker's own messages stream to stderr; without it they are captured and a failure's
    reason becomes the WorkerError message."""
    if not 1 <= limit <= 200:
        raise ValueError("--limit must be between 1 and 200")
    if mode not in ("both", "concept", "text"):
        raise ValueError("--mode must be both, concept or text")
    if mode == "concept" and (regex or ext):
        raise ValueError("--regex and --ext apply to the text path; use --mode text or both")
    request = dict(action="search", cache=str(cache), paths=list(paths), query=query, within=within,
                   mode=mode, regex=regex, ext=ext, limit=limit)
    if progress:
        progress("starting Starforge search")
    completed = subprocess.run(worker_argv(), input=json.dumps(request), stdout=subprocess.PIPE,
                               stderr=None if progress else subprocess.PIPE, text=True)
    if completed.returncode:
        reasons = [line for line in (completed.stderr or "").splitlines() if line.startswith("navcom sources: ")]
        raise WorkerError(completed.returncode, reasons[-1].removeprefix("navcom sources: ") if reasons else "")
    return json.loads(completed.stdout)


def conversation_source(api, root, index):
    """Use NavCom's existing project discovery, not a second project classifier."""
    from navcom_discovery import Discovery

    if not index.is_file():
        return None
    with sqlite3.connect(
        index.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.3
    ) as conn:
        offset = 0
        while True:
            data = Discovery(api).view(
                conn,
                {
                    "action": ["list"],
                    "grouping": ["projects"],
                    "limit": ["200"],
                    "offset": [str(offset)],
                },
            )
            for node in data["nodes"]:
                path = Path(node["label"]).expanduser()
                if path.is_absolute() and path.resolve() == root:
                    return node["collection"]
            if not data["more"]:
                return None
            offset += 200


def render(result):
    if "sources" in result and isinstance(result["sources"], list):
        for source in result["sources"]:
            print(f"{source['id']}  {source['root']}")
            print(
                f"  Scope: {', '.join(source['include'])} · {source['coverage']['files']} files · {len(source['coverage']['excluded'])} excluded"
            )
            if source.get("conversation_collection"):
                print(
                    "  Conversations: navcom atlas explore "
                    + source["conversation_collection"]
                )
        print("Last complete harvest: " + str(result.get("published", "none")))
    elif "concept_hits" in result:
        for key, title in [
            ("concept_hits", "CONCEPTS / GEMS"),
            ("text_hits", "CODE / DOCS"),
        ]:
            print(title)
            for hit in result[key]:
                print(
                    "  "
                    + hit["source_path"]
                    + (":" + str(hit["line"]) if "line" in hit else "")
                )
                print(
                    "    "
                    + str(
                        hit.get("match")
                        or hit.get("description")
                        or hit.get("name", "")
                    )
                )
                if hit.get("conversation_command"):
                    print("    " + shlex.join(hit["conversation_command"]))
            if not result[key]:
                print("  No matches.")
        print(result["freshness"])
        if result["potentially_truncated"]:
            print("Result limit reached; narrow --within / --ext or raise --limit.")
        print("Query cache: " + ("hit" if result["query_cache_hit"] else "stored"))
    else:
        print(
            f"Harvest complete: {result['analyzed_sources']} analyzed, {result['cached_sources']} cached ({result['seconds']}s)."
        )


def run(api, argv):
    p = parser()
    args = p.parse_args(argv)
    if not args.action:
        p.print_help()
        return 0
    try:
        from navcom_navigation import history_cache, paths
        index = getattr(args, "index", None) or api.default_index_path()
        cache = paths(index, sources=args.cache)[1].resolve()
        if args.action == "read":
            from navcom_source_reader import read_source
            result=read_source(args.source,args.path,line=args.line,limit=args.limit,cache_path=cache,
                history_cache=args.history_cache or history_cache(index),history=args.history,snapshot=args.snapshot,published=args.published)
            if args.json:print(json.dumps(result,indent=2))
            else:
                print(result.get("source_path") or result.get("original_path") or args.path)
                for row in result.get("lines",[]):print(str(row["number"]).rjust(6)+"  "+row["text"])
                if result.get("cli_command"):print("\n"+result["cli_command"])
            return 0
        if args.action == "list":
            result = sources_list(cache)
        elif args.action == "search":
            result = search(cache, " ".join(args.words), within=args.within, paths=args.path, mode=args.mode,
                            regex=args.regex, ext=args.ext, limit=args.limit,
                            progress=lambda message: print("navcom sources ▸ " + message, file=sys.stderr, flush=True))
        else:
            request = dict(action=args.action, cache=str(cache))
            discovery = None
            if args.action == "discover":
                from navcom_source_discovery import discover
                print("navcom sources ▸ discovering indexed source scopes",file=sys.stderr,flush=True)
                discovery=discover(api,index.expanduser(),cache,limit=args.limit,offset=args.offset,within=args.within,
                    progress=lambda done,total,root:print(f'navcom sources ▸ {done}/{total} · {root}',file=sys.stderr,flush=True))
                if not args.harvest:
                    print(json.dumps(discovery,indent=2) if args.json else "\n".join(s["root"]+"\n  "+", ".join(s["include"]) for s in discovery["sources"])+"\nCoverage: "+json.dumps(discovery["coverage"]))
                    return 0
                if not discovery["sources"]:raise ValueError("No supported local code or documents in this discovery scope")
                request.update(action="harvest",sources=discovery["sources"])
            if args.action == "harvest":
                root = args.root.expanduser().resolve()
                if not root.is_dir():
                    raise ValueError("Source directory does not exist: " + str(root))
                if min(args.max_files, args.max_bytes, args.max_file_bytes) < 1:
                    raise ValueError("Scan budgets must be positive")
                print(
                    "navcom sources ▸ discovering conversation handoff",
                    file=sys.stderr,
                    flush=True,
                )
                collection = conversation_source(api, root, index.expanduser())
                if collection is None:
                    print(
                        "navcom sources: no indexed project handoff; source search will still work",
                        file=sys.stderr,
                    )
                request["sources"] = [
                    dict(
                        id=source_id(root),
                        root=str(root),
                        label=root.name,
                        include=args.include or ["."],
                        max_files=args.max_files,
                        max_bytes=args.max_bytes,
                        max_file_bytes=args.max_file_bytes,
                        conversation_collection=collection,
                    )
                ]
            print(
                "navcom sources ▸ starting Starforge " + args.action,
                file=sys.stderr,
                flush=True,
            )
            completed = subprocess.run(
                worker_argv(),
                input=json.dumps(request),
                stdout=subprocess.PIPE,
                text=True,
            )
            if completed.returncode:
                return completed.returncode
            result = json.loads(completed.stdout)
            if discovery:result["discovery_coverage"]=discovery["coverage"]
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            render(result)
        return 0
    except WorkerError as exc:
        return exc.returncode
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print("navcom sources: " + str(exc), file=sys.stderr)
        return 1
