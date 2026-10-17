Feature: Places — list, explore, show, files, related, inspect and harvested sources
  As a captain flying the cockpit
  I want every place verb the action rail exposes to work from the command line first
  So that the browser stays a view of the same answers

  The Orchard galaxy is real: a Git repository with a declared system and two
  workspace apps, a standalone predecessor repository, both harvested by native
  Starforge and charted by `navcom atlas refresh --space`, all inside a
  throwaway HOME. {kind:label} names a charted place; {kind:label@parent} picks
  one of two places that share a label.

  Background:
    Given a home with sessions from every harness
    And a charted Orchard galaxy

  @critical
  Scenario: List systems, then only the planets inside one system
    When I run on the chart: navcom atlas list systems
    Then it succeeds
    And the output contains "Orchard tools  [system · established]"
    And the output contains "Products: 3 · lantern-modern, Orchard suite, radar-classic"
    And the output contains "Independent & unassigned  [system · unassigned]"
    When I run on the chart: navcom atlas list planets --within {system:Orchard tools}
    Then it succeeds
    And the output contains "Your galaxy / Orchard tools"
    And the output shows "{planet:lantern-modern}"
    And the output shows "{planet:Orchard suite}"
    And the output shows "{planet:radar-classic@Orchard tools}"
    And the output does not show "{planet:radar-classic@Independent & unassigned}"
    And the owner's real NavCom caches were not touched

  Scenario: Explore a product to see its code districts
    When I run on the chart: navcom atlas explore {planet:lantern-modern}
    Then it succeeds
    And the output contains "Your galaxy / Orchard tools / lantern-modern"
    And the output contains "passkeys · permissions · signin (4 files)  [district · suggested]"
    And the output contains "starforge token group"

  @critical
  Scenario: Show carries the exact CLI command for every verb the place accepts
    When I run on the chart: navcom atlas show {planet:lantern-modern} --json
    Then it succeeds
    And the JSON "center.label" is "lantern-modern"
    And the place offers the commands "explore, show, search, navigate, list, files, related, inspect, inspect_refresh, history_timeline, history_explore, source_search"
    And the place offers no launch, board or chart refresh command
    And every offered command is pinned to this scenario's caches
    And the offered "files" command runs as printed
    And the output contains "apps/lantern/auth/passkeys.py"

  Scenario: Files in a district, filtered by words, each with its own read command
    When I run on the chart: navcom atlas files {district:passkeys · permissions · signin (4 files)} --query tokens
    Then it succeeds
    And the output contains "apps/lantern/auth/tokens.py"
    And the output contains "1–1 of 1 matching retained files."
    And the output does not contain "apps/lantern/auth/signin.py"
    When I run the printed command containing "navcom sources read"
    Then it succeeds
    And the output contains "password identity authentication token"

  Scenario: Related finds the documented reference to the standalone predecessor
    When I run on the chart: navcom atlas related {planet:Orchard suite}
    Then it succeeds
    And the output contains "Documented reference:"
    And the output contains "work/radar-classic"
    And the output contains "README.md:5"
    And the output contains "neither changes the chart or establishes historical succession"

  # Inspect is cached until --refresh: after the working copy moves on, plain
  # inspect keeps the earlier observation and only --refresh sees the new commit.
  Scenario: Inspect observes physical code locations once, reuses that observation, and --refresh observes again
    When I run on the chart: navcom atlas inspect {planet:lantern-modern}
    Then it succeeds
    And the output contains "lantern-modern · physical code locations"
    And the output contains "New observation"
    And the output contains "branch: main"
    And the output shows "commit: {commit:modern}"
    When the Orchard working copy gets a new commit
    And I run on the chart: navcom atlas inspect {planet:lantern-modern}
    Then it succeeds
    And the output contains "Cached observation"
    And the output shows "commit: {commit:modern}"
    And the output does not show "commit: {commit:later}"
    When I run on the chart: navcom atlas inspect {planet:lantern-modern} --refresh
    Then it succeeds
    And the output contains "New observation"
    And the output shows "commit: {commit:later}"
    And the output does not show "commit: {commit:modern}"
    And the output does not contain "Cached observation"

  # radar-classic is a separate repository with no conversations of its own; the
  # Orchard working copy is the fixture sessions' project folder.
  Scenario: Sources list shows each harvested source with its scope, and which one has conversations
    When I run on the chart: navcom sources list
    Then it succeeds
    And the output contains "work/proj-alpha"
    And the output contains "work/radar-classic"
    And the output contains "  Scope: . · 3 files · 1 excluded"
    When I run on the chart: navcom sources list --json
    Then it succeeds
    And the harvested sources are "proj-alpha, radar-classic", all inside this scenario's home
    And only the source "proj-alpha" carries a conversation collection
    When I run on the chart: navcom sources list
    And I run the printed command containing "Conversations: navcom atlas explore"
    Then it succeeds
    And the output contains "How should orchard login keep amber tokens? orchardamber"
