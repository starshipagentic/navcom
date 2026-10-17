Feature: Fleet verbs — ships, starbases, carried context, boarding checks and expert questions
  As a captain looking at the fleet
  I want to list ships, read what they carry, check boarding and prepare questions
  So that nothing is boarded, launched or asked until I explicitly confirm it

  The fixture fleet is a Starship snapshot: the working ship Orchard sits at a
  remote starbase; its stored archive is local and carries two conversations.
  The tides expert is a Hermes profile; its fixture Hermes install can list
  profiles, reports and records each gateway status check, and records it if
  anything ever starts Hermes itself.

  Background:
    Given a home with sessions from every harness
    And a charted Orchard galaxy
    And launchers that record any call

  @critical
  Scenario: List ships and starbases
    When I run on the chart: navcom atlas list ships
    Then it succeeds
    And the output contains "Orchard  [ship · recorded]"
    And the output contains "remote.example: /remote/fleet/orchard/working"
    And the output shows "Read context: navcom atlas context {ship:Orchard}"
    When I run on the chart: navcom atlas list starbases
    Then it succeeds
    And the output contains "Bertha dock  [starbase · recorded]"
    And the output contains "Ships: 1 · Orchard"
    And the owner's real NavCom caches were not touched

  Scenario: A stored archive is listed beside its working ship
    Given the chart has {archive:Orchard · archive}
    When I run on the chart: navcom atlas list ships
    Then it succeeds
    And the output contains "Orchard · archive  [ship archive · recorded]"
    And the output shows "stored copy: Orchard · archive · {archive:Orchard · archive}"
    And the output shows "working copy: Orchard · {ship:Orchard}"

  @critical
  Scenario: Ship context lists, then searches, the carried conversations
    Given the chart has {archive:Orchard · archive}
    When I run on the chart: navcom atlas context {archive:Orchard · archive}
    Then it succeeds
    And the output contains "Orchard · archive · carried context · available"
    And the output contains "2 carried sessions"
    When I run on the chart: navcom atlas context {archive:Orchard · archive} --query amber
    Then it succeeds
    And the output contains "session-0 · turn 3 · user"
    And the output contains "Why did Orchard choose amber storage?"
    And the output contains "session-0 · turn 7 · assistant"
    And the output does not contain "verify orchard login"
    And no launcher was called

  # Page one ends inside "decisions", so neither page may hold the other's words.
  Scenario: Handover reads the ship's documented HANDOVER.md in bounded pages, not its conversations
    Given the chart has {archive:Orchard · archive}
    When I run on the chart: navcom atlas context {archive:Orchard · archive} --handover --max-chars 40
    Then it succeeds
    And the output contains "Orchard · archive · carried context · available"
    And the output contains "Recover amber storage decision"
    And the output contains ".starship/HANDOVER.md"
    And the output does not contain "verify login"
    And the output does not contain "Why did Orchard choose amber storage?"
    When I run the printed command containing "Continue: navcom atlas context"
    Then it succeeds
    And the output contains "s, then verify login."
    And the output does not contain "# Orchard"
    And the output does not contain "Continue:"
    When I run on the chart: navcom atlas context {ship:Orchard} --handover
    Then it fails with exit code 2
    And the output contains "Ship location is remote or unspecified; no local boarding route was inspected."
    And the output does not contain "Recover amber storage"
    And no launcher was called

  @critical
  Scenario: Board --validate refuses a remote ship without inspecting or launching anything
    When I run on the chart: navcom atlas board {ship:Orchard} --validate --json
    Then it fails with exit code 2
    And the JSON "interaction.state" is "blocked"
    And the JSON "interaction.reason" is "Ship location is remote or unspecified; no local boarding route was inspected."
    And the JSON "interaction.handoff.status" is "not launched"
    And the JSON "interaction.validation.turn_sent" is "false"
    And no launcher was called

  Scenario: Board --validate refuses a stored archive
    Given the chart has {archive:Orchard · archive}
    When I run on the chart: navcom atlas board {archive:Orchard · archive} --validate
    Then it fails with exit code 2
    And the output contains "Orchard · archive · blocked"
    And the output contains "archives cannot board a captain"
    And no launcher was called

  @critical
  Scenario: Ask prepares a reviewed question without sending it
    Given the chart has {star:tides}
    When I run on the chart: navcom atlas ask {star:tides} "What do the tide records say?" --json
    Then it succeeds
    And the JSON "interaction.state" is "review_required"
    And the JSON "interaction.question" is "What do the tide records say?"
    And the JSON "interaction.execution.question_sent" is "false"
    And the JSON "interaction.execution.agent_started" is "false"
    And the expert was never started
    And no launcher was called
    When I run on the chart: navcom atlas ask {star:tides} "What do the tide records say?"
    Then it succeeds
    And the output contains "tides · review required"
    And the output contains "To open this exact action in a terminal, repeat with --launch --review"
    And the expert was never started

  # The fixture Hermes records every gateway status check and any start of Hermes itself.
  @critical
  Scenario: Observe checks the expert's gateway status without starting it or asking anything
    Given the chart has {star:tides}
    When I run on the chart: navcom atlas inspect {star:tides}
    Then it succeeds
    And the output contains "tides · living-expertise candidate"
    And the output contains "Observation: null"
    And the expert's gateway status was never checked
    When I run on the chart: navcom atlas inspect {star:tides} --observe --json
    Then it succeeds
    And the JSON "inspection.observation.state" is "gateway_not_running"
    And the JSON "inspection.observation.started_services" is "false"
    And the JSON "inspection.observation.model_readiness" is "unverified"
    And the expert's gateway status was checked 1 time
    Given the tides gateway is running
    When I run on the chart: navcom atlas inspect {star:tides} --observe --json
    Then it succeeds
    And the JSON "inspection.observation.state" is "gateway_running"
    And the JSON "inspection.observation.started_services" is "false"
    And the expert's gateway status was checked 2 times
    And the expert was never started
    And no launcher was called

  @critical
  Scenario: Only the reviewed question opens, and only in a new terminal tab
    Given the chart has {star:tides}
    And the captain's terminal is tmux
    When I run on the chart: navcom atlas ask {star:tides} "What do the tide records say?" --json
    And I launch "Erase the tide records." with that review token
    Then it fails with exit code 2
    And stderr contains "review the handoff again"
    And no launcher was called
    When I launch "What do the tide records say?" with that review token
    Then it succeeds
    And the output contains "tides · dispatched"
    And the launcher "tmux" was called with "--profile=tides chat --cli"
    And the launcher "tmux" was called with "--query=What do the tide records say?"
    And no launcher but "tmux" was called
    And the expert was never started

  Scenario: With no known terminal, a reviewed launch hands over the command and starts nothing
    Given the chart has {star:tides}
    When I run on the chart: navcom atlas ask {star:tides} "What do the tide records say?" --json
    And I launch "What do the tide records say?" with that review token
    Then it fails with exit code 2
    And stderr contains "can't open a tab in this terminal"
    And no launcher but "pbcopy" was called
    And the expert was never started
