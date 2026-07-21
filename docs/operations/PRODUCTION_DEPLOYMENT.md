# Production deployment trust bundle

Production deployment has two independent approvals:

1. A protected pull request, merge to `main`, and exact `main` push CI approve the application candidate.
2. A root operator approves and transactionally installs the seven-file deployment trust bundle for that exact `main` SHA.

Repository copies are never production entrypoints. The supported root commands are:

```text
/usr/local/sbin/xjie-production-install EXPECTED_MAIN_SHA SOURCE_ROOT
/usr/local/sbin/xjie-production-install --recover
/usr/local/sbin/xjie-production-launch --doctor
```

Deploy and ingest also start through `/usr/local/sbin/xjie-production-launch`. Their GitHub token is one NUL-terminated value on an anonymous stdin pipe; it must never be placed in argv, the environment, a file, shell history, logs, this document, or project memory. `/usr/local/sbin/xjie-production-deploy` is an internal supervised child and must not be invoked directly.

## Fixed installed identity

The approval manifest and installer use this exact order:

| # | Repository source | Installed path | Owner / mode |
| ---: | --- | --- | --- |
| 1 | `scripts/launch_production_deploy.py` | `/usr/local/sbin/xjie-production-launch` | `root:root 0555`, regular, one link |
| 2 | `scripts/deploy_literature.sh` | `/usr/local/sbin/xjie-production-deploy` | `root:root 0555`, regular, one link |
| 3 | `backend/deploy/production_container.json` | `/usr/local/libexec/xjie-production-deploy/production_container.json` | `root:root 0444`, regular, one link |
| 4 | `backend/deploy/production_deploy_guard.py` | `/usr/local/libexec/xjie-production-deploy/production_deploy_guard.py` | `root:root 0444`, regular, one link |
| 5 | `tools/run_regression_gate.py` | `/usr/local/libexec/xjie-production-deploy/run_regression_gate.py` | `root:root 0444`, regular, one link |
| 6 | `quality/expected_python_tests.json` | `/usr/local/libexec/xjie-production-deploy/expected_python_tests.json` | `root:root 0444`, regular, one link |
| 7 | `scripts/install_production_deploy_bundle.py` | `/usr/local/sbin/xjie-production-install` | `root:root 0555`, regular, one link |

The installer is deliberately last. If power is lost during replacement, the currently running/recoverable installer remains installed until the other six files are durable.

Every source-root and installed-path ancestor must be a real `root:root` directory with no group/other write bit. Every source must be a root-owned regular file, have one hard link, be non-writable by group/other, and remain byte/identity stable across the transaction. The installer opens files with `O_NOFOLLOW`; symlinks, hard links, mutable ancestors, changed identities, extra/missing entries, or digest mismatches fail closed.

## Root approval manifest

The approval is the regular, one-link file:

```text
/etc/xjie-production-deploy/bundle-approval.json  root:root 0400
```

It has exactly the top-level keys `schema_version`, `expected_main_sha`, and `files`, in that order. It contains exactly the seven entries above, in that order; each entry has exactly `source`, `destination`, `mode`, and `sha256`, in that order. Modes are four-character octal strings (`"0555"` or `"0444"`). `expected_main_sha` is the exact 40-character lowercase merged `main` SHA, and every `sha256` is the independently approved 64-character lowercase file digest.

The following is a shape example only; repeated digits must be replaced with the reviewed real values:

```json
{"schema_version":1,"expected_main_sha":"1111111111111111111111111111111111111111","files":[{"source":"scripts/launch_production_deploy.py","destination":"/usr/local/sbin/xjie-production-launch","mode":"0555","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"source":"scripts/deploy_literature.sh","destination":"/usr/local/sbin/xjie-production-deploy","mode":"0555","sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},{"source":"backend/deploy/production_container.json","destination":"/usr/local/libexec/xjie-production-deploy/production_container.json","mode":"0444","sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"},{"source":"backend/deploy/production_deploy_guard.py","destination":"/usr/local/libexec/xjie-production-deploy/production_deploy_guard.py","mode":"0444","sha256":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"},{"source":"tools/run_regression_gate.py","destination":"/usr/local/libexec/xjie-production-deploy/run_regression_gate.py","mode":"0444","sha256":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"},{"source":"quality/expected_python_tests.json","destination":"/usr/local/libexec/xjie-production-deploy/expected_python_tests.json","mode":"0444","sha256":"ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"},{"source":"scripts/install_production_deploy_bundle.py","destination":"/usr/local/sbin/xjie-production-install","mode":"0555","sha256":"0000000000000000000000000000000000000000000000000000000000000000"}]}
```

Write the real manifest through an independently reviewed root provisioning procedure. Never generate its trust decision from an unreviewed checkout. The installer rechecks the manifest's inode and full metadata before replacement, after replacement, and before commit.

## Installation transaction

The source root must be an absolute, normalized root-controlled tree containing the approved content at the seven fixed relative paths. Run:

```text
/usr/local/sbin/xjie-production-install 0123456789abcdef0123456789abcdef01234567 /root/xjie-approved-main
```

Before writing anything, the installer:

- requires real root and disables core dumps/process dumping;
- loads the installed launcher lock API, takes the same root deployment lock and legacy compatibility lock, and rejects a live lease;
- rejects an active production cutover journal;
- requires the exact pinned production-container specification and a running, healthy production container;
- runs the currently installed launcher `--doctor` through an installer-only fixed-FD authority protocol;
- verifies the stable root approval and all seven source/installed identities and digests.

It then writes `/var/lib/xjie-production-deploy/bundle-install.json` as `root:root 0600`. The state directory is `root:root 0700`. Every stage, replacement, and rollback step is journaled and fsynced. Each new stage and old backup is in the destination's directory, so replacement is an atomic same-filesystem rename.

After all seven replacements, the installer verifies the aggregate installed digest, runs the new launcher `--doctor`, and verifies production health again. Only then does it mark the transaction verified, fsync and remove the journal, and remove the validated backup/stage files. A launcher that acquires its normal root lock refuses to start while this journal exists. Environment variables cannot activate the installer-only doctor exception; it requires the inherited root/legacy lock descriptors plus a one-use anonymous authority pipe.

Any install failure restores every exact old digest in reverse order, then runs the old launcher `--doctor` and production health check before clearing the journal. Recovery refuses to overwrite a target whose current digest is neither the journaled old nor new digest.

## Crash recovery

Do not delete or edit the journal, hidden stage files, or hidden backup files. With no deploy/ingest process active, run:

```text
/usr/local/sbin/xjie-production-install --recover
```

Recovery always converges to the recorded old bundle; it never guesses that a mixed bundle is acceptable. A normal install invocation also detects and rolls back an interrupted transaction, then stops and requires the operator to rerun the approved install command. If recovery reports an unjournaled target, unsafe artifact identity, failed old doctor, or unhealthy production container, retain all evidence and resolve that exact identity problem instead of deleting the journal.

The first-ever installation of this transaction mechanism is a separate bootstrap ceremony: an out-of-band, reviewed root provisioner must install all seven exact files, modes, directories, launch authority, and approval manifest together, then run the launcher doctor. After bootstrap, direct copying is forbidden; all bundle updates use `xjie-production-install`.

## Candidate qualification and runtime order

For a normal deployment, the trusted launcher and entrypoint:

1. Validate and hash the installed seven-file bundle, take the global locks, and refuse an install journal or incompatible live lease.
2. Recover a cutover journal using only the installed trusted implementation before beginning new qualification.
3. Bind a clean local view to the exact official HTTPS `main` SHA with replacement refs, hooks, fsmonitor, alternate object stores, custom Git execution paths, user config, proxies, and credential-helper fallback disabled.
4. Fetch each fixed bundle blob from that exact official commit and require byte equality with the root-installed bundle, both before and after the read-only source archive is materialized.
5. Run the installed release gate—not candidate Python—to prove official default branch/tip, merged PR provenance, exact successful `main` push check, and distinct `main`/locked-legacy-`XAGE` protections.
6. Build the digest-bound production image, scan its archive and runtime identity, run exact backend inventory, prove no migration delta, and execute the read-only schema contract before journaled cutover.
7. Revalidate official qualification and installed identities at the defined pre-database, pre-cutover, and pre-journal-clear boundaries.

A successful cutover retains one stopped rollback backup. The next online-qualified deployment may remove it only after all managed cleanup candidates pass the batch identity validation.

## Database schema dry-run

The candidate model is materialized only in an isolated reference PostgreSQL server. The reference server, materializer, and reference catalog reader use Docker log driver `none`. The materializer has no network, receives only its ephemeral reference-database URI, and runs with a 64 KiB file limit and timeout. Its stdout result and stderr are separate owner-only files capped at 64 KiB; success requires empty stderr and a guard validation bound to the exact candidate migration manifest. Failure may display only a bounded stderr tail, after which both files are deleted. The reference catalog is separately capped at 16 MiB.

The production catalog probe remains capped at 64 KiB. Its minimal probe environment is derived from—and checked against—the immutable application-env snapshot before a digest-pinned `psql` client receives it. The production account must be a dedicated read-only principal in addition to the probe's server-attested read-only transaction.

Before the first real deployment with the catalog guard, run the same generated probe during an approved read-only maintenance check and retain only its non-secret result/evidence. Production history may contain legacy tables or native `JSONB` columns that differ from the current ORM manifest. Do not weaken exact comparison or alias `JSON` and `JSONB` to make the check pass. Any confirmed difference is a separate baseline/model reconciliation project with backup and recovery evidence.

Never place production credentials or credential-derived values in repository files, logs, documentation, evidence, chat, or project memory.
