"""Bounded source windows from published Starforge artifacts, never live files."""

import codecs
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat


MAX_LINES = 200
MAX_WINDOW_BYTES = 64 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
KEY = re.compile(r"[0-9a-f]{64}\Z")


class SourceReadError(ValueError):
    """The requested immutable source cannot be read safely or completely."""


def _relative(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value or "\\" in value:
        raise SourceReadError("Supply one source file path")
    path = PurePosixPath(value)
    if ".." in path.parts:
        raise SourceReadError("Source path traversal is not allowed")
    return path


@contextlib.contextmanager
def _open(root_fd, relative, directory=False):
    """Resolve every untrusted descendant with openat/O_NOFOLLOW."""
    path = _relative(str(relative))
    if path.is_absolute() or not path.parts:
        raise SourceReadError("Reader paths must stay within the configured cache")
    parent = os.dup(root_fd)
    target = None
    try:
        for part in path.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if directory else os.O_NONBLOCK)
        target = os.open(path.parts[-1], flags, dir_fd=parent)
        metadata = os.fstat(target)
        if not (stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)):
            raise SourceReadError("Source reader requires regular snapshot files")
        yield target
    except OSError as error:
        raise SourceReadError("Snapshot file unavailable or a symlink was rejected: " + str(relative)) from error
    finally:
        if target is not None:
            os.close(target)
        os.close(parent)


def _json(root_fd, relative):
    with _open(root_fd, relative) as fd:
        if os.fstat(fd).st_size > MAX_METADATA_BYTES:
            raise SourceReadError("Snapshot metadata exceeds its read budget")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            raise SourceReadError("Snapshot metadata exceeds its read budget")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise SourceReadError("Invalid published snapshot metadata") from error
    if not isinstance(value, dict):
        raise SourceReadError("Invalid published snapshot metadata")
    return value


def _same_path(value, *paths):
    """Compare addresses only; never resolve or inspect a live-source path."""
    candidate = _relative(value)
    return any(candidate == PurePosixPath(str(path)) for path in paths)


def _window(fd, line, limit, max_file_bytes):
    before = os.fstat(fd)
    if before.st_size > max_file_bytes:
        raise SourceReadError("Snapshot file exceeds the reader's bounded file budget")
    sha = hashlib.sha256()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    consumed = 0
    completed = 0
    pending = False
    rows = []
    row = None
    used = 0
    byte_truncated = False
    try:
        with os.fdopen(os.dup(fd), "rb") as stream:
            while fragment := stream.readline(MAX_WINDOW_BYTES):
                consumed += len(fragment)
                if consumed > max_file_bytes:
                    raise SourceReadError("Snapshot file exceeds the reader's bounded file budget")
                if b"\0" in fragment:
                    raise SourceReadError("Binary snapshot files cannot be displayed as source")
                decoder.decode(fragment, final=False)
                sha.update(fragment)
                number = completed + 1
                pending = True
                if line <= number < line + limit:
                    if used < MAX_WINDOW_BYTES:
                        if row is None:
                            row = dict(number=number, raw=bytearray(), truncated=False)
                            rows.append(row)
                        available = MAX_WINDOW_BYTES - used
                        piece = fragment[:available]
                        row["raw"].extend(piece)
                        used += len(piece)
                    else:
                        piece = b""
                    if len(piece) < len(fragment):
                        byte_truncated = True
                        if row is not None:
                            row["truncated"] = True
                if fragment.endswith(b"\n"):
                    completed += 1
                    pending = False
                    row = None
            decoder.decode(b"", final=True)
    except UnicodeError as error:
        raise SourceReadError("Snapshot file is not UTF-8 text") from error
    after = os.fstat(fd)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or consumed != before.st_size:
        raise SourceReadError("Snapshot changed while it was being read; retry after refreshing the harvest")
    total_lines = completed + int(pending)
    if line > max(1, total_lines):
        raise SourceReadError("Requested line is past the end of this snapshot (" + str(total_lines) + " lines)")
    output = []
    for item in rows:
        raw = bytes(item.pop("raw"))
        if raw.endswith(b"\n"):
            raw = raw[:-1]
            if raw.endswith(b"\r"):
                raw = raw[:-1]
        # The whole file was validated above; only a clipped final codepoint may be incomplete.
        output.append(dict(item, text=raw.decode("utf-8", "ignore")))
    end = output[-1]["number"] if output else 0
    return dict(lines=output, sha256=sha.hexdigest(), bytes=consumed,
                window=dict(start=line, end=end, total_lines=total_lines, requested_lines=limit,
                            returned_lines=len(output), bytes=sum(len(r["text"].encode()) for r in output),
                            max_lines=MAX_LINES, max_bytes=MAX_WINDOW_BYTES, byte_truncated=byte_truncated,
                            previous_line=max(1, line-limit) if line > 1 else None,
                            next_line=end+1 if end and end < total_lines else None))


def _source_record(cache_fd, cache, cache_alias, source_id, snapshot="", published=None, state=None):
    """Validate one published artifact for both inventory and content readers."""
    state = state if state is not None else _json(cache_fd, "current.json")
    sources = state.get("sources")
    if not isinstance(sources, list):
        raise SourceReadError("Published source registry is unavailable")
    stamp = state.get("published")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
        raise SourceReadError("Published source generation is missing or invalid")
    matches = [s for s in sources if isinstance(s, dict) and s.get("id") == source_id]
    if not matches:
        matches = [s for s in sources if isinstance(s, dict) and source_id in (s.get("label"), s.get("root"))]
    if len(matches) != 1:
        raise SourceReadError("Source must identify exactly one published source ID, unique label, or root")
    source = matches[0]
    source_id = source.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise SourceReadError("Published source identity is missing")
    artifact = _relative(source.get("artifact", ""))
    key = artifact.name
    if not KEY.fullmatch(key) or not _same_path(str(artifact), cache / "artifacts" / key, cache_alias / "artifacts" / key):
        raise SourceReadError("Source artifact is outside the published cache")
    if snapshot and snapshot != key:
        raise SourceReadError("Source snapshot changed. Search again before opening this result.")
    # The registry can advance when an unrelated source is harvested. An exact
    # artifact pin remains valid only while this source still publishes that key;
    # an unpinned search result must retain its exact registry generation.
    if published is not None and stamp != published and not snapshot:
        raise SourceReadError("Source search is stale: its published generation changed. Search again before opening this result.")
    receipt = _json(cache_fd, "artifacts/" + key + "/receipt.json")
    recorded = receipt.get("source", {})
    if any(not isinstance(receipt.get(k), str) or not KEY.fullmatch(receipt[k]) for k in ("signature", "extractor")):
        raise SourceReadError("Published source receipt is missing its content identity")
    if not isinstance(recorded, dict) or recorded.get("id") != source_id or any(
            receipt.get(k) != source.get(k) for k in ("signature", "extractor")) or any(
            recorded.get(k) != source.get(k) for k in ("root", "include")):
        raise SourceReadError("Published source receipt does not match the registry")
    expected_key = hashlib.sha256(json.dumps([recorded, receipt.get("signature"), receipt.get("extractor")], sort_keys=True).encode()).hexdigest()
    if key != expected_key:
        raise SourceReadError("Published source artifact identity does not match its receipt")
    root = _relative(source.get("root", ""))
    if not root.is_absolute():
        raise SourceReadError("Published source root is not an absolute address")
    return source, recorded, root, key, stamp


def _read(cache_fd, cache, cache_alias, source_id, path, line, limit, snapshot, published, historical):
    source, recorded, root, key, stamp = _source_record(cache_fd, cache, cache_alias, source_id, snapshot, published)
    source_id = source["id"]
    requested = _relative(path)
    if requested.is_absolute():
        bases = [root, PurePosixPath(str(cache / "artifacts" / key / "source")),
                 PurePosixPath(str(cache_alias / "artifacts" / key / "source"))]
        matching = [base for base in bases if requested.is_relative_to(base)]
        if not matching:
            raise SourceReadError("Requested file is outside this published source")
        relative = requested.relative_to(max(matching, key=lambda base: len(base.parts)))
    else:
        relative = requested
    if not relative.parts:
        raise SourceReadError("Select a file, not a source directory")
    scopes = recorded.get("include", [])
    if not scopes or not any(relative.is_relative_to(_relative(scope)) for scope in scopes):
        raise SourceReadError("File is outside the published source's selected paths")
    history_record = None
    if historical:
        history_record = next((item for item in historical.get("files", []) if isinstance(item, dict) and item.get("path") == str(relative)), None)
        if not history_record:
            raise SourceReadError("File is not in the pinned Git receipt")
        if source_id != historical.get("id") or not _same_path(str(root), historical["snapshot_path"]):
            raise SourceReadError("Historical harvest does not match the pinned Git snapshot")
        provenance = recorded.get("provenance", {})
        if provenance.get("commit") != historical.get("commit") or provenance.get("tree") != historical.get("tree"):
            raise SourceReadError("Historical harvest revision does not match its Git receipt")
    max_file = recorded.get("max_file_bytes", MAX_FILE_BYTES)
    if not isinstance(max_file, int) or isinstance(max_file, bool) or max_file < 1:
        raise SourceReadError("Invalid published source file budget")
    snapshot_relative = "artifacts/" + key + "/source/" + str(relative)
    with _open(cache_fd, snapshot_relative) as fd:
        content = _window(fd, line, limit, min(max_file, MAX_FILE_BYTES))
    if history_record and (history_record.get("sha256") != content["sha256"] or history_record.get("bytes") != content["bytes"]):
        raise SourceReadError("Snapshot file does not match its pinned Git content hash")
    original_root = historical["repository"] if historical else str(root)
    return dict(schema_version=1, source_id=source_id, label=source.get("label", source_id),
                relative_path=str(relative), original_path=str(PurePosixPath(original_root) / relative),
                snapshot_path=str(cache / snapshot_relative), snapshot=key,
                published=stamp, **content,
                ref=dict(source=source_id, path=str(relative), snapshot=key, published=stamp,
                         history=historical["id"] if historical else ""),
                provenance=dict(kind="git_revision" if historical else "published_harvest",
                                source_signature=source.get("signature"), extractor=source.get("extractor"),
                                snapshot=key, published=stamp, current_file_read=False,
                                requested_published=published,
                                publication_changed=published is not None and published != stamp,
                                pin_validation="exact currently published artifact" if snapshot else "current source publication",
                                file_hash_verification="pinned Git receipt" if historical else "computed from published snapshot bytes; receipt records an aggregate source signature",
                                commit=historical.get("commit") if historical else None,
                                tree=historical.get("tree") if historical else None,
                                captured_at=historical.get("observed_at") if historical else None,
                                timestamp_policy="Published identifies the verified source registry generation; source capture time is not recorded." if not historical else "Captured at is the pinned Git snapshot observation time."))


def read_source(source_id, path, *, line=1, limit=80, cache_path=None, history_cache=None,
                history="", snapshot="", published=None):
    """Read at most 200 lines/64 KiB from one registered immutable artifact.

    ``path`` may be relative or the original displayed address. Original roots
    are used only for lexical mapping, never opened. Historical reads require
    an existing pinned receipt and harvest; this service never runs Starforge.
    An exact ``snapshot`` pin may survive an unrelated registry publication;
    the returned publication is the registry actually verified for this read.
    """
    if not isinstance(source_id, str) or not source_id or len(source_id) > 4096:
        raise SourceReadError("Supply one published source ID")
    if any(not isinstance(n, int) or isinstance(n, bool) for n in (line, limit)) or line < 1 or not 1 <= limit <= MAX_LINES:
        raise SourceReadError("Line must be positive and limit must be between 1 and 200")
    if snapshot and (not isinstance(snapshot, str) or not KEY.fullmatch(snapshot)):
        raise SourceReadError("Snapshot must be its exact artifact SHA-256 identity")
    if published is not None and (isinstance(published, bool) or not isinstance(published, (float, int)) or not math.isfinite(published)):
        raise SourceReadError("Published generation must be a finite timestamp")
    if history and (not isinstance(history, str) or not KEY.fullmatch(history)):
        raise SourceReadError("History must be an exact pinned receipt identity")
    configured = history_cache if history else cache_path
    if configured is None:
        raise SourceReadError("A configured " + ("history" if history else "source") + " cache is required")
    alias = Path(configured).expanduser().absolute()
    canonical = alias.resolve()
    fd = None
    try:
        fd = os.open(canonical, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        if history:
            prefix = "revisions/" + history
            receipt = _json(fd, prefix + "/receipt.json")
            if receipt.get("id") != history or receipt.get("kind") != "git_revision" or not _same_path(
                    receipt.get("snapshot_path", ""), canonical / prefix / "snapshot", alias / prefix / "snapshot"):
                raise SourceReadError("Invalid pinned Git snapshot receipt")
            with _open(fd, prefix + "/harvest", directory=True) as harvest_fd:
                result = _read(harvest_fd, canonical / prefix / "harvest", alias / prefix / "harvest",
                               source_id, path, line, limit, snapshot, published, receipt)
        else:
            result = _read(fd, canonical, alias, source_id, path, line, limit, snapshot, published, None)
    except OSError as error:
        raise SourceReadError("Published source cache is unavailable") from error
    finally:
        if fd is not None:
            os.close(fd)
    command = ["navcom", "sources", "read", result["source_id"], result["relative_path"], "--line", str(line),
               "--limit", str(limit), "--snapshot", result["snapshot"]]
    if result["published"] is not None:
        command.extend(["--published", str(result["published"])])
    if history:
        command.extend(["--history", history, "--history-cache", str(alias)])
    else:
        command.extend(["--cache", str(alias)])
    result["cli_command"] = shlex.join(command)
    return result
