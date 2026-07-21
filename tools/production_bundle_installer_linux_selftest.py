#!/usr/bin/env python3
"""Root/Linux transaction tests for the production trust-bundle installer.

This is intentionally a direct self-test rather than ``unittest`` discovery: the
tracked Python inventory must remain exact, while the installer needs real root
ownership, Linux ``O_NOFOLLOW``/``flock`` behaviour, and durable rename/fsync
operations.
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


installer = load_module(
    "xjie_production_bundle_installer_selftest",
    REPO_ROOT / "scripts" / "install_production_deploy_bundle.py",
)
launcher = load_module(
    "xjie_production_launcher_installer_selftest",
    REPO_ROOT / "scripts" / "launch_production_deploy.py",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_new(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        mode,
    )
    try:
        installer.write_all(descriptor, payload)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def replace_file(path: Path, payload: bytes, mode: int) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    write_new(path, payload, mode)


def close_all(files) -> None:
    for item in files:
        item.close()


def expect_install_error(callback, label: str) -> None:
    try:
        callback()
    except installer.InstallError:
        return
    raise AssertionError(label + " did not fail closed")


def fixture_manifest(specs, expected_sha: str, new_payloads: list[bytes]) -> dict:
    return {
        "schema_version": 1,
        "expected_main_sha": expected_sha,
        "files": [
            {
                "source": spec.source,
                "destination": spec.destination,
                "mode": format(spec.mode, "04o"),
                "sha256": sha256(payload),
            }
            for spec, payload in zip(specs, new_payloads)
        ],
    }


def legacy_schema_v1_journal(
    specs,
    expected_sha: str,
    approval_payload: bytes,
    old,
    new,
) -> dict:
    """Independent fixture for the already-deployed schema-v1 writer."""
    old_entries = [(spec.destination, item.payload) for spec, item in zip(specs, old)]
    new_entries = [(spec.destination, item.payload) for spec, item in zip(specs, new)]
    return {
        "schema_version": 1,
        "state": "planned",
        "expected_main_sha": expected_sha,
        "approval_sha256": sha256(approval_payload),
        "old_bundle_sha256": installer.bundle_sha256(old_entries),
        "new_bundle_sha256": installer.bundle_sha256(new_entries),
        "staged_count": 0,
        "replaced_count": 0,
        "rollback_count": 0,
        "files": [
            {
                "source": spec.source,
                "destination": spec.destination,
                "mode": format(spec.mode, "04o"),
                "old_sha256": sha256(old_file.payload),
                "new_sha256": sha256(new_file.payload),
                "stage": installer.artifact_paths(spec.destination)[0],
                "backup": installer.artifact_paths(spec.destination)[1],
            }
            for spec, old_file, new_file in zip(specs, old, new)
        ],
    }


def write_manifest(path: Path, manifest: dict) -> None:
    payload = (json.dumps(manifest, separators=(",", ":")) + "\n").encode("ascii")
    replace_file(path, payload, 0o400)


def assert_bundle(specs, expected: list[bytes]) -> None:
    for spec, payload in zip(specs, expected):
        path = Path(spec.destination)
        metadata = path.lstat()
        require(stat.S_ISREG(metadata.st_mode), "installed target is not regular")
        require(metadata.st_uid == 0 and metadata.st_gid == 0, "target is not root:root")
        require(metadata.st_nlink == 1, "target link count changed")
        require(stat.S_IMODE(metadata.st_mode) == spec.mode, "target mode changed")
        require(path.read_bytes() == payload, "installed target payload differs")


def assert_no_artifacts(specs) -> None:
    for spec in specs:
        stage, backup = installer.artifact_paths(spec.destination)
        require(not os.path.lexists(stage), "stale stage survived")
        require(not os.path.lexists(backup), "stale backup survived")


def prepare_interrupted_transaction(
    store,
    approval_path: Path,
    source_root: Path,
    expected_sha: str,
    replace_count: int,
    *,
    leave_last_count_unjournaled: bool = False,
    legacy_schema_v1: bool = False,
):
    approval, manifest = installer.load_approval_manifest(
        expected_sha,
        str(approval_path),
    )
    sources = installer.load_approved_sources(str(source_root), manifest)
    old = installer.load_installed_bundle()
    try:
        journal = (
            legacy_schema_v1_journal(
                installer.BUNDLE_SPECS,
                expected_sha,
                approval.payload,
                old,
                sources,
            )
            if legacy_schema_v1
            else installer.make_journal(expected_sha, approval.payload, old, sources)
        )
        installer.prepare_transaction(store, journal, old, sources)
        journal["state"] = "replacing"
        store.write(journal)
        for index in range(replace_count):
            record = journal["files"][index]
            spec = installer.BUNDLE_SPECS[index]
            installer.validate_artifact(
                record["stage"], spec.mode, record["new_sha256"], "selftest stage"
            )
            installer.replace_same_directory(record["stage"], record["destination"])
            installer.validate_artifact(
                record["destination"],
                spec.mode,
                record["new_sha256"],
                "selftest replacement",
            )
            if not (leave_last_count_unjournaled and index == replace_count - 1):
                journal["replaced_count"] = index + 1
                store.write(journal)
        return journal
    finally:
        approval.close()
        close_all(sources)
        close_all(old)


def exercise_installer(root: Path) -> None:
    expected_sha = "1" * 40
    source_root = root / "source"
    installed_root = root / "installed"
    approval_root = root / "approval"
    source_root.mkdir(mode=0o700)
    installed_root.mkdir(mode=0o700)
    approval_root.mkdir(mode=0o700)

    original_specs = installer.BUNDLE_SPECS
    specs = tuple(
        installer.BundleSpec(
            original.source,
            str(installed_root / f"trusted-{index}"),
            original.mode,
        )
        for index, original in enumerate(original_specs)
    )
    installer.BUNDLE_SPECS = specs
    old_payloads = [f"old-{index}\n".encode("ascii") for index in range(7)]
    new_payloads = [f"new-{index}\n".encode("ascii") for index in range(7)]
    for spec, old_payload, new_payload in zip(specs, old_payloads, new_payloads):
        write_new(Path(spec.destination), old_payload, spec.mode)
        source = source_root / spec.source
        source.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_new(source, new_payload, 0o400)

    approval_path = approval_root / "bundle-approval.json"
    manifest = fixture_manifest(specs, expected_sha, new_payloads)
    write_manifest(approval_path, manifest)
    journal_path = root / "state" / "bundle-install.json"
    store = installer.JournalStore(str(journal_path))

    doctor_observations: list[str] = []
    health_observations: list[str] = []
    reject_new_doctor = False

    def observe_bundle() -> str:
        payloads = [Path(spec.destination).read_bytes() for spec in specs]
        if payloads == old_payloads:
            return "old"
        if payloads == new_payloads:
            return "new"
        raise AssertionError("doctor/health observed a mixed transaction")

    def doctor() -> None:
        observed = observe_bundle()
        doctor_observations.append(observed)
        if reject_new_doctor and observed == "new":
            raise RuntimeError("intentional new-doctor rejection")

    def health() -> None:
        observed = observe_bundle()
        health_observations.append(observed)

    try:
        installer.install_bundle(
            expected_sha,
            str(source_root),
            store,
            doctor,
            health,
            approval_path=str(approval_path),
        )
        assert_bundle(specs, new_payloads)
        require(not store.exists(), "success journal survived")
        assert_no_artifacts(specs)
        require(doctor_observations == ["old", "new"], "doctor order is not old/new")
        require(health_observations == ["old", "new"], "health order is not old/new")

        for spec, payload in zip(specs, old_payloads):
            replace_file(Path(spec.destination), payload, spec.mode)
        doctor_observations.clear()
        health_observations.clear()
        reject_new_doctor = True
        expect_install_error(
            lambda: installer.install_bundle(
                expected_sha,
                str(source_root),
                store,
                doctor,
                health,
                approval_path=str(approval_path),
            ),
            "post-replacement doctor rejection",
        )
        reject_new_doctor = False
        assert_bundle(specs, old_payloads)
        require(not store.exists(), "rollback journal survived")
        assert_no_artifacts(specs)
        require(
            doctor_observations == ["old", "new", "old"],
            "failed-install doctor order is not old/new/old",
        )
        require(
            health_observations == ["old", "old"],
            "failed-install health order is not preflight/rollback-old",
        )

        doctor_observations.clear()
        health_observations.clear()
        legacy_journal = prepare_interrupted_transaction(
            store,
            approval_path,
            source_root,
            expected_sha,
            4,
            leave_last_count_unjournaled=True,
            legacy_schema_v1=True,
        )
        parsed_legacy_journal = store.load()
        require(
            parsed_legacy_journal["schema_version"] == 1
            and len(parsed_legacy_journal["files"]) == 7,
            "new installer did not parse the legacy schema-v1 seven-file journal",
        )
        require(
            specs[-1].source == "scripts/install_production_deploy_bundle.py"
            and parsed_legacy_journal["files"][-1]["source"]
            == "scripts/install_production_deploy_bundle.py",
            "schema-v1 compatibility lost the installer-last recovery invariant",
        )
        installer.rollback_transaction(store, doctor, health)
        assert_bundle(specs, old_payloads)
        require(not store.exists(), "crash-recovery journal survived")
        assert_no_artifacts(specs)
        require(doctor_observations == ["old"], "recovery did not doctor old bundle")
        require(health_observations == ["old"], "recovery did not health-check old bundle")

        for malformed, label in (
            (True, "boolean journal root"),
            ([], "list journal root"),
            (None, "null journal root"),
        ):
            expect_install_error(
                lambda malformed=malformed: installer.validate_journal(malformed),
                label,
            )
        malformed_state = json.loads(json.dumps(legacy_journal))
        malformed_state["state"] = True
        expect_install_error(
            lambda: installer.validate_journal(malformed_state),
            "boolean journal state",
        )
        malformed_mode = json.loads(json.dumps(legacy_journal))
        malformed_mode["files"][0]["mode"] = []
        expect_install_error(
            lambda: installer.validate_journal(malformed_mode),
            "list journal mode",
        )
        malformed_digest = json.loads(json.dumps(legacy_journal))
        malformed_digest["files"][0]["old_sha256"] = None
        expect_install_error(
            lambda: installer.validate_journal(malformed_digest),
            "null journal digest",
        )

        doctor_observations.clear()
        health_observations.clear()
        journal = prepare_interrupted_transaction(
            store,
            approval_path,
            source_root,
            expected_sha,
            1,
            leave_last_count_unjournaled=True,
        )
        first = Path(specs[0].destination)
        replace_file(first, b"unjournaled-third-party\n", specs[0].mode)
        expect_install_error(
            lambda: installer.rollback_transaction(store, doctor, health),
            "third-party rollback target",
        )
        require(store.exists(), "unsafe recovery cleared its journal")
        replace_file(first, new_payloads[0], specs[0].mode)
        installer.rollback_transaction(store, doctor, health)
        assert_bundle(specs, old_payloads)
        require(not store.exists(), "repaired recovery journal survived")
        assert_no_artifacts(specs)
        require(journal["replaced_count"] == 0, "test did not cover pre-count crash")

        approval, approved = installer.load_approval_manifest(
            expected_sha,
            str(approval_path),
        )
        approval.close()
        hardlink = source_root / "hardlink-probe"
        os.link(source_root / specs[0].source, hardlink)
        try:
            expect_install_error(
                lambda: close_all(
                    installer.load_approved_sources(str(source_root), approved)
                ),
                "hard-linked source",
            )
        finally:
            hardlink.unlink()

        wrong_digest_manifest = fixture_manifest(specs, expected_sha, new_payloads)
        wrong_digest_manifest["files"][0]["sha256"] = "0" * 64
        write_manifest(approval_path, wrong_digest_manifest)
        approval, wrong_digest_approval = installer.load_approval_manifest(
            expected_sha,
            str(approval_path),
        )
        try:
            expect_install_error(
                lambda: close_all(
                    installer.load_approved_sources(
                        str(source_root),
                        wrong_digest_approval,
                    )
                ),
                "approval/source digest mismatch",
            )
        finally:
            approval.close()

        reordered_manifest = fixture_manifest(specs, expected_sha, new_payloads)
        reordered_manifest["files"][0], reordered_manifest["files"][1] = (
            reordered_manifest["files"][1],
            reordered_manifest["files"][0],
        )
        write_manifest(approval_path, reordered_manifest)
        expect_install_error(
            lambda: installer.load_approval_manifest(
                expected_sha,
                str(approval_path),
            ),
            "approval file order",
        )
        write_manifest(approval_path, manifest)

        symlink_source = source_root / specs[0].source
        symlink_target = symlink_source.with_name(".selftest-symlink-target")
        symlink_source.rename(symlink_target)
        symlink_source.symlink_to(symlink_target.name)
        approval, approved = installer.load_approval_manifest(
            expected_sha,
            str(approval_path),
        )
        try:
            try:
                installer.load_approved_sources(str(source_root), approved)
            except (installer.InstallError, OSError):
                pass
            else:
                raise AssertionError("symbolic-link source did not fail closed")
        finally:
            approval.close()
            symlink_source.unlink()
            symlink_target.rename(symlink_source)

        invalid_manifest = fixture_manifest(specs, expected_sha, new_payloads)
        invalid_manifest["schema_version"] = True
        write_manifest(approval_path, invalid_manifest)
        expect_install_error(
            lambda: installer.load_approval_manifest(
                expected_sha,
                str(approval_path),
            ),
            "boolean manifest schema",
        )
        write_manifest(approval_path, manifest)

        pinned_spec = root / "pinned-production-container.json"
        write_new(
            pinned_spec,
            (json.dumps(installer.PINNED_SPEC, separators=(",", ":")) + "\n").encode(
                "ascii"
            ),
            0o444,
        )
        require(
            installer.load_production_spec(str(pinned_spec)) == installer.PINNED_SPEC,
            "exact production spec was rejected",
        )
        changed_spec = dict(installer.PINNED_SPEC)
        changed_spec["restart_policy"] = "always"
        replace_file(
            pinned_spec,
            (json.dumps(changed_spec, separators=(",", ":")) + "\n").encode(
                "ascii"
            ),
            0o444,
        )
        expect_install_error(
            lambda: installer.load_production_spec(str(pinned_spec)),
            "non-pinned production spec",
        )
    finally:
        store.close()
        installer.BUNDLE_SPECS = original_specs


def wait_success(pid: int, label: str) -> None:
    observed, status = os.waitpid(pid, 0)
    require(observed == pid, label + " child could not be reaped")
    require(os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, label + " failed")


def exercise_launcher_protocol(root: Path) -> None:
    state = root / "launcher-state"
    state.mkdir(mode=0o700)
    journal = state / "bundle-install.json"
    write_new(journal, b"{}\n", 0o600)
    original_state = launcher.INSTALL_STATE_DIR
    original_journal = launcher.INSTALL_JOURNAL
    launcher.INSTALL_STATE_DIR = str(state)
    launcher.INSTALL_JOURNAL = str(journal)
    try:
        try:
            launcher.reject_active_install_journal(str(journal))
        except SystemExit:
            pass
        else:
            raise AssertionError("launcher accepted an active install journal")
    finally:
        launcher.INSTALL_STATE_DIR = original_state
        launcher.INSTALL_JOURNAL = original_journal

    authority_read, authority_write = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        try:
            os.close(authority_write)
            root_source = fcntl.fcntl(os.open("/dev/null", os.O_RDONLY), fcntl.F_DUPFD, 20)
            legacy_source = fcntl.fcntl(os.open("/dev/null", os.O_RDONLY), fcntl.F_DUPFD, 20)
            authority_source = fcntl.fcntl(authority_read, fcntl.F_DUPFD, 20)
            os.dup2(root_source, launcher.INSTALLER_ROOT_LOCK_FD)
            os.dup2(legacy_source, launcher.INSTALLER_LEGACY_LOCK_FD)
            os.dup2(authority_source, launcher.INSTALLER_AUTHORITY_FD)
            require(
                launcher.consume_installer_doctor_authority(["--doctor"]),
                "launcher rejected the complete installer doctor protocol",
            )
            os._exit(0)
        except BaseException:
            os._exit(1)
    os.close(authority_read)
    installer.write_all(authority_write, launcher.INSTALLER_AUTHORITY_MARKER)
    os.close(authority_write)
    wait_success(pid, "complete installer doctor protocol")

    pid = os.fork()
    if pid == 0:
        try:
            for descriptor in (
                launcher.INSTALLER_ROOT_LOCK_FD,
                launcher.INSTALLER_LEGACY_LOCK_FD,
                launcher.INSTALLER_AUTHORITY_FD,
            ):
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            source = fcntl.fcntl(os.open("/dev/null", os.O_RDONLY), fcntl.F_DUPFD, 20)
            os.dup2(source, launcher.INSTALLER_ROOT_LOCK_FD)
            try:
                launcher.consume_installer_doctor_authority(["--doctor"])
            except SystemExit:
                os._exit(0)
            os._exit(1)
        except BaseException:
            os._exit(1)
    wait_success(pid, "partial installer doctor protocol rejection")


def main() -> None:
    require(sys.platform.startswith("linux"), "selftest requires Linux")
    require(os.geteuid() == 0 and os.getegid() == 0, "selftest requires root")
    os.umask(0o077)
    root = Path(tempfile.mkdtemp(prefix="xjie-bundle-installer-", dir="/root"))
    try:
        root.chmod(0o700)
        exercise_installer(root)
        exercise_launcher_protocol(root)
    finally:
        shutil.rmtree(root)
    print("production bundle installer linux selftest: PASS")


if __name__ == "__main__":
    main()
