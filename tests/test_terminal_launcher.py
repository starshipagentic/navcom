"""A local web launch may use Terminal without changing headless CLI behavior."""
import os
import shlex
import stat
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def desktop(navcom, tmp_path, monkeypatch):
    for key in ("TERM_PROGRAM", "CMUX_WORKSPACE_ID", "CMUX_SOCKET_PATH", "CMUX_BUNDLED_CLI_PATH",
                "TMUX", "WEZTERM_PANE", "KITTY_WINDOW_ID", "SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(navcom.sys, "platform", "darwin")
    monkeypatch.setattr(navcom.shutil, "which", lambda _: None)
    monkeypatch.setattr(navcom.os, "getuid", lambda: 501)
    monkeypatch.setattr(navcom.os, "geteuid", lambda: 501)
    original_stat = os.stat
    console = SimpleNamespace(st_uid=501, st_mode=stat.S_IFCHR)
    monkeypatch.setattr(navcom.os, "stat", lambda path, *a, **kw:
                        console if path == "/dev/console" else original_stat(path, *a, **kw))
    commands, copied = [], []
    monkeypatch.setattr(navcom, "copy_to_clipboard", lambda text: copied.append(text) or True)
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw:
                        commands.append((argv, kw)) or SimpleNamespace(returncode=0))
    plan = dict(cwd=str(tmp_path), provider="codex",
                argv=["/usr/bin/ssh", "-tt", "recorded-host", "literal 'quote'; $(not-a-command)"])
    return plan, console, commands, copied


def test_explicit_web_launch_without_terminal_environment_uses_local_desktop(navcom, desktop):
    plan, _, commands, copied = desktop
    ok, message = navcom.resume_in_new_tab(plan, allow_gui=True)
    assert ok and message == "opened in a new Terminal window"
    line = "cd " + shlex.quote(plan["cwd"]) + " && " + shlex.join(plan["argv"])
    assert commands == [([
        "/usr/bin/osascript", "-e", 'tell application "Terminal" to do script ' + navcom._applescript_str(line),
        "-e", 'tell application "Terminal" to activate'],
        dict(capture_output=True, text=True, timeout=15, env=None))]
    assert not copied


def test_headless_cli_does_not_infer_gui_permission_from_logged_in_user(navcom, desktop):
    plan, _, commands, copied = desktop
    ok, message = navcom.resume_in_new_tab(plan)
    assert not ok and "copied" in message
    assert not commands and len(copied) == 1


@pytest.mark.parametrize("marker", ["SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"])
def test_web_fallback_does_not_open_gui_from_ssh(navcom, desktop, monkeypatch, marker):
    plan, _, commands, _ = desktop
    monkeypatch.setenv(marker, "remote-session")
    assert navcom.resume_in_new_tab(plan, allow_gui=True)[0] is False
    assert not commands


@pytest.mark.parametrize("condition", ["foreign-console", "root", "elevated", "missing-console", "not-device", "linux"])
def test_web_fallback_requires_owned_mac_console(navcom, desktop, monkeypatch, condition):
    plan, console, commands, _ = desktop
    if condition == "foreign-console":
        console.st_uid = 502
    elif condition == "root":
        console.st_uid = 0
        monkeypatch.setattr(navcom.os, "getuid", lambda: 0)
    elif condition == "elevated":
        monkeypatch.setattr(navcom.os, "geteuid", lambda: 0)
    elif condition == "missing-console":
        original_stat = os.stat
        def absent(path, *a, **kw):
            if path == "/dev/console":
                raise FileNotFoundError(path)
            return original_stat(path, *a, **kw)
        monkeypatch.setattr(navcom.os, "stat", absent)
    elif condition == "not-device":
        console.st_mode = stat.S_IFREG
    else:
        monkeypatch.setattr(navcom.sys, "platform", "linux")
    assert navcom.resume_in_new_tab(plan, allow_gui=True)[0] is False
    assert not commands


@pytest.mark.parametrize("terminal,marker,first", [
    ("cmux", "CMUX_WORKSPACE_ID", "/installed/cmux"),
    ("tmux", "TMUX", "tmux"),
    ("wezterm", "WEZTERM_PANE", "wezterm"),
    ("kitty", "KITTY_WINDOW_ID", "kitty"),
    ("iTerm.app", "TERM_PROGRAM", "osascript"),
    ("Apple_Terminal", "TERM_PROGRAM", "osascript"),
    ("ghostty", "TERM_PROGRAM", "open"),
])
def test_explicit_web_launch_preserves_preferred_terminal(navcom, desktop, monkeypatch, terminal, marker, first):
    plan, _, commands, copied = desktop
    monkeypatch.setenv(marker, terminal)
    monkeypatch.setattr(navcom.shutil, "which", lambda name: "/installed/" + name)
    assert navcom.resume_in_new_tab(plan, allow_gui=True)[0] is True
    assert len(commands) == 1 and commands[0][0][0] == first
    assert not copied


def test_failed_desktop_dispatch_still_reports_failure_and_copies(navcom, desktop, monkeypatch):
    plan, _, commands, copied = desktop
    def denied(argv, **kw):
        commands.append((argv, kw))
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(subprocess, "run", denied)
    ok, message = navcom.resume_in_new_tab(plan, allow_gui=True)
    assert not ok and "copied" in message
    assert len(commands) == 1 and len(copied) == 1


def test_web_fallback_runs_after_preferred_terminal_fails(navcom, desktop, monkeypatch):
    plan, _, commands, copied = desktop
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    def preferred_unavailable(argv, **kw):
        commands.append((argv, kw))
        return SimpleNamespace(returncode=0 if argv[0] == "/usr/bin/osascript" else 1)
    monkeypatch.setattr(subprocess, "run", preferred_unavailable)
    ok, message = navcom.resume_in_new_tab(plan, allow_gui=True)
    assert ok and message == "opened in a new Terminal window"
    assert len(commands) == 2 and 'iTerm2' in commands[0][0][2]
    assert commands[1][0][0] == "/usr/bin/osascript" and not copied


def test_pasted_prompt_path_keeps_explicit_gui_choice(navcom, desktop):
    plan, _, commands, copied = desktop
    plan["paste"] = "A user-reviewed prompt"
    ok, message = navcom.resume_in_new_tab(plan, allow_gui=True)
    assert ok and "prompt is on your clipboard" in message
    assert len(commands) == 1 and copied == [plan["paste"]]
