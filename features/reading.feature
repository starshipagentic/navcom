Feature: Reading and narrowing sessions
  As an agent that found a hit
  I want to open the surrounding turns and narrow by time and project
  So that I get exactly the context I need

  Background:
    Given a home with sessions from every harness

  @critical
  Scenario: Open the turns around a hit by its ref
    When I run: navcom zebracornpi --pi
    And I open the ref of the first "pi" session at turn 2
    Then it succeeds
    And the output contains "▶ #2 user:"
    And the output contains "serve qwen on the studio box"

  Scenario: Open a whole session by ref
    When I run: navcom --open ses_opencode1
    Then it succeeds
    And the output contains "cmd: grep -c it( tests/cerbos.test.ts"

  Scenario: Unknown ref is a clear error
    When I run: navcom --open nosuchsession
    Then it fails with exit code 1
    And the output contains "no session matches"

  Scenario: Context mode expands the turns around each hit
    When I run: navcom zebracorncodex --context
    Then it succeeds
    And the output contains "▶ #"
    And the output contains "cmd: rg cognito src/"

  Scenario: No query lists recent sessions with titles
    When I run navcom with no arguments
    Then it succeeds
    And the output contains "most recent sessions"
    And the output contains "Verify cerbos test gaps"
    And the output contains "Goose kubernetes session"

  Scenario: --here keeps only sessions from the current project
    When I run: navcom zebracorn --here
    Then it succeeds
    And every harness is in the results
    When I run from outside the project: navcom zebracorn --here
    Then it succeeds
    And the output contains "No hits."

  Scenario: --project filters by path fragment
    When I run: navcom zebracorn --project proj-alpha
    Then it succeeds
    And every harness is in the results
    When I run: navcom zebracorn --project nothing-like-this
    Then it succeeds
    And the output contains "No hits."

  Scenario: Date filters use each session's last activity
    When I run: navcom zebracorn --since 2020-01-01
    Then it succeeds
    And every harness is in the results
    When I run: navcom zebracorn --days 1
    Then it succeeds
    And the output contains "No hits."

  Scenario: --where shows every harness location
    When I run: navcom --where
    Then it succeeds
    And the output contains "goose"
    And the output contains "opencode"
    And the output contains "omo"

  Scenario: --this-session searches only the conversation navcom runs inside
    When I run with CLAUDE_CODE_SESSION_ID=11111111-2222-4333-8444-555555555555: navcom zebracorn --this-session
    Then it succeeds
    And the output lists 1 sessions
    And the "claude" harness is in the results
