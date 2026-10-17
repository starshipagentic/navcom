Feature: Search inside a place, a source or one conversation
  As a captain who has flown somewhere
  I want every search to stay inside the place, source or session I chose
  So that a local question never gets a galaxy-wide answer

  Lantern (auth code) and Radar (telemetry code) live side by side in the
  Orchard suite; a standalone radar-classic repository shares Radar's name.

  Background:
    Given a home with sessions from every harness
    And a charted Orchard galaxy

  @critical
  Scenario: Evidence search finds code inside the place and nothing from its neighbours
    When I run on the chart: navcom atlas search passkey --within {planet:lantern-modern} --space --evidence
    Then it succeeds
    And the output contains "lantern-modern · evidence found"
    And the output contains "apps/lantern/auth/passkeys.py"
    When I run on the chart: navcom atlas search telemetry --within {planet:lantern-modern} --space --evidence
    Then it succeeds
    And the output does not contain "evidence found"
    And the output does not contain "apps/radar"
    And the owner's real NavCom caches were not touched

  Scenario: Evidence search finds the place's own conversations with the command that opens them
    When I run on the chart: navcom atlas search orchardamber --within {planet:Orchard suite} --space --evidence
    Then it succeeds
    And the output contains "Conversation: How should orchard login keep amber tokens? orchardamber"
    And the output contains "navcom --open a7c3e1d2-3333-4444-8555-666666666666:1"

  # Every fixture module, Radar's and radar-classic's included, says "token", so
  # a search that escaped lantern-modern would show radar files and group its
  # evidence under the whole suite.
  @critical
  Scenario: Fly to a place, then find words there
    When I run on the chart: navcom atlas navigate "fly to lantern-modern then find token"
    Then it succeeds
    And the output contains "resolved: Resolved search place: lantern-modern."
    And the output shows "Destination: {planet:lantern-modern}"
    And the output contains "lantern-modern · evidence found"
    And the output contains "apps/lantern/auth/tokens.py"
    And the output does not contain "radar"
    And the output does not contain "Orchard suite · evidence found"

  @critical
  Scenario: An ambiguous place name returns choices instead of a galaxy-wide search
    When I run on the chart: navcom atlas navigate "find telemetry in radar-classic"
    Then it succeeds
    And the output contains "choose: Choose the place to search; no code or conversations have been searched yet."
    And the output shows "--choose {planet:radar-classic@Orchard tools}"
    And the output shows "--choose {planet:radar-classic@Independent & unassigned}"
    And the output does not contain "evidence found"
    When I run the printed command containing "--choose {planet:radar-classic@Independent & unassigned}"
    Then it succeeds
    And the output contains "Your galaxy / Independent & unassigned / radar-classic"
    And the output contains "radar-classic/radar/beacon.py"
    And the output does not contain "apps/radar"

  Scenario: Source search stays inside one harvested source and path
    When I run on the chart: navcom sources search passkey --within {source:proj-alpha} --path apps/lantern
    Then it succeeds
    And the output contains "apps/lantern/auth/passkeys.py"
    When I run on the chart: navcom sources search telemetry --within {source:proj-alpha} --path apps/lantern
    Then it succeeds
    And the output contains "No matches."
    And the output does not contain "apps/radar"

  @critical
  Scenario: Search inside one conversation
    When I run on the chart: navcom orchard login --file a7c3e1d2
    Then it succeeds
    And the output contains "2 hits in 1 session"
    And the output contains "ref a7c3e1d2"
    And the output contains "#3 user: Lantern now needs passkeys for «orchard» «login»."
    When I run on the chart: navcom zebracorn --file a7c3e1d2
    Then it succeeds
    And the output contains "No hits."
    And the output lists 0 sessions
