#!/usr/bin/env python3
"""Fail closed unless a Release app bundle is structurally safe and marker-free."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import stat
import struct
import sys
import unicodedata
import zipfile
from pathlib import Path
from typing import Any


FORBIDDEN_PREFIXES = (
    b"XJIE_UI_TEST_",
    b"XJIE_DEBUG_",
    b"XJIE_DISABLE_",
    b"UIAutomation",
)

FORBIDDEN_EXACT_MARKERS = (
    b"XAGE_INITIAL_SECTION",
    b"ui-validation-token",
    b"UI-VALIDATION",
    b"ui-automation.invalid",
    b"xjie.uiTest.",
    b"xjie.debug.uiValidationLogin",
    "UI 验证入口".encode(),
    "打印已注册通知（控制台）".encode(),
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN ENCRYPTED PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"-----BEGIN DSA PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
)

FORBIDDEN_MARKERS = FORBIDDEN_PREFIXES + FORBIDDEN_EXACT_MARKERS
EXPECTED_BUNDLE_IDENTIFIER = "com.xjie.app"
EXPECTED_API_BASE_URL = "https://www.jianjieaitech.com"
SENSITIVE_FILE_SUFFIXES = (
    ".pem",
    ".key",
    ".p8",
    ".p12",
    ".pfx",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".db",
    ".db-shm",
    ".db-wal",
    ".db3",
    ".der",
    ".pkcs8",
    ".jwk",
)
PRIVATE_KEY_MARKERS = tuple(
    marker for marker in FORBIDDEN_EXACT_MARKERS if b"PRIVATE KEY" in marker
)
IPA_SCAN_CHUNK_SIZE = 1024 * 1024
IPA_MAX_MEMBER_SIZE = 4 * 1024 * 1024 * 1024
IPA_MAX_TOTAL_SIZE = 8 * 1024 * 1024 * 1024
IPA_MAX_COMPRESSION_RATIO = 1000
IPA_COMPRESSION_RATIO_MIN_SIZE = 1024 * 1024
PRIVATE_KEY_BINARY_SCAN_MAX_SIZE = 1024 * 1024
BINARY_PRIVATE_KEY_MARKER = b"BINARY PRIVATE KEY"
SQLITE_HEADER = b"SQLite format 3\x00"
OPENSSH_PRIVATE_KEY_MAGIC = b"openssh-key-v1\x00"
EXPECTED_PROVISIONING_SIGNER_ID = "Apple iPhone OS Provisioning Profile Signing"
PRIVATE_KEY_ALGORITHM_OIDS = {
    bytes.fromhex("2a864886f70d010101"),  # rsaEncryption
    bytes.fromhex("2a8648ce3d0201"),  # id-ecPublicKey
    bytes.fromhex("2a8648ce380401"),  # id-dsa
    bytes.fromhex("2b656e"),  # X25519
    bytes.fromhex("2b6570"),  # Ed25519
}
PRIVATE_KEY_ENCRYPTION_OIDS = {
    bytes.fromhex("2a864886f70d01050d"),  # PBES2
    bytes.fromhex("2a864886f70d010503"),
    bytes.fromhex("2a864886f70d010506"),
    bytes.fromhex("2a864886f70d01050a"),
    bytes.fromhex("2a864886f70d01050b"),
}
PKCS7_DATA_OID = bytes.fromhex("2a864886f70d010701")

# Mach-O values are defined by <mach-o/loader.h> and <mach/machine.h>.  Keep
# this parser self-contained so release validation does not trust a `file`,
# `lipo`, or `otool` executable resolved through the caller's PATH.
MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
MH_EXECUTE = 0x2
LC_VERSION_MIN_MACOSX = 0x24
LC_VERSION_MIN_IPHONEOS = 0x25
LC_VERSION_MIN_TVOS = 0x2F
LC_VERSION_MIN_WATCHOS = 0x30
LC_BUILD_VERSION = 0x32
PLATFORM_IOS = 2
PLATFORM_IOSSIMULATOR = 7

MACH_HEADER_64 = struct.Struct("<IiiIIIII")
LOAD_COMMAND = struct.Struct("<II")
BUILD_VERSION_COMMAND = struct.Struct("<IIIIII")
VERSION_MIN_COMMAND = struct.Struct("<IIII")
LEGACY_VERSION_COMMANDS = {
    LC_VERSION_MIN_MACOSX,
    LC_VERSION_MIN_IPHONEOS,
    LC_VERSION_MIN_TVOS,
    LC_VERSION_MIN_WATCHOS,
}


def _require_real_directory(path: Path, description: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{description} does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{description} must not be a symbolic link: {path}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{description} must be a real directory: {path}")


def _require_regular_file(path: Path, description: str, *, nonempty: bool) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{description} does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError(f"{description} must not be a symbolic link: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{description} must be a regular file: {path}")
    if nonempty and metadata.st_size == 0:
        raise ValueError(f"{description} must not be empty: {path}")


def _load_info_plist(root: Path) -> dict[str, Any]:
    info_plist = root / "Info.plist"
    _require_regular_file(info_plist, "Info.plist", nonempty=True)
    try:
        with info_plist.open("rb") as handle:
            payload = plistlib.load(handle)
    except (EOFError, plistlib.InvalidFileException, TypeError, ValueError) as exc:
        raise ValueError(f"Info.plist is not a valid property list: {info_plist}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Info.plist top level must be a dictionary")
    return payload


def _validated_executable_name(info_plist: dict[str, Any]) -> str:
    executable_name = info_plist.get("CFBundleExecutable")
    if not isinstance(executable_name, str):
        raise ValueError("CFBundleExecutable must be a string")
    if not executable_name or executable_name.strip() != executable_name:
        raise ValueError("CFBundleExecutable must be a non-empty filename")
    if executable_name in {".", ".."}:
        raise ValueError("CFBundleExecutable must name one file")
    if "/" in executable_name or "\\" in executable_name or "\x00" in executable_name:
        raise ValueError("CFBundleExecutable must not contain a path or NUL byte")
    if any(ord(character) < 32 or ord(character) == 127 for character in executable_name):
        raise ValueError("CFBundleExecutable must not contain control characters")
    return executable_name


def _validate_production_info_plist(info_plist: dict[str, Any]) -> None:
    if info_plist.get("CFBundleIdentifier") != EXPECTED_BUNDLE_IDENTIFIER:
        raise ValueError(f"CFBundleIdentifier must be {EXPECTED_BUNDLE_IDENTIFIER}")
    version = info_plist.get("CFBundleShortVersionString")
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version) is None:
        raise ValueError("CFBundleShortVersionString must contain numeric version segments")
    build = info_plist.get("CFBundleVersion")
    if not isinstance(build, str) or re.fullmatch(r"[1-9][0-9]*", build) is None:
        raise ValueError("CFBundleVersion must be a positive integer")
    if info_plist.get("API_BASE_URL") != EXPECTED_API_BASE_URL:
        raise ValueError(f"API_BASE_URL must be {EXPECTED_API_BASE_URL}")
    for key in ("NSHealthShareUsageDescription", "NSHealthUpdateUsageDescription"):
        value = info_plist.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a non-empty string")


def _validate_ios_device_macho(path: Path) -> None:
    """Require one thin, executable arm64 Mach-O targeting iOS devices.

    Universal/FAT files deliberately fail closed.  Xcode's iOS application
    executable is a thin arm64 Mach-O, so accepting extra slices would widen
    the release boundary without providing a product requirement.
    """

    metadata = path.lstat()
    if metadata.st_mode & 0o111 == 0:
        raise ValueError("CFBundleExecutable must have an executable permission bit")

    with path.open("rb") as handle:
        header_payload = handle.read(MACH_HEADER_64.size)
        if len(header_payload) != MACH_HEADER_64.size:
            raise ValueError("CFBundleExecutable has a truncated Mach-O header")

        (
            magic,
            cpu_type,
            _cpu_subtype,
            file_type,
            command_count,
            commands_size,
            _flags,
            _reserved,
        ) = MACH_HEADER_64.unpack(header_payload)

        if magic != MH_MAGIC_64:
            raise ValueError(
                "CFBundleExecutable must be a thin little-endian 64-bit Mach-O"
            )
        if cpu_type != CPU_TYPE_ARM64:
            raise ValueError("CFBundleExecutable Mach-O CPU type must be arm64")
        if file_type != MH_EXECUTE:
            raise ValueError("CFBundleExecutable Mach-O file type must be MH_EXECUTE")
        if command_count == 0:
            raise ValueError("CFBundleExecutable Mach-O must contain load commands")
        if commands_size < command_count * LOAD_COMMAND.size:
            raise ValueError("CFBundleExecutable Mach-O load-command table is invalid")
        if commands_size > metadata.st_size - MACH_HEADER_64.size:
            raise ValueError("CFBundleExecutable has truncated Mach-O load commands")

        commands = handle.read(commands_size)
        if len(commands) != commands_size:
            raise ValueError("CFBundleExecutable has truncated Mach-O load commands")

    offset = 0
    build_version_count = 0
    legacy_iphoneos_count = 0
    for command_index in range(command_count):
        if offset + LOAD_COMMAND.size > len(commands):
            raise ValueError(
                f"CFBundleExecutable Mach-O load command {command_index} is truncated"
            )
        command, command_size = LOAD_COMMAND.unpack_from(commands, offset)
        if command_size < LOAD_COMMAND.size or command_size % 8 != 0:
            raise ValueError(
                f"CFBundleExecutable Mach-O load command {command_index} has invalid size"
            )
        command_end = offset + command_size
        if command_end > len(commands):
            raise ValueError(
                f"CFBundleExecutable Mach-O load command {command_index} exceeds its table"
            )

        if command == LC_BUILD_VERSION:
            if command_size < BUILD_VERSION_COMMAND.size:
                raise ValueError("CFBundleExecutable has a truncated LC_BUILD_VERSION")
            _, _, platform, _minimum_os, _sdk, tool_count = (
                BUILD_VERSION_COMMAND.unpack_from(commands, offset)
            )
            expected_size = BUILD_VERSION_COMMAND.size + tool_count * 8
            if command_size != expected_size:
                raise ValueError("CFBundleExecutable has an invalid LC_BUILD_VERSION size")
            if platform == PLATFORM_IOSSIMULATOR:
                raise ValueError(
                    "CFBundleExecutable targets iOS Simulator instead of an iOS device"
                )
            if platform != PLATFORM_IOS:
                raise ValueError(
                    "CFBundleExecutable LC_BUILD_VERSION platform must be iOS device (2)"
                )
            build_version_count += 1
        elif command in LEGACY_VERSION_COMMANDS:
            if command_size != VERSION_MIN_COMMAND.size:
                raise ValueError("CFBundleExecutable has an invalid legacy platform command")
            if command != LC_VERSION_MIN_IPHONEOS:
                raise ValueError(
                    "CFBundleExecutable legacy platform command must be "
                    "LC_VERSION_MIN_IPHONEOS"
                )
            legacy_iphoneos_count += 1

        offset = command_end

    if offset != len(commands):
        raise ValueError("CFBundleExecutable Mach-O load-command table has trailing bytes")
    if build_version_count and legacy_iphoneos_count:
        raise ValueError("CFBundleExecutable has ambiguous iOS platform declarations")
    if build_version_count > 1 or legacy_iphoneos_count > 1:
        raise ValueError("CFBundleExecutable has duplicate iOS platform declarations")
    if build_version_count != 1 and legacy_iphoneos_count != 1:
        raise ValueError(
            "CFBundleExecutable must declare iOS using LC_BUILD_VERSION or "
            "LC_VERSION_MIN_IPHONEOS"
        )


def _regular_bundle_files(root: Path) -> list[Path]:
    """Return every regular file, rejecting links and special entries."""

    files: list[Path] = []
    pending_directories = [root]
    while pending_directories:
        directory = pending_directories.pop()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)

        child_directories: list[Path] = []
        for entry in entries:
            path = Path(entry.path)
            metadata = entry.stat(follow_symlinks=False)
            relative_path = path.relative_to(root)
            if any(_is_sensitive_file_name(component) for component in relative_path.parts):
                raise ValueError(
                    f"release app bundle contains a sensitive/runtime path: {relative_path}"
                )
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(
                    f"release app bundle must not contain symbolic links: {relative_path}"
                )
            if stat.S_ISDIR(metadata.st_mode):
                child_directories.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                files.append(path)
            else:
                raise ValueError(
                    f"release app bundle contains a non-regular entry: {relative_path}"
                )

        pending_directories.extend(reversed(child_directories))

    return sorted(files, key=lambda path: str(path.relative_to(root)))


def _is_sensitive_file_name(name: str) -> bool:
    lowered_name = unicodedata.normalize("NFC", name).casefold().rstrip(" .")
    if lowered_name.startswith(".env"):
        return True
    if lowered_name in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"}:
        return True
    return re.search(
        r"\.(?:pem|key|p8|p12|pfx|sqlite|sqlite3|db|db3|der|pkcs8|jwk)(?:$|[.-])",
        lowered_name,
    ) is not None


def _der_tlv(payload: bytes, offset: int) -> tuple[int, bytes, int] | None:
    if offset + 2 > len(payload):
        return None
    tag = payload[offset]
    first_length = payload[offset + 1]
    cursor = offset + 2
    if first_length & 0x80:
        length_bytes = first_length & 0x7F
        if length_bytes == 0 or length_bytes > 4 or cursor + length_bytes > len(payload):
            return None
        encoded = payload[cursor:cursor + length_bytes]
        if encoded[0] == 0:
            return None
        length = int.from_bytes(encoded, "big")
        if length < 128:
            return None
        cursor += length_bytes
    else:
        length = first_length
    end = cursor + length
    if end > len(payload):
        return None
    return tag, payload[cursor:end], end


def _der_children(payload: bytes) -> list[tuple[int, bytes]] | None:
    children: list[tuple[int, bytes]] = []
    offset = 0
    while offset < len(payload):
        item = _der_tlv(payload, offset)
        if item is None:
            return None
        tag, value, offset = item
        children.append((tag, value))
    return children


def _der_sequence_children(payload: bytes) -> list[tuple[int, bytes]] | None:
    outer = _der_tlv(payload, 0)
    # Only the DER object's declared bytes are interpreted.  Trailing bytes
    # must not let an otherwise valid private key evade detection by padding
    # the member beyond the bounded prefix scan.
    if outer is None or outer[0] != 0x30:
        return None
    return _der_children(outer[1])


def _der_algorithm_oid(sequence_value: bytes) -> bytes | None:
    children = _der_children(sequence_value)
    if not children or children[0][0] != 0x06:
        return None
    return children[0][1]


def _looks_like_binary_private_key(payload: bytes) -> bool:
    if payload.startswith(OPENSSH_PRIVATE_KEY_MAGIC):
        return True
    if payload.startswith(SQLITE_HEADER):
        return True
    jwk = None
    stripped = payload.lstrip()
    if stripped.startswith(b"{"):
        depth = 0
        in_string = False
        escaped = False
        for index, byte in enumerate(stripped):
            if in_string:
                if escaped:
                    escaped = False
                elif byte == 0x5C:
                    escaped = True
                elif byte == 0x22:
                    in_string = False
                continue
            if byte == 0x22:
                in_string = True
            elif byte == 0x7B:
                depth += 1
            elif byte == 0x7D:
                depth -= 1
                if depth == 0:
                    try:
                        jwk = json.loads(stripped[:index + 1].decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
                    break
    if isinstance(jwk, dict) and jwk.get("kty") in {"RSA", "EC", "OKP"} \
            and isinstance(jwk.get("d"), str) and bool(jwk["d"]):
        return True

    children = _der_sequence_children(payload)
    if not children:
        return False
    tags = [tag for tag, _value in children]
    version = children[0][1] if children[0][0] == 0x02 else b""

    # Traditional PKCS#1 RSA and OpenSSL DSA private-key structures.
    if len(children) >= 9 and all(tag == 0x02 for tag in tags[:9]) \
            and version in {b"\x00", b"\x01"}:
        sizes = [len(value) for _tag, value in children[:9]]
        if sizes[1] >= 64 and sizes[3] >= 32 and sizes[4] >= 16 and sizes[5] >= 16:
            return True
    if len(children) == 6 and all(tag == 0x02 for tag in tags) and version == b"\x00":
        sizes = [len(value) for _tag, value in children]
        if sizes[1] >= 64 and sizes[2] >= 16 and sizes[3] >= 32 and sizes[5] >= 16:
            return True

    # SEC1 EC private key.
    if len(children) >= 2 and tags[0:2] == [0x02, 0x04] \
            and version == b"\x01" and 16 <= len(children[1][1]) <= 80 \
            and all(tag in {0xA0, 0xA1} for tag in tags[2:]):
        return True

    # Unencrypted/encrypted PKCS#8 and PKCS#12/PFX containers.
    if len(children) >= 3 and tags[0:3] == [0x02, 0x30, 0x04] \
            and version in {b"\x00", b"\x01"}:
        if _der_algorithm_oid(children[1][1]) in PRIVATE_KEY_ALGORITHM_OIDS \
                and len(children[2][1]) >= 16:
            return True
    if len(children) >= 2 and tags[0:2] == [0x30, 0x04]:
        if _der_algorithm_oid(children[0][1]) in PRIVATE_KEY_ENCRYPTION_OIDS \
                and len(children[1][1]) >= 16:
            return True
    if len(children) >= 2 and tags[0:2] == [0x02, 0x30] and version == b"\x03":
        if _der_algorithm_oid(children[1][1]) == PKCS7_DATA_OID:
            return True
    return False


def _der_declared_object_end(payload: bytes) -> int | None:
    if len(payload) < 2 or payload[0] != 0x30:
        return None
    first_length = payload[1]
    cursor = 2
    if first_length & 0x80:
        length_bytes = first_length & 0x7F
        if length_bytes == 0 or length_bytes > 4 or cursor + length_bytes > len(payload):
            return None
        encoded = payload[cursor:cursor + length_bytes]
        if encoded[0] == 0:
            return None
        length = int.from_bytes(encoded, "big")
        if length < 128:
            return None
        cursor += length_bytes
    else:
        length = first_length
    return cursor + length


def _binary_secret_prefix_is_forbidden(payload: bytes, *, truncated: bool) -> bool:
    """Detect a complete key or fail closed on a truncated self-described candidate."""

    if _looks_like_binary_private_key(payload):
        return True
    if not truncated:
        return False
    stripped = payload.lstrip(b" \t\r\n")
    if not stripped:
        # A bounded scanner cannot prove that a whitespace-only prefix is not
        # followed by a self-described JSON secret just beyond the limit.
        return True
    if stripped.startswith(b"{"):
        # A top-level JSON object that exceeds the bounded prefix may hide the
        # private `d` member after arbitrary in-object padding.
        return True
    declared_der_end = _der_declared_object_end(payload)
    return declared_der_end is not None and declared_der_end > len(payload)


def _validated_ipa_member_identity(entry: zipfile.ZipInfo) -> tuple[str, bool]:
    original_name = entry.orig_filename
    name = entry.filename
    if original_name != name or not name or "\x00" in original_name \
            or "\\" in name or name.startswith("/"):
        raise ValueError(f"unsafe IPA member path: {name!r}")
    is_directory = entry.is_dir()
    path_without_trailing_slash = name[:-1] if is_directory else name
    if not path_without_trailing_slash:
        raise ValueError(f"unsafe IPA member path: {name!r}")
    components = path_without_trailing_slash.split("/")
    if any(
        not component
        or component in {".", ".."}
        or any(ord(character) < 32 or ord(character) == 127 for character in component)
        for component in components
    ):
        raise ValueError(f"unsafe IPA member path: {name!r}")
    for component in components:
        normalized_component = unicodedata.normalize("NFC", component).casefold().rstrip(" .")
        if not normalized_component:
            raise ValueError(f"unsafe IPA member path: {name!r}")
        if _is_sensitive_file_name(component):
            raise ValueError(f"IPA contains a sensitive/runtime path: {name!r}")
    if re.fullmatch(r"[A-Za-z]:.*", components[0]) is not None:
        raise ValueError(f"unsafe IPA member path: {name!r}")
    normalized = "/".join(
        unicodedata.normalize("NFC", component).casefold()
        for component in components
    )
    return normalized, is_directory


def _validate_ipa_member_mode(entry: zipfile.ZipInfo, is_directory: bool) -> None:
    mode = (entry.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    expected_type = stat.S_IFDIR if is_directory else stat.S_IFREG
    if file_type not in {0, expected_type}:
        raise ValueError(f"IPA member must be a regular file or directory: {entry.filename!r}")


def _validate_ipa_member_extra(entry: zipfile.ZipInfo) -> None:
    """Allow only Xcode/ditto's fixed old-Unix atime/mtime metadata field."""

    if not entry.extra:
        return
    if len(entry.extra) != 12:
        raise ValueError(f"IPA member extra metadata is forbidden: {entry.filename!r}")
    field_id, field_length, access_time, modification_time = struct.unpack(
        "<HHII", entry.extra
    )
    if field_id != 0x5855 or field_length != 8:
        raise ValueError(f"IPA member extra metadata is forbidden: {entry.filename!r}")
    earliest = 946684800  # 2000-01-01 UTC
    latest = 4102444800  # 2100-01-01 UTC
    if not all(earliest <= value <= latest for value in (access_time, modification_time)):
        raise ValueError(f"IPA member extra metadata timestamps are invalid: {entry.filename!r}")


def _validate_ipa_local_extra(entry: zipfile.ZipInfo, local_extra: bytes) -> None:
    """Allow the exact Xcode/ditto local form corresponding to central metadata."""

    if not entry.extra and not local_extra:
        return
    if len(entry.extra) != 12 or len(local_extra) != 16:
        raise ValueError("IPA ZIP local and central extra metadata differ")
    central_id, central_length, central_access, central_modification = struct.unpack(
        "<HHII", entry.extra
    )
    (
        local_id,
        local_length,
        local_access,
        local_modification,
        owner_id,
        group_id,
    ) = struct.unpack("<HHIIHH", local_extra)
    if (central_id, central_length) != (0x5855, 8) \
            or (local_id, local_length) != (0x5855, 12) \
            or (local_access, local_modification) != (
                central_access,
                central_modification,
            ) \
            or (owner_id, group_id) != (501, 20):
        raise ValueError("IPA ZIP local and central extra metadata differ")


def _archive_member_marker(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    markers: tuple[bytes, ...],
    *,
    chunk_size: int = IPA_SCAN_CHUNK_SIZE,
) -> bytes | None:
    if chunk_size <= 0:
        raise ValueError("IPA marker scan chunk size must be positive")
    if not markers or any(not marker for marker in markers):
        raise ValueError("IPA forbidden markers must be non-empty")
    overlap_length = max(len(marker) for marker in markers) - 1
    overlap = b""
    bytes_read = 0
    with archive.open(entry, "r") as handle:
        while chunk := handle.read(chunk_size):
            bytes_read += len(chunk)
            if bytes_read > entry.file_size:
                raise ValueError(f"IPA member expanded beyond its declared size: {entry.filename!r}")
            payload = overlap + chunk
            for marker in markers:
                if marker in payload:
                    return marker
            overlap = payload[-overlap_length:] if overlap_length else b""
    if bytes_read != entry.file_size:
        raise ValueError(f"IPA member size does not match its archive metadata: {entry.filename!r}")
    return None


def _archive_member_has_binary_secret(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
) -> bool:
    with archive.open(entry, "r") as handle:
        payload = handle.read(PRIVATE_KEY_BINARY_SCAN_MAX_SIZE + 1)
    truncated = entry.file_size > len(payload)
    if not truncated and len(payload) != entry.file_size:
        raise ValueError(f"IPA member size does not match its archive metadata: {entry.filename!r}")
    return _binary_secret_prefix_is_forbidden(payload, truncated=truncated)


def _regular_file_marker(
    path: Path,
    markers: tuple[bytes, ...],
    *,
    chunk_size: int = IPA_SCAN_CHUNK_SIZE,
) -> bytes | None:
    """Scan raw container bytes as well as separately decompressed members."""

    if chunk_size <= 0 or not markers or any(not marker for marker in markers):
        raise ValueError("IPA raw marker scan configuration is invalid")
    overlap_length = max(len(marker) for marker in markers) - 1
    overlap = b""
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            payload = overlap + chunk
            for marker in markers:
                if marker in payload:
                    return marker
            overlap = payload[-overlap_length:] if overlap_length else b""
    return None


def _validate_zip_envelope(ipa: Path) -> tuple[int, int, int]:
    """Reject executable prefixes, comments and bytes after the final EOCD."""

    size = ipa.stat().st_size
    tail_size = min(size, 22 + 65535)
    with ipa.open("rb") as handle:
        prefix = handle.read(4)
        handle.seek(size - tail_size)
        tail = handle.read(tail_size)
    if prefix != b"PK\x03\x04":
        raise ValueError("exported IPA is not a valid ZIP archive: missing local file header")
    signature = b"PK\x05\x06"
    candidates: list[tuple[int, int]] = []
    offset = 0
    while True:
        position = tail.find(signature, offset)
        if position < 0:
            break
        if position + 22 <= len(tail):
            comment_length = struct.unpack_from("<H", tail, position + 20)[0]
            if position + 22 + comment_length == len(tail):
                candidates.append((position, comment_length))
        offset = position + 1
    if len(candidates) != 1:
        raise ValueError("IPA ZIP must have one final end-of-central-directory record")
    position, comment_length = candidates[0]
    if comment_length != 0:
        raise ValueError("IPA ZIP archive comments are forbidden")
    eocd_offset = size - tail_size + position
    (
        _signature,
        disk_number,
        central_disk_number,
        entries_on_disk,
        total_entries,
        central_size,
        central_offset,
        _comment_length,
    ) = struct.unpack_from("<4s4H2LH", tail, position)
    if disk_number != 0 or central_disk_number != 0 or entries_on_disk != total_entries:
        raise ValueError("IPA ZIP multi-disk archives are forbidden")
    if total_entries in {0, 0xFFFF} or central_size == 0xFFFFFFFF \
            or central_offset == 0xFFFFFFFF:
        raise ValueError("IPA ZIP must be a non-empty non-Zip64 archive")
    if central_offset + central_size != eocd_offset:
        raise ValueError("IPA ZIP central directory is not contiguous with its final record")
    return central_offset, central_size, total_entries


def _validate_zip_local_records(
    ipa: Path,
    entries: list[zipfile.ZipInfo],
    central_offset: int,
    expected_entry_count: int,
) -> None:
    """Bind every local header/data span contiguously to its central entry."""

    if len(entries) != expected_entry_count:
        raise ValueError("IPA ZIP central-directory entry count changed")
    expected_offset = 0
    header_struct = struct.Struct("<4s5H3L2H")
    with ipa.open("rb") as handle:
        for entry in sorted(entries, key=lambda item: item.header_offset):
            if entry.header_offset != expected_offset:
                raise ValueError("IPA ZIP contains an unreferenced local-record gap")
            handle.seek(entry.header_offset)
            header = handle.read(header_struct.size)
            if len(header) != header_struct.size:
                raise ValueError("IPA ZIP contains a truncated local file header")
            (
                signature,
                _extract_version,
                flag_bits,
                compression_method,
                _modification_time,
                _modification_date,
                crc32,
                compressed_size,
                uncompressed_size,
                filename_length,
                extra_length,
            ) = header_struct.unpack(header)
            if signature != b"PK\x03\x04":
                raise ValueError("IPA ZIP local file signature changed")
            if flag_bits != entry.flag_bits or compression_method != entry.compress_type:
                raise ValueError("IPA ZIP local and central compression metadata differ")
            uses_descriptor = bool(flag_bits & 0x08)
            if uses_descriptor:
                if (crc32, compressed_size, uncompressed_size) != (0, 0, 0):
                    raise ValueError("IPA ZIP streamed local sizes must remain zero")
            elif (crc32, compressed_size, uncompressed_size) != (
                    entry.CRC, entry.compress_size, entry.file_size):
                raise ValueError("IPA ZIP local and central size/CRC metadata differ")
            local_name = handle.read(filename_length)
            local_extra = handle.read(extra_length)
            if len(local_name) != filename_length or len(local_extra) != extra_length:
                raise ValueError("IPA ZIP local file metadata is truncated")
            encoding = "utf-8" if flag_bits & 0x800 else "cp437"
            try:
                expected_name = entry.orig_filename.encode(encoding)
            except UnicodeEncodeError as exc:
                raise ValueError("IPA ZIP member name encoding is not canonical") from exc
            if local_name != expected_name:
                raise ValueError("IPA ZIP local and central member names differ")
            _validate_ipa_local_extra(entry, local_extra)
            expected_offset = (
                entry.header_offset
                + header_struct.size
                + filename_length
                + extra_length
                + entry.compress_size
            )
            if uses_descriptor:
                handle.seek(expected_offset)
                descriptor = handle.read(16)
                if len(descriptor) != 16 or struct.unpack("<4sLLL", descriptor) != (
                    b"PK\x07\x08",
                    entry.CRC,
                    entry.compress_size,
                    entry.file_size,
                ):
                    raise ValueError("IPA ZIP data descriptor does not match central metadata")
                expected_offset += 16
            if expected_offset > central_offset:
                raise ValueError("IPA ZIP local member overlaps its central directory")
    if expected_offset != central_offset:
        raise ValueError("IPA ZIP contains unreferenced bytes before its central directory")


def validate_ipa_container(ipa: Path) -> None:
    """Validate every IPA member before extraction or upload."""

    _require_regular_file(ipa, "exported IPA", nonempty=True)
    raw_marker = _regular_file_marker(ipa, PRIVATE_KEY_MARKERS)
    if raw_marker is not None:
        raise ValueError(
            "IPA container metadata contains private-key content: "
            + raw_marker.decode("ascii")
        )
    central_offset, _central_size, expected_entry_count = _validate_zip_envelope(ipa)
    raw_names: set[str] = set()
    normalized_names: dict[str, str] = {}
    total_size = 0
    try:
        with zipfile.ZipFile(ipa) as archive:
            if archive.comment:
                raise ValueError("IPA ZIP archive comments are forbidden")
            entries = archive.infolist()
            if not entries:
                raise ValueError("exported IPA is empty")
            _validate_zip_local_records(
                ipa,
                entries,
                central_offset,
                expected_entry_count,
            )
            for entry in entries:
                if entry.comment:
                    raise ValueError(f"IPA member comments are forbidden: {entry.filename!r}")
                _validate_ipa_member_extra(entry)
                if entry.filename in raw_names:
                    raise ValueError(f"duplicate IPA member path: {entry.filename!r}")
                raw_names.add(entry.filename)

                normalized_name, is_directory = _validated_ipa_member_identity(entry)
                previous_name = normalized_names.get(normalized_name)
                if previous_name is not None:
                    raise ValueError(
                        "IPA member paths collide after Unicode/case normalization: "
                        f"{previous_name!r}, {entry.filename!r}"
                    )
                normalized_names[normalized_name] = entry.filename
                _validate_ipa_member_mode(entry, is_directory)

                if is_directory:
                    if entry.file_size != 0:
                        raise ValueError(
                            f"IPA directory member must not contain data: {entry.filename!r}"
                        )
                    continue
                if entry.flag_bits & 0x1:
                    raise ValueError(f"encrypted IPA member is forbidden: {entry.filename!r}")
                if entry.file_size > IPA_MAX_MEMBER_SIZE:
                    raise ValueError(f"IPA member is too large: {entry.filename!r}")
                total_size += entry.file_size
                if total_size > IPA_MAX_TOTAL_SIZE:
                    raise ValueError("IPA total uncompressed size is too large")
                if entry.file_size >= IPA_COMPRESSION_RATIO_MIN_SIZE:
                    if entry.compress_size <= 0 \
                            or entry.file_size / entry.compress_size > IPA_MAX_COMPRESSION_RATIO:
                        raise ValueError(
                            f"IPA member has an unsafe compression ratio: {entry.filename!r}"
                        )
                marker = _archive_member_marker(archive, entry, PRIVATE_KEY_MARKERS)
                if marker is not None:
                    raise ValueError(
                        "IPA contains private-key content: "
                        f"{entry.filename!r}:{marker.decode('ascii')}"
                    )
                if _archive_member_has_binary_secret(archive, entry):
                    raise ValueError(
                        f"IPA contains a binary private-key/database payload: {entry.filename!r}"
                    )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"exported IPA is not a valid ZIP archive: {ipa}") from exc


def validate_provisioning_cms_status(status: str) -> None:
    """Require macOS Security.framework to trust one pinned Apple signer."""

    signer_counts = re.findall(r"\bnsigners=(\d+)\s*;", status)
    signers = re.findall(
        r"\bsigner(\d+)\.id=\"([^\"]*)\"\s*;\s*"
        r"signer\1\.status=([A-Za-z0-9_]+)\s*;",
        status,
    )
    if signer_counts != ["1"] or signers != [
        ("0", EXPECTED_PROVISIONING_SIGNER_ID, "GoodSignature")
    ]:
        raise ValueError(
            "embedded provisioning profile is not trusted as a single Apple-signed CMS"
        )


def validate_release_build_settings(payload: Any) -> dict[str, str]:
    """Require the effective app Release settings used by archive, not PBX text alone."""

    if not isinstance(payload, list):
        raise ValueError("Xcode build settings JSON must be a list")
    matches = [
        item for item in payload
        if isinstance(item, dict)
        and item.get("target") == "Xjie"
        and isinstance(item.get("buildSettings"), dict)
        and item["buildSettings"].get("PRODUCT_BUNDLE_IDENTIFIER")
        == EXPECTED_BUNDLE_IDENTIFIER
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one Xjie application build-settings target, found {len(matches)}")
    settings = matches[0]["buildSettings"]
    expected = {
        "CONFIGURATION": "Release",
        "SDKROOT": (
            "/Applications/Xcode.app/Contents/Developer/Platforms/"
            "iPhoneOS.platform/Developer/SDKs/iPhoneOS26.2.sdk"
        ),
        "PLATFORM_NAME": "iphoneos",
        "ARCHS": "arm64",
        "VALID_ARCHS": "arm64 arm64e armv7 armv7s",
        "ONLY_ACTIVE_ARCH": "NO",
        "ENABLE_TESTABILITY": "NO",
        "SWIFT_COMPILATION_MODE": "wholemodule",
        "DEBUG_INFORMATION_FORMAT": "dwarf-with-dsym",
        "VALIDATE_PRODUCT": "YES",
        "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator",
        "PRODUCT_TYPE": "com.apple.product-type.application",
        "INFOPLIST_FILE": "Xjie/Info.plist",
        "GENERATE_INFOPLIST_FILE": "YES",
        "CODE_SIGN_ENTITLEMENTS": "Xjie/Xjie.entitlements",
        "SWIFT_VERSION": "5.0",
        "IPHONEOS_DEPLOYMENT_TARGET": "17.0",
        "TARGETED_DEVICE_FAMILY": "1,2",
        "SKIP_INSTALL": "NO",
        "PRODUCT_BUNDLE_IDENTIFIER": EXPECTED_BUNDLE_IDENTIFIER,
    }
    for key, expected_value in expected.items():
        if settings.get(key) != expected_value:
            raise ValueError(
                f"effective Release build setting {key} changed; "
                f"expected {expected_value!r}, got {settings.get(key)!r}"
            )
    forbidden = (
        "SWIFT_ACTIVE_COMPILATION_CONDITIONS",
        "OTHER_SWIFT_FLAGS",
        "GCC_PREPROCESSOR_DEFINITIONS",
        "EXCLUDED_SOURCE_FILE_NAMES",
        "INCLUDED_SOURCE_FILE_NAMES",
        "SWIFT_EXEC",
        "CC",
        "LD",
        "OTHER_LDFLAGS",
        "OTHER_CFLAGS",
        "OTHER_CPLUSPLUSFLAGS",
        "SWIFT_OBJC_BRIDGING_HEADER",
        "SWIFT_INCLUDE_PATHS",
    )
    present = [key for key in forbidden if settings.get(key) not in {None, ""}]
    if present:
        raise ValueError(
            "effective Release build settings contain forbidden overrides: "
            + ", ".join(present)
        )
    target_build_directory = settings.get("TARGET_BUILD_DIR")
    if not isinstance(target_build_directory, str) or not target_build_directory:
        raise ValueError("effective Release build setting TARGET_BUILD_DIR is invalid")
    expected_search_paths = {
        "LIBRARY_SEARCH_PATHS": [target_build_directory],
        "FRAMEWORK_SEARCH_PATHS": [target_build_directory],
        "HEADER_SEARCH_PATHS": [target_build_directory + "/include"],
    }
    for key, expected_paths in expected_search_paths.items():
        value = settings.get(key)
        if not isinstance(value, str) or value.split() != expected_paths:
            raise ValueError(
                f"effective Release build setting {key} changed; "
                f"expected only generated build-product paths, got {value!r}"
            )
    version = settings.get("MARKETING_VERSION")
    build = settings.get("CURRENT_PROJECT_VERSION")
    if not isinstance(version, str) or re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version) is None:
        raise ValueError("effective MARKETING_VERSION is invalid")
    if not isinstance(build, str) or re.fullmatch(r"[1-9][0-9]*", build) is None:
        raise ValueError("effective CURRENT_PROJECT_VERSION is invalid")
    return {"app_version": version, "app_build": build}


def validate_bundle_structure(root: Path) -> list[Path]:
    _require_real_directory(root, "release app bundle")
    info_plist = _load_info_plist(root)
    executable_name = _validated_executable_name(info_plist)
    _validate_production_info_plist(info_plist)
    _require_regular_file(
        root / executable_name,
        "CFBundleExecutable",
        nonempty=True,
    )
    _validate_ios_device_macho(root / executable_name)
    return _regular_bundle_files(root)


def file_contains_marker(path: Path, marker: bytes, chunk_size: int = 1024 * 1024) -> bool:
    if not marker:
        raise ValueError("forbidden marker must not be empty")
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    overlap = b""
    overlap_length = len(marker) - 1
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            payload = overlap + chunk
            if marker in payload:
                return True
            overlap = payload[-overlap_length:] if overlap_length else b""
    return False


def forbidden_bundle_markers(root: Path) -> list[tuple[Path, bytes]]:
    files = validate_bundle_structure(root)
    violations: list[tuple[Path, bytes]] = []
    for path in files:
        for marker in FORBIDDEN_MARKERS:
            if file_contains_marker(path, marker):
                violations.append((path.relative_to(root), marker))
        with path.open("rb") as handle:
            payload = handle.read(PRIVATE_KEY_BINARY_SCAN_MAX_SIZE + 1)
        if _binary_secret_prefix_is_forbidden(
            payload,
            truncated=path.stat().st_size > len(payload),
        ):
            violations.append((path.relative_to(root), BINARY_PRIVATE_KEY_MARKER))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipa", type=Path)
    parser.add_argument("--cms-status-stdin", action="store_true")
    parser.add_argument("--release-build-settings-stdin", action="store_true")
    parser.add_argument("app_bundle", nargs="?", type=Path)
    args = parser.parse_args(argv)
    if sum((
        args.ipa is not None,
        args.app_bundle is not None,
        args.cms_status_stdin,
        args.release_build_settings_stdin,
    )) != 1:
        parser.error(
            "provide exactly one app bundle path, --ipa IPA_PATH, "
            "--cms-status-stdin, or --release-build-settings-stdin"
        )
    try:
        if args.cms_status_stdin:
            status = sys.stdin.read(65537)
            if len(status) > 65536:
                raise ValueError("provisioning CMS status output is unexpectedly large")
            validate_provisioning_cms_status(status)
            violations = []
        elif args.release_build_settings_stdin:
            raw_settings = sys.stdin.read(4 * 1024 * 1024 + 1)
            if len(raw_settings) > 4 * 1024 * 1024:
                raise ValueError("Xcode build settings JSON is unexpectedly large")
            try:
                settings_payload = json.loads(raw_settings)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Xcode build settings JSON is invalid: {exc}") from exc
            validate_release_build_settings(settings_payload)
            violations = []
        elif args.ipa is not None:
            validate_ipa_container(args.ipa)
            violations: list[tuple[Path, bytes]] = []
        else:
            violations = forbidden_bundle_markers(args.app_bundle)
    except (OSError, ValueError, zipfile.LargeZipFile) as exc:
        print(f"RELEASE BUNDLE VALIDATION: FAILED: {exc}", file=sys.stderr)
        return 1
    if violations:
        details = ", ".join(
            f"{path}:{marker.decode('utf-8', errors='backslashreplace')}"
            for path, marker in violations
        )
        print(
            "RELEASE BUNDLE VALIDATION: FAILED: forbidden release marker found: "
            + details,
            file=sys.stderr,
        )
        return 1
    if args.cms_status_stdin:
        print("RELEASE BUNDLE VALIDATION: PASSED; provisioning CMS signer is trusted")
    elif args.release_build_settings_stdin:
        print("RELEASE BUNDLE VALIDATION: PASSED; effective Release build settings are pinned")
    elif args.ipa is not None:
        print("RELEASE BUNDLE VALIDATION: PASSED; IPA container is safe and key-free")
    else:
        print("RELEASE BUNDLE VALIDATION: PASSED; bundle is valid and marker-free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
