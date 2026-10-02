Feature: Fast search across every harness
  As an LLM agent (or a human) recalling past coding sessions
  I want one command that finds the turns that mention something
  So that I can pick up context without re-reading whole transcripts

  Background:
    Given a home with sessions from every harness

  @critical
  Scenario: Bare words search every harness, compact by default
    When I run: navcom zebracorn
    Then it succeeds
    And the output contains "navcom: "
    And every harness is in the results
    And the output has no terminal escape codes
    And the output contains "→ read around a hit: navcom --open"

  @critical
  Scenario: --compact is accepted and changes nothing
    When I run: navcom zebracorn --compact
    Then it succeeds
    And every harness is in the results

  Scenario Outline: Each harness is searchable on its own
    When I run: navcom zebracorn<harness> --<harness>
    Then it succeeds
    And the "<harness>" harness is in the results
    And the output lists <sessions> sessions

    Examples:
      | harness  | sessions |
      | claude   | 1        |
      | codex    | 1        |
      | gemini   | 1        |
      | pi       | 1        |
      | omo      | 1        |
      | opencode | 1        |
      | goose    | 1        |
      | grok     | 1        |
      | kilo     | 1        |
      | dsh      | 1        |

  Scenario: Gemini CLI 0.39+ JSONL sessions are indexed with their edits replayed
    When I run: navcom zebracornjsonlgem
    Then it succeeds
    And the output contains "final answer"
    And the output does not contain "draft answer"
    When I run: navcom zebracornrewound
    Then the output contains "No hits."

  Scenario: Legacy opencode and goose storage are indexed too
    When I run: navcom zebracornocleg OR zebracornlegacygoose
    Then it succeeds
    And the "opencode" harness is in the results
    And the "goose" harness is in the results

  Scenario: Shell commands the agent ran are searchable, noise is not
    When I run: navcom drizzle-kit --cmd
    Then it succeeds
    And the output contains "cmd:"
    When I run: navcom zebracornthinking OR zebracorntoolresult OR zebracornsynthetic OR zebracornmeta
    Then it succeeds
    And the output contains "No hits."

  Scenario: navcom does not find its own past invocations
    When I run: navcom zebracorn --cmd
    Then it succeeds
    And the output does not contain "navcom --query zebracorn"

  Scenario: Slash-command arguments are kept as what the user asked
    When I run: navcom zebracorn release --user
    Then it succeeds
    And the output contains "/goal"

  Scenario: Escape codes logged inside a session never leak out
    When I run: navcom abc1234 --context --color always
    Then it succeeds
    And the output does not contain "[2mabc1234"

  Scenario: Harness picker accepts names and aliases
    When I run: navcom zebracorn -p omo-ai,pi-dev
    Then it succeeds
    And the output lists 2 sessions
    When I run: navcom zebracorn -p nope
    Then it fails with exit code 2
    And stderr contains "unknown harness"

  Scenario: Gemini content stored as a list of parts reads as text
    When I run: navcom terraform --gemini
    Then it succeeds
    And the output contains "plan for zebracorn zebracorngemini"
    And the output does not contain "{'text'"

  Scenario: JSON output for tools
    When I run: navcom zebracorncodex --json
    Then it succeeds
    And the output is valid JSON with 1 sessions

  Scenario: -n is per harness so every harness gets a turn
    When I run: navcom zebracorn -n 1
    Then it succeeds
    And every harness is in the results
    And the output contains "top 1 per harness shown"

  Scenario: Version from the flags LLMs guess
    When I run: navcom -v
    Then it succeeds
    And the output contains "navcom 0.5.0"

  @critical
  Scenario: Every registered harness indexes prompts, replies, commands and tool output — never injected context
    Then every registered harness passes the four-role check
    When I run: navcom zebracorninjected --everything --include-self
    Then the output contains "No hits."
