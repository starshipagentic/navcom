Feature: Get back into a past conversation yourself
  As a developer who found the conversation I need
  I want the exact command that cds into its folder and reopens it in its harness
  So that I can pick up where I (or my agent) left off without hunting for ids

  Background:
    Given a home with sessions from every harness

  @critical
  Scenario: Search results end with the copy-paste command that reopens the top session
    When I run: navcom zebracorn
    Then it succeeds
    And the output contains "→ get back into ["
    And the output contains "any session: navcom --resume <ref>"

  @critical
  Scenario Outline: navcom --resume gives the cd + reopen command for every harness that can resume
    When I resume the first "<harness>" session from a search
    Then it succeeds
    And the output contains "cd "
    And the output contains "<command>"

    Examples:
      | harness  | command                                              |
      | claude   | claude --resume                                      |
      | codex    | codex resume                                         |
      | gemini   | gemini --resume                                      |
      | opencode | opencode --session ses_opencode1                     |
      | kilo     | kilo --session ses_kilo1                             |
      | pi       | pi --session                                         |
      | goose    | goose session --resume --session-id 20260904_1       |
      | dsh      | dsh tui --resume session-7a48d7c9-b372-4f90-8537-d9c82b6c65a7 |
      | grok     | --resume 0199bbbb-cccc-7ddd-8eee-ffff00001111         |
      | qwen     | qwen --resume 0f0e0d0c-0000-4000-8000-00000000qwen    |
      | kimi     | kimi -S session_00000000-0000-4000-8000-0000000kimi01 |
      | crush    | crush --session 5e55a0de                              |
      | copilot  | copilot --resume                                      |
      | cline    | cline --id 1790000000000_fixtr                        |
      | codewhale | codewhale --resume 0f0e0d0c-0b0a-4009-8807-060504030201 |
      | reasonix | reasonix --resume 20261001-000000                     |
      | deepcode | deepcode -r 6f1c2d3e-4a5b-4c6d-8e7f-001122334455      |
      | hermes   | hermes --resume 20261001_120000_abc123                |
      | openhands | openhands --resume 0123456789abcdef0123456789abcdef  |
      | vibe     | vibe --resume 0123abcd                                |
      | agy      | agy --conversation 0f1e2d3c-4b5a-4968-8777-a6b5c4d3e2f1 |
      | droid    | droid --resume 0b5e1f0e-1111-4222-8333-944455556666   |
      | cursor   | cursor-agent --resume 5c0ffee0-1111-4222-8333-944455556666 |
      | kiro     | kiro-cli                                              |
      | amp      | amp threads continue T-019cc922-3fd6-706b-9950-e56ccf39e65a |
      | auggie   | auggie --resume 3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a22  |
      | grokdev  | grok --session 9c50d8f22635                           |

  Scenario Outline: Harnesses with no resume-by-id get the closest command, and say what it does
    When I resume the first "<harness>" session from a search
    Then it succeeds
    And the output contains "<command>"
    And stderr mentions "<says>"

    Examples:
      | harness  | command                       | says                       |
      | continue | cn --fork                     | copy of its history        |
      | aider    | aider --restore-chat-history  | whole chat history         |

  Scenario: --open shows how to resume the session it prints
    When I run: navcom zebracorn --claude
    And I open the ref of the first "claude" session at turn 2
    Then the output contains "resume: cd "
    And the output contains "claude --resume"

  Scenario: --json carries the resume command for agents and scripts
    When I run: navcom zebracorn --codex --json
    Then it succeeds
    And the output contains ""resume": "cd "

  Scenario: A hit ref works too
    When I run: navcom zebracorn --codex
    And I resume the first "codex" hit ref
    Then it succeeds
    And the output contains "codex resume"

  @critical
  Scenario: A session too old to reopen gets a fresh agent primed to reload it
    When I run: navcom zebracorn --codex
    And the "codex" transcript is deleted
    And I resume the first "codex" session from the last search
    Then it succeeds
    And stderr mentions "can't reopen this session"
    And the output contains "cd "
    And the output contains "run `navcom --recap "

  Scenario: A deleted Claude session is restored from navcom's archive on resume
    When I run: navcom zebracorn --claude
    And the "claude" transcript is deleted
    And I resume the first "claude" session from the last search
    Then it succeeds
    And stderr mentions "restores it from the archive first"

  @critical
  Scenario: navcom --recap gives an LLM the whole story, sized for its context
    When I run: navcom zebracorn --codex
    And I recap the first "codex" session
    Then it succeeds
    And the output contains "## What the user asked"
    And the output contains "## Where it stopped"
    And the output contains "## Commands run"
    And the output contains "## Dig deeper"

  Scenario: Search results point at the recap
    When I run: navcom zebracorn --codex
    Then the output contains "whole story: navcom --recap "

  Scenario: Revive any session in another agent
    When I run: navcom zebracorn --codex
    And I run --resume on the first "codex" session with: --with gemini --print
    Then it succeeds
    And the output contains "gemini -i "
    And the output contains "navcom --recap "

  Scenario: An agent navcom can't start with a prompt is a clear error
    When I run: navcom zebracorn --codex
    And I run --resume on the first "codex" session with: --with aider
    Then it fails with exit code 2
    And the output contains "Pick one of: claude, codex"
