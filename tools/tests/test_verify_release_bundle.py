from __future__ import annotations

import importlib.util
import plistlib
import stat
import struct
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "verify_release_bundle.py"
SPEC = importlib.util.spec_from_file_location("verify_release_bundle", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


class ReleaseBundleVerifierTests(unittest.TestCase):
    @staticmethod
    def make_macho(
        *,
        cpu_type: int = verifier.CPU_TYPE_ARM64,
        file_type: int = verifier.MH_EXECUTE,
        platform: int = verifier.PLATFORM_IOS,
        legacy_iphoneos: bool = False,
        extra_commands: tuple[bytes, ...] = (),
    ) -> bytes:
        if legacy_iphoneos:
            platform_command = struct.pack(
                "<IIII",
                verifier.LC_VERSION_MIN_IPHONEOS,
                verifier.VERSION_MIN_COMMAND.size,
                17 << 16,
                26 << 16,
            )
        else:
            platform_command = struct.pack(
                "<IIIIII",
                verifier.LC_BUILD_VERSION,
                verifier.BUILD_VERSION_COMMAND.size,
                platform,
                17 << 16,
                26 << 16,
                0,
            )
        commands = (platform_command,) + extra_commands
        command_payload = b"".join(commands)
        header = struct.pack(
            "<IiiIIIII",
            verifier.MH_MAGIC_64,
            cpu_type,
            0,
            file_type,
            len(commands),
            len(command_payload),
            0,
            0,
        )
        return header + command_payload + b"release-binary-without-test-code"

    @staticmethod
    def write_executable(path: Path, payload: bytes, *, executable: bool = True) -> None:
        path.write_bytes(payload)
        path.chmod(0o755 if executable else 0o644)

    @staticmethod
    def make_valid_bundle(parent: Path, name: str = "Xjie.app") -> Path:
        app = parent / name
        app.mkdir()
        (app / "Info.plist").write_bytes(
            plistlib.dumps(
                {
                    "CFBundleIdentifier": "com.xjie.app",
                    "CFBundleExecutable": "Xjie",
                    "CFBundleShortVersionString": "1.0",
                    "CFBundleVersion": "17",
                    "API_BASE_URL": "https://www.jianjieaitech.com",
                    "NSHealthShareUsageDescription": "读取健康数据",
                    "NSHealthUpdateUsageDescription": "写入健康数据",
                }
            )
        )
        ReleaseBundleVerifierTests.write_executable(
            app / "Xjie",
            ReleaseBundleVerifierTests.make_macho(),
        )
        return app

    def test_clean_bundle_passes_and_every_forbidden_marker_fails(self):
        trusted_cms = (
            'SMIME: level=0.2; type=signedData; nsigners=1; '
            'signer0.id="Apple iPhone OS Provisioning Profile Signing"; '
            'signer0.status=GoodSignature; level=0.1; type=data;'
        )
        verifier.validate_provisioning_cms_status(trusted_cms)
        for untrusted_cms in (
            trusted_cms.replace("GoodSignature", "SigningCertNotTrusted"),
            trusted_cms.replace(
                "Apple iPhone OS Provisioning Profile Signing", "Not Apple"
            ),
            trusted_cms.replace("nsigners=1", "nsigners=2"),
            trusted_cms + ' signer1.id="Apple"; signer1.status=GoodSignature;',
        ):
            with self.subTest(untrusted_cms=untrusted_cms):
                with self.assertRaisesRegex(ValueError, "single Apple-signed CMS"):
                    verifier.validate_provisioning_cms_status(untrusted_cms)

        release_settings = {
            "CONFIGURATION": "Release",
            "SDKROOT": "/Applications/Xcode.app/Contents/Developer/Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS26.2.sdk",
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
            "PRODUCT_BUNDLE_IDENTIFIER": "com.xjie.app",
            "MARKETING_VERSION": "1.0",
            "CURRENT_PROJECT_VERSION": "17",
            "TARGET_BUILD_DIR": "/tmp/DerivedData/Build/Products/Release-iphoneos",
            "LIBRARY_SEARCH_PATHS": "/tmp/DerivedData/Build/Products/Release-iphoneos ",
            "FRAMEWORK_SEARCH_PATHS": "/tmp/DerivedData/Build/Products/Release-iphoneos ",
            "HEADER_SEARCH_PATHS": "/tmp/DerivedData/Build/Products/Release-iphoneos/include ",
        }
        settings_payload = [{"target": "Xjie", "buildSettings": release_settings}]
        self.assertEqual(
            verifier.validate_release_build_settings(settings_payload),
            {"app_version": "1.0", "app_build": "17"},
        )
        for key, value in (
            ("CONFIGURATION", "Debug"),
            ("ARCHS", "x86_64"),
            ("ENABLE_TESTABILITY", "YES"),
            ("SWIFT_ACTIVE_COMPILATION_CONDITIONS", "DEBUG"),
            ("OTHER_SWIFT_FLAGS", "-DDEBUG"),
            ("EXCLUDED_SOURCE_FILE_NAMES", "APIService.swift"),
            ("SWIFT_EXEC", "/tmp/untrusted-swift"),
            ("OTHER_LDFLAGS", "-force_load /tmp/rogue.a"),
            ("OTHER_CFLAGS", "-include /tmp/rogue.h"),
            ("OTHER_CPLUSPLUSFLAGS", "-include /tmp/rogue.hpp"),
            ("SWIFT_OBJC_BRIDGING_HEADER", "/tmp/rogue.h"),
            ("SWIFT_INCLUDE_PATHS", "/tmp/rogue-modules"),
            ("LIBRARY_SEARCH_PATHS", "/tmp/rogue-libraries"),
            ("FRAMEWORK_SEARCH_PATHS", "/tmp/rogue-frameworks"),
            ("HEADER_SEARCH_PATHS", "/tmp/rogue-headers"),
        ):
            with self.subTest(effective_release_setting=key):
                mutated = dict(release_settings)
                mutated[key] = value
                with self.assertRaisesRegex(ValueError, "effective Release build setting"):
                    verifier.validate_release_build_settings(
                        [{"target": "Xjie", "buildSettings": mutated}]
                    )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = self.make_valid_bundle(root)
            executable = app / "Xjie"
            valid_executable = executable.read_bytes()
            self.assertEqual(verifier.forbidden_bundle_markers(app), [])

            legacy_executable = self.make_macho(legacy_iphoneos=True)
            self.write_executable(executable, legacy_executable)
            self.assertEqual(verifier.forbidden_bundle_markers(app), [])
            self.write_executable(executable, valid_executable)

            for marker in verifier.FORBIDDEN_MARKERS:
                with self.subTest(marker=marker):
                    self.write_executable(
                        executable,
                        valid_executable + b"prefix\x00" + marker + b"\x00suffix",
                    )
                    self.assertEqual(
                        verifier.forbidden_bundle_markers(app),
                        [(Path("Xjie"), marker)],
                    )
            self.write_executable(executable, valid_executable)

            invalid_machos = (
                ("ASCII", b"release-binary-without-test-code", "Mach-O"),
                (
                    "FAT",
                    bytes.fromhex("cafebabe") + b"\x00" * 60,
                    "Mach-O",
                ),
                (
                    "x86_64",
                    self.make_macho(cpu_type=0x01000007),
                    "arm64",
                ),
                (
                    "dylib",
                    self.make_macho(file_type=0x6),
                    "MH_EXECUTE",
                ),
                (
                    "simulator",
                    self.make_macho(platform=verifier.PLATFORM_IOSSIMULATOR),
                    "iOS Simulator",
                ),
                (
                    "macOS",
                    self.make_macho(platform=1),
                    "platform must be iOS device",
                ),
                (
                    "truncated header",
                    valid_executable[:16],
                    "truncated Mach-O header",
                ),
                (
                    "truncated commands",
                    valid_executable[: verifier.MACH_HEADER_64.size + 8],
                    "truncated Mach-O load commands",
                ),
            )
            for variant, payload, error in invalid_machos:
                with self.subTest(macho_variant=variant):
                    self.write_executable(executable, payload)
                    with self.assertRaisesRegex(ValueError, error):
                        verifier.forbidden_bundle_markers(app)
            self.write_executable(executable, valid_executable)

            self.write_executable(executable, valid_executable, executable=False)
            with self.assertRaisesRegex(ValueError, "executable permission"):
                verifier.forbidden_bundle_markers(app)
            self.write_executable(executable, valid_executable)

            duplicate_build_version = struct.pack(
                "<IIIIII",
                verifier.LC_BUILD_VERSION,
                verifier.BUILD_VERSION_COMMAND.size,
                verifier.PLATFORM_IOS,
                17 << 16,
                26 << 16,
                0,
            )
            self.write_executable(
                executable,
                self.make_macho(extra_commands=(duplicate_build_version,)),
            )
            with self.assertRaisesRegex(ValueError, "duplicate iOS platform"):
                verifier.forbidden_bundle_markers(app)
            self.write_executable(executable, valid_executable)

            info_plist = app / "Info.plist"
            valid_info = info_plist.read_bytes()
            for contents in (None, b"", b"not a plist"):
                with self.subTest(info_plist=contents):
                    info_plist.unlink(missing_ok=True)
                    if contents is not None:
                        info_plist.write_bytes(contents)
                    with self.assertRaisesRegex(ValueError, "Info.plist"):
                        verifier.forbidden_bundle_markers(app)
            info_plist.write_bytes(valid_info)

            production_info = plistlib.loads(valid_info)
            for key, invalid_value in (
                ("CFBundleIdentifier", "com.example.staging"),
                ("CFBundleShortVersionString", "1.0-beta"),
                ("CFBundleVersion", "0"),
                ("API_BASE_URL", "https://staging.example.invalid"),
                ("NSHealthShareUsageDescription", ""),
                ("NSHealthUpdateUsageDescription", None),
            ):
                with self.subTest(info_key=key, invalid_value=invalid_value):
                    mutated = dict(production_info)
                    if invalid_value is None:
                        mutated.pop(key, None)
                    else:
                        mutated[key] = invalid_value
                    info_plist.write_bytes(plistlib.dumps(mutated))
                    with self.assertRaisesRegex(ValueError, key):
                        verifier.forbidden_bundle_markers(app)
            info_plist.write_bytes(valid_info)

            for sensitive_name in (
                ".env",
                ".env.production",
                "secret.pem",
                "AuthKey_TEST.p8",
                "distribution.p12",
                "signing.pfx",
                "cache.sqlite",
                "cache.sqlite3",
                "data.db-wal",
                "data.db3",
                "AuthKey.der",
                "private.pkcs8",
                "signing.jwk",
                "id_rsa",
            ):
                with self.subTest(sensitive_name=sensitive_name):
                    sensitive = app / sensitive_name
                    sensitive.write_bytes(b"not-for-release")
                    with self.assertRaisesRegex(ValueError, "sensitive/runtime path"):
                        verifier.forbidden_bundle_markers(app)
                    sensitive.unlink()

            sensitive_directory = app / ".env "
            sensitive_directory.mkdir()
            (sensitive_directory / "credentials").write_bytes(b"binary-secret")
            with self.assertRaisesRegex(ValueError, "sensitive/runtime path"):
                verifier.forbidden_bundle_markers(app)
            (sensitive_directory / "credentials").unlink()
            sensitive_directory.rmdir()

            external_info = root / "External-Info.plist"
            external_info.write_bytes(valid_info)
            info_plist.unlink()
            info_plist.symlink_to(external_info)
            with self.assertRaisesRegex(ValueError, "Info.plist.*symbolic link"):
                verifier.forbidden_bundle_markers(app)
            info_plist.unlink()
            info_plist.write_bytes(valid_info)

            for executable_name in (
                None,
                "",
                " Xjie",
                "Xjie ",
                ".",
                "..",
                "Frameworks/Xjie",
                "Xjie\\helper",
                "Xjie\nhelper",
            ):
                with self.subTest(CFBundleExecutable=executable_name):
                    payload = dict(production_info)
                    if executable_name is None:
                        payload.pop("CFBundleExecutable", None)
                    else:
                        payload["CFBundleExecutable"] = executable_name
                    info_plist.write_bytes(plistlib.dumps(payload))
                    with self.assertRaisesRegex(ValueError, "CFBundleExecutable"):
                        verifier.forbidden_bundle_markers(app)
            info_plist.write_bytes(valid_info)

            executable.unlink()
            with self.assertRaisesRegex(ValueError, "CFBundleExecutable"):
                verifier.forbidden_bundle_markers(app)
            executable.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "CFBundleExecutable"):
                verifier.forbidden_bundle_markers(app)
            self.write_executable(executable, valid_executable)

            external_executable = root / "External-Xjie"
            self.write_executable(external_executable, valid_executable)
            executable.unlink()
            executable.symlink_to(external_executable)
            with self.assertRaisesRegex(ValueError, "CFBundleExecutable.*symbolic link"):
                verifier.forbidden_bundle_markers(app)
            executable.unlink()
            self.write_executable(executable, valid_executable)

            internal_link = app / "linked-resource"
            internal_link.symlink_to(executable)
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                verifier.forbidden_bundle_markers(app)
            internal_link.unlink()

            real_app = self.make_valid_bundle(root, "Real.app")
            linked_app = root / "Linked.app"
            linked_app.symlink_to(real_app, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symbolic link"):
                verifier.forbidden_bundle_markers(linked_app)

            regular_file = root / "NotAnApp.app"
            regular_file.write_bytes(b"not a directory")
            with self.assertRaisesRegex(ValueError, "real directory"):
                verifier.forbidden_bundle_markers(regular_file)

    def test_marker_split_across_read_chunks_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "binary"
            marker = verifier.FORBIDDEN_MARKERS[0]
            path.write_bytes(b"1234567" + marker + b"tail")
            self.assertTrue(verifier.file_contains_marker(path, marker, chunk_size=8))

            def write_ipa(
                name: str,
                entries: tuple[tuple[str | zipfile.ZipInfo, bytes], ...],
                *,
                compression: int = zipfile.ZIP_STORED,
                archive_comment: bytes = b"",
            ) -> Path:
                ipa = root / name
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(ipa, "w", compression=compression) as archive:
                        for member, payload in entries:
                            archive.writestr(member, payload)
                        archive.comment = archive_comment
                return ipa

            clean_entries = (
                ("Payload/Xjie.app/Xjie", b"device executable"),
                ("SwiftSupport/libswiftCore.dylib", b"swift runtime"),
                ("Symbols/Xjie.symbols", b"symbols without credentials"),
            )
            clean_ipa = write_ipa("clean.ipa", clean_entries)
            verifier.validate_ipa_container(clean_ipa)

            nul_member = zipfile.ZipInfo("Payload/file\x00hidden")
            with self.assertRaisesRegex(ValueError, "unsafe IPA member path"):
                verifier._validated_ipa_member_identity(nul_member)

            for sensitive_path in (
                "SwiftSupport/AuthKey_TEST.p8",
                "Symbols/secret.pem",
                ".env.production",
                "Payload/Xjie.app/cache.sqlite-wal",
                "Symbols/database.db.backup",
                "SwiftSupport/.env/credentials",
                "Symbols/secret.p8 /credentials",
                "Symbols/secret.p8 ",
                "Symbols/secret.pem./payload",
            ):
                with self.subTest(sensitive_path=sensitive_path):
                    ipa = write_ipa(
                        "sensitive.ipa",
                        clean_entries + ((sensitive_path, b"not-for-release"),),
                    )
                    with self.assertRaisesRegex(ValueError, "sensitive/runtime path"):
                        verifier.validate_ipa_container(ipa)

            for marker_index, private_marker in enumerate(verifier.PRIVATE_KEY_MARKERS):
                with self.subTest(private_marker=private_marker):
                    split_payload = (
                        b"A" * (verifier.IPA_SCAN_CHUNK_SIZE - 5)
                        + private_marker
                        + b"tail"
                    )
                    private_key_ipa = write_ipa(
                        f"private-key-content-{marker_index}.ipa",
                        clean_entries + (("Symbols/blob.bin", split_payload),),
                    )
                    with self.assertRaisesRegex(ValueError, "private-key content"):
                        verifier.validate_ipa_container(private_key_ipa)
                    metadata_key_ipa = write_ipa(
                        f"private-key-comment-{marker_index}.ipa",
                        clean_entries,
                        archive_comment=b"metadata:" + private_marker,
                    )
                    with self.assertRaisesRegex(ValueError, "private-key content"):
                        verifier.validate_ipa_container(metadata_key_ipa)

            def der_length(length: int) -> bytes:
                if length < 128:
                    return bytes([length])
                encoded = length.to_bytes((length.bit_length() + 7) // 8, "big")
                return bytes([0x80 | len(encoded)]) + encoded

            def der_tlv(tag: int, payload: bytes) -> bytes:
                return bytes([tag]) + der_length(len(payload)) + payload

            def der_integer(payload: bytes) -> bytes:
                return der_tlv(0x02, payload)

            rsa_body = b"".join((
                der_integer(b"\x00"),
                der_integer(b"\x00" + b"N" * 64),
                der_integer(b"\x01\x00\x01"),
                der_integer(b"\x00" + b"D" * 64),
                der_integer(b"\x00" + b"P" * 32),
                der_integer(b"\x00" + b"Q" * 32),
                der_integer(b"\x00" + b"A" * 32),
                der_integer(b"\x00" + b"B" * 32),
                der_integer(b"\x00" + b"C" * 32),
            ))
            disguised_der = der_tlv(0x30, rsa_body)
            self.assertTrue(verifier._looks_like_binary_private_key(disguised_der))
            padded_jwk = (
                b'{"kty":"RSA","n":"n","e":"AQAB","d":"secret"}'
                + b"P" * (verifier.PRIVATE_KEY_BINARY_SCAN_MAX_SIZE + 1)
            )
            padded_der = (
                disguised_der
                + b"P" * (verifier.PRIVATE_KEY_BINARY_SCAN_MAX_SIZE + 1)
            )
            oversized_jwk = (
                b'{"kty":"RSA","padding":"'
                + b"A" * (verifier.PRIVATE_KEY_BINARY_SCAN_MAX_SIZE + 1)
                + b'","d":"secret"}'
            )
            whitespace_prefixed_jwk = (
                b" " * (verifier.PRIVATE_KEY_BINARY_SCAN_MAX_SIZE + 2)
                + b'{"kty":"RSA","d":"secret"}'
            )
            oversized_rsa_body = b"".join((
                der_integer(b"\x00"),
                der_integer(b"\x00" + b"N" * (verifier.PRIVATE_KEY_BINARY_SCAN_MAX_SIZE + 1)),
                der_integer(b"\x01\x00\x01"),
                der_integer(b"\x00" + b"D" * 64),
                der_integer(b"\x00" + b"P" * 32),
                der_integer(b"\x00" + b"Q" * 32),
                der_integer(b"\x00" + b"A" * 32),
                der_integer(b"\x00" + b"B" * 32),
                der_integer(b"\x00" + b"C" * 32),
            ))
            oversized_der = der_tlv(0x30, oversized_rsa_body)
            self.assertTrue(verifier._looks_like_binary_private_key(oversized_jwk))
            self.assertTrue(verifier._looks_like_binary_private_key(oversized_der))
            for name, payload in (
                ("innocent.bin", disguised_der),
                ("padded-der.bin", padded_der),
                ("oversized-der.bin", oversized_der),
                ("opaque.dat", verifier.OPENSSH_PRIVATE_KEY_MAGIC + b"payload"),
                ("cache.bin", verifier.SQLITE_HEADER + b"payload"),
                ("public-looking.json", b'{"kty":"RSA","n":"n","e":"AQAB","d":"secret"}'),
                ("padded-jwk.bin", padded_jwk),
                ("oversized-jwk.bin", oversized_jwk),
                ("whitespace-prefixed-jwk.bin", whitespace_prefixed_jwk),
            ):
                with self.subTest(binary_secret=name):
                    binary_secret_ipa = write_ipa(
                        "binary-secret.ipa",
                        clean_entries + ((f"Symbols/{name}", payload),),
                    )
                    with self.assertRaisesRegex(
                        ValueError, "binary private-key/database payload"
                    ):
                        verifier.validate_ipa_container(binary_secret_ipa)

            binary_app = self.make_valid_bundle(root, "Binary.app")
            for resource_name, payload in (
                ("padded-der.bin", padded_der),
                ("padded-jwk.bin", padded_jwk),
                ("oversized-der.bin", oversized_der),
                ("oversized-jwk.bin", oversized_jwk),
                ("whitespace-prefixed-jwk.bin", whitespace_prefixed_jwk),
            ):
                with self.subTest(bundle_binary_secret=resource_name):
                    resource = binary_app / resource_name
                    resource.write_bytes(payload)
                    self.assertIn(
                        (Path(resource_name), verifier.BINARY_PRIVATE_KEY_MARKER),
                        verifier.forbidden_bundle_markers(binary_app),
                    )
                    resource.unlink()

            metadata_payloads = (
                disguised_der,
                b'{"kty":"RSA","d":"secret"}',
                verifier.OPENSSH_PRIVATE_KEY_MAGIC + b"payload",
                verifier.SQLITE_HEADER + b"payload",
            )

            def write_gap_ipa(name: str, payload: bytes) -> Path:
                raw = clean_ipa.read_bytes()
                eocd_offset = raw.rfind(b"PK\x05\x06")
                self.assertGreaterEqual(eocd_offset, 0)
                fields = list(struct.unpack_from("<4s4H2LH", raw, eocd_offset))
                central_size = fields[5]
                central_offset = fields[6]
                self.assertEqual(central_offset + central_size, eocd_offset)
                fields[6] = central_offset + len(payload)
                rewritten_eocd = struct.pack("<4s4H2LH", *fields)
                gap_ipa = root / name
                gap_ipa.write_bytes(
                    raw[:central_offset]
                    + payload
                    + raw[central_offset:eocd_offset]
                    + rewritten_eocd
                )
                return gap_ipa

            def write_local_extra_ipa(name: str, payload: bytes) -> Path:
                raw = bytearray(clean_ipa.read_bytes())
                eocd_offset = raw.rfind(b"PK\x05\x06")
                fields = list(struct.unpack_from("<4s4H2LH", raw, eocd_offset))
                central_offset = fields[6]
                with zipfile.ZipFile(clean_ipa) as archive:
                    target = max(archive.infolist(), key=lambda item: item.header_offset)
                filename_length, extra_length = struct.unpack_from(
                    "<HH", raw, target.header_offset + 26
                )
                insertion = target.header_offset + 30 + filename_length + extra_length
                struct.pack_into(
                    "<H", raw, target.header_offset + 28, extra_length + len(payload)
                )
                fields[6] = central_offset + len(payload)
                rewritten_eocd = struct.pack("<4s4H2LH", *fields)
                local_extra_ipa = root / name
                local_extra_ipa.write_bytes(
                    bytes(raw[:insertion])
                    + payload
                    + bytes(raw[insertion:eocd_offset])
                    + rewritten_eocd
                )
                return local_extra_ipa

            for index, payload in enumerate(metadata_payloads):
                with self.subTest(unreferenced_gap_secret=index):
                    gap_ipa = write_gap_ipa(f"gap-{index}.ipa", payload)
                    with self.assertRaisesRegex(ValueError, "unreferenced"):
                        verifier.validate_ipa_container(gap_ipa)

                with self.subTest(local_extra_secret=index):
                    local_extra_ipa = write_local_extra_ipa(
                        f"local-extra-{index}.ipa", payload
                    )
                    with self.assertRaisesRegex(ValueError, "local and central extra"):
                        verifier.validate_ipa_container(local_extra_ipa)

                with self.subTest(archive_comment_secret=index):
                    commented = write_ipa(
                        f"commented-{index}.ipa",
                        clean_entries,
                        archive_comment=payload,
                    )
                    with self.assertRaisesRegex(ValueError, "archive comments are forbidden"):
                        verifier.validate_ipa_container(commented)

                with self.subTest(member_comment_secret=index):
                    member = zipfile.ZipInfo(f"Symbols/commented-{index}.bin")
                    member.comment = payload
                    commented_member = write_ipa(
                        f"member-comment-{index}.ipa",
                        clean_entries + ((member, b"ordinary payload"),),
                    )
                    with self.assertRaisesRegex(ValueError, "member comments are forbidden"):
                        verifier.validate_ipa_container(commented_member)

                with self.subTest(member_extra_secret=index):
                    member = zipfile.ZipInfo(f"Symbols/extra-{index}.bin")
                    member.extra = struct.pack("<HH", 0xCAFE, len(payload)) + payload
                    extra_member = write_ipa(
                        f"member-extra-{index}.ipa",
                        clean_entries + ((member, b"ordinary payload"),),
                    )
                    with self.assertRaisesRegex(ValueError, "extra metadata"):
                        verifier.validate_ipa_container(extra_member)

                with self.subTest(trailing_secret=index):
                    trailing = write_ipa(f"trailing-{index}.ipa", clean_entries)
                    with trailing.open("ab") as handle:
                        handle.write(payload)
                    with self.assertRaisesRegex(
                        ValueError,
                        "end-of-central-directory|private-key content",
                    ):
                        verifier.validate_ipa_container(trailing)

            duplicate_ipa = write_ipa(
                "duplicate.ipa",
                (("Payload/file", b"one"), ("Payload/file", b"two")),
            )
            with self.assertRaisesRegex(ValueError, "duplicate IPA member"):
                verifier.validate_ipa_container(duplicate_ipa)

            for collision_entries in (
                (("Symbols/Case", b"one"), ("symbols/case", b"two")),
                (("Symbols/Caf\u00e9", b"one"), ("Symbols/Cafe\u0301", b"two")),
            ):
                with self.subTest(collision_entries=collision_entries):
                    collision_ipa = write_ipa("collision.ipa", collision_entries)
                    with self.assertRaisesRegex(ValueError, "normalization"):
                        verifier.validate_ipa_container(collision_ipa)

            for unsafe_path in (
                "../secret",
                "Payload/../secret",
                "/absolute/secret",
                "Payload//secret",
                "Payload\\secret",
            ):
                with self.subTest(unsafe_path=unsafe_path):
                    unsafe_ipa = write_ipa("unsafe-path.ipa", ((unsafe_path, b"x"),))
                    with self.assertRaisesRegex(ValueError, "unsafe IPA member path"):
                        verifier.validate_ipa_container(unsafe_ipa)

            for file_type, label in (
                (stat.S_IFLNK, "symlink"),
                (stat.S_IFIFO, "fifo"),
                (stat.S_IFCHR, "character-device"),
            ):
                with self.subTest(file_type=label):
                    special = zipfile.ZipInfo(f"Symbols/{label}")
                    special.create_system = 3
                    special.external_attr = (file_type | 0o600) << 16
                    special_ipa = write_ipa("special.ipa", ((special, b"target"),))
                    with self.assertRaisesRegex(ValueError, "regular file or directory"):
                        verifier.validate_ipa_container(special_ipa)

            zip_bomb_ipa = write_ipa(
                "unsafe-ratio.ipa",
                (("Payload/zeros", b"\x00" * (verifier.IPA_COMPRESSION_RATIO_MIN_SIZE + 1)),),
                compression=zipfile.ZIP_DEFLATED,
            )
            with self.assertRaisesRegex(ValueError, "unsafe compression ratio"):
                verifier.validate_ipa_container(zip_bomb_ipa)

            invalid_ipa = root / "invalid.ipa"
            invalid_ipa.write_bytes(b"not a zip archive")
            with self.assertRaisesRegex(ValueError, "not a valid ZIP"):
                verifier.validate_ipa_container(invalid_ipa)


if __name__ == "__main__":
    unittest.main()
