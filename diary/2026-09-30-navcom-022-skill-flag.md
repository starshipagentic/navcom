# navcom 0.2.2: `navcom --skill` hands any agent the skill card

**Pain:** Nothing universal lets a CLI give an LLM its skill card. `--help` is the only
convention every model knows. We wanted the obvious move — "ask the tool for its SKILL.md" — and
found someone had already drafted it.

## Summary

- `navcom --skill` prints the stock `SKILL.md`. It's mentioned at the top of `--help` and in the card itself.
- `navcom --skill install` does full-service install into every harness present (Claude Code,
  Codex, `~/.agents` for pi/omo/opencode/goose) and reports where. `--install-skills` is kept as a
  hidden alias.
- `--skill list`, `--skill list --json` and `--skill export` implement the **Skillflag** draft
  (Onur Solmaz, 2026-01-11, github.com/osolmaz/skillflag, spec v0.1):
  - `list`: `<id>\t<summary>`, or JSON with `skillflag_version`, `id`, `summary`, `version`,
    `files` and `digest`.
  - `export`: a deterministic USTAR stream with a single `navcom-session-recall/` top-level
    directory, `mtime`/`uid` 0, and `root` names.
- **Interop proven:** `navcom --skill export | HOME=<tmp> npx -y skillflag install --agent claude
  --scope user` installed a SKILL.md byte-identical to ours.

## Decisions

- **Rejected Skillflag's "producers MUST NOT install into agents" rule.** The owner's philosophy is
  full-turn service: newcomers need it working, and power users know how to delete a folder. We
  keep the silent auto-install and a real `--skill install`. We stay compatible on list and export
  only, so their installer still works.
- **A bare `--skill` means `show`.** Simplest for an LLM: one flag, one card.
- **Adoption reality:** Skillflag had 8 GitHub stars at the time. LLMs don't try `--skill` by
  instinct yet. `--help` remains the universal entry point, and it now points at `--skill`.

## Snippets

```bash
navcom --skill | head                         # the card
navcom --skill list --json                    # digest == sha256 of `navcom --skill export`
navcom --skill export | tar -tvf -            # navcom-session-recall/ + SKILL.md, epoch mtimes
navcom --skill export | shasum -a 256         # 839aa8cc… for 0.2.1's card (deterministic)
```

## Files changed

- `navcom.py`: `SKILL_SUMMARY`, `skill_tar_bytes`, `cmd_skill`, the `--skill`/`--skills` flag
  with early dispatch (no index needed), a help line, a card line, and the version bump to 0.2.2.
- `features/skills.feature` and its steps: show, install, Skillflag list/json/export (tar
  structure), and a bad action.
- `README.md`: the `--skill` block. `skills/.../SKILL.md` regenerated. `pyproject.toml` set to 0.2.2.

**tags:** navcom, skillflag, SKILL.md, agent-skills, --skill, interop, full-service-install. A CLI
that can hand any agent its own manual, and installs it anyway.
