Feature: The navcom skill card installs itself
  As a user who never wants to be asked
  I want every agent harness to learn about navcom automatically
  So that agents reach for navcom without being told

  Background:
    Given a home with sessions from every harness

  @critical
  Scenario: Any navcom run silently installs the skill for every present harness
    When I run: navcom zebracorn
    Then it succeeds
    And the skill card exists for "claude"
    And the skill card exists for "codex"
    And the skill card exists for "agents"
    And stderr does not mention skills

  Scenario: A skill someone edited is left alone
    When I run: navcom zebracorn
    And I edit the "claude" skill card
    And I run: navcom zebracorn
    Then the "claude" skill card still has my edit

  Scenario: An older navcom-managed card is updated on upgrade
    When I run: navcom zebracorn
    And the "codex" skill card is from an older navcom
    And I run: navcom zebracorn
    Then the "codex" skill card is current

  Scenario: Opting out
    When I run with NAVCOM_NO_SKILLS=1: navcom zebracorn
    Then the skill card is missing for "claude"

  Scenario: --install-skills shows where it went
    When I run: navcom --install-skills
    Then it succeeds
    And the output contains "navcom-session-recall/SKILL.md"

  @critical
  Scenario: --skill prints the stock skill card
    When I run: navcom --skill
    Then it succeeds
    And the output starts with the skill frontmatter
    And the output contains "navcom --open <ref>:<turn>"

  Scenario: --skill install does the full-service install and reports
    When I run with NAVCOM_NO_SKILLS=1: navcom --skill install
    Then it succeeds
    And the skill card exists for "claude"
    And the skill card exists for "codex"
    And the skill card exists for "agents"

  Scenario: Skillflag-compatible list and export
    When I run: navcom --skill list
    Then it succeeds
    And the output contains "navcom-session-recall	"
    When I run: navcom --skill list --json
    Then it succeeds
    And the output contains ""skillflag_version": "0.1""
    And the output contains ""digest": "sha256:"
    When I export the skill as a tar stream
    Then the tar holds exactly "navcom-session-recall/SKILL.md" under one top-level directory

  Scenario: --skill with a wrong action is a clear error
    When I run: navcom --skill frobnicate
    Then it fails with exit code 2

  @critical
  Scenario: navcom stops Claude Code from deleting history after 30 days
    Given Claude settings without a retention value
    When I run: navcom zebracorn
    Then Claude's cleanupPeriodDays is 36500
    And the other Claude settings are untouched
    And a backup of the original Claude settings exists

  Scenario: An explicit retention choice is respected
    Given Claude settings with cleanupPeriodDays 90
    When I run: navcom zebracorn
    Then Claude's cleanupPeriodDays is 90

  Scenario: A Claude settings file navcom can't parse is never touched
    Given Claude settings that are not plain JSON
    When I run: navcom zebracorn
    Then it succeeds
    And the Claude settings file is byte-for-byte unchanged

  Scenario: --where reports Claude's retention
    When I run: navcom --where
    Then the output contains "keeps history ~forever"

  Scenario: navcom's index is private to its owner
    When I run: navcom zebracorn
    Then every navcom index file is readable only by its owner
