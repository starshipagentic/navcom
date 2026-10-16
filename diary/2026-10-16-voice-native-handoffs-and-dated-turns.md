# October 16 — voice, native handoffs, and dated conversations

The bridge remains usable while these interactions are added. The galactic goal
is still active; terminal dispatch and metadata inspection are not human takeover.

## Decisions carried into code

- Keep NavCom's CLI and browser on the same services. `atlas ask` prepares a
  Hermes question and `atlas board` discovers/validates a native captain route.
  Opening either requires the exact reviewed identity and fresh validation.
  Use installed Hermes and ship-commission tools, never receipt-supplied scripts.
- An expert's broad inventory root can hide its own declaration under bounded
  search. Resolve the selected declaration's Git repository through existing
  discovery tools; keep the old inventory scope as provenance. This fixed the
  actual Observatory preparation without a project-specific catalog patch.
- Use the installed small Whisper model for optional local speech. Capture at
  most 20 seconds, two CPU threads, one transcription across NavCom processes,
  short-lived model, no downloads. Preserve newer typing and require Search
  after transcription. Cancel/Escape/navigation release capture.
- Save original message timestamps in the ordinary indexing pipeline. Old rows
  converge through existing bounded parser upgrades; no hand-filled dates.
  Native Codex/Claude/Gemini/pi/omo timestamps are supported. Unsupported or
  malformed dates remain unknown; edits cannot borrow an older message date.
- Show dated conversation passages separately from historical Git source. The
  current project address establishes scope, not historical ownership or exact
  commit membership. Opening the full current chat is an explicitly labeled step.

## Proof so far

- Actual local CLI speech: synthetic “Fly to semantic observatory.”, 1.776 seconds
  of audio, transcribed correctly in 2.1 seconds. No microphone was recorded.
- Actual Observatory question preparation succeeds, with question_sent=false.
  No live question was sent and no model/container was started.
- Two real sessions ingested into a temporary index: 38/38 native turns dated.
  The original conversation index was not manually edited.
- Browser fixture: April excludes the later Cognito decision; September finds
  it. Dated child passage includes its parent, without current titles or later
  turns. Escape closes the passage; Back restores date and query. Query now
  survives copied historical URLs as well as browser history.
- Browser real expert review appears, and changing the question removes the
  stale launch action. Native launch was deliberately not exercised against a
  real agent in this test.

## Not decided or not yet proven

No new provider abstraction beyond the verified native interfaces. No model
installation, cloud speech, automatic captain commissioning or remote boarding.
Real microphone capture, a real expert answer, visible captain takeover and
historical ownership reconstruction remain unverified. Remote Bertha ship routes
remain unavailable from this Mac. Wider intake/ownership coverage remains work.

## Installed checkpoint

The combined regression ran 414 cases: 413 passed, and one older fixture assumed
indexing never stores project metadata. That fixture now explicitly represents a
legacy index; its 30-case spatial/timestamp gate passes. The final star gate passes
37 cases; boarding and voice pass 39. All 130 BDD scenarios / 699 steps pass.
JavaScript syntax, Python compilation, generated help card and diff checks pass.

The offline wheel and installed pipx package match all 32 runtime files. Installed
speech recognized the same phrase in 2.054 seconds. Installed expert preparation
and dated parent/child CLI results passed. A normal installed matrix/EXP32 search
exercised the automatic parser upgrade: 53 sessions now use parser version 4 and
25,189 of 695,530 indexed rows have recorded timestamps. Coverage is still partial;
no direct SQL backfill was performed.

The installed bridge remains open at http://127.0.0.1:62811/?view=space . Real
remote NavCom ship boarding reports unavailable before any captain connection.
No live expert question or captain launch was performed. Screenshot:
`/tmp/navcom-galaxy-interactions-ready.jpg`. No release was published.
