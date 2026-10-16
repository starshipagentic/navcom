# Carried ship context

2026-10-16. NavCom delegates carried-conversation search and open to the
independently installed ship-commission `scripts/navcom.py`. This reads retained
dialogue, not current host conversations or a live captain. It does not board,
restore, commission, contact a service, or send an agent a turn.

```text
navcom atlas context SHIP
navcom atlas context SHIP --query "storage decision"
navcom atlas context SHIP --session SESSION --turn 7 --catalog SHA256
navcom atlas context SHIP --handover
```

Use an exact ship ID or a unique chart name. `--turn` means one exact original
message index, not a new sequential index or a starting offset. `--offset` counts
matching messages (or sessions for the catalog); handover offsets count
characters. Returned `cli_command`, `continue_command`, and message
`open_command` preserve the selected ship and carried catalog generation.

The shared service is `navcom_navigation.context(...)`. GET
`/api/space/context` accepts `within`, `action` (`inspect`, `search`, `open`, or
`handover`), `q`, `ref`, `turn`, `offset`, `limit`, `max_chars`, and `catalog`.
Its flat response contains `state`, `ship_id`, `context_kind`, `catalog`,
`provenance`, `coverage`, and the action's `sessions`, `messages`, or `text`.
`next_offset` is null at the end. An unavailable response has a `reason` and
`coverage.complete=false`; the CLI exits 2. The API does not accept executable
paths or tool configuration from requests.

Pass the returned `catalog` for later dialogue reads and inventory pages. A
changed catalog returns unavailable and asks the caller to search/reopen the
current inventory. Handover is a separate documented file and does not accept
a dialogue catalog pin.

The lower-level `navcom_ship_context.inspect_context` reads only the public
catalog metadata. `read_context` reads only catalog-declared dialogue records
under `.starship/secrets/navcom/` or the exact `.starship/HANDOVER.md` document.
It validates the exact ship's explicitly local host before touching that
namespace. Remote and unspecified hosts never become local mount guesses.

Each read is bounded: a 1 MiB catalog, 1,000 session entries, 8 MiB per dialogue
record, 64 MiB total selected records, and a 15-second native reader process.
Output is at most 50 messages with 8,000 characters each; defaults are 10 and
2,000. Handover is capped at 256 KiB and paged by characters. A catalog open can
select one session when the whole ship exceeds the search bound. File traversal
reuses the source reader's descriptor-relative no-follow/nonblocking opens.

The native reader receives an ephemeral view of the unchanged bounded catalog
and selected record bytes. It never runs the ship's carried scripts. The view
is deleted after the read; cargo, host history and indexes are unchanged. Record
hashes, when present in the native catalog, are checked before execution. Native
message IDs, original turn indices, roles and clipping indicators are retained.

The public fixture tests use the current installed native reader, not a search
stub. They prove CLI/API parity, pagination, exact-turn reads, generated command
replay, handover, remote unavailability and changed-catalog rejection. These
tests do not establish live captain takeover or application readiness.

## Automatic archive discovery

The fleet adapter keeps the bridge's working ships at their recorded hosts and
paths. Exact `.starship/commission/<id>/RESULT.json` evidence also anchors a
sibling `archive`, when a standard capture receipt records this host as origin.
The installed Starship observer reads the bounded descriptor metadata in one
batch. Cache identities include the evidence, receipt, descriptor and installed
tool identity. Repeated unchanged refreshes do not rerun the observer.

Each archive is a separate `kind=ship, form=archive` destination. `archive_of`
links it to the recorded working ship; source-root links associate it with code
places without establishing ownership. Neither link inflates conversation
counts. Missing receipts, foreign origins and unavailable metadata remain
coverage gaps. Integrity and captain readiness remain separate and unverified.

`atlas list ships`, search, show and context include these stored copies.
Unfiltered `atlas explore` keeps the overview clear and explicitly reports its
stored-copy catalog. In the bridge, **Stored ship copies** at the galaxy and
**Ships & stored context** at linked destinations expose the same records.
Archives support carried-context reading but reject boarding before workspace,
route or captain inspection. No archive bytes are changed.

Real isolated CLI proof on October 16 discovered 22 archives alongside the 107
unchanged working-ship IDs. The CBT archive lists eight sessions; search and
exact-original-turn reading succeeded through the installed native reader.
Its remote working ship remained locally unavailable. This is metadata/context
proof, not a seal verification or captain takeover.

## Navigator federation

Navigator search also calls the native carried-history reader for ships in the
selected hierarchy and ships with an explicit saved source-context association
to its products or experiments. Associated ships may expose their recorded
archive copies. This is a storage association, not ownership or transcript
membership. District searches never inherit whole-product cargo; an exact ship
search never substitutes a linked physical copy.

Carried matches have a separate evidence section. The address is the physical
ship ID, catalog SHA-256, native session ID and original message index. Identical
session IDs in different physical copies stay distinct. Missing titles use a
labeled verbatim excerpt, not a generated title; read time never becomes a
conversation date. Native search matches all case-folded whitespace terms in
catalog order and supplies no semantic ranking.

The private bounded query cache checks the native catalog, record identities and
installed reader. Repeated searches reuse zero-match results as well as hits and
advance to unsearched ships. Coverage reports unavailable and unsearched copies;
no match in a partial search does not prove absence. CLI opening commands and the
bridge's carried reader retain the exact catalog pin.
