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
    When I run: navcom -n 100
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
    When I run: navcom zebracorn --until 2026-01-01
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

  Scenario: The session navcom runs inside is left out of normal searches
    When I run with CLAUDE_CODE_SESSION_ID=11111111-2222-4333-8444-555555555555: navcom zebracornclaude
    Then it succeeds
    And the output contains "No hits."
    When I run with CLAUDE_CODE_SESSION_ID=11111111-2222-4333-8444-555555555555: navcom zebracorn
    Then it succeeds
    And the output contains "hits from this session (--include-self to show)"
    And the output does not contain "zebracornclaude"
    When I run with CLAUDE_CODE_SESSION_ID=11111111-2222-4333-8444-555555555555: navcom zebracornsubagent
    Then it succeeds
    And the output contains "No hits."
    When I run with CLAUDE_CODE_SESSION_ID=11111111-2222-4333-8444-555555555555: navcom zebracornclaude --include-self
    Then it succeeds
    And the "claude" harness is in the results

  Scenario: --file accepts a bare session file name
    When I run: navcom zebracorn --file 11111111-2222-4333-8444-555555555555.jsonl
    Then it succeeds
    And the output lists 1 sessions
    And the "claude" harness is in the results

  Scenario: --latest narrows to the single newest session
    When I run: navcom zebracorn --latest
    Then it succeeds
    And the output lists 1 sessions

  Scenario: --list honours --recent and harness filters
    When I run: navcom --list --recent 1 --claude
    Then it succeeds
    And the output contains "claude"
    And the output does not contain "codex"

  Scenario: A read-only index is still searchable
    When I run: navcom zebracorn
    And I make the index read-only
    And I run: navcom zebracorncodex
    Then it succeeds
    And the "codex" harness is in the results

  Scenario: A hanging summarizer is killed on time
    Given a summarizer CLI that hangs forever
    When I run with NAVCOM_SUMMARY_TIMEOUT=6: navcom zebracorn --solo
    Then it succeeds
    And stderr contains "timed out"

  Scenario: Unknown flags are reported on stdout too when output is captured
    When I run: navcom zebracorn --frobnicate
    Then it fails with exit code 2
    And the output contains "unrecognized arguments: --frobnicate"

  Scenario: The same session id in two harnesses opens the right copy
    Given the pi session was imported into omo under the same id with different content
    When I run: navcom zebracorn
    And I run: navcom zebracornimported --omo
    Then it succeeds
    And the output contains "ref omo:123456789abc"
    And the output contains "navcom --open omo:123456789abc:"
    When I open the printed ref
    Then the output contains "zebracornimported"
