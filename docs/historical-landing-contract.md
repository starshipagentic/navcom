# Landing inside a saved historical product

The owner journey is to enter a system at a chosen time, land on a product,
inspect its authentication or other meaningful area, read code, then return
without losing date, scope or viewpoint. A link to the current product does not
satisfy that journey.

## Existing foundation

A saved system plan already pins repository heads, cutoff, current address IDs,
positions and selected file scopes. Its exact query result contains validated
committed snapshots and native Starforge token groups. `history land` consumes
those saved results; it does not invent a classifier or a second index.

```text
navcom history land PLACE --cursor PIN --result-key KEY
navcom history land PLACE --cursor PIN --result-key KEY --group GROUP --query TEXT
```

System output supplies a complete Land command. Product output supplies complete
district commands. JSON output preserves immutable source references for the
existing source reader. The local HTTP endpoint is `POST /api/history/land` with
`within`, `cursor`, `result_key`, optional `group`, `q` and `limit`. Cache location
and execution deadline belong to the server, not the client request.

## Data and boundaries

- The cursor selects one existing immutable plan; `result_key` selects the exact
  saved query/limit result set. Missing results do not trigger current discovery.
- The product must be a saved plan anchor, match its repository job and original
  scope, and have a successful validated snapshot receipt.
- Product files are the retained paths within that saved scope. A district is a
  suggestion from one existing native group, restricted to its exact members.
  Labels format the native evidence using the existing shared label helper.
- Both search paths use the receipt's historical source cache and the selected
  file whitelist. Current files, current catalog ownership and newer HEADs are
  never consulted. Missing or changed retained bytes fail visibly.
- Breadcrumbs use available saved ancestors. Missing outer ancestor metadata is
  disclosed; no present-day ancestor is substituted.
- Current addresses establish navigation, not historical ownership. Git dates
  are not deployment dates. Native exclusions, partial grouping and undated
  conversation limitations remain visible.

The bridge retains the origin system viewpoint and the selected product/group,
result key and pin. Back returns to the earlier viewpoint; reload and links must
reopen that same saved state. Search changes the query, never the date or pins.
Explicit Return to present remains the route to current geography.

Journey links carry the camera. The URL holds `camera=SCALE_X_Y`: the absolute
scale to four significant digits and the pan in whole pixels, updated with
`replaceState` whenever the camera moves (a camera move never adds a history
entry). A copied link opened in a new tab or profile therefore lands on the same
date, pin, district, query and view; Back and reload keep using the exact camera
saved in history state. A link carries the current camera only: after *Back to
dated system* from a freshly opened link, the system opens at its default framing.
The camera is view state; no service or CLI result names it.

Implementation and native CLI/browser evidence are recorded in the
[land in the past](../diary/2026-10-16-land-in-the-past.md) and
[handoff](../diary/2026-10-16-galactic-navigation-handoff.md) diaries. This contract by itself does
not establish that the journey has passed.
