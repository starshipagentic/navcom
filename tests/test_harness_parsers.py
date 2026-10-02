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
