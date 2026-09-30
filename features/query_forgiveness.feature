Feature: Queries never break on punctuation or odd syntax
  As an LLM that types whatever the user said
  I want navcom to accept any query text
  So that I never have to retry with the punctuation stripped out

  Background:
    Given a home with sessions from every harness

  @critical
  Scenario Outline: Punctuation-heavy queries succeed without syntax errors
    When I search with these literal arguments
      | arg     |
      | <query> |
    Then it succeeds
    And the output does not contain "syntax error"
    And the output contains "<expect>"

    Examples:
      | query                               | expect           |
      | it's broken; again?                 | claude           |
      | drizzle migration, it's broken      | claude           |
      | main()                              | claude           |
      | (see main())                        | claude           |
      | v0.1.3 log-search                   | claude           |
      | don't use generate                  | claude           |
      | "drizzle migration"                 | claude           |
      | “drizzle migration”                 | claude           |
      | drizzle AND                         | claude           |
      | OR drizzle                          | claude           |
      | NOT                                 | query:           |
      | (drizzle OR cognito                 | claude           |
      | *                                   | No hits.         |
      | ' OR 1=1 --                         | query:           |
      | drizzle, cognito, terraform         | gemini           |
      | cognito; terraform                  | codex            |
      | cerbos \| kubectl                   | goose            |

  Scenario: Words split across flags and bare arguments are all used
    When I run: navcom --query drizzle migration --claude
    Then it succeeds
    And the output contains "drizzle* migration*"

  Scenario: When no single turn has every word, fall back to any word
    When I run: navcom cognito terraform kubernetes
    Then it succeeds
    And the output contains "note: no single turn contains ALL"
    And the "codex" harness is in the results

  Scenario: Queries with awkward shell quoting can come through stdin
    When I pipe this query into navcom
      """
      it's the "drizzle"; migration, (really)
      """
    Then it succeeds
    And the "claude" harness is in the results

  Scenario: A leading verb is ignored
    When I run: navcom search zebracorncodex
    Then it succeeds
    And the output contains "query: zebracorncodex*"

  Scenario: Unknown flags get a suggestion instead of a bare usage dump
    When I run: navcom zebracorn --jsn
    Then it fails with exit code 2
    And stderr contains "did you mean --json"
