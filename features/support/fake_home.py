"""Build a throwaway HOME holding one realistic session per harness navcom reads.

Every session mentions the marker word ``zebracorn`` plus a harness-specific
word ``zebracorn<harness>`` so scenarios can prove each harness is indexed.
Formats mirror what the real tools write (checked against local installs and,
for goose, against block/goose's session_manager.rs + message.rs).
"""
import json
import os
import sqlite3
from pathlib import Path

PUNCTUATED = "how do we fix the drizzle migration, it's broken; again? (see main()) — v0.1.3 log-search"
PROJECT = "proj-alpha"


def _jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _touch(path, epoch):
    os.utime(path, (epoch, epoch))


def build(home: Path, base_epoch: float = 1_790_000_000):
    home.mkdir(parents=True, exist_ok=True)
    workdir = home / "work" / PROJECT
    workdir.mkdir(parents=True, exist_ok=True)
    cwd = str(workdir)
    encoded = cwd.replace("/", "-").replace(".", "-").replace("_", "-")
    sessions = {}

    # ── Claude Code ────────────────────────────────────────────────────────
    claude = home / ".claude" / "projects" / encoded / "11111111-2222-4333-8444-555555555555.jsonl"
    _jsonl(claude, [
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Caveat: injected by a hook, zebracornmeta"}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>/goal</command-name>\n<command-args>ship the zebracorn release</command-args>"}},
        {"type": "user", "message": {"role": "user", "content": PUNCTUATED + " zebracorn zebracornclaude"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Use drizzle-kit push (don't use generate). zebracornclaude fixed."},
            {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "npx drizzle-kit push --force"}},
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "navcom --query zebracorn --compact"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "added 3 packages, migration applied zebracorntoolclaude"},
            {"type": "tool_result", "tool_use_id": "t2", "content": "navcom: 3 hits in 2 sessions · query: zebracorn* zebracornselfoutput"},
        ]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Committed and pushed as \x1b[2mabc1234\x1b[0m done"}]}},
    ])
    sub = claude.parent / claude.stem / "subagents" / "agent-a1b2c3.jsonl"
    _jsonl(sub, [{"type": "user", "message": {"role": "user", "content": "subagent digging zebracornsubagent"}}])
    _touch(sub, base_epoch + 90)
    _touch(claude, base_epoch + 100)
    sessions["claude"] = claude

    # ── Codex ──────────────────────────────────────────────────────────────
    codex = home / ".codex" / "sessions" / "2026" / "09" / "01" / \
        "rollout-2026-09-01T10-00-00-0199aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee.jsonl"
    _jsonl(codex, [
        {"timestamp": "2026-09-01T10:00:00Z", "type": "session_meta", "payload": {"id": "x", "cwd": cwd}},
        {"timestamp": "2026-09-01T10:00:01Z", "type": "event_msg", "payload": {"type": "user_message", "message": "find the cognito auth bug zebracorn zebracorncodex"}},
        {"timestamp": "2026-09-01T10:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "find the cognito auth bug zebracorn zebracorncodex"}]}},
        {"timestamp": "2026-09-01T10:00:03Z", "type": "response_item", "payload": {"type": "function_call", "name": "shell_command", "call_id": "c1", "arguments": json.dumps({"command": "rg cognito src/"})}},
        {"timestamp": "2026-09-01T10:00:03Z", "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": json.dumps({"output": "src/auth.ts:12: cognito refresh zebracorntoolcodex", "metadata": {"exit_code": 0}})}},
        {"timestamp": "2026-09-01T10:00:03Z", "type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "c2", "arguments": json.dumps({"cmd": "npm test -- auth", "workdir": "/x"})}},
        {"timestamp": "2026-09-01T10:00:03Z", "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "c3", "input": 'const r = await tools.exec_command({"cmd": "git log --oneline -3"}); text(r)'}},
        {"timestamp": "2026-09-01T10:00:03Z", "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c3", "output": [{"type": "input_text", "text": "Script completed\nOutput:\nabc1234 fix zebracornjsexec"}]}},
        {"timestamp": "2026-09-01T10:00:04Z", "type": "event_msg", "payload": {"type": "agent_message", "message": "The cognito token refresh was missing. zebracorncodex"}},
    ])
    _touch(codex, base_epoch + 200)
    sessions["codex"] = codex

    # ── Gemini CLI ─────────────────────────────────────────────────────────
    gemini = home / ".gemini" / "tmp" / PROJECT / "chats" / "session-2026-09-02.json"
    gemini.parent.mkdir(parents=True, exist_ok=True)
    gemini.write_text(json.dumps({
        "sessionId": "g1", "lastUpdated": "2026-09-02T00:00:00Z",
        "messages": [
            {"type": "user", "content": [{"text": "terraform plan for zebracorn zebracorngemini"}], "timestamp": "2026-09-02T00:00:00Z"},
            {"type": "gemini", "content": "Run terraform plan -out=tf.plan zebracorngemini", "timestamp": "2026-09-02T00:00:01Z",
             "toolCalls": [{"name": "run_shell_command", "args": {"command": "terraform plan -out=tf.plan"},
                            "resultDisplay": "Plan: 3 to add zebracorntoolgemini"}]},
        ],
    }))
    (home / ".gemini" / "projects.json").write_text(json.dumps({"projects": {cwd: PROJECT}}))
    _touch(gemini, base_epoch + 300)
    sessions["gemini"] = gemini

    # ── pi and omo (same JSONL format) ─────────────────────────────────────
    for name, root in (("pi", home / ".pi" / "agent" / "sessions"), ("omo", home / ".omo" / "agent" / "sessions")):
        path = root / f"-{encoded}--" / f"2026-09-03T00-00-00-000Z_01a0aaaa-bbbb-7ccc-8ddd-{'1' if name == 'pi' else '2'}23456789abc.jsonl"
        _jsonl(path, [
            {"type": "session", "version": 3, "id": "s", "timestamp": "2026-09-03T00:00:00Z", "cwd": cwd},
            {"type": "model_change", "id": "m", "provider": "x", "modelId": "y"},
            {"type": "message", "id": "1", "message": {"role": "user", "content": [{"type": "text", "text": f"hello"}]}},
            {"type": "message", "id": "2", "message": {"role": "user", "content": [{"type": "text", "text": f"serve qwen on the studio box zebracorn zebracorn{name}"}]}},
            {"type": "message", "id": "3", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "secret thoughts zebracornthinking"},
                {"type": "text", "text": f"Checking the mlx server first. zebracorn{name}"},
                {"type": "toolCall", "id": "c1", "name": "bash", "arguments": {"command": "ps aux | grep mlx", "timeout": 10}},
                {"type": "toolCall", "id": "c2", "name": "memory", "arguments": {"command": "create", "file_path": "x"}},
            ]}},
            {"type": "message", "id": "4", "message": {"role": "toolResult", "toolCallId": "c1", "toolName": "bash", "content": [{"type": "text", "text": "zebracorntoolresult"}]}},
            {"type": "message", "id": "5", "message": {"role": "bashExecution", "command": "pwd", "output": "/x zebracornbashexec", "exitCode": 0}},
        ])
        _touch(path, base_epoch + (400 if name == "pi" else 500))
        sessions[name] = path

    # ── opencode (SQLite) + legacy JSON storage ────────────────────────────
    oc_root = home / ".local" / "share" / "opencode"
    oc_root.mkdir(parents=True, exist_ok=True)
    db = oc_root / "opencode.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT, slug TEXT NOT NULL,
            directory TEXT NOT NULL, title TEXT NOT NULL, version TEXT NOT NULL, time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL);
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL);
    """)
    t = int((base_epoch + 600) * 1000)
    con.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)",
                ("ses_opencode1", "p1", None, "slug", cwd, "Verify cerbos test gaps", "1", t, t))
    con.execute("INSERT INTO message VALUES (?,?,?,?,?)", ("msg_1", "ses_opencode1", t, t, json.dumps({"role": "user"})))
    con.execute("INSERT INTO message VALUES (?,?,?,?,?)", ("msg_2", "ses_opencode1", t + 1, t + 1, json.dumps({"role": "assistant"})))
    parts = [
        ("prt_1", "msg_1", {"type": "text", "text": "check the cerbos policies zebracorn zebracornopencode"}),
        ("prt_1b", "msg_1", {"type": "text", "text": "<system-reminder>zebracornsynthetic</system-reminder>", "synthetic": True}),
        ("prt_2", "msg_2", {"type": "reasoning", "text": "zebracornthinking"}),
        ("prt_3", "msg_2", {"type": "tool", "tool": "bash", "callID": "c", "state": {"status": "completed", "input": {"command": "grep -c it( tests/cerbos.test.ts"}, "output": "22 zebracorntoolopencode"}}),
        ("prt_4", "msg_2", {"type": "text", "text": "22 cerbos tests found. zebracornopencode"}),
    ]
    for i, (pid, mid, data) in enumerate(parts):
        con.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", (pid, mid, "ses_opencode1", t + i, t + i, json.dumps(data)))
    con.commit()
    con.close()
    sessions["opencode"] = f"{db}#ses_opencode1"

    legacy_msg = oc_root / "storage" / "message" / "ses_legacy1"
    legacy_msg.mkdir(parents=True, exist_ok=True)
    (legacy_msg / "msg_a.json").write_text(json.dumps({"id": "msg_a", "sessionID": "ses_legacy1", "role": "user", "time": {"created": 1}}))
    (legacy_msg / "msg_b.json").write_text(json.dumps({"id": "msg_b", "sessionID": "ses_legacy1", "role": "assistant", "time": {"created": 2}}))
    for mid, text in (("msg_a", "old opencode question zebracornocleg"), ("msg_b", "old opencode answer zebracornocleg")):
        pdir = oc_root / "storage" / "part" / mid
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "prt_x.json").write_text(json.dumps({"type": "text", "text": text}))
    info = oc_root / "storage" / "session" / "proj1" / "ses_legacy1.json"
    info.parent.mkdir(parents=True, exist_ok=True)
    info.write_text(json.dumps({"id": "ses_legacy1", "title": "Legacy opencode chat", "directory": cwd}))
    _touch(legacy_msg, base_epoch + 800)
    sessions["opencode-legacy"] = str(legacy_msg)

    # ── goose (SQLite sessions.db) + legacy .jsonl ─────────────────────────
    goose_root = home / ".local" / "share" / "goose" / "sessions"
    goose_root.mkdir(parents=True, exist_ok=True)
    gdb = goose_root / "sessions.db"
    con = sqlite3.connect(gdb)
    con.executescript("""
        CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
            working_dir TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT, session_id TEXT NOT NULL,
            role TEXT NOT NULL, content_json TEXT NOT NULL, created_timestamp INTEGER NOT NULL, timestamp TIMESTAMP,
            tokens INTEGER, metadata_json TEXT);
    """)
    con.execute("INSERT INTO sessions (id, name, description, working_dir, updated_at) VALUES (?,?,?,?,?)",
                ("20260904_1", "Goose kubernetes session", "", cwd, "2026-09-04 00:00:00"))
    msgs = [
        ("user", [{"type": "text", "text": "why is the kubernetes pod crashlooping zebracorn zebracorngoose"}]),
        ("assistant", [
            {"type": "text", "text": "Let me check the pod logs. zebracorngoose"},
            {"type": "toolRequest", "id": "r1", "toolCall": {"status": "success", "value": {"name": "developer__shell", "arguments": {"command": "kubectl logs pod/api-0"}}}},
        ]),
        ("user", [{"type": "toolResponse", "id": "r1", "toolResult": {"status": "success", "value": [{"type": "text", "text": "CrashLoopBackOff zebracorntoolgoose"}]}}]),
    ]
    for i, (role, content) in enumerate(msgs):
        con.execute("INSERT INTO messages (session_id, role, content_json, created_timestamp) VALUES (?,?,?,?)",
                    ("20260904_1", role, json.dumps(content), int(base_epoch + 700 + i)))
    con.commit()
    con.close()
    sessions["goose"] = f"{gdb}#20260904_1"

    goose_legacy = goose_root / "20240101_120000.jsonl"
    _jsonl(goose_legacy, [
        {"working_dir": cwd, "description": "legacy goose", "message_count": 2},
        {"role": "user", "created": 1, "content": [{"type": "text", "text": "legacy goose question zebracornlegacygoose"}]},
        {"role": "assistant", "created": 2, "content": [{"type": "text", "text": "legacy goose answer zebracornlegacygoose"}]},
    ])
    _touch(goose_legacy, base_epoch + 50)
    sessions["goose-legacy"] = goose_legacy

    # ── Gemini CLI ≥ 0.39: append-only JSONL with $set / $patch / $rewindTo ──
    gj = home / ".gemini" / "tmp" / PROJECT / "chats" / "session-2026-09-05T00-00-abcd1234.jsonl"
    _jsonl(gj, [
        {"sessionId": "abcd1234-0000", "projectHash": "x", "startTime": "2026-09-05T00:00:00Z", "kind": "main", "directories": [cwd]},
        {"$set": {"messages": [{"id": "m1", "type": "user", "content": [{"text": "checkpointed question zebracornjsonlgem"}]}]}},
        {"id": "m2", "type": "gemini", "content": "draft answer", "toolCalls": [
            {"id": "tc1", "name": "run_shell_command", "args": {"command": "kubectl get pods"}, "status": "executing"}]},
        {"id": "m2", "type": "gemini", "content": "final answer zebracornjsonlgem", "toolCalls": [
            {"id": "tc1", "name": "run_shell_command", "args": {"command": "kubectl get pods"}, "status": "executing"}]},
        {"$patch": {"id": "m2", "toolCalls": [{"id": "tc1", "resultDisplay": "api-0 Running zebracornjsonltool", "status": "success"}]}},
        {"id": "m3", "type": "user", "content": [{"text": "rewound away zebracornrewound"}]},
        {"$rewindTo": "m3"},
        {"id": "m4", "type": "user", "content": [{"text": "after rewind zebracornafterrewind"}]},
    ])
    _touch(gj, base_epoch + 310)
    sessions["gemini-jsonl"] = gj

    # ── DeepSeek Harness (dsh): zstd-compressed JSONL, multiple frames ──
    dsh_dir = home / ".dsh" / "sessions" / ("--" + cwd.replace("/", "-").lstrip("-") + "--") / "session-7a48d7c9-b372-4f90-8537-d9c82b6c65a7"
    dsh_dir.mkdir(parents=True, exist_ok=True)
    dsh_lines = [
        {"type": "session", "version": 4, "id": "session-7a48d7c9-b372-4f90-8537-d9c82b6c65a7", "cwd": cwd},
        {"type": "user/message", "seq": 1, "data": {"content": [{"type": "text", "text": "run the calc check zebracorndsh"}], "source": {"kind": "user"}}},
        {"type": "user/message", "seq": 2, "data": {"content": [{"type": "text", "text": "runtime context zebracorninjected"}], "source": {"kind": "runtime-context"}}},
        {"type": "session/title", "seq": 3, "data": {"title": "Verify calc with DeepSeek"}},
        {"type": "assistant/message", "seq": 4, "data": {"message": {"role": "assistant", "content": [
            {"type": "reasoning", "text": "secret zebracornthinking"}, {"type": "text", "text": "Running it now zebracorndsh."}]}}},
        {"type": "tool/call", "seq": 5, "data": {"callId": "c1", "name": "bash", "arguments": json.dumps({"command": "python3 -c 'print(42)'"})}},
        {"type": "tool/result", "seq": 6, "data": {"message": {"role": "tool", "toolCallId": "c1", "content": [{"type": "text", "text": "42 zebracorndshtool"}], "isError": False}}},
    ]
    payload = "".join(json.dumps(r) + "\n" for r in dsh_lines).encode()
    zpath = dsh_dir / "session.v4.jsonl.zstd"
    import shutil as _sh
    import subprocess as _sp
    if _sh.which("zstd"):
        half = len(payload) // 2
        cut = payload.rfind(b"\n", 0, half) + 1
        frames = b"".join(_sp.run(["zstd", "-q", "-c"], input=part, capture_output=True, check=True).stdout
                          for part in (payload[:cut], payload[cut:]))   # two frames, like dsh writes
        zpath.write_bytes(frames)
        _touch(zpath, base_epoch + 800)
        sessions["dsh"] = zpath

    # ── Grok Build: ACP updates.jsonl + summary.json ──
    from urllib.parse import quote
    grok_dir = home / ".grok" / "sessions" / quote(cwd, safe="") / "0199bbbb-cccc-7ddd-8eee-ffff00001111"
    grok_dir.mkdir(parents=True, exist_ok=True)
    def env(update):
        return {"timestamp": 1, "method": "session/update", "params": {"sessionId": "s", "update": update}}
    _jsonl(grok_dir / "updates.jsonl", [
        env({"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "check the rust build "}}),
        env({"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "zebracorngrok"}}),
        env({"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "zebracornthinking"}}),
        env({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "Building now, "}}),
        env({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "zebracorngrok answer."}}),
        env({"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "Run cargo build", "kind": "execute", "rawInput": {"command": "cargo build --release"}}),
        env({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "in_progress", "content": [{"type": "text", "text": "partial"}]}),
        env({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed",
             "content": [{"type": "content", "content": {"type": "text", "text": "Finished release zebracorngroktool"}}]}),
        {"sessionId": "s", "update": {"sessionUpdate": "user_message_chunk", "content": {"type": "text", "text": "bare legacy line zebracorngroklegacy"}}},
    ])
    (grok_dir / "summary.json").write_text(json.dumps({"title": "Rust release build", "cwd": cwd}))
    _touch(grok_dir / "updates.jsonl", base_epoch + 850)
    sessions["grok"] = grok_dir / "updates.jsonl"

    # ── Kilo Code CLI: opencode's SQLite schema at ~/.local/share/kilo/kilo.db ──
    kdb = home / ".local" / "share" / "kilo" / "kilo.db"
    kdb.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(kdb)
    con.executescript("""
        CREATE TABLE session (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, parent_id TEXT, slug TEXT NOT NULL,
            directory TEXT NOT NULL, title TEXT NOT NULL, version TEXT NOT NULL, time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL);
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL, data TEXT NOT NULL);
        CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT NOT NULL, session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL, data TEXT NOT NULL);
    """)
    kt = int((base_epoch + 900) * 1000)
    con.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)", ("ses_kilo1", "p", None, "s", cwd, "Kilo refactor", "1", kt, kt))
    con.execute("INSERT INTO message VALUES (?,?,?,?,?)", ("msg_k1", "ses_kilo1", kt, kt, json.dumps({"role": "user"})))
    con.execute("INSERT INTO part VALUES (?,?,?,?,?,?)", ("prt_k1", "msg_k1", "ses_kilo1", kt, kt,
                json.dumps({"type": "text", "text": "refactor the router zebracornkilo"})))
    con.commit()
    con.close()
    sessions["kilo"] = f"{kdb}#ses_kilo1"
    return sessions, workdir


def env_for(home: Path):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PI_CODING_AGENT", "OMO_CODING_AGENT", "GOOSE_", "OPENCODE", "CLAUDE", "CODEX", "GEMINI",
                                "NAVCOM", "DSH_", "GROK_", "KILO", "XDG_"))}
    env.update({
        "HOME": str(home),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "CODEX_HOME": str(home / ".codex"),
        "CLAUDE_CONFIG_DIR": str(home / ".claude"),
        "NAVCOM_INDEX": str(home / "navcom-index.sqlite"),
        "NO_COLOR": "1",
        "NAVCOM_DRY_SCHEDULER": "1",
        "NAVCOM_ARCHIVE_DIR": str(home / ".navcom" / "archive"),
    })
    return env
