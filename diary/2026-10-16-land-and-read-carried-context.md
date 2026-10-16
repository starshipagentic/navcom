# Land, browse, and read what a ship carries

October 16, 2026. Continue the galactic bridge without replacing Starforge's
classification or Starship's context reader.

Decided and implemented:

- `atlas files PLACE` lists only files already retained by the selected product,
  moon or district. The CLI, web endpoint and landing panel share one service.
  Filters, pages and file reads preserve the artifact generation. Missing paths
  and bounded scans disclose partial coverage; a partial scan cannot offer an
  unstable next page. Browsing invokes no harvest or source analysis.
- `atlas context SHIP` lists the carried catalog and uses the independently
  installed Starship reader to search and open original message indices. It also
  reads the documented handover. Subsequent reads and returned commands pin the
  catalog hash. Native input is a bounded, temporary, unchanged copy created and
  removed by the tool; there is no manually synchronized catalog or cargo.
- The ship inspector has a separate carried-context panel. Search, exact-turn
  opening, Back, reload and handover use that same public service. Captain launch
  stays a distinct action. The current remote ships correctly remain unavailable
  to a local reader.
- Starforge's native dependency extractor qualifies nested runnable manifests.
  Konva and PureCSS remain inside CarePlus instead of becoming extra product
  planets; their retained code is still searchable. Explicit local/workspace
  packages and independent native Git roots retain their destinations.
- The Navigator accepts the complete destination phrase `experiment 32` as an
  alias for the existing numbered experiment name. This is a general command
  language alias, not a new classifier or project profile; ambiguity and scope
  are preserved and content queries are unchanged.
- Exact zero PCM audio returns no text without invoking the local recognizer.
  Capture, cancellation and WAV conversion have regression coverage. No model
  was downloaded. Existing local Whisper recognized synthetic speech in 2.05s;
  that is not a real microphone test.

CLI proof preceded UI adoption. The real EXP29 engine/jobs district lists its
v31-v34 retained files; the v34 source opens from the published snapshot. The
browser verified filtering, reading, Back and reload. A clearly isolated Orchard
fixture proved carried catalog → typed search → exact turn → reload → Back →
handover using the installed native reader. The real Bertha cbt-origins ship
showed remote unavailability without substituting local host conversations.

Unresolved and not decided: native fleet discovery still omits a local commission
archive that is separate from its remote working ship. A future adapter must
represent the archive from native commission evidence, not relabel the remote
ship. Broader harvest coverage is partial. Real microphone capture, an expert
reply and visible captain takeover remain unverified. This checkpoint does not
complete the overall goal or publish an external release.

Validation checkpoint: 641 pytest tests and 130 BDD scenarios (699 steps) passed.
The final controller/alias/file gate passed 41 tests after the last continuity
fixes. The offline wheel was installed locally and 38 runtime files plus nine
asset/license files match checkout, wheel and installation bytes. Installed CLI
file-list → pinned v34 read and native carried search both passed. Installed
browser text `find matrix in experiment 32` resolved EXP32 with source and
conversation evidence while preserving the galaxy chart; actual Syra flight
showed 20 destinations. The original flight URL remains available.
