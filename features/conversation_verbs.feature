Feature: Conversation verbs — open, recap, family and resume previews launch nothing
  As a captain who found a conversation
  I want to read it, get its whole story, see its family and preview how to get back into it
  So that the action rail can offer these verbs without ever starting an agent by accident

  Every agent CLI and terminal launcher on PATH is a recorder: if anything is
  started, the recorder says so.

  Background:
    Given a home with sessions from every harness
    And the Orchard design conversation
    And launchers that record any call

  @critical
  Scenario: Open a conversation at an exact turn
    When I run: navcom --open a7c3e1d2:3
    Then it succeeds
    And the output contains "ref a7c3e1d2  turns 1-4 of 4"
    And the output contains "▶ #3 user:"
    And the output contains "Lantern now needs passkeys for orchard login."
    And the output contains "resume: cd ~/work/proj-alpha && claude --resume a7c3e1d2-3333-4444-8555-666666666666"
    And the output contains "recap:  navcom --recap a7c3e1d2"
    And no launcher was called

  @critical
  Scenario: Recap gives the whole story
    When I run: navcom --recap a7c3e1d2
    Then it succeeds
    And the output contains "navcom --recap · claude"
    And the output contains "## What the user asked"
    And the output contains "How should orchard login keep amber tokens?"
    And the output contains "passkeys"
    And no launcher was called

  @critical
  Scenario: Resume --print previews the original harness command
    When I run: navcom --resume a7c3e1d2 --print
    Then it succeeds
    And the output contains "cd ~/work/proj-alpha && claude --resume a7c3e1d2-3333-4444-8555-666666666666"
    And no launcher was called

  @critical
  Scenario Outline: Resume --with another harness --print previews a primed fresh session
    When I run: navcom --resume a7c3e1d2:3 --with <harness> --print
    Then it succeeds
    And the output contains "cd ~/work/proj-alpha && <command>"
    And the output contains "run `navcom --recap a7c3e1d2`"
    And the output contains "`navcom --open a7c3e1d2:3` for the part I was looking at"
    And no launcher was called

    Examples:
      | harness | command    |
      | codex   | codex '    |
      | gemini  | gemini -i  |
      | claude  | claude '   |

  # The home's Claude conversation 11111111 has one subagent, agent-a1b2c3; the
  # Orchard design conversation has no relatives and must never join that family.
  @critical
  Scenario: Find a subagent, show its family, then its whole tree, without launching anything
    When I run: navcom zebracornsubagent
    Then it succeeds
    And the output contains "ref agent-a1b2c3"
    When I run: navcom atlas show agent-a1b2c3
    Then it succeeds
    And the output contains "subagent digging zebracornsubagent"
    And the output contains "Parent: 11111111-2222-4333-8444-555555555555"
    And the output contains "navcom --resume agent-a1b2c3 --print"
    And the output does not contain "Children:"
    When I run: navcom atlas show 11111111
    Then it succeeds
    And the output contains "Children: agent-a1b2c3"
    And the output does not contain "Parent:"
    When I run: navcom atlas tree agent-a1b2c3
    Then it succeeds
    And the output contains "/goal ship the zebracorn release"
    And the output contains "  ↳ subagent digging zebracornsubagent"
    And the output contains "1–2 of 2 items"
    And the output does not contain "orchard"
    When I run: navcom atlas tree a7c3e1d2
    Then it succeeds
    And the output contains "How should orchard login keep amber tokens? orchardamber"
    And the output contains "1–1 of 1 items"
    And the output does not contain "zebracorn"
    And no launcher was called

  # tmux is checked before any platform-specific terminal, so this runs anywhere.
  Scenario: The recorders are live — a --tab resume does reach a terminal launcher
    Given my terminal is tmux
    When I run: navcom --resume a7c3e1d2 --tab
    Then it succeeds
    And the launcher "tmux" was called with "claude --resume a7c3e1d2-3333-4444-8555-666666666666"
    And no launcher but "tmux" was called
