"""Each harness parser yields clean user/assistant/cmd turns from the real on-disk formats."""
import os

import fake_home
import pytest


@pytest.fixture()
def home(tmp_path, monkeypatch):
    sessions, workdir = fake_home.build(tmp_path / "home")
    for key, value in fake_home.env_for(tmp_path / "home").items():
        monkeypatch.setenv(key, value)
    for key in list(os.environ):
        if key.startswith(("PI_CODING_AGENT", "OMO_CODING_AGENT", "GOOSE_", "OPENCODE")):
            monkeypatch.delenv(key, raising=False)
    return sessions


def turns(navcom, key, provider):
    return list(navcom.iter_clean_turns(str(key), provider))


def test_claude_skips_meta_rescues_slash_commands_strips_ansi(navcom, home):
    got = turns(navcom, home["claude"], "claude")
    texts = [t for _, t in got]
    assert not any("zebracornmeta" in t for t in texts)
    assert ("user", "/goal ship the zebracorn release") in got
    assert ("cmd", "npx drizzle-kit push --force") in got
    assert any("abc1234" in t and "\x1b" not in t for t in texts)


def test_codex_dedupes_the_double_logged_user_message(navcom, home):
    got = turns(navcom, home["codex"], "codex")
    users = [t for r, t in got if r == "user"]
    assert users == ["find the cognito auth bug zebracorn zebracorncodex"]
    assert ("cmd", "rg cognito src/") in got


def test_gemini_list_of_parts(navcom, home):
    got = turns(navcom, home["gemini"], "gemini")
    assert got[0] == ("user", "terraform plan for zebracorn zebracorngemini")


@pytest.mark.parametrize("harness", ["pi", "omo"])
def test_pi_family(navcom, home, harness):
    got = turns(navcom, home[harness], harness)
    roles = [r for r, _ in got]
    assert ("cmd", "ps aux | grep mlx") in got and ("cmd", "pwd") in got
    assert not any("zebracornthinking" in t for _, t in got)
    assert ("tool", "[bash: ps aux | grep mlx]\nzebracorntoolresult") in got
    assert ("tool", "[bash: pwd]\n/x zebracornbashexec") in got
    assert not any(r == "cmd" and t == "create" for r, t in got)  # memory tool's "command" arg is not a shell
    assert roles[:2] == ["user", "user"]


def test_opencode_db_and_legacy(navcom, home):
    got = turns(navcom, home["opencode"], "opencode")
    assert ("user", "check the cerbos policies zebracorn zebracornopencode") in got
    assert ("cmd", "grep -c it( tests/cerbos.test.ts") in got
    assert not any("zebracornsynthetic" in t or "zebracornthinking" in t for _, t in got)
    assert ("tool", "[bash: grep -c it( tests/cerbos.test.ts]\n22 zebracorntoolopencode") in got
    legacy = turns(navcom, home["opencode-legacy"], "opencode")
    assert legacy == [("user", "old opencode question zebracornocleg"), ("assistant", "old opencode answer zebracornocleg")]


def test_goose_db_and_legacy(navcom, home):
    got = turns(navcom, home["goose"], "goose")
    assert got[0][0] == "user" and "crashlooping" in got[0][1]
    assert ("cmd", "kubectl logs pod/api-0") in got
    assert ("tool", "[developer__shell: kubectl logs pod/api-0]\nCrashLoopBackOff zebracorntoolgoose") in got
    legacy = turns(navcom, home["goose-legacy"], "goose")
    assert [r for r, _ in legacy] == ["user", "assistant"]


def test_every_harness_is_listed(navcom, home):
    providers = {log[3] for log in navcom.list_logs(navcom.ALL_PROVIDERS)}
    assert providers == set(navcom.ALL_PROVIDERS)


def test_short_refs_do_not_collide_for_uuid7(navcom):
    a = "/x/2026-09-27T17-33-52-519Z_01a0e3ee-2e06-77de-8ed9-c8873f07fe0d.jsonl"
    b = "/x/2026-09-27T17-33-58-464Z_01a0e3ee-453f-76fc-8ddb-a8df78cc76a4.jsonl"
    assert navcom.short_ref(a) != navcom.short_ref(b)
    assert navcom.short_ref("/x/11111111-2222-4333-8444-555555555555.jsonl") == "11111111"


def test_incremental_append_indexes_only_new_lines(navcom, home, tmp_path):
    conn = navcom.open_index(tmp_path / "idx.sqlite")
    key = str(home["claude"])
    st = os.stat(key)
    navcom.index_log(conn, (key, st.st_mtime, st.st_size, "claude"))
    before = navcom.max_msg_index(conn, key)
    with open(key, "a") as fh:
        fh.write('{"type":"user","message":{"role":"user","content":"appended zebracornappend"}}\n')
        fh.write('{"type":"user","message":{"role":"us')  # half-written line: must wait
    st = os.stat(key)
    navcom.index_log(conn, (key, st.st_mtime + 1, st.st_size, "claude"))
    assert navcom.max_msg_index(conn, key) == before + 1
    hits, _, _ = navcom.search_hits(conn, "zebracornappend")
    assert len(hits) == 1


def test_claude_tool_outputs_labelled_and_navcom_output_skipped(navcom, home):
    got = turns(navcom, home["claude"], "claude")
    assert ("tool", "[Bash: npx drizzle-kit push --force]\nadded 3 packages, migration applied zebracorntoolclaude") in got
    assert not any("zebracornselfoutput" in t for _, t in got)


def test_codex_new_style_commands_and_outputs(navcom, home):
    got = turns(navcom, home["codex"], "codex")
    assert ("cmd", "npm test -- auth") in got                      # function_call exec_command {cmd}
    assert ("cmd", "git log --oneline -3") in got                  # custom_tool_call exec (JS wrapper)
    assert ("tool", "[shell_command: rg cognito src/]\nsrc/auth.ts:12: cognito refresh zebracorntoolcodex") in got
    assert any(r == "tool" and "zebracornjsexec" in t and t.startswith("[exec: git log") for r, t in got)


def test_gemini_tool_output(navcom, home):
    got = turns(navcom, home["gemini"], "gemini")
    assert ("tool", "[run_shell_command: terraform plan -out=tf.plan]\nPlan: 3 to add zebracorntoolgemini") in got


def test_long_tool_output_keeps_head_and_tail(navcom):
    text = "START " + "x " * 5000 + " FINAL ERROR: boom"
    capped = navcom.cap_tool_output(text)
    assert capped.startswith("START") and capped.endswith("FINAL ERROR: boom") and "chars omitted" in capped
    assert len(capped) < 4300
    assert navcom.cap_tool_output("data:image/png;base64," + "A" * 5000) == "[binary data]"


def test_archive_is_incremental_and_restorable(navcom, home, tmp_path):
    import gzip
    conn = navcom.open_index(tmp_path / "idx.sqlite")
    key = str(home["claude"])
    st = os.stat(key)
    log = (key, st.st_mtime, st.st_size, "claude")
    navcom.archive_logs(conn, [log], budget=None)
    with open(key, "a") as fh:
        fh.write('{"type":"user","message":{"role":"user","content":"later turn"}}\n')
    st = os.stat(key)
    files, written = navcom.archive_logs(conn, [(key, st.st_mtime, st.st_size, "claude")], budget=None)
    assert files == 1 and written < 200          # only the appended bytes were compressed
    archived = navcom.archive_path_for(key, "claude")
    original = open(key, "rb").read()
    assert gzip.open(archived).read() == original  # multi-member gzip == the original, byte for byte
    assert oct(os.stat(archived).st_mode & 0o777) == "0o600"
    os.remove(key)
    assert navcom.cmd_restore(conn, "11111111", None) == 0
    assert open(key, "rb").read() == original


def test_codex_json_envelope_unwrapped(navcom):
    role, text = navcom.tool_turn("exec_command: make", '{"exit_code": 2, "wall_time_seconds": 0.9, "output": "make: *** [all] Error 2"}')
    assert text == "[exec_command: make]\nexit 2\nmake: *** [all] Error 2"


def test_navcom_output_rule_is_narrow(navcom):
    assert navcom._is_navcom_output("Bash: navcom drizzle -n 3", "anything")
    assert navcom._is_navcom_output("Bash: cd ~/x && navcom --open ab:3", "anything")
    assert not navcom._is_navcom_output("Bash: command -v navcom; ls ~/dev", "/Users/t/.local/bin/navcom\nproj-a")
    assert navcom._is_navcom_output("Bash: command -v navcom; navcom x | head", "navcom: 3 hits in 2 sessions")


def test_pi_session_name_is_the_title(navcom, home, tmp_path):
    path = home["pi"]
    with open(path, "a") as fh:
        fh.write('{"type":"session_info","id":"x","name":"Studio box qwen setup"}\n')
    assert navcom._native_title(str(path), "pi") == "Studio box qwen setup"


def test_gemini_jsonl_replay(navcom, home):
    got = turns(navcom, home["gemini-jsonl"], "gemini")
    assert ("user", "checkpointed question zebracornjsonlgem") in got          # $set.messages checkpoint
    assert ("assistant", "final answer zebracornjsonlgem") in got               # later same-id line wins
    assert not any(t == "draft answer" for _, t in got)
    assert ("cmd", "kubectl get pods") in got
    assert ("tool", "[run_shell_command: kubectl get pods]\napi-0 Running zebracornjsonltool") in got  # $patch
    assert not any("zebracornrewound" in t for _, t in got)                        # $rewindTo
    assert ("user", "after rewind zebracornafterrewind") in got


def test_dsh_zstd_multiframe(navcom, home):
    if "dsh" not in home:
        pytest.skip("zstd not installed")
    got = turns(navcom, home["dsh"], "dsh")
    assert got[0] == ("user", "run the calc check zebracorndsh")
    assert not any("zebracorninjected" in t or "zebracornthinking" in t for _, t in got)
    assert ("cmd", "python3 -c 'print(42)'") in got
    assert ("tool", "[bash: python3 -c 'print(42)']\n42 zebracorndshtool") in got
    assert navcom._native_title(str(home["dsh"]), "dsh") == "Verify calc with DeepSeek"
    assert navcom.short_ref(str(home["dsh"])) == "7a48d7c9"


def test_grok_updates(navcom, home):
    got = turns(navcom, home["grok"], "grok")
    assert got[0] == ("user", "check the rust build zebracorngrok")               # chunks joined
    assert ("assistant", "Building now, zebracorngrok answer.") in got
    assert ("cmd", "cargo build --release") in got
    assert ("tool", "[Run cargo build: cargo build --release]\nFinished release zebracorngroktool") in got
    assert not any(t == "partial" or "zebracornthinking" in t for _, t in got)    # in_progress + thoughts skipped
    assert ("user", "bare legacy line zebracorngroklegacy") in got                 # pre-envelope lines
    assert navcom._native_title(str(home["grok"]), "grok") == "Rust release build"
    assert navcom._project_from_key(str(home["grok"]), "grok").endswith("proj-alpha")


def test_kilo_uses_opencode_schema(navcom, home):
    assert turns(navcom, home["kilo"], "kilo") == [("user", "refactor the router zebracornkilo")]


def test_gemini_retention_fix(navcom, home, tmp_path):
    import json
    settings = navcom.gemini_settings_path()
    settings.write_text(json.dumps({"mcpServers": {"x": {}}}))
    assert navcom.ensure_gemini_retention() is True
    data = json.loads(settings.read_text())
    assert data["general"]["sessionRetention"] == {"enabled": False} and data["mcpServers"] == {"x": {}}
    settings.write_text(json.dumps({"general": {"sessionRetention": {"enabled": True, "maxAge": "90d"}}}))
    assert navcom.ensure_gemini_retention() is False                              # explicit choice respected


def test_grok_real_summary_shape(navcom, home):
    import json
    summary = home["grok"].parent / "summary.json"
    summary.write_text(json.dumps({"info": {"id": "x", "cwd": "/tmp/real-grok-project"},
                                   "generated_title": "Generated by Grok", "session_summary": "s"}))
    assert navcom._native_title(str(home["grok"]), "grok") == "Generated by Grok"
    assert navcom._project_from_key(str(home["grok"]), "grok") == "/tmp/real-grok-project"


def test_yaml_retention_edit_is_minimal(navcom, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("model: x\nsessions:\n    retention_days: 90\nother:\n  a: 1\n")
    assert navcom.ensure_yaml_setting(cfg, "sessions.auto_prune", False)
    text = cfg.read_text()
    assert "sessions:\n    auto_prune: false  # set by navcom: keep history\n    retention_days: 90\n" in text
    assert navcom.yaml_setting(cfg, "sessions.auto_prune") == "false"
    assert not navcom.ensure_yaml_setting(cfg, "sessions.auto_prune", False)       # idempotent
    cfg2 = tmp_path / "c2.yaml"
    cfg2.write_text("model: x\n")
    assert navcom.ensure_yaml_setting(cfg2, "sessions.auto_prune", False)
    assert cfg2.read_text().endswith("sessions:\n  auto_prune: false  # set by navcom: keep history\n")
    cfg3 = tmp_path / "c3.yaml"
    cfg3.write_text("sessions: {retention_days: 5}\n")
    assert not navcom.ensure_yaml_setting(cfg3, "sessions.auto_prune", False)       # flow style: hands off
    cfg4 = tmp_path / "c4.yaml"
    cfg4.write_text("sessions:\n  auto_prune: true\n")
    assert not navcom.ensure_yaml_setting(cfg4, "sessions.auto_prune", False)       # explicit choice kept
