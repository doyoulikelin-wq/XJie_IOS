# Canonical main bootstrap impact-contract audit

Date: 2026-07-14 (Asia/Shanghai)

## Scope

This checkpoint repairs the regression-contract boundary needed before the official `XAGE` history can bootstrap canonical `main`. It does not change application behavior, backend production code, database state, build number, signing, or TestFlight.

## Preserved failure

- Bootstrap PR: `#6`
- Failed workflow run: `29308076626`
- Failed policy job: `87005751227`
- Exact finding: the old `main` to `XAGE` cumulative range was missing `backend_chat_ai`, `backend_core`, and `backend_health_sync` from `change_impact.json`, and its selected contracts covered none of those primary domains.
- The run was not rerun and is not eligible for merge. A later green run cannot erase this failure; it must use a new commit containing the permanent repair.

## Root cause and same-class scan

The fixed original failure range, old `main@06be174bc05114ad920d1df1aa784c629a57f029..XAGE@da33da3cf24da903f70786f2a304770ed318ab57`, contains 74 commits and 235 changed paths across all 11 registered behavior domains. Those counts belong only to that preserved range and are not reused after this repair advances `XAGE`. The manifest at the original `XAGE` head described only the most recent chat accessibility repair, not the cumulative promotion range. Comparing every behavior domain with every contract found one deeper schema flaw: `backend_core` was the only domain with no contract at all.

The repair therefore keeps range classification fail-closed, adds the domain-specific `BACKEND-CORE-001`, and makes registry validation reject every behavior domain that lacks at least one contract. It intentionally does not add an all-domain bootstrap contract, because such a contract could become a blanket bypass for unrelated future changes.

An independent adversarial review then found that set coverage alone was still insufficient: a future domain could be added to an unrelated existing contract's `domains` and appear covered without acquiring its own explicit contract identity. Registry schema 2 therefore adds ordered `required_contract_ids` to all 11 domains. A code-side pinned mapping must match those arrays exactly; the mapping must also reverse exactly to the complete contract ID set and every contract's ordered `domains`. The change manifest must list the full required-contract union for every primary domain. A future domain, bilateral attachment to `PROCESS-GATE-001`, empty or duplicate requirements, order drift, reverse-domain drift, or an orphan blanket contract now fails closed.

A second adversarial pass kept every pinned ID and domain relationship intact but shortened `AI-SAFETY-001` to a one-character invariant with a generic `test_` substring anchor, then swapped the complete invariant/anchor definitions of `AI-SAFETY-001` and `UX-NAV-001`; the prior existence check accepted both. The guard now pins the SHA-256 of each complete normalized contract definition, including ordered domains, invariant, and exact path/symbol anchors. Both content-rebinding mutations fail without relying on human interpretation of the contract names.

A third pass kept all contract identities and definitions intact while clearing conservative overrides, shrinking UI verification to Release build only, hiding chat source paths, accepting every line as meaningful test evidence, or removing architecture limits. Each could previously weaken classification or execution without touching a contract digest. The guard now also pins the SHA-256 of the complete normalized registry, covering every domain mapping, override, architecture limit, command, and release-gate field. The five concrete bypass mutations are locked in the same named regression test.

## Named regression

The existing exact test inventory is preserved at 74 IDs. Two existing test IDs were strengthened:

- `RegressionGuardTests.test_manifest_contracts_must_cover_every_primary_domain`
  - reproduces the original three missing backend domains with the real registry;
  - adds the chat/health declarations and proves `backend_core` still blocks;
  - adds `BACKEND-CORE-001` and requires zero errors.
- `RegressionGuardTests.test_real_registry_rejects_process_identity_and_command_weakening`
  - rejects removing `backend_core` from its named contract;
  - rejects leaving `backend_chat_ai` with no contract coverage.

The first focused execution passed 2/2 in 33.868 seconds. After the initial schema-2 mapping assertions were added, the same IDs passed 2/2 in 43.857 seconds. Contract-definition digests then passed 2/2 in 47.800 seconds. After the full-registry digest and five policy-bypass mutations were added, the exact command `/usr/bin/python3 -I tools/tests/test_regression_guard.py RegressionGuardTests.test_manifest_contracts_must_cover_every_primary_domain RegressionGuardTests.test_real_registry_rejects_process_identity_and_command_weakening` passed 2/2 in 55.803 seconds; the exact tools inventory remains 74 IDs.

The pre-digest schema-2 tree passed the exact tools gate, `/usr/bin/python3 -I tools/python_test_gate.py tools`: 74/74 executed, zero skipped, in 155.430 seconds. Because the digest guard and tests changed afterward, that run is retained only as a checkpoint; final tools evidence must come from the stable-tree complete impacted gate.

Later full-gate attempts were deliberately interrupted as soon as review found stale range-count wording, a missing exact command in evidence, and then the future-domain attachment gap. Partial green components from those interrupted attempts are not counted as final-tree evidence.

## First complete local checkpoint

The complete working-tree gate, executed with `/usr/bin/python3 -I tools/run_regression_gate.py impacted`, finished successfully at 2026-07-14 13:50 (Asia/Shanghai):

- tools: 74/74;
- backend AI: 213/213;
- backend full: 261 passed plus the three fixed permitted skips, for exactly 264 collected IDs;
- backend Health: 25/25;
- iOS Unit: 149/149;
- iPhone 17 Pro full UI: 5/5;
- iPhone SE (3rd generation) small-screen UI: 2/2;
- unsigned generic iOS Release archive and device bundle validation: passed;
- final working-tree diff check: passed.

The xcresult summaries independently report zero failures, skips, or expected failures for all 149 Unit, 5 full-UI, and 2 small-screen UI tests. This is a checkpoint for the tree before this evidence text was written; it is not reused as proof for the amended tree.

## Remaining exact gates

Before this checkpoint can be merged into `XAGE`, the evidence-amended final tree still requires registry/working/range checks, the tracked tools inventory, a new complete impacted local gate, an exact feature-SHA PR run, and an exact merged-SHA push run. Only then may bootstrap PR #6 receive a new head SHA and a new complete run. No signed archive, export, or upload is permitted in this sequence.
