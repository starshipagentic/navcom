Feature: Dated history — timeline, one commit, a dated journey, landing and dated conversations
  As a captain looking back in time
  I want to land on a product exactly as it was committed at a date
  So that later files, labels and conversations never leak into the past

  The Orchard suite was committed on 2025-03-01 (lantern-classic: signin, tokens,
  permissions) and again on 2025-06-01 (renamed lantern-modern, plus passkeys).
  Its design conversation has turns dated 2025-03-10 (amber tokens) and
  2025-05-20 (passkeys). The current chart only knows lantern-modern.

  Background:
    Given a home with sessions from every harness
    And a charted Orchard galaxy

  Scenario: The timeline lists only the commits that touched a place
    When I run on the chart: navcom history timeline {planet:lantern-modern}
    Then it succeeds
    And the output contains "Selected paths: apps/lantern"
    And the output contains "2025-06-01T00:00:00Z  Lantern learns passkeys"
    And the output contains "2025-03-01T00:00:00Z  Classic Orchard products"
    When I run on the chart: navcom history timeline {planet:radar-classic@Orchard tools}
    Then it succeeds
    And the output contains "Selected paths: apps/radar"
    And the output contains "2025-03-01T00:00:00Z  Classic Orchard products"
    And the output does not contain "Lantern learns passkeys"

  Scenario: The timeline narrows to one file with --include, and never widens past the place
    When I run on the chart: navcom history timeline {planet:lantern-modern} --include apps/lantern/auth/tokens.py
    Then it succeeds
    And the output contains "Selected paths: apps/lantern/auth/tokens.py"
    And the output contains "2025-03-01T00:00:00Z  Classic Orchard products"
    And the output does not contain "Lantern learns passkeys"
    When I run on the chart: navcom history timeline {planet:lantern-modern} --include apps/lantern/auth/passkeys.py
    Then it succeeds
    And the output contains "2025-06-01T00:00:00Z  Lantern learns passkeys"
    And the output does not contain "Classic Orchard products"
    When I run on the chart: navcom history timeline {planet:lantern-modern} --include apps/radar
    Then it fails with exit code 2
    And stderr contains "--include must stay within the selected place's repository-relative scope"
    And the output does not contain "Classic Orchard products"

  Scenario: The timeline reads one chosen Git repository with --repo, and only one the place records
    When I run on the chart: navcom history timeline --repo {repo:radar-classic}
    Then it succeeds
    And the output contains "Selected paths: ."
    And the output contains "2024-11-01T00:00:00Z  Standalone radar"
    And the output does not contain "Classic Orchard products"
    When I run on the chart: navcom history timeline {planet:lantern-modern} --repo {repo:orchard}
    Then it succeeds
    And the output contains "Selected paths: apps/lantern"
    And the output contains "2025-06-01T00:00:00Z  Lantern learns passkeys"
    And the output does not contain "Standalone radar"
    When I run on the chart: navcom history timeline {planet:lantern-modern} --repo {repo:radar-classic}
    Then it fails with exit code 2
    And stderr contains "--repo is not a recorded Git location for this place"
    And the output does not contain "Standalone radar"

  # A linked worktree on its own branch gives every Orchard place a second Git
  # copy whose HEAD has one Lantern commit the original lacks. Worktrees share
  # one object store, so only HEAD ancestry (timeline) and the chosen repository
  # (explore and its replay command) can show which copy was read.
  @critical
  Scenario: A place with two Git copies asks for --repo, and reads exactly the copy --repo names
    Given the Orchard suite has a second working copy with its own Lantern commit
    When I run on the chart: navcom history timeline {planet:lantern-modern}
    Then it fails with exit code 2
    And stderr contains "This place has multiple Git copies; select one with --repo ROOT"
    And stderr contains "work/orchard-mirror"
    And stderr contains "work/proj-alpha"
    And the output does not contain "Lantern learns passkeys"
    When I run on the chart: navcom history timeline {planet:lantern-modern} --repo {repo:orchard-mirror}
    Then it succeeds
    And the output contains "work/orchard-mirror"
    And the output contains "2025-07-01T00:00:00Z  Mirror-only lantern work"
    And the output contains "2025-06-01T00:00:00Z  Lantern learns passkeys"
    When I run on the chart: navcom history timeline {planet:lantern-modern} --repo {repo:orchard}
    Then it succeeds
    And the output contains "work/proj-alpha"
    And the output contains "2025-06-01T00:00:00Z  Lantern learns passkeys"
    And the output does not contain "Mirror-only lantern work"
    And the output does not contain "orchard-mirror"
    When I run on the chart: navcom history explore {planet:lantern-modern} {commit:mirror} --repo {repo:orchard-mirror} --json
    Then it succeeds
    And the JSON "repository" is "{repo:orchard-mirror}"
    And the JSON "snapshot.repository" is "{repo:orchard-mirror}"
    And the JSON "subject" is "Mirror-only lantern work"
    When I run the "cli_command" of that JSON
    Then it succeeds
    And the JSON "repository" is "{repo:orchard-mirror}"
    And the JSON "commit" is the mirror Orchard commit
    When I run on the chart: navcom history explore {planet:lantern-modern} {commit:classic} --repo {repo:orchard} --json
    Then it succeeds
    And the JSON "repository" is "{repo:orchard}"
    And the JSON "snapshot.repository" is "{repo:orchard}"
    And the owner's real NavCom caches were not touched

  # The classic commit predates passkeys.py: exploring it must show and search
  # only what was committed then, whatever the working copy holds today.
  @critical
  Scenario: Explore one commit, then search only the files committed in it
    When I run on the chart: navcom history explore {planet:lantern-modern} {commit:classic} --query password --json
    Then it succeeds
    And the JSON "commit" is the classic Orchard commit
    And the JSON "subject" is "Classic Orchard products"
    And the committed files are "apps/lantern/README.md, apps/lantern/auth/permissions.py, apps/lantern/auth/signin.py, apps/lantern/auth/tokens.py, apps/lantern/package.json"
    And the revision evidence has hits, all inside the committed files
    When I run the "cli_command" of that JSON with "password" replaced by "passkey"
    Then it succeeds
    And the JSON "commit" is the classic Orchard commit
    And the revision evidence has no hits
    When I run on the chart: navcom history explore {planet:lantern-modern} {commit:modern} --query passkey
    Then it succeeds
    And the output contains "  apps/lantern/auth/passkeys.py"
    And the output does not contain "apps/radar"
    When I run on the chart: navcom history explore {planet:lantern-modern} {commit:classic} --repo {repo:radar-classic}
    Then it fails with exit code 2
    And stderr contains "--repo is not a recorded Git location for this place"
    And the owner's real NavCom caches were not touched

  @critical
  Scenario: A dated system journey lands on a product through its own printed Land command
    When I run on the chart: navcom history system {system:Orchard tools} --at 2025-04-01 --json
    Then it succeeds
    And the JSON node {planet:lantern-modern} is labelled "lantern-classic"
    When I follow the "land_command" of {planet:lantern-modern} in that JSON
    Then it succeeds
    And the JSON "center.label" is "lantern-classic"
    And the JSON "commit" is the classic Orchard commit
    And the landed files are "apps/lantern/README.md, apps/lantern/auth/permissions.py, apps/lantern/auth/signin.py, apps/lantern/auth/tokens.py, apps/lantern/package.json"
    And the owner's real NavCom caches were not touched

  @critical
  Scenario: Land in a dated district and search only its committed files
    When I run on the chart: navcom history system {system:Orchard tools} --at 2025-04-01 --json
    And I follow the "land_command" of {planet:lantern-modern} in that JSON
    And I follow the "land_command" of the node labelled "permissions · signin · tokens" with: --query password
    Then it succeeds
    And the JSON "center.label" is "permissions · signin · tokens"
    And the landed files are "apps/lantern/auth/permissions.py, apps/lantern/auth/signin.py, apps/lantern/auth/tokens.py"
    And the landed evidence has hits, all inside the landed files
    When I run the "cli_command" of that JSON with "--query=password" replaced by "--query=passkey"
    Then it succeeds
    And the landed evidence has no hits

  Scenario: A saved landing survives the working copy and chart disappearing
    When I run on the chart: navcom history system {system:Orchard tools} --at 2025-04-01 --json
    And I follow the "land_command" of {planet:lantern-modern} in that JSON
    And the Orchard working copy and the current chart are deleted
    And I run the "cli_command" of that JSON
    Then it succeeds
    And the JSON "center.label" is "lantern-classic"
    And the JSON "commit" is the classic Orchard commit

  @critical
  Scenario: Dated conversations at a cutoff exclude later turns
    When I run on the chart: navcom history conversations {planet:Orchard suite} --at 2025-04-01 --query "orchard login"
    Then it succeeds
    And the output contains "Orchard suite · current address · at or before 2025-04-01T00:00:00Z"
    And the output contains "2025-03-10T09:00:00Z · claude · a7c3e1d2-3333-4444-8555-666666666666:1"
    And the output does not contain "passkeys"
    And the output contains "after cutoff"
    When I run on the chart: navcom history conversations {planet:Orchard suite} --at 2025-04-01 --query passkeys
    Then it succeeds
    And the output contains "No eligible dated conversation passages were found."
    When I run on the chart: navcom history conversations {planet:Orchard suite} --at 2025-06-01 --query passkeys
    Then it succeeds
    And the output contains "2025-05-20T09:01:00Z · claude · a7c3e1d2-3333-4444-8555-666666666666:4"
