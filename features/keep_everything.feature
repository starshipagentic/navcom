Feature: Keep everything — tool outputs, raw transcripts, daily upkeep
  As someone whose project history is irreplaceable
  I want navcom to keep and search every tool output and every raw transcript
  So that nothing depends on a harness's retention policy or on me remembering

  Background:
    Given a home with sessions from every harness

  @critical
  Scenario: Tool outputs are searchable with --tool, and stay out of normal searches
    When I run: navcom zebracorntoolclaude
    Then it succeeds
    And the output contains "No hits."
    When I run: navcom zebracorntoolclaude --tool
    Then it succeeds
    And the output contains "tool: [Bash: npx drizzle-kit push --force]"
    When I run: navcom zebracorntoolgoose OR zebracorntoolopencode OR zebracorntoolgemini OR zebracorntoolcodex --tool
    Then it succeeds
    And the "goose" harness is in the results
    And the "opencode" harness is in the results
    And the "gemini" harness is in the results
    And the "codex" harness is in the results

  Scenario: --everything searches turns and tool outputs together
    When I run: navcom cognito --everything --codex
    Then it succeeds
    And the output contains "user:"
    And the output contains "tool:"

  Scenario: navcom's own output is never indexed as a tool output
    When I run: navcom zebracornselfoutput --everything --include-self
    Then it succeeds
    And the output contains "No hits."

  @critical
  Scenario: Every Claude transcript is archived and comes back after deletion
    When I run: navcom --maintain
    Then it succeeds
    And the output contains "archived"
    And the claude transcript has a private archive copy
    When the claude transcript is deleted
    And I run: navcom zebracornclaude
    Then the output contains "claude"
    When I run: navcom --restore 11111111
    Then it succeeds
    And the output contains "claude --resume 11111111-2222-4333-8444-555555555555"
    And the claude transcript is back byte for byte

  Scenario: --restore all brings back every deleted transcript
    When I run: navcom --maintain
    And the claude transcript is deleted
    And I run: navcom --restore all
    Then it succeeds
    And the claude transcript is back byte for byte

  Scenario: The daily job installs itself, and off stays off
    When I run: navcom zebracorn
    Then a daily navcom --maintain job is scheduled
    When I run: navcom --daily off
    Then it succeeds
    And no daily job is scheduled
    When I run: navcom zebracorn
    Then no daily job is scheduled
    When I run: navcom --daily on
    Then a daily navcom --maintain job is scheduled

  Scenario: --where shows the archive and the daily job
    When I run: navcom --maintain
    And I run: navcom --where
    Then the output contains "archive"
    And the output contains "daily"
