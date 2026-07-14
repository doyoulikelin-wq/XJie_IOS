from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = REPO_ROOT / "tools" / "regression_guard.py"
GUARD_SPEC = importlib.util.spec_from_file_location("release_policy_regression_guard", GUARD_PATH)
assert GUARD_SPEC is not None and GUARD_SPEC.loader is not None
guard = importlib.util.module_from_spec(GUARD_SPEC)
sys.modules[GUARD_SPEC.name] = guard
GUARD_SPEC.loader.exec_module(guard)
NOTIFICATION_CENTER_PATTERN = re.compile(
    r"\bUNUserNotificationCenter\s*\.\s*current\s*\(\s*\)",
    re.MULTILINE,
)


def ui_test_policy_violations(
    sources: dict[str, str],
    *,
    enforce_support_digest: bool = False,
) -> list[str]:
    violations: list[str] = []
    support_path = "XAgeUITestCase.swift"
    static_sources = {
        path: guard._swift_static_code(source)
        for path, source in sources.items()
    }
    support = static_sources.get(support_path, "")
    support_raw = sources.get(support_path, "")
    combined = "\n".join(static_sources.values())
    if len(re.findall(r"\bXCUIApplication\b", combined)) != 3 \
            or len(re.findall(r"\bXCUIApplication\s*\(", combined)) != 1:
        violations.append("UI suite must keep the exact shared application type/initializer contract")
    if len(re.findall(r"\.\s*launch\b", support)) != 1 \
            or len(re.findall(r"\.\s*terminate\b", support)) != 2:
        violations.append("shared UI base must keep the exact audited lifecycle contract")
    if "final override func setUpWithError" not in support \
            or "final override func tearDownWithError" not in support \
            or "auditCurrentApplicationLaunch()" not in support \
            or "didLaunchAtLeastOnce" not in support:
        violations.append("shared UI base must audit every launch from teardown")
    if enforce_support_digest:
        try:
            class_start = support_raw.index("class XAgeUITestCase")
            class_end = support_raw.index(
                "private enum XAgeUITestApplicationFactory",
                class_start,
            )
            class_source = support_raw[class_start:class_end]
        except ValueError:
            violations.append("shared UI base class structure is missing")
        else:
            class_digest = hashlib.sha256(
                re.sub(r"\s+", "", class_source).encode("utf-8")
            ).hexdigest()
            if class_digest != "677c2b13f8c38a42d8f142612b9f8d930cdf1fa05c43d358b8f2253e8b480244":
                violations.append("shared UI lifecycle, wait, or network-audit implementation changed")
    for path, source in static_sources.items():
        if path != support_path and re.search(r"\bXCUIApplication\b", source):
            violations.append(f"application type or initializer outside shared support: {path}")
        if path != support_path and re.search(r"\.\s*(?:launch|terminate)\b", source):
            violations.append(f"direct application lifecycle outside shared support: {path}")
        if path != support_path and "XAgeUITestApplicationFactory" in source:
            violations.append(f"shared application factory used outside audited base: {path}")
        if path != support_path and re.search(
            r"\boverride\s+func\s+(?:setUpWithError|tearDownWithError)\b", source
        ):
            violations.append(f"audited lifecycle overridden outside shared support: {path}")
        if re.search(r"\bfunc\s+test\w+\s*\(", source):
            classes = re.findall(r"\bclass\s+\w+\s*:\s*([\w.]+)", source)
            if not classes or any(base != "XAgeUITestCase" for base in classes):
                violations.append(f"UI test class does not inherit audited base: {path}")
    return violations


def production_session_violations(sources: dict[str, str]) -> list[str]:
    return guard.network_transport_violations(sources)


def swift_compiler_block_digests(source: str) -> list[str]:
    stack: list[int] = []
    blocks: list[tuple[int, str]] = []
    directive_pattern = re.compile(
        r"^\s*#(if|elseif|else|endif)\b[^\r\n]*",
        re.MULTILINE,
    )
    for match in directive_pattern.finditer(source):
        directive = match.group(1)
        if directive == "if":
            stack.append(match.start())
        elif directive == "endif":
            if not stack:
                raise ValueError("compiler directive closes without a matching #if")
            start = stack.pop()
            normalized = re.sub(r"\s+", "", source[start:match.end()])
            blocks.append(
                (start, hashlib.sha256(normalized.encode("utf-8")).hexdigest())
            )
    if stack:
        raise ValueError("compiler directive remains unterminated")
    return [digest for _, digest in sorted(blocks)]


def chat_quiescence_policy_violations(sources: dict[str, str]) -> list[str]:
    violations: list[str] = []
    xage_key = "Views/Home/XAgeMainView.swift"
    chat_key = "Views/Chat/ChatView.swift"
    markdown_key = "Views/Shared/MarkdownTextView.swift"
    model_tests_key = "Tests/ChatViewModelTests.swift"
    ui_tests_key = "Tests/XAgeHighIntensityContextUITests.swift"
    xage_raw = sources[xage_key]
    xage_main = guard._swift_static_code(xage_raw)
    chat_view = guard._swift_static_code(sources[chat_key])
    chat_raw = sources[chat_key]
    markdown = guard._swift_static_code(sources[markdown_key])
    markdown_raw = sources[markdown_key]
    home_raw = sources["Views/Home/HomeView.swift"]
    ui_tests_raw = sources[ui_tests_key]
    production_raw_sources = {
        path: source
        for path, source in sources.items()
        if not path.startswith("Tests/")
    }
    production_sources = {
        path: guard._swift_static_code(source)
        for path, source in production_raw_sources.items()
    }

    try:
        surface_start = xage_main.index("private struct XAgeConversationSurface")
        surface_end = xage_main.index("private struct XAgeChatThinkingCard", surface_start)
        surface = xage_main[surface_start:surface_end]
        surface_raw_start = xage_raw.index("private struct XAgeConversationSurface")
        surface_raw_end = xage_raw.index("private struct XAgeChatThinkingCard", surface_raw_start)
        surface_raw = xage_raw[surface_raw_start:surface_raw_end]
        tab_consumer_start = xage_raw.index("                    TabView(selection: $selectedSection)")
        tab_consumer_end = xage_raw.index(
            "            .onChange(of: selectedSection)",
            tab_consumer_start,
        )
        tab_consumer = xage_raw[tab_consumer_start:tab_consumer_end]
        observer_start = surface.index(".onChange(of: vm.messages.count)")
        observer_end = surface.index("                XAgeChatInputBar(", observer_start)
        observers = surface[observer_start:observer_end]
        helper_start = surface.index("private func scrollToBottom")
        helper_end = surface.index("private var attachmentMenuOverlay", helper_start)
        xage_helper = surface[helper_start:helper_end]
        shared_start = chat_view.index("enum ChatAutoScroll")
        shared_end = chat_view.index("struct ChatLifecycleProbe", shared_start)
        shared_helper = chat_view[shared_start:shared_end]
        lifecycle_start = chat_raw.index("struct ChatLifecycleProbe")
        lifecycle_end = chat_raw.index("struct ChatProgressIndicator", lifecycle_start)
        lifecycle_probe = chat_raw[lifecycle_start:lifecycle_end]
        progress_start = lifecycle_end
        progress_end = chat_raw.index(
            "@MainActor\nprivate final class SpeechInputManager",
            progress_start,
        )
        progress_indicator = chat_raw[progress_start:progress_end]
        legacy_input_start = chat_raw.index("    private var inputBar")
        legacy_input_end = chat_raw.index("    // MARK: - 历史会话", legacy_input_start)
        legacy_input = chat_raw[legacy_input_start:legacy_input_end]
        legacy_surface_start = chat_raw.index("struct ChatView")
        legacy_surface_end = chat_raw.index("enum ChatAutoScroll", legacy_surface_start)
        legacy_surface_raw = chat_raw[legacy_surface_start:legacy_surface_end]
        legacy_message_list_start = chat_view.index("private var messageList")
        legacy_message_list_end = chat_view.index("private var welcomeMessage", legacy_message_list_start)
        legacy_message_list = chat_view[legacy_message_list_start:legacy_message_list_end]
        composition_start = chat_raw.index("private struct CompositionSafeTextView")
        composition_text_view = chat_raw[composition_start:]
        input_bar_start = xage_raw.index("private struct XAgeChatInputBar")
        input_bar_end = xage_raw.index("private struct XAgeAttachmentMenu", input_bar_start)
        input_bar = xage_raw[input_bar_start:input_bar_end]
        thinking_card_start = xage_raw.index("private struct XAgeChatThinkingCard")
        thinking_card_end = xage_raw.index("private struct XAgeChatWelcome", thinking_card_start)
        thinking_card = xage_raw[thinking_card_start:thinking_card_end]
        assistant_orb_start = xage_raw.index("private struct XAgeAssistantOrb")
        assistant_orb_end = xage_raw.index("private struct XAgeChatBubble", assistant_orb_start)
        assistant_orb = xage_raw[assistant_orb_start:assistant_orb_end]
        upload_card_start = xage_raw.index("private struct XAgeChatUploadStatusCard")
        upload_card_end = xage_raw.index(
            "@MainActor\nprivate final class XAgeSpeechInputManager",
            upload_card_start,
        )
        upload_card = xage_raw[upload_card_start:upload_card_end]
        bubble_start = xage_raw.index("private struct XAgeChatBubble")
        bubble_end = xage_raw.index("private struct XAgeChatInputBar", bubble_start)
        bubble = xage_raw[bubble_start:bubble_end]
        welcome_start = xage_raw.index("private struct XAgeChatWelcome")
        welcome_end = xage_raw.index("private struct XAgeStarterRow", welcome_start)
        welcome = xage_raw[welcome_start:welcome_end]
        markdown_view_start = markdown_raw.index("struct MarkdownTextView")
        markdown_view_end = markdown_raw.index("struct AccessibleMarkdownText", markdown_view_start)
        markdown_view = markdown_raw[markdown_view_start:markdown_view_end]
        accessible_text_start = markdown_raw.index("struct AccessibleMarkdownText")
        accessible_text_end = markdown_raw.index(
            "struct AccessibleMarkdownAccessibilitySegment",
            accessible_text_start,
        )
        accessible_text = markdown_raw[accessible_text_start:accessible_text_end]
        accessible_links_start = markdown_raw.index(
            "private struct AccessibleMarkdownAccessibilityRepresentation",
            accessible_text_end,
        )
        accessible_links_end = markdown_raw.index(
            "struct AccessibleMarkdownRendering",
            accessible_links_start,
        )
        accessible_links = markdown_raw[accessible_links_start:accessible_links_end]
        renderer_start = markdown_raw.index("enum AccessibleMarkdownRenderer")
        markdown_renderer = markdown_raw[renderer_start:]
        installer_start = xage_main.index("private struct XAgeVerticalKeyboardDismissInstaller")
        installer_end = xage_main.index("struct XAgeDataCardPreferenceSnapshot", installer_start)
        keyboard_installer = xage_main[installer_start:installer_end]
        ui_settled_start = ui_tests_raw.index("    private func assertChatSettled")
        ui_settled_end = ui_tests_raw.index("    private func tapAndWait", ui_settled_start)
        ui_settled = ui_tests_raw[ui_settled_start:ui_settled_end]
        legacy_quick_grid_start = home_raw.index("    private var quickGrid")
        legacy_quick_grid_end = home_raw.index("    private func quickItem", legacy_quick_grid_start)
        legacy_quick_grid = home_raw[legacy_quick_grid_start:legacy_quick_grid_end]
    except ValueError:
        return ["continuous-chat scroll policy structure is missing"]

    expected_triggers = (
        "vm.messages.count",
        "vm.sending",
        "vm.thinkingStepIndex",
        "reportUploadVM.uploading",
        "reportUploadVM.backgroundTaskHint",
    )
    if observers.count(".onChange(of:") != len(expected_triggers):
        violations.append("continuous-chat scroll triggers must remain an exact audited set")
    for trigger in expected_triggers:
        pattern = (
            r"\.onChange\s*\(\s*of\s*:\s*"
            + re.escape(trigger)
            + r"[^)]*\)\s*\{[^{}]*\bscrollToBottom\s*\(\s*proxy\s*\)[^{}]*\}"
        )
        if len(re.findall(pattern, observers)) != 1:
            violations.append(f"chat state trigger must use the shared scroll path: {trigger}")
    if observers.count("scrollToBottom(proxy)") != len(expected_triggers):
        violations.append("every audited chat state trigger must call the local scroll helper once")
    for forbidden in ("proxy.scrollTo", "ChatAutoScroll.toBottom", "withAnimation", "DispatchQueue"):
        if forbidden in observers:
            violations.append(f"chat state observers bypass the local scroll helper: {forbidden}")

    if xage_helper.count("ChatAutoScroll.toBottom") != 1:
        violations.append("XAGE chat must delegate exactly once to ChatAutoScroll")
    if surface.count("scrollToBottom(proxy)") != len(expected_triggers):
        violations.append("no chat scroll trigger may be added outside the audited observer block")
    if len(re.findall(r"\bproxy\b", surface)) != 8:
        violations.append("XAGE conversation may pass its ScrollViewProxy only through audited sites")
    for forbidden in (".scrollTo", "scrollPosition", "setContentOffset", "contentOffset"):
        if forbidden in surface:
            violations.append(f"XAGE conversation has an unaudited scroll mechanism: {forbidden}")
    if re.search(r"\.\s*animation\s*\(", surface) \
            or re.search(r"\.\s*animation\s*\(", legacy_message_list):
        violations.append("chat message layout may not add implicit animations around dynamic history")
    forbidden_submit_modifiers = ("keyboardShortcut", "onSubmit", "submitLabel")
    for forbidden in forbidden_submit_modifiers:
        pattern = rf"(?<![A-Za-z0-9_])`?{forbidden}`?(?![A-Za-z0-9_])"
        if re.search(pattern, surface) or re.search(pattern, guard._swift_static_code(legacy_surface_raw)):
            violations.append(f"chat surface may not intercept multiline Return through {forbidden}")

    expected_compiler_directives = {
        "App/AppDelegate.swift": ["#if DEBUG", "#else", "#endif"],
        "App/XjieApp.swift": [
            "#if DEBUG", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
            "#if DEBUG", "#else", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
        ],
        "Services/APIService.swift": [
            "#if DEBUG", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
        ],
        "Services/APIServiceProtocol.swift": ["#if DEBUG", "#endif"],
        "Services/AuthManager.swift": [
            "#if DEBUG", "#endif", "#if DEBUG", "#else", "#endif", "#if DEBUG", "#endif",
            "#if DEBUG", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
        ],
        "Services/Environment.swift": [
            "#if DEBUG", "#endif", "#if DEBUG", "#else", "#endif", "#if DEBUG", "#endif",
        ],
        "Services/PushNotificationManager.swift": ["#if DEBUG", "#else", "#endif"],
        "Utils/NetworkMonitor.swift": ["#if DEBUG", "#else", "#endif"],
        "ViewModels/AppleHealthSyncViewModel.swift": ["#if DEBUG", "#else", "#endif"],
        "ViewModels/ChatViewModel.swift": ["#if DEBUG", "#endif"],
        "Views/Chat/ChatView.swift": [
            "#if DEBUG", "#else", "#endif", "#if DEBUG", "#else", "#endif",
        ],
        "Views/Health/HealthView.swift": [
            "#if canImport(ActivityKit)", "#endif", "#if canImport(ActivityKit)", "#endif",
            "#if canImport(ActivityKit)", "#endif",
        ],
        "Views/Home/XAgeMainView.swift": [
            "#if DEBUG", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
            "#if DEBUG", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
            "#if DEBUG", "#endif", "#if targetEnvironment(simulator)", "#else", "#endif",
        ],
        "Views/Login/LoginView.swift": [
            "#if DEBUG", "#endif", "#if DEBUG", "#endif",
        ],
        "Views/Medications/MedicationListView.swift": ["#if DEBUG", "#endif"],
    }
    expected_compiler_block_digests = {
        "App/AppDelegate.swift": ["4b86c6606d0ac071214526dba5766edba2811d8983137b83c4114381ca6cebfb"],
        "App/XjieApp.swift": [
            "7579b28750b11b61f1966ee07ab6a94eadda3e860396437d962b4feba3fd1ddf",
            "70efece6f9ce6f4c252babd3b3415fd94c6e7836091d4c930f04fb16fa4e722b",
            "4d657833e4df34a2f666fb17bb08a14dc68380ad00cfb9979ca717caca2234a2",
            "dfe5f0989f810478c2696d2db6b562322f91d90b4a1516a6940a5108dba0b189",
            "f7d5d3ef3e0ebc486dbe204becc8f54d14f9c97474a55671f8d545ce3f0f0fec",
            "e6a84428515090aecaa1aa43a8cbf53182735ae13faa89a11ffc10beb56cfb6f",
        ],
        "Services/APIService.swift": [
            "f5f8485b3b403b5ebf32b3428be47610fa372587bf547898ec8f0232347bb5dc",
            "030e008f921c491543bf8cf2ceb4555ef333df5e08c1f147e2ccfd1c5f31173f",
            "94febc3ffb14605656fb971a1380f1f719488758d47be0083bbd8d98279ff3e3",
        ],
        "Services/APIServiceProtocol.swift": ["a061b98b65e590bf8d59a56691b82e25f0710104be9c8237eebb407d1632ccef"],
        "Services/AuthManager.swift": [
            "a55cf0b6c639ca15c3279605028785407acc7c0c7427df94e50ec2a71844d6d8",
            "acd18e3897577977078a97c45d81059061147e60fae407e5ba37589427b33a84",
            "e51dff693a1b41e16a8ef2aea1fb617fcf593f1b9b1ccb47742554362273e272",
            "b501683c8c1e2de153acfe10d1e24e66f9699d9748fc70ca65da8a79457e8f33",
            "81a111ad6f5b1b4fb8221ac66c68ac138326b834feef9a9b0e64788c04c5e0fa",
            "ae97c9b8da970f84ea164430b6e43ce2fc23a05547c2cf6a585a0d9e160be3c0",
        ],
        "Services/Environment.swift": [
            "5eb98d24a3a05af6e528d3fa79de6df8d34d891496bb8d2b91f45f1269bb80b6",
            "586881e0e400a95782dcd7530a2798095ba79e108226474bbecce7c2423c0ef3",
            "c0f74029121ddc3a8a6bd407b237d0a84e92e900038e129416a24b8603bd6a96",
        ],
        "Services/PushNotificationManager.swift": ["11f911f437371150659377c3d397a97d06a6d6dde4087c34963c3c3db16850ff"],
        "Utils/NetworkMonitor.swift": ["11f911f437371150659377c3d397a97d06a6d6dde4087c34963c3c3db16850ff"],
        "ViewModels/AppleHealthSyncViewModel.swift": ["11f911f437371150659377c3d397a97d06a6d6dde4087c34963c3c3db16850ff"],
        "ViewModels/ChatViewModel.swift": ["5fb5e11441b5f60790e8723b17e39f373338a3abeb8bf47e63a37944074e4d04"],
        "Views/Chat/ChatView.swift": [
            "b67871bc47b04de422983585f1a1b622ab8a81dbd20560e4ecfc61833824ad34",
            "d020059ceb9e967d67486a8a4efb7b616b9aca660546a62094c1e6aa871d6894",
        ],
        "Views/Health/HealthView.swift": [
            "bc9cfef21bc3405cf0212437e8091427f215f7a59c79c4b7bd89f4cfa32ff606",
            "2e168d87896ab53827adbd89bfb80a6d113c70351590c4abb0b4f01e2fecf2c4",
            "dfea3bed6699089c65b123b6d2cfb31051e2966254cce4b99f34b0f3420f94cf",
        ],
        "Views/Home/XAgeMainView.swift": [
            "5c6210f8db5f805e8dfe21d7db95f96c7bb9c75357888ffe51fe603d77db2ae9",
            "331114a38cfb1b39ef3a7b69025192d5a96ee6f3d368e708ed2ec96353ac71dc",
            "c7f03b17e74fe46b940c6485043871606de6472a3ebeea36396cc6c26f01bcdb",
            "556291b9a48d8852073833b58f40bc190079d581295975257e486f43096fff1c",
            "9ab6b6de6ca78124a890b6923e31136434d0d37dad2ec087d4e538c05d73239e",
            "c0f74029121ddc3a8a6bd407b237d0a84e92e900038e129416a24b8603bd6a96",
            "bbdf5d7a721411b94fd038c422c4e18af13cfd9f7104a4d0fc50bf6596be499b",
            "83cc2fde4ee34dc0cadb724470b0ef62f8016a4a081460de68c88f4d25044b74",
        ],
        "Views/Login/LoginView.swift": [
            "72668378d9b29d93f0a92faad53acfe46fd9fb8d0226df9215c5b95d6949134d",
            "b6227006825aeca2af8b3cef6aaf5718c37e1b9956c3108355f45cae0412a342",
        ],
        "Views/Medications/MedicationListView.swift": ["d40629ed2a7903deffcb3acefd165d945e66ae36f4da99522d3d59edd75cb8f5"],
    }
    expected_automation_identifiers = {
        "App/AppDelegate.swift": 1,
        "App/XjieApp.swift": 2,
        "Services/APIService.swift": 4,
        "Services/PushNotificationManager.swift": 1,
        "Utils/NetworkMonitor.swift": 1,
        "ViewModels/AppleHealthSyncViewModel.swift": 1,
        "Views/Chat/ChatView.swift": 2,
    }
    expected_submit_identifier_inventory = {
        "keyboardShortcut": {},
        "onSubmit": {
            "Views/Health/HealthView.swift": 2,
            "Views/Home/ExerciseCard.swift": 2,
            "Views/Home/XAgeMainView.swift": 4,
            "Views/Login/LoginView.swift": 14,
            "Views/Medications/MedicationEditView.swift": 2,
            "Views/Medications/XAgeMedicationManagementView.swift": 8,
        },
        "submitLabel": {
            "Views/Home/XAgeMainView.swift": 4,
            "Views/Login/LoginView.swift": 14,
            "Views/Medications/XAgeMedicationManagementView.swift": 6,
        },
    }
    expected_process_arguments_inventory = {
        "App/AppDelegate.swift": 1,
        "App/XjieApp.swift": 3,
        "Services/APIService.swift": 1,
        "Services/AuthManager.swift": 2,
        "Services/Environment.swift": 1,
        "Services/NotificationScheduler.swift": 1,
        "Services/PushNotificationManager.swift": 4,
        "Utils/NetworkMonitor.swift": 1,
        "ViewModels/AppleHealthSyncViewModel.swift": 4,
        "ViewModels/ChatViewModel.swift": 1,
        "Views/Chat/ChatView.swift": 2,
        "Views/Home/XAgeMainView.swift": 2,
    }
    expected_process_environment_inventory = {
        "App/XjieApp.swift": 1,
        "Services/AuthManager.swift": 1,
        "Services/Environment.swift": 1,
        "Views/Home/XAgeMainView.swift": 2,
    }
    expected_ui_test_literals = {
        "Services/APIService.swift": ["XJIE_UI_TEST_STUB_NETWORK"],
        "Services/APIServiceProtocol.swift": ["XJIE_UI_TEST_STUB_CHAT"],
        "Services/AuthManager.swift": ["XJIE_UI_TEST_RESET_AUTH"],
        "Views/Home/XAgeMainView.swift": ["XJIE_UI_TEST_RESET_DATA_CARDS"],
    }
    expected_chat_surface_identifiers = {
        "XAgeConversationSurface": {"Views/Home/XAgeMainView.swift": 2},
        "ChatView": {
            "Views/Chat/ChatView.swift": 1,
            "Views/Home/HomeView.swift": 1,
        },
    }
    for path, raw_source in production_raw_sources.items():
        directives = [
            re.sub(r"\s+", " ", match.group(0).strip())
            for match in re.finditer(
                r"^\s*#(?:if|elseif|else|endif)\b[^\r\n]*",
                raw_source,
                re.MULTILINE,
            )
        ]
        if directives != expected_compiler_directives.get(path, []):
            violations.append(f"production compiler-directive inventory changed: {path}")
        try:
            compiler_blocks = swift_compiler_block_digests(raw_source)
        except ValueError:
            compiler_blocks = []
            violations.append(f"production compiler-directive nesting is invalid: {path}")
        if compiler_blocks != expected_compiler_block_digests.get(path, []):
            violations.append(f"production compiler-directive block changed or moved: {path}")
        static_source = production_sources[path]
        automation_count = len(
            re.findall(
                r"(?<![A-Za-z0-9_])`?UIAutomationMode`?(?![A-Za-z0-9_])",
                static_source,
            )
        )
        if automation_count != expected_automation_identifiers.get(path, 0):
            violations.append(f"production UIAutomationMode inventory changed: {path}={automation_count}")
        arguments_count = len(
            re.findall(
                r"\bProcessInfo\s*\.\s*processInfo\s*\.\s*arguments\b",
                static_source,
            )
        )
        environment_count = len(
            re.findall(
                r"\bProcessInfo\s*\.\s*processInfo\s*\.\s*environment\b",
                static_source,
            )
        )
        if arguments_count != expected_process_arguments_inventory.get(path, 0):
            violations.append(f"production ProcessInfo.arguments inventory changed: {path}={arguments_count}")
        if environment_count != expected_process_environment_inventory.get(path, 0):
            violations.append(f"production ProcessInfo.environment inventory changed: {path}={environment_count}")
        command_line_arguments_count = len(
            re.findall(r"\bCommandLine\s*\.\s*arguments\b", static_source)
        )
        if command_line_arguments_count != 0:
            violations.append(f"production CommandLine.arguments inventory changed: {path}={command_line_arguments_count}")
        ui_test_literals = re.findall(r'"(XJIE_UI_TEST_[A-Za-z0-9_]+)"', raw_source)
        if ui_test_literals != expected_ui_test_literals.get(path, []):
            violations.append(f"production UI-test literal inventory changed: {path}")
        for identifier, expected_inventory in expected_chat_surface_identifiers.items():
            identifier_count = len(
                re.findall(
                    rf"(?<![A-Za-z0-9_])`?{identifier}`?(?![A-Za-z0-9_])",
                    static_source,
                )
            )
            if identifier_count != expected_inventory.get(path, 0):
                violations.append(f"production chat surface inventory changed: {path}:{identifier}={identifier_count}")
        for identifier, expected_inventory in expected_submit_identifier_inventory.items():
            count = len(
                re.findall(
                    rf"(?<![A-Za-z0-9_])`?{identifier}`?(?![A-Za-z0-9_])",
                    static_source,
                )
            )
            if count != expected_inventory.get(path, 0):
                violations.append(f"production submit modifier inventory changed: {path}:{identifier}={count}")

    expected_xage_consumer_attachment = '''XAgeConversationSurface(
                            selectedSection: $selectedSection,
                            historyRequest: chatHistoryRequest
                        )
                            .tag(XAgeTopSection.chat)

                        XAgeHealthspanView('''
    expected_legacy_consumer_attachment = '''NavigationLink(destination: ChatView(isEmbedded: true)) {
                quickItem(icon: "bubble.left.and.text.bubble.right", label: "助手小捷")
            }
            NavigationLink(destination: HealthView())'''
    if xage_raw.count(expected_xage_consumer_attachment) != 1:
        violations.append("XAGE conversation outer consumer attachment changed from the audited form")
    home_raw = production_raw_sources.get("Views/Home/HomeView.swift", "")
    if home_raw.count(expected_legacy_consumer_attachment) != 1:
        violations.append("legacy ChatView outer consumer attachment changed from the audited form")

    expected_scroll_members = {
        "Views/Chat/ChatView.swift": 1,
        "Views/HealthData/HealthDataView.swift": 1,
        "Views/Home/XAgeMainView.swift": 2,
        "Views/PatientHistory/PatientHistoryView.swift": 2,
    }
    expected_chat_auto_scroll_calls = {
        "Views/Chat/ChatView.swift": 1,
        "Views/Home/XAgeMainView.swift": 1,
    }
    expected_chat_auto_scroll_identifiers = {
        "Views/Chat/ChatView.swift": 2,
        "Views/Home/XAgeMainView.swift": 1,
    }
    expected_scroll_proxy_identifiers = {
        "Views/Chat/ChatView.swift": 1,
        "Views/Home/XAgeMainView.swift": 3,
        "Views/PatientHistory/PatientHistoryView.swift": 1,
    }
    expected_transaction_identifiers = {
        "Views/Chat/ChatView.swift": 1,
    }
    expected_with_transaction_identifiers = {
        "Views/Chat/ChatView.swift": 1,
    }
    expected_disable_animation_identifiers = {
        "Views/Chat/ChatView.swift": 1,
    }
    expected_on_change_identifiers = {
        "App/XjieApp.swift": 2,
        "Views/Chat/ChatView.swift": 2,
        "Views/Health/HealthView.swift": 1,
        "Views/Health/ManualIndicatorSheet.swift": 1,
        "Views/Health/MoodLogView.swift": 1,
        "Views/Home/XAgeMainView.swift": 20,
        "Views/Login/LoginView.swift": 2,
        "Views/Login/PasswordResetSheet.swift": 1,
        "Views/Meals/MealsView.swift": 1,
        "Views/Settings/ChangePasswordSheet.swift": 1,
    }
    expected_uikit_scroll_identifiers = {
        "UIScrollView": {"Views/Home/XAgeMainView.swift": 2},
        "contentOffset": {"Views/Home/XAgeMainView.swift": 1},
        "setContentOffset": {},
        "scrollRectToVisible": {},
        "scrollToItem": {},
        "scrollToRow": {},
        "scrollRangeToVisible": {},
        "scrollPosition": {},
        "ScrollPosition": {},
    }
    for path, source in production_sources.items():
        scroll_identifier_count = len(
            re.findall(r"(?<![A-Za-z0-9_])`?scrollTo`?(?![A-Za-z0-9_])", source)
        )
        scroll_members = len(re.findall(r"\.\s*`?\s*scrollTo\s*`?", source))
        if scroll_members != expected_scroll_members.get(path, 0):
            violations.append(
                f"production ScrollViewProxy.scrollTo inventory changed: {path}={scroll_members}"
            )
        if scroll_identifier_count != expected_scroll_members.get(path, 0):
            violations.append(
                f"production scrollTo identifier inventory changed: {path}={scroll_identifier_count}"
            )
        shared_calls = len(
            re.findall(r"\bChatAutoScroll\s*\.\s*`?\s*toBottom\s*`?", source)
        )
        if shared_calls != expected_chat_auto_scroll_calls.get(path, 0):
            violations.append(f"ChatAutoScroll call inventory changed: {path}={shared_calls}")
        shared_identifiers = len(
            re.findall(r"(?<![A-Za-z0-9_])`?ChatAutoScroll`?(?![A-Za-z0-9_])", source)
        )
        if shared_identifiers != expected_chat_auto_scroll_identifiers.get(path, 0):
            violations.append(
                f"ChatAutoScroll identifier inventory changed: {path}={shared_identifiers}"
            )
        proxy_identifiers = len(
            re.findall(r"(?<![A-Za-z0-9_])`?ScrollViewProxy`?(?![A-Za-z0-9_])", source)
        )
        if proxy_identifiers != expected_scroll_proxy_identifiers.get(path, 0):
            violations.append(
                f"ScrollViewProxy identifier inventory changed: {path}={proxy_identifiers}"
            )
        for identifier, expected_inventory in (
            ("Transaction", expected_transaction_identifiers),
            ("withTransaction", expected_with_transaction_identifiers),
            ("disablesAnimations", expected_disable_animation_identifiers),
        ):
            count = len(
                re.findall(
                    rf"(?<![A-Za-z0-9_])`?{identifier}`?(?![A-Za-z0-9_])",
                    source,
                )
            )
            if count != expected_inventory.get(path, 0):
                violations.append(f"chat transaction identifier inventory changed: {path}:{identifier}={count}")
        on_change_count = len(
            re.findall(r"(?<![A-Za-z0-9_])`?onChange`?(?![A-Za-z0-9_])", source)
        )
        if on_change_count != expected_on_change_identifiers.get(path, 0):
            violations.append(f"production onChange identifier inventory changed: {path}={on_change_count}")
        for identifier, expected_inventory in expected_uikit_scroll_identifiers.items():
            count = len(
                re.findall(
                    rf"(?<![A-Za-z0-9_])`?{identifier}`?(?![A-Za-z0-9_])",
                    source,
                )
            )
            if count != expected_inventory.get(path, 0):
                violations.append(f"UIKit scroll identifier inventory changed: {path}:{identifier}={count}")
    expected_shared_helper = (
        "enumChatAutoScroll{"
        "staticfunctoBottom<ID:Hashable>(_id:ID,usingproxy:ScrollViewProxy){"
        "vartransaction=SwiftUI.Transaction(animation:nil)"
        "transaction.disablesAnimations=true"
        "SwiftUI.withTransaction(transaction){proxy.scrollTo(id,anchor:.bottom)}"
        "}}"
    )
    expected_xage_helper = (
        "privatefuncscrollToBottom(_proxy:ScrollViewProxy){"
        "ChatAutoScroll.toBottom(Self.bottomAnchorID,using:proxy)"
        "}"
        "privatefuncdismissChatKeyboard(){"
        "inputFocused=false"
        "XAgeKeyboard.dismiss()"
        "}"
        "privatefuncsendStarterPrompt(_prompt:String){"
        "dismissChatKeyboard()"
        "Task{awaitvm.sendText(prompt)}"
        "}"
        "privatefuncretryMessage(id:String){"
        "dismissChatKeyboard()"
        "Task{awaitvm.retryMessage(id:id)}"
        "}"
    )
    if re.sub(r"\s+", "", shared_helper) != expected_shared_helper:
        violations.append("shared chat scroll helper changed from the audited synchronous form")
    if re.sub(r"\s+", "", xage_helper) != expected_xage_helper:
        violations.append("XAGE chat scroll helper changed from the audited delegation form")
    xage_surface_digest = hashlib.sha256(
        re.sub(r"\s+", "", surface_raw).encode("utf-8")
    ).hexdigest()
    legacy_surface_digest = hashlib.sha256(
        re.sub(r"\s+", "", legacy_surface_raw).encode("utf-8")
    ).hexdigest()
    tab_consumer_digest = hashlib.sha256(
        re.sub(r"\s+", "", tab_consumer).encode("utf-8")
    ).hexdigest()
    legacy_quick_grid_digest = hashlib.sha256(
        re.sub(r"\s+", "", legacy_quick_grid).encode("utf-8")
    ).hexdigest()
    if xage_surface_digest != "beed55e003edf8c3a63753c63146467341fd03fe9f7be9d614e728b878e2bc9c":
        violations.append("XAGE conversation surface changed outside its audited complete structure")
    if legacy_surface_digest != "c88de412afb3c11fe741a5f2d16d145881bd2c03146bc3a5ca81b69914288e4c":
        violations.append("legacy ChatView surface changed outside its audited complete structure")
    if tab_consumer_digest != "5d90d456a9951a61f03bf84b1bcb26a9ef9e10c3c9512cdeaf7e3b24acf211e1":
        violations.append("XAGE root TabView consumers changed outside their audited complete structure")
    if legacy_quick_grid_digest != "f9677a47dd582c7f50ea097329bb6f4ad41c62cef9ffb57d716442404d40afff":
        violations.append("legacy HomeView quick-grid consumers changed outside their audited complete structure")
    expected_bottom_anchor = '''private static let bottomAnchorID = "xage.chat.bottom"'''
    expected_bottom_sentinel = '''Color.clear
                                .frame(height: 1)
                                .id(Self.bottomAnchorID)'''
    if surface_raw.count(expected_bottom_anchor) != 1 \
            or surface_raw.count(expected_bottom_sentinel) != 1 \
            or surface_raw.count("Self.bottomAnchorID") != 2 \
            or surface_raw.count('"xage.chat.bottom"') != 1:
        violations.append("XAGE chat bottom anchor definition, sentinel, or helper attachment changed")
    else:
        sentinel_index = surface_raw.index(expected_bottom_sentinel)
        preceding_dynamic_indexes = [
            surface_raw.index("ForEach(vm.messages)"),
            surface_raw.index("if reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil"),
            surface_raw.index("if vm.sending"),
        ]
        if sentinel_index <= max(preceding_dynamic_indexes):
            violations.append("XAGE chat bottom sentinel must remain after every dynamic message state")

    outbound_methods = (
        "sendMessage",
        "sendText",
        "retryMessage",
        "grantAIConsentAndRetry",
        "startPlanConversation",
    )
    expected_outbound_identifiers = {
        "sendMessage": {"ViewModels/ChatViewModel.swift": 1},
        "sendText": {
            "ViewModels/ChatViewModel.swift": 1,
            "Views/Chat/ChatView.swift": 2,
            "Views/Home/XAgeMainView.swift": 3,
        },
        "retryMessage": {
            "ViewModels/ChatViewModel.swift": 1,
            "Views/Chat/ChatView.swift": 3,
            "Views/Home/XAgeMainView.swift": 3,
        },
        "grantAIConsentAndRetry": {
            "ViewModels/ChatViewModel.swift": 1,
            "Views/Home/XAgeMainView.swift": 1,
        },
        "startPlanConversation": {
            "ViewModels/ChatViewModel.swift": 1,
            "Views/Chat/ChatView.swift": 1,
        },
    }
    expected_outbound_calls = {
        "sendMessage": {"ViewModels/ChatViewModel.swift": 1},
        "sendText": {
            "ViewModels/ChatViewModel.swift": 1,
            "Views/Chat/ChatView.swift": 2,
            "Views/Home/XAgeMainView.swift": 3,
        },
        "retryMessage": {
            "ViewModels/ChatViewModel.swift": 1,
            "Views/Chat/ChatView.swift": 3,
            "Views/Home/XAgeMainView.swift": 3,
        },
        "grantAIConsentAndRetry": {
            "ViewModels/ChatViewModel.swift": 1,
            "Views/Home/XAgeMainView.swift": 1,
        },
        "startPlanConversation": {
            "ViewModels/ChatViewModel.swift": 1,
            "Views/Chat/ChatView.swift": 1,
        },
    }
    expected_outbound_member_calls = {
        "sendMessage": {},
        "sendText": {
            "Views/Chat/ChatView.swift": 2,
            "Views/Home/XAgeMainView.swift": 3,
        },
        "retryMessage": {
            "Views/Chat/ChatView.swift": 1,
            "Views/Home/XAgeMainView.swift": 1,
        },
        "grantAIConsentAndRetry": {"Views/Home/XAgeMainView.swift": 1},
        "startPlanConversation": {"Views/Chat/ChatView.swift": 1},
    }
    for path, source in production_sources.items():
        for method in outbound_methods:
            identifier_count = len(
                re.findall(rf"(?<![A-Za-z0-9_])`?{method}`?(?![A-Za-z0-9_])", source)
            )
            call_count = len(
                re.findall(rf"(?<![A-Za-z0-9_])`?{method}`?\s*\(", source)
            )
            member_call_count = len(
                re.findall(rf"\.\s*`?\s*{method}\s*\(", source)
            )
            expected = (
                expected_outbound_identifiers[method].get(path, 0),
                expected_outbound_calls[method].get(path, 0),
                expected_outbound_member_calls[method].get(path, 0),
            )
            actual = (identifier_count, call_count, member_call_count)
            if actual != expected:
                violations.append(
                    f"production chat outbound inventory changed: "
                    f"{path}:{method}={actual}/{expected}"
                )
    expected_legacy_observer = """.onChange(of: vm.messages.count) { _, _ in
                ChatAutoScroll.toBottom("bottom", using: proxy)
            }"""
    expected_legacy_bottom_sentinel = '''Color.clear.frame(height: 1).id("bottom")'''
    if chat_raw.count(expected_legacy_observer) != 1 \
            or chat_raw.count(expected_legacy_bottom_sentinel) != 1 \
            or chat_raw.count('"bottom"') != 2:
        violations.append("legacy chat bottom sentinel or messages observer changed from the audited synchronous form")
    elif chat_raw.index(expected_legacy_bottom_sentinel) <= chat_raw.index("if vm.sending"):
        violations.append("legacy chat bottom sentinel must remain after the dynamic sending state")
    expected_legacy_hide_keyboard = '''private static func hideKeyboard() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
        )
    }'''
    expected_xage_hide_keyboard = '''@MainActor
private enum XAgeKeyboard {
    static func dismiss() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
    }
}'''
    if chat_raw.count(expected_legacy_hide_keyboard) != 1 \
            or xage_raw.count(expected_xage_hide_keyboard) != 1:
        violations.append("chat keyboard dismissal owners must invoke resignFirstResponder")
    expected_keyboard_owner_inventory = {
        "Views/Chat/ChatView.swift": 1,
        "Views/Elderly/ElderlyCheckinSheet.swift": 1,
        "Views/Home/XAgeMainView.swift": 1,
        "Views/Login/LoginView.swift": 1,
    }
    for path, source in production_sources.items():
        send_action_count = len(re.findall(r"\bUIApplication\s*\.\s*shared\s*\.\s*sendAction\s*\(", source))
        resign_count = len(re.findall(r"\bUIResponder\s*\.\s*resignFirstResponder\b", source))
        expected_count = expected_keyboard_owner_inventory.get(path, 0)
        if send_action_count != expected_count or resign_count != expected_count:
            violations.append(
                f"keyboard resign owner inventory changed: {path}={send_action_count}/{resign_count}"
            )
    composition_digest = hashlib.sha256(
        re.sub(r"\s+", "", composition_text_view).encode("utf-8")
    ).hexdigest()
    if composition_digest != "a6e3ef2f6d625ea9096553cdbf21b3815b8577369f87c454484e063171106c74" \
            or "returnKeyType" in composition_text_view \
            or "shouldChangeTextIn" in composition_text_view \
            or "onSubmit" in composition_text_view:
        violations.append("legacy composition-safe editor must preserve Return as a multiline line break")
    expected_xage_observers = """.onChange(of: vm.messages.count) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: vm.sending) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: vm.thinkingStepIndex) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: reportUploadVM.uploading) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: reportUploadVM.backgroundTaskHint ?? "") { _, _ in
                        scrollToBottom(proxy)
                    }"""
    if xage_raw.count(expected_xage_observers) != 1:
        violations.append("XAGE chat observers changed from the audited synchronous forms")
    expected_lifecycle_probe = r'''struct ChatLifecycleProbe: View {
    let sending: Bool
    let messageCount: Int
    let latestRole: String?
    let inputFocused: Bool

    @ViewBuilder
    var body: some View {
        #if DEBUG
        if UIAutomationMode.isEnabled(arguments: ProcessInfo.processInfo.arguments) {
            Color.clear
                .frame(width: 1, height: 1)
                .accessibilityElement(children: .ignore)
                .accessibilityIdentifier("xage.chat.lifecycle")
                .accessibilityLabel("Chat lifecycle")
                .accessibilityValue(accessibilityValue)
                .allowsHitTesting(false)
        }
        #else
        EmptyView()
        #endif
    }

    private var accessibilityValue: String {
        let phase = sending ? "sending" : "idle"
        let focused = inputFocused ? "true" : "false"
        return "phase=\(phase);messages=\(messageCount);latest=\(latestRole ?? "none");focused=\(focused)"
    }
}'''
    if re.sub(r"\s+", "", lifecycle_probe) != re.sub(r"\s+", "", expected_lifecycle_probe):
        violations.append("chat lifecycle probe changed from the audited app-owned state")
    expected_progress_indicator = '''struct ChatProgressIndicator: View {
    let tint: Color

    @ViewBuilder
    var body: some View {
        Group {
            #if DEBUG
            if UIAutomationMode.isEnabled(arguments: ProcessInfo.processInfo.arguments) {
                Image(systemName: "ellipsis")
            } else {
                ProgressView()
            }
            #else
            ProgressView()
            #endif
        }
        .controlSize(.small)
        .tint(tint)
        .foregroundStyle(tint)
        .frame(width: 16, height: 16)
    }
}'''
    if re.sub(r"\s+", "", progress_indicator) != re.sub(r"\s+", "", expected_progress_indicator):
        violations.append("chat progress indicator changed from the audited automation-static form")
    expected_thinking_attachment = '''if vm.sending {
                                XAgeChatThinkingCard(
                                    currentHint: vm.thinkingHint.isEmpty ? "正在思考…" : vm.thinkingHint,
                                    steps: vm.thinkingProgressItems
                                )
                                .id("xage.chat.thinking")
                            }'''
    expected_thinking_indicator_use = '''ChatProgressIndicator(tint: Color(hex: "18AFA7"))'''
    if surface_raw.count(expected_thinking_attachment) != 1:
        violations.append("XAGE sending state must remain attached to the audited thinking card")
    if len(re.findall(r"(?<![A-Za-z0-9_])`?ProgressView`?(?![A-Za-z0-9_])", surface)) != 0:
        violations.append("XAGE conversation surface may not add an animation-backed progress bypass")
    if thinking_card.count(expected_thinking_indicator_use) != 1 \
            or "ProgressView" in thinking_card:
        violations.append("XAGE thinking card must use the automation-static progress indicator")
    thinking_card_digest = hashlib.sha256(
        re.sub(r"\s+", "", thinking_card).encode("utf-8")
    ).hexdigest()
    if thinking_card_digest != "fa556875b0d32e8fc7647f657dbe35b90be287ef39752d5f98cb36e68a25591b":
        violations.append("XAGE thinking card changed from the audited static and visible form")
    assistant_orb_digest = hashlib.sha256(
        re.sub(r"\s+", "", assistant_orb).encode("utf-8")
    ).hexdigest()
    if assistant_orb_digest != "4086d9d3890bce9bbdecab4559fd5f06cdf6325d49b2adbe1f92f02f07661c7d":
        violations.append("XAGE assistant orb changed from the audited automation-static form")
    expected_upload_indicator_use = '''ChatProgressIndicator(tint: Color(hex: "159D8F"))'''
    upload_card_digest = hashlib.sha256(
        re.sub(r"\s+", "", upload_card).encode("utf-8")
    ).hexdigest()
    if upload_card.count(expected_upload_indicator_use) != 1 \
            or "ProgressView" in upload_card \
            or upload_card_digest != "e6a37f6fa34dacc1e4ef204c7f60a2e096f85d766e53f4ef8a605db7a7d18966":
        violations.append("XAGE upload status card must use the audited automation-static progress indicator")
    expected_progress_identifier_inventory = {
        "Views/Chat/ChatView.swift": 1,
        "Views/Home/XAgeMainView.swift": 2,
    }
    for path, source in production_sources.items():
        count = len(
            re.findall(r"(?<![A-Za-z0-9_])`?ChatProgressIndicator`?(?![A-Za-z0-9_])", source)
        )
        if count != expected_progress_identifier_inventory.get(path, 0):
            violations.append(f"ChatProgressIndicator identifier inventory changed: {path}={count}")
    expected_continuous_animation_identifiers = {
        "symbolEffect": {},
        "phaseAnimator": {},
        "keyframeAnimator": {},
        "TimelineView": {},
        "repeatCount": {},
        "repeatForever": {"Views/Components/SplashView.swift": 1},
    }
    for path, source in production_sources.items():
        for identifier, expected_inventory in expected_continuous_animation_identifiers.items():
            count = len(
                re.findall(
                    rf"(?<![A-Za-z0-9_])`?{identifier}`?(?![A-Za-z0-9_])",
                    source,
                )
            )
            if count != expected_inventory.get(path, 0):
                violations.append(f"continuous animation inventory changed: {path}:{identifier}={count}")

    expected_legacy_send_helpers = '''private func sendCurrentInput() {
        guard let text = vm.consumeInputForSending() else { return }
        Self.hideKeyboard()
        Task { @MainActor in
            await Task.yield()
            if vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines) == text {
                vm.inputValue = ""
            }
            await vm.sendText(text)
        }
    }

    private func sendPrompt(_ prompt: String) {
        Self.hideKeyboard()
        Task { await vm.sendText(prompt) }
    }

    private func retryMessage(id: String) {
        Self.hideKeyboard()
        Task { await vm.retryMessage(id: id) }
    }'''
    expected_legacy_input_submit = '''CompositionSafeTextView(
                text: $vm.inputValue,
                placeholder: "问血糖、饮食、病史...",
                isEnabled: !vm.sending
            )'''
    expected_legacy_send_button = '''Button {
                sendCurrentInput()
            } label: {
                Image(systemName: "paperplane.fill")'''
    expected_legacy_starter = '''private func sendStarterPrompt(_ prompt: String) {
        sendPrompt(prompt)
    }'''
    expected_legacy_followup = '''Button {
                            sendPrompt(q)
                        } label: {'''
    expected_legacy_retry = '''Button("重试") {
                                retryMessage(id: msg.id)
                            }'''
    expected_legacy_initial_wiring = '''.task {
            await vm.loadConversations()
            sendInitialPromptIfNeeded()
        }
        .onChange(of: initialPrompt ?? "") { _, _ in
            sendInitialPromptIfNeeded()
        }'''
    expected_legacy_initial_helper = '''private func sendInitialPromptIfNeeded() {
        guard let prompt = initialPrompt?.trimmingCharacters(in: .whitespacesAndNewlines),
              !prompt.isEmpty else { return }
        Self.hideKeyboard()
        Task { @MainActor in
            await vm.startPlanConversation(prompt: prompt)
            onInitialPromptConsumed()
        }
    }'''
    for expected, message in (
        (expected_legacy_send_helpers, "legacy chat send/retry helpers must dismiss the keyboard before async work"),
        (expected_legacy_input_submit, "legacy chat multiline editor must preserve return for line breaks"),
        (expected_legacy_send_button, "legacy chat send button must use the audited send helper"),
        (expected_legacy_starter, "legacy chat starter must use the audited send helper"),
        (expected_legacy_followup, "legacy chat follow-up must use the audited send helper"),
        (expected_legacy_retry, "legacy chat retry must use the audited retry helper"),
        (expected_legacy_initial_wiring, "legacy initial prompt triggers must use the audited synchronous scheduler"),
        (expected_legacy_initial_helper, "legacy initial prompt must dismiss the keyboard before async work"),
    ):
        if chat_raw.count(expected) != 1:
            violations.append(message)

    expected_send_current_input = '''private func sendCurrentInput() {
        guard let text = vm.consumeInputForSending() else { return }
        inputFocused.wrappedValue = false
        XAgeKeyboard.dismiss()
        Task { @MainActor in
            await Task.yield()
            if vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines) == text {
                vm.inputValue = ""
            }
            await vm.sendText(text)
        }
    }'''
    if input_bar.count(expected_send_current_input) != 1:
        violations.append("chat send path must synchronously release focus and dismiss the keyboard")
    expected_xage_input_submit = '''TextField("输入或长按说话", text: $vm.inputValue, axis: .vertical)
                .font(.system(size: 15))
                .textFieldStyle(.plain)
                .lineLimit(1...5)
                .padding(.vertical, 11)
                .frame(minHeight: 44)
                .focused(inputFocused)
                .accessibilityIdentifier("xage.chat.input")'''
    expected_xage_send_button = '''Button {
                sendCurrentInput()
            } label: {
                Image(systemName: "paperplane.fill")'''
    if input_bar.count(expected_xage_input_submit) != 1 \
            or input_bar.count(expected_xage_send_button) != 1 \
            or input_bar.count("sendCurrentInput") != 2 \
            or ".onSubmit" in input_bar \
            or ".submitLabel" in input_bar:
        violations.append("XAGE return must insert a line break and only the send button may invoke the send helper")
    if ".keyboardShortcut" in input_bar or ".keyboardShortcut" in legacy_input:
        violations.append("chat Return must remain a multiline line break without a send-button shortcut")
    expected_welcome_wiring = '''XAgeChatWelcome(
                                    vm: vm,
                                    onSendPrompt: sendStarterPrompt
                                )'''
    expected_retry_wiring = '''onRetry: { retryMessage(id: msg.id) }'''
    expected_consent_wiring = '''Button("同意并继续") {
                dismissChatKeyboard()
                Task { await vm.grantAIConsentAndRetry() }
            }'''
    if surface_raw.count(expected_welcome_wiring) != 1 \
            or surface_raw.count(expected_retry_wiring) != 1 \
            or surface_raw.count(expected_consent_wiring) != 1:
        violations.append("XAGE starter, retry, and consent sends must dismiss the keyboard before async work")
    expected_welcome_first_action = '''Button {
                onSendPrompt("帮我整理病史摘要")
            } label: {'''
    expected_welcome_second_action = '''Button {
                onSendPrompt("帮我分析最近报告趋势")
            } label: {'''
    if welcome.count("let onSendPrompt: (String) -> Void") != 1 \
            or welcome.count(expected_welcome_first_action) != 1 \
            or welcome.count(expected_welcome_second_action) != 1 \
            or welcome.count("onSendPrompt(") != 2 \
            or "Task" in welcome \
            or "vm.sendMessage" in welcome:
        violations.append("XAGE welcome prompts must delegate through the audited keyboard-dismiss send path")
    expected_upload_send = '''private func uploadReports(_ files: [XAgeReportUploadFile]) {
        guard !files.isEmpty else { return }
        inputFocused = false
        XAgeKeyboard.dismiss()
        reportUploadVM.uploadDocType = "exam"
        Task {
            var uploaded: [(fileName: String, documentId: String)] = []
            for file in files {
                if let doc = await reportUploadVM.uploadFile(data: file.data, fileName: file.fileName) {
                    uploaded.append((file.fileName, doc.id))
                }
            }
            if !uploaded.isEmpty {
                let prompt = reportAnalysisPrompt(uploaded: uploaded)
                if vm.sending {
                    vm.inputValue = prompt
                } else {
                    await vm.sendText(prompt)
                }
            }
        }
    }'''
    if surface_raw.count(expected_upload_send) != 1:
        violations.append("report-upload follow-up must dismiss the keyboard before async upload and chat send")
    expected_lifecycle_wiring = '''ChatLifecycleProbe(
                sending: vm.sending,
                messageCount: vm.messages.count,
                latestRole: vm.messages.last?.role,
                inputFocused: inputFocused
            )'''
    if surface_raw.count(expected_lifecycle_wiring) != 1:
        violations.append("XAGE lifecycle probe must remain wired to live chat and focus state")
    expected_assistant_rendering = '''Group {
                    if isUser {
                        Text(message.content)
                    } else {
                        AccessibleMarkdownText(text: message.content)
                    }
                }'''
    expected_markdown_wrapper = '''struct MarkdownTextView: View {
    let text: String

    var body: some View {
        AccessibleMarkdownText(text: text)
            .font(.subheadline)
            .foregroundColor(.appText)
            .multilineTextAlignment(.leading)
    }
}'''
    if bubble.count(expected_assistant_rendering) != 1:
        violations.append("XAGE assistant bubble must consume the audited accessible Markdown renderer")
    bubble_digest = hashlib.sha256(
        re.sub(r"\s+", "", bubble).encode("utf-8")
    ).hexdigest()
    if bubble_digest != "4b20560ea6a720bf3ab2d08eebd0faa86d028f37aef4e9867792af3f1ca78e67":
        violations.append("XAGE chat bubble changed from the audited visible accessibility form")
    if re.sub(r"\s+", "", markdown_view) != re.sub(r"\s+", "", expected_markdown_wrapper):
        violations.append("shared MarkdownTextView must delegate to AccessibleMarkdownText")
    expected_markdown_identifier_inventory = {
        "Views/Home/XAgeMainView.swift": 1,
        "Views/Shared/MarkdownTextView.swift": 2,
    }
    for path, source in production_sources.items():
        count = len(
            re.findall(r"(?<![A-Za-z0-9_])`?AccessibleMarkdownText`?(?![A-Za-z0-9_])", source)
        )
        if count != expected_markdown_identifier_inventory.get(path, 0):
            violations.append(f"AccessibleMarkdownText identifier inventory changed: {path}={count}")
    installer_digest = hashlib.sha256(
        re.sub(r"\s+", "", keyboard_installer).encode("utf-8")
    ).hexdigest()
    if installer_digest != "c8ecd185e1b33780c1199828e3348d1f7682f7fed2c4a45014c8021747dc4bfd":
        violations.append("XAGE vertical keyboard installer changed from the audited gesture-only form")

    markdown_requirements = (
        "let rendering = AccessibleMarkdownRenderer.render(text)",
        "if let rendered = rendering.attributed",
        "let rendered = try? AttributedString(",
        "Text(rendered)",
        "Text(verbatim: text)",
        "Text(verbatim: rendering.accessibilityText)",
        "AccessibleMarkdownAccessibilityRepresentation(",
        "if rendering.accessibilitySegments.contains(where: { $0.link != nil })",
        "Link(destination: link)",
        ".accessibilityAddTraits(.isLink)",
        "Text(verbatim: segment.text)",
        "accessibilitySegments: accessibilitySegments(from: rendered)",
        "segments[lastIndex].link == run.link",
        "link: run.link",
        "static func render(_ content: String) -> AccessibleMarkdownRendering",
        "guard containsPotentialMarkdown(content)",
        "let accessibilityText = String(rendered.characters)",
        "let hasPresentationAttributes = rendered.runs.contains",
        "guard accessibilityText != content || hasPresentationAttributes else",
        "private static let autolinkCandidatePattern",
        "return content.range(of: autolinkCandidatePattern",
        "options: .regularExpression",
    )
    for required in markdown_requirements:
        if required not in markdown:
            violations.append(f"accessible Markdown split is missing {required}")
    if "if true" in markdown or "if false" in markdown:
        violations.append("accessible Markdown rendering may not bypass its content predicate")
    if '["*", "_", "~", "`", "[", "<", "\\\\", "&"]' not in markdown_raw:
        violations.append("Markdown candidates must conservatively include every inline delimiter")
    if "content.unicodeScalars.contains" not in markdown \
            or "$0.value == 0x0D || $0.value == 0" not in markdown:
        violations.append("Markdown candidates must preserve Foundation CR and NUL normalization")
    if "(?i)(?:://|www\\.|mailto:|@)" not in markdown_raw:
        violations.append("Markdown candidates must include Foundation autolinks")
    expected_accessible_text = '''struct AccessibleMarkdownText: View {
    let text: String

    @ViewBuilder
    var body: some View {
        let rendering = AccessibleMarkdownRenderer.render(text)
        if let rendered = rendering.attributed {
            Text(rendered)
                .accessibilityRepresentation {
                    if rendering.accessibilitySegments.contains(where: { $0.link != nil }) {
                        AccessibleMarkdownAccessibilityRepresentation(
                            segments: rendering.accessibilitySegments
                        )
                    } else {
                        Text(verbatim: rendering.accessibilityText)
                    }
                }
        } else {
            Text(verbatim: text)
                .accessibilityRepresentation {
                    Text(verbatim: text)
                }
        }
    }
}'''
    if re.sub(r"\s+", "", accessible_text) != re.sub(r"\s+", "", expected_accessible_text):
        violations.append("accessible Markdown routing changed from the audited replacement tree")
    expected_accessible_links = '''private struct AccessibleMarkdownAccessibilityRepresentation: View {
    let segments: [AccessibleMarkdownAccessibilitySegment]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(segments) { segment in
                if let link = segment.link {
                    Link(destination: link) {
                        Text(verbatim: segment.text)
                    }
                    .accessibilityAddTraits(.isLink)
                } else {
                    Text(verbatim: segment.text)
                }
            }
        }
    }
}'''
    if re.sub(r"\s+", "", accessible_links) != re.sub(r"\s+", "", expected_accessible_links):
        violations.append("accessible Markdown link actions changed from the audited representation")
    markdown_renderer_digest = hashlib.sha256(
        re.sub(r"\s+", "", markdown_renderer).encode("utf-8")
    ).hexdigest()
    if markdown_renderer_digest != "ef8bc2317c61529b4342a5772018b80438db45a16228c70c00e1011f4be8728d":
        violations.append("accessible Markdown renderer changed from the audited Debug/Release-identical route")
    expected_ui_settled = '''    private func assertChatSettled(expectedMessageCount: Int, context: String) {
        let lifecycle = app.descendants(matching: .any)["xage.chat.lifecycle"]
        XCTAssertTrue(lifecycle.waitForExistence(timeout: 4), "\\(context)：应暴露可审计的聊天生命周期状态")
        let expected = "phase=idle;messages=\\(expectedMessageCount);latest=assistant;focused=false"
        XCTAssertTrue(
            waitUntil(timeout: 6) { (lifecycle.value as? String) == expected },
            "\\(context)：聊天必须唯一收口到 \\(expected)，实际为 \\(String(describing: lifecycle.value))"
        )
        XCTAssertFalse(
            app.descendants(matching: .any)["xage.chat.thinking.card"].exists,
            "\\(context)：助手回复完成后思考状态必须消失"
        )
    }

'''
    expected_ui_submit_and_settle = '''send.tap()
        assertChatSettled(expectedMessageCount: expectedMessageCount, context: "发送问题：\\(text)")
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 5), "发送后应释放输入框焦点并关闭输入法")'''
    expected_multiline_return_case = '''let multilineContinuation = "\\n补充：请按优先级排序"
        input.typeText(multilineContinuation)
        let submittedPrompt = longPrompt + multilineContinuation
        XCTAssertTrue(waitUntil(timeout: 4) {
            (input.value as? String) == submittedPrompt
        }, "回车应插入新行而不是发送或关闭键盘，保持微信式多行编辑")
        attachScreenshot(named: "chat-multiline-input")

        let chatScroll = app.scrollViews["xage.chat.scroll"]
        XCTAssertTrue(chatScroll.waitForExistence(timeout: 4), "问答滚动区域应存在")
        let send = app.buttons["xage.chat.send"]
        XCTAssertTrue(waitUntil(timeout: 4) { send.isEnabled && send.isHittable }, "长问题输入完成后发送按钮应可用")
        send.tap()
        assertChatSettled(expectedMessageCount: 2, context: "小屏长问题发送")
        XCTAssertTrue(app.keyboards.firstMatch.waitForNonExistence(timeout: 4), "发送长问题后应关闭输入法")
        XCTAssertTrue(app.staticTexts[submittedPrompt].waitForExistence(timeout: 5), "含手动换行的长问题应完整显示为用户消息")
        XCTAssertTrue(
            app.staticTexts["UI 自动化回复：\\(submittedPrompt)"].waitForExistence(timeout: 5),
            "小屏内容首次溢出后仍应显示确定性助手回复"
        )'''
    expected_ui_link_action_assertion = '''let link = app.buttons[expectedAssistantLinkLabel]
            XCTAssertTrue(
                link.waitForExistence(timeout: 5),
                "富文本助手回复必须向辅助功能树暴露可激活 Link 动作"
            )
            XCTAssertTrue(link.isHittable, "富文本助手链接必须可以由用户激活")'''
    if ui_settled != expected_ui_settled \
            or ui_tests_raw.count(expected_ui_submit_and_settle) != 1 \
            or ui_tests_raw.count(expected_multiline_return_case) != 1 \
            or ui_tests_raw.count(expected_ui_link_action_assertion) != 1:
        violations.append("continuous-chat UI must prove multiline Return editing and the exact app-owned terminal state after send")
    for semantic_case in (
        '"A * B * C"',
        '"- 列表"',
        '"**粗体**"',
        '"*斜体*"',
        '"_斜体_"',
        '"[指南](https://example.com)"',
        '"<https://example.com>"',
        '"*跨行\\n强调*"',
        '"[跨行\\n链接](https://example.com)"',
        '"H~2~O"',
        '"访问 https://example.com 获取指南"',
        '"www.example.com"',
        '"联系 test@example.com"',
        '"A\\rB"',
        '"A\\r\\nB"',
        '"A\\0B"',
        "XCTAssertNil(rendering.attributed",
        "XCTAssertNotNil(rendering.attributed",
        "XCTAssertEqual(rendering.accessibilityText",
        "rendered?.runs.contains(where: { $0.link != nil })",
        "linkedRendering.accessibilitySegments.map(\\.text)",
        "linkedRendering.accessibilitySegments.compactMap(\\.link)",
        "singleTildeText?.runs.contains(where: { $0.inlinePresentationIntent != nil })",
    ):
        if semantic_case not in sources[model_tests_key]:
            violations.append(f"Markdown routing regression assertion is missing {semantic_case}")
    return violations


def workflow_fail_open_violations(workflow: str) -> list[str]:
    violations: list[str] = []
    if re.search(r"(?m)^\s*continue-on-error\s*:", workflow):
        violations.append("continue-on-error is forbidden")
    for line in workflow.splitlines():
        stripped = line.strip()
        if stripped.startswith("if:") and stripped != "if: always()":
            violations.append(f"conditional skip is forbidden: {stripped}")
        if "||" in stripped and not (
            stripped.startswith("if [[") and stripped.endswith("]]; then")
        ):
            violations.append(f"OR-list can swallow a failure: {stripped}")
        if "&&" in stripped and not (
            stripped.startswith("if [[") and stripped.endswith("]]; then")
        ):
            violations.append(f"AND-list can swallow a failure: {stripped}")
    for pattern, label in (
        (r"(?m)(?:^\s*|[;&|]\s*)set\s+\+[euo]", "shell strict mode disabled"),
        (r"(?m)(?:^\s*|[;&|]\s*)exit\s+0(?:\s|$)", "forced successful exit"),
    ):
        if re.search(pattern, workflow):
            violations.append(label)

    lines = workflow.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)run:\s*\|\s*$", line)
        if match is None:
            if re.match(r"^\s*run:\s*\S", line):
                violations.append("one-line run step cannot prove strict shell mode")
            continue
        indentation = len(match.group(1))
        commands: list[str] = []
        for candidate in lines[index + 1:]:
            if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indentation:
                break
            stripped = candidate.strip()
            if stripped and not stripped.startswith("#"):
                commands.append(stripped)
        if not commands or commands[0] != "set -euo pipefail":
            violations.append(f"run block at line {index + 1} does not start fail-closed")
    return violations


class ReleasePolicyTests(unittest.TestCase):
    def test_ci_covers_xage_backend_and_never_swallows_failures(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        policy_job = workflow[
            workflow.index("  policy:\n"):workflow.index("  backend:\n")
        ]
        self.assertEqual(workflow_fail_open_violations(workflow), [])
        self.assertIn("branches: [main, XAGE]", workflow)
        self.assertEqual(
            re.findall(r"^    runs-on:\s*(\S+)\s*$", policy_job, re.MULTILINE),
            ["macos-15"],
        )
        self.assertIn("/usr/bin/python3 -I tools/python_test_gate.py tools", policy_job)
        self.assertIn("/usr/bin/python3 -I tools/regression_guard.py validate", policy_job)
        self.assertIn("/usr/bin/python3 -I tools/regression_guard.py check", policy_job)
        self.assertIn("Backend full regression", workflow)
        self.assertIn("python -I tools/python_test_gate.py backend", workflow)
        self.assertNotRegex(policy_job, r"(?m)^\s+python3\s+-I\s+")
        self.assertIn("regression_guard.py validate", workflow)
        self.assertIn("name: quality-gate", workflow)
        self.assertIn("set -o pipefail", workflow)
        self.assertNotIn("|| true", workflow)
        self.assertNotIn("    paths:", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotRegex(workflow, r"uses:\s+[^\s]+@v\d")
        self.assertIn("xcode-version: '26.3'", workflow)
        for mutation in (
            workflow.replace("set -euo pipefail", "set +e", 1),
            workflow.replace("- name: Run backend tests", "- name: Run backend tests\n        continue-on-error: true"),
            workflow.replace("- name: Run backend tests", "- name: Run backend tests\n        if: false"),
            workflow.replace("echo \"All required regression gates passed.\"", "exit 0"),
            workflow.replace(
                "/usr/bin/python3 -I tools/python_test_gate.py tools",
                "/usr/bin/python3 -I tools/python_test_gate.py tools && echo tools-passed",
                1,
            ),
        ):
            with self.subTest(mutation=mutation):
                self.assertTrue(workflow_fail_open_violations(mutation))

    def test_every_python_test_command_uses_the_inventory_and_skip_gate(self):
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            registry["commands"]["guard_unit"],
            "/usr/bin/python3 -I tools/python_test_gate.py tools",
        )
        self.assertEqual(registry["release_gate"]["latest_uploaded_build"], 17)
        for command_id in ("backend_ai", "backend_health", "backend_full"):
            command = registry["commands"][command_id]
            self.assertIn("tools/python_test_gate.py backend", command)
            self.assertIn(" -I tools/python_test_gate.py", command)
            self.assertIn("--junitxml", command)
            self.assertNotIn(" -m pytest ", command)
        self.assertIn("--profile full", registry["commands"]["backend_full"])
        self.assertIn("--profile focused", registry["commands"]["backend_ai"])
        self.assertIn("--profile focused", registry["commands"]["backend_health"])
        python_gate = (REPO_ROOT / "tools" / "python_test_gate.py").read_text(encoding="utf-8")
        self.assertIn('[sys.executable, "-I", "-m", "pytest"', python_gate)

    def test_release_script_requires_head_bound_gate_before_archive(self):
        script = (REPO_ROOT / "scripts" / "release_testflight.sh").read_text(encoding="utf-8")
        self.assertTrue(script.startswith("#!/bin/zsh -f\n"))
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        gate_position = script.index("run_regression_gate.py assert-release")
        archive_position = script.index("clean archive")
        export_position = script.index("-exportArchive")
        ipa_container_position = script.index(
            '"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"'
        )
        ipa_snapshot_position = script.index(
            'ipa_snapshot_parent=$(/usr/bin/mktemp -d "$tmp_parent/xjie-ipa-snapshot.XXXXXX")'
        )
        ipa_extract_position = script.index('/usr/bin/ditto -x -k "$ipa"')
        distribution_position = script.index("Distribution IPA verified")
        archive_only_position = script.index('if [[ "$mode" == "--archive-only" ]]')
        upload_position = script.index("--upload-app")
        git_guard_position = script.index("readonly -a forbidden_git_environment")
        replace_guard_position = script.index("for-each-ref --format='%(refname)' refs/replace")
        release_lock_position = script.index('/bin/mkdir -- "$release_lock_dir"')
        cleanup_trap_position = script.index("trap 'cleanup_release' EXIT")
        auth_preflight_position = script.index(
            'if [[ "$mode" == "--upload" ]]; then\n  configure_upload_authentication\nfi'
        )
        xcode_pin_position = script.index('readonly pinned_developer_dir=')
        version_validation_position = script.index("Refusing invalid MARKETING_VERSION")
        build_validation_position = script.index("Refusing invalid CURRENT_PROJECT_VERSION")
        archive_removal_position = script.index('/bin/rm -rf -- "$archive"')
        entitlement_redirection_position = script.index('> "$entitlements"')
        self.assertLess(git_guard_position, gate_position)
        self.assertLess(replace_guard_position, gate_position)
        self.assertLess(release_lock_position, gate_position)
        self.assertLess(release_lock_position, cleanup_trap_position)
        self.assertLess(cleanup_trap_position, auth_preflight_position)
        self.assertLess(release_lock_position, auth_preflight_position)
        self.assertLess(auth_preflight_position, xcode_pin_position)
        self.assertLess(auth_preflight_position, gate_position)
        self.assertLess(gate_position, archive_position)
        self.assertLess(archive_position, export_position)
        self.assertLess(export_position, ipa_snapshot_position)
        self.assertLess(ipa_snapshot_position, ipa_container_position)
        self.assertLess(export_position, ipa_container_position)
        self.assertLess(ipa_container_position, ipa_extract_position)
        self.assertLess(ipa_extract_position, distribution_position)
        self.assertLess(export_position, distribution_position)
        self.assertLess(distribution_position, archive_only_position)
        self.assertLess(archive_only_position, upload_position)
        self.assertLess(version_validation_position, archive_removal_position)
        self.assertLess(build_validation_position, archive_removal_position)
        self.assertLess(version_validation_position, entitlement_redirection_position)
        self.assertLess(build_validation_position, entitlement_redirection_position)
        self.assertGreaterEqual(script.count("run_regression_gate.py assert-release"), 2)
        self.assertIn('"$python_bin" -I "$candidate_repo/tools/verify_release_bundle.py" "$app"', script)
        self.assertIn("/usr/bin/env -i", script)
        self.assertIn('export PATH="$safe_path"', script)
        self.assertIn('readonly safe_path="/usr/bin:/bin:/usr/sbin:/sbin"', script)
        self.assertIn('readonly python_bin="/usr/bin/python3"', script)
        self.assertNotIn("command -v python3", script)
        self.assertIn("unset PYTHONHOME PYTHONPATH", script)
        self.assertIn("XCODE_XCCONFIG_FILE", script)
        self.assertIn('[[ "$testability" == "NO" ]]', script)
        self.assertIn('[[ "$swift_conditions" != *DEBUG* ]]', script)
        self.assertIn("-showBuildSettings", script)
        self.assertIn("-json", script)
        self.assertIn("ApplicationProperties:ApplicationPath", script)
        self.assertIn("--path-format=absolute --git-common-dir", script)
        self.assertIn("/usr/bin/git", script)
        self.assertIn("export GIT_NO_REPLACE_OBJECTS=1", script)
        self.assertIn('"GIT_NO_REPLACE_OBJECTS=1"', script)
        self.assertIn("Refusing release with local Git replace refs", script)
        self.assertIn("Refusing release with unsafe local Git configuration", script)
        self.assertNotIn("${unsafe_git_config", script)
        self.assertIn("Refusing release with repository-local attributes override", script)
        self.assertIn('readonly pinned_developer_dir="/Applications/Xcode.app/Contents/Developer"', script)
        self.assertIn("Xcode 26.3\\nBuild version 17C529", script)
        self.assertIn("clone --no-local --no-checkout --no-tags", script)
        self.assertIn('project="$candidate_repo/Xjie/Xjie.xcodeproj"', script)
        self.assertGreaterEqual(script.count("verify_candidate_snapshot"), 4)
        self.assertIn("archive_cdhash=", script)
        self.assertIn('[[ "$current_cdhash" != "$archive_cdhash" ]]', script)
        self.assertEqual(script.count("-exportArchive"), 1)
        self.assertEqual(script.count("--upload-app"), 1)
        self.assertIn('[[ "$(/usr/libexec/PlistBuddy -c \'Print :destination\' "$export_options")" == "export" ]]', script)
        self.assertIn('ipa_candidates=("$export_path"/*.ipa(N))', script)
        self.assertIn('(( ${#ipa_candidates[@]} != 1 ))', script)
        self.assertIn('distribution_apps=("$distribution_payload"/*.app(N))', script)
        self.assertIn('[[ "$(/usr/bin/lipo -archs "$distribution_executable")" == "arm64" ]]', script)
        self.assertIn('set(platforms) != {2}', script)
        self.assertIn('get-task-allow raw', script)
        self.assertIn('beta-reports-active raw', script)
        self.assertIn('embedded.mobileprovision', script)
        self.assertIn('profile.get("ProvisionedDevices") is not None', script)
        self.assertEqual(
            script.count('"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"'),
            2,
        )
        self.assertIn('/bin/chmod 700 "$ipa_snapshot_parent"', script)
        self.assertIn('exported_ipa_sha256_before=$(sha256_file "$exported_ipa")', script)
        self.assertIn('exported_ipa_sha256_after=$(sha256_file "$exported_ipa")', script)
        self.assertIn('ipa_sha256=$(sha256_file "$ipa")', script)
        self.assertIn('[[ "$exported_ipa_sha256_before" != "$exported_ipa_sha256_after"', script)
        self.assertIn('[[ "$(sha256_file "$ipa")" != "$ipa_sha256" ]]', script)
        self.assertIn('/bin/chmod 400 "$ipa"', script)
        self.assertIn('"$(/usr/bin/stat -f \'%l\' "$ipa")" != "1"', script)
        self.assertIn('--extract-certificates "$distribution_app"', script)
        self.assertIn('profile.get("DeveloperCertificates")', script)
        self.assertIn('leaf_certificate not in developer_certificates', script)
        cms_status_position = script.index("security cms -D -h 0 -n")
        cms_validation_position = script.index("--cms-status-stdin")
        cms_decode_position = script.index('security cms -D -i "$embedded_profile"')
        self.assertLess(cms_status_position, cms_validation_position)
        self.assertLess(cms_validation_position, cms_decode_position)
        self.assertIn(
            'profile_cms_status=$(/usr/bin/security cms -D -h 0 -n -i '
            '"$embedded_profile" 2>&1)',
            script,
        )
        self.assertIn("Apple iPhone OS Provisioning Profile Signing", (
            REPO_ROOT / "tools" / "verify_release_bundle.py"
        ).read_text(encoding="utf-8"))
        self.assertIn('ipa_sha256=$(sha256_file "$ipa")', script)
        self.assertIn('distribution_cdhash=$(code_directory_hash "$distribution_app")', script)
        self.assertIn('current_ipa_sha256=$(sha256_file "$ipa")', script)
        self.assertIn('current_distribution_cdhash=$(code_directory_hash "$distribution_app")', script)
        self.assertGreaterEqual(script.count("recheck_distribution_identity"), 3)
        self.assertIn('XJIE_ASC_API_KEY_ID', script)
        self.assertIn('XJIE_ASC_API_ISSUER_ID', script)
        self.assertIn('XJIE_ASC_USERNAME', script)
        self.assertIn('XJIE_ASC_PASSWORD_KEYCHAIN_ITEM', script)
        self.assertIn('--password "@keychain:$XJIE_ASC_PASSWORD_KEYCHAIN_ITEM"', script)
        self.assertIn('Refusing mixed App Store Connect authentication metadata.', script)
        self.assertIn('/usr/bin/xcrun altool', script)
        self.assertIn('-f "$ipa"', script)
        self.assertNotIn('@env:', script)
        self.assertNotIn('--auth-string', script)
        self.assertNotIn('--p8-file-path', script)
        self.assertNotIn('destination\' "$export_options")" == "upload"', script)
        self.assertIn('/bin/mkdir -- "$archive_parent_path"', script)
        self.assertIn('release_lock_dir="$common_dir/xjie-testflight-release.lock"', script)
        self.assertIn("trap 'cleanup_release' EXIT", script)
        self.assertIn("re.fullmatch(r\"[0-9]+(?:\\.[0-9]+)*\"", script)
        self.assertIn("re.fullmatch(r\"[1-9][0-9]*\"", script)
        self.assertIn("require_canonical_direct_child", script)
        self.assertIn('require_canonical_direct_child "$archive_parent" "$archive"', script)
        self.assertIn('require_canonical_direct_child "$tmp_parent" "$export_path"', script)
        self.assertIn(
            'export_path=$(/usr/bin/mktemp -d "$tmp_parent/xjie-testflight-export.XXXXXX")',
            script,
        )
        self.assertIn('/bin/chmod 700 "$export_path"', script)
        self.assertIn('"$(/usr/bin/stat -f \'%Lp\' "$export_path")" != "700"', script)
        self.assertIn('/usr/bin/mktemp "$tmp_parent/xjie-release-entitlements.XXXXXX"', script)
        self.assertIn('/bin/unlink "$entitlements"', script)
        self.assertIn("manageAppVersionAndBuildNumber", script)

        required_distribution_fragments = (
            '== "export" ]]',
            'ipa_candidates=("$export_path"/*.ipa(N))',
            '"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"',
            'Distribution IPA verified:',
            'current_ipa_sha256=$(sha256_file "$ipa")',
            'current_distribution_cdhash=$(code_directory_hash "$distribution_app")',
            'plutil -extract beta-reports-active raw -o - "$distribution_entitlements"',
            'leaf_certificate not in developer_certificates',
            '--password "@keychain:$XJIE_ASC_PASSWORD_KEYCHAIN_ITEM"',
            '--upload-app \\\n    -f "$ipa"',
        )

        def distribution_policy_violations(candidate: str) -> list[str]:
            violations = [
                fragment for fragment in required_distribution_fragments
                if fragment not in candidate
            ]
            if any(forbidden in candidate for forbidden in ("@env:", "--auth-string", "--p8-file-path")):
                violations.append("unsafe credential transport")
            try:
                if not (
                    candidate.index("-exportArchive")
                    < candidate.index('"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"')
                    < candidate.index('/usr/bin/ditto -x -k "$ipa"')
                    < candidate.index("Distribution IPA verified:")
                    < candidate.index('if [[ "$mode" == "--archive-only" ]]')
                    < candidate.index("--upload-app")
                ):
                    violations.append("distribution verification order")
            except ValueError:
                violations.append("missing distribution stage")
            return violations

        self.assertEqual(distribution_policy_violations(script), [])
        for mutation in (
            script.replace('== "export" ]]', '== "upload" ]]', 1),
            script.replace('"$candidate_repo/tools/verify_release_bundle.py" --ipa "$ipa"', "", 1),
            script.replace('current_ipa_sha256=$(sha256_file "$ipa")', "current_ipa_sha256=$ipa_sha256", 1),
            script.replace('plutil -extract beta-reports-active raw -o - "$distribution_entitlements"', 'plutil -extract removed-beta-entitlement raw -o - "$distribution_entitlements"', 1),
            script.replace('leaf_certificate not in developer_certificates', 'False', 1),
            script.replace('--password "@keychain:$XJIE_ASC_PASSWORD_KEYCHAIN_ITEM"', '--password "@env:XJIE_ASC_PASSWORD"', 1),
            script.replace('--upload-app \\\n    -f "$ipa"', '--upload-app \\\n    -f "$archive"', 1),
        ):
            with self.subTest(distribution_mutation=mutation):
                self.assertTrue(distribution_policy_violations(mutation))
        forbidden_git_environment = (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_CONFIG",
            "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_SYSTEM",
            "GIT_CONFIG_COUNT",
            "GIT_CEILING_DIRECTORIES",
        )
        clean_environment = {
            key: value for key, value in os.environ.items()
            if key not in forbidden_git_environment
            and not key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_"))
        }
        for variable in forbidden_git_environment:
            with self.subTest(variable=variable):
                environment = dict(clean_environment)
                environment[variable] = "/tmp/untrusted-release-redirection"
                result = subprocess.run(
                    ["/bin/zsh", "-f", "scripts/release_testflight.sh", "--archive-only"],
                    cwd=REPO_ROOT,
                    env=environment,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"Refusing release with repository-redirecting environment: {variable}",
                    result.stdout,
                )
        for variable in ("HTTPS_PROXY", "http_proxy", "ALL_PROXY", "SSL_CERT_FILE"):
            with self.subTest(variable=variable):
                environment = dict(clean_environment)
                environment[variable] = "/tmp/untrusted-network-redirection"
                result = subprocess.run(
                    ["/bin/zsh", "-f", "scripts/release_testflight.sh", "--archive-only"],
                    cwd=REPO_ROOT,
                    env=environment,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"Refusing release with proxy or custom-CA environment: {variable}",
                    result.stdout,
                )
        auth_environment = {
            "HOME": os.environ.get("HOME", "/var/empty"),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8",
        }
        for authentication, expected_message in (
            ({}, "Upload requires one complete App Store Connect authentication method."),
            ({"XJIE_ASC_API_KEY_ID": "ABCDEFGHIJ"}, "Upload requires one complete App Store Connect authentication method."),
            (
                {
                    "XJIE_ASC_API_KEY_ID": "ABCDEFGHIJ",
                    "XJIE_ASC_API_ISSUER_ID": "01234567-89ab-cdef-0123-456789abcdef",
                    "XJIE_ASC_USERNAME": "qa@example.invalid",
                    "XJIE_ASC_PASSWORD_KEYCHAIN_ITEM": "xjie-testflight",
                },
                "Refusing mixed App Store Connect authentication metadata.",
            ),
        ):
            with self.subTest(authentication=authentication):
                result = subprocess.run(
                    ["/bin/zsh", "-f", "scripts/release_testflight.sh", "--upload"],
                    cwd=REPO_ROOT,
                    env={**auth_environment, **authentication},
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_message, result.stdout)
        self.assertIn(
            "xcodebuild archive",
            registry["commands"]["ios_release_build"],
        )
        self.assertIn(
            "-destination 'generic/platform=iOS'",
            registry["commands"]["ios_release_build"],
        )
        self.assertIn(
            "tools/verify_release_bundle.py /tmp/xjie-quality-release.xcarchive/Products/Applications/Xjie.app",
            registry["commands"]["ios_release_build"],
        )

    def test_hooks_never_use_verify_bypass(self):
        hooks = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((REPO_ROOT / ".githooks").iterdir())
            if path.is_file()
        )
        self.assertIn("regression_guard.py", hooks)
        self.assertNotIn("\n  python3 tools/regression_guard.py", hooks)
        self.assertNotIn("\n    python3 tools/regression_guard.py", hooks)
        self.assertGreaterEqual(
            hooks.count("/usr/bin/python3 -I tools/regression_guard.py"),
            4,
        )
        self.assertNotIn("--no-verify", hooks)

    def test_pre_push_allows_candidate_push_before_release_evidence(self):
        hook = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
        self.assertIn("regression_guard.py validate", hook)
        self.assertIn("regression_guard.py check", hook)
        self.assertIn("clean_git -C \"$repo_root\" worktree add --detach", hook)
        self.assertNotIn("assert-release", hook)

    def test_hooks_validate_immutable_candidate_snapshots(self):
        pre_commit = (REPO_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
        pre_push = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
        self.assertIn("git write-tree", pre_commit)
        self.assertIn("git commit-tree", pre_commit)
        self.assertIn('clean_git -C "$repo_root" worktree add --detach --quiet "$snapshot"', pre_commit)
        self.assertIn("check --base HEAD^ --head HEAD", pre_commit)
        self.assertNotIn("check --staged", pre_commit)
        self.assertIn('clean_git -C "$repo_root" worktree add --detach --quiet "$active_snapshot" "$local_sha"', pre_push)
        self.assertIn('git merge-base "$local_sha" refs/remotes/origin/XAGE', pre_push)
        self.assertNotIn('git rev-parse "$local_sha^"', pre_push)
        self.assertIn("local_git_env=$(git rev-parse --local-env-vars)", pre_commit)
        self.assertIn("unset $local_git_env", pre_commit)
        self.assertIn("local_git_env=$(git rev-parse --local-env-vars)", pre_push)
        self.assertIn("unset $local_git_env", pre_push)

        environment = os.environ.copy()
        environment["GIT_INDEX_FILE"] = ".git/index"
        result = subprocess.run(
            ["/bin/sh", str(REPO_ROOT / ".githooks" / "pre-commit")],
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout)

    def test_ui_domain_always_includes_small_screen_gate(self):
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        ui_domain = next(
            item for item in registry["behavior_domains"] if item["id"] == "ios_ui_interaction"
        )
        self.assertIn("ios_ui_small", ui_domain["verification_commands"])

    def test_ci_runs_small_screen_before_quality_gate(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("small_device_id", workflow)
        self.assertIn("Xjie-CI-Small.xcresult", workflow)
        self.assertIn(
            "testNavigationTouchTargetsAndFormDismissalConventions",
            workflow,
        )
        self.assertIn("testMetricManagerPageAndChatKeyboardLifecycle", workflow)
        self.assertIn("deviceTypeIdentifier", workflow)
        self.assertGreaterEqual(workflow.count("validate_xcresult.py"), 2)
        self.assertIn("--expected-profile ios_all", workflow)
        self.assertIn("--expected-profile ios_ui_small", workflow)
        self.assertNotIn("--minimum-tests", workflow)
        self.assertNotIn("actions/cache", workflow)
        self.assertIn("rm -rf /tmp/Xjie-CI.xcresult /tmp/Xjie-CI-Derived", workflow)
        self.assertIn("-derivedDataPath /tmp/Xjie-CI-Small-Derived", workflow)
        self.assertIn("/bin/zsh -f -n scripts/release_testflight.sh", workflow)
        self.assertIn("Xcode 26.3\\nBuild version 17C529", workflow)
        self.assertIn("xcodebuild archive", workflow)
        self.assertIn("-destination 'generic/platform=iOS'", workflow)
        self.assertIn("/tmp/Xjie-CI-Release.xcarchive/Products/Applications/Xjie.app", workflow)
        self.assertNotIn("Release-iphonesimulator", workflow)
        self.assertIn('python3 -I tools/verify_release_bundle.py "$release_app"', workflow)
        self.assertIn("needs: [policy, backend, ios]", workflow)

    def test_required_ui_tests_use_single_deterministic_app_factory_and_audit(self):
        source_root = REPO_ROOT / "Xjie" / "XjieUITests"
        sources = {
            str(path.relative_to(source_root)): path.read_text(encoding="utf-8")
            for path in sorted(source_root.rglob("*.swift"))
        }
        combined = "\n".join(sources.values())
        support = sources["XAgeUITestCase.swift"]
        teardown_start = support.index("final override func tearDownWithError")
        launch_start = support.index("final func launchApplication", teardown_start)
        teardown = support[teardown_start:launch_start]
        quiet_window = re.search(
            r"timeIntervalSince\(stableSince\)\s*>=\s*([0-9]+(?:\.[0-9]+)?)",
            support,
        )
        self.assertEqual(
            ui_test_policy_violations(sources, enforce_support_digest=True),
            [],
        )
        self.assertIn("XAgeUITestApplicationFactory", combined)
        self.assertIn("XJIE_UI_TEST_STUB_NETWORK", combined)
        self.assertIn("app.terminate()", teardown)
        self.assertIsNotNone(quiet_window)
        self.assertGreaterEqual(float(quiet_window.group(1)), 1.5)
        self.assertNotIn("dismissKnownAlertsIfNeeded", combined)

        always_true_wait_helper = dict(sources)
        always_true_wait_helper["XAgeUITestCase.swift"] = always_true_wait_helper[
            "XAgeUITestCase.swift"
        ].replace(
            '''    final func waitUntil(timeout: TimeInterval, condition: @escaping () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return condition()
    }''',
            '''    final func waitUntil(timeout: TimeInterval, condition: @escaping () -> Bool) -> Bool {
        true
    }''',
            1,
        )
        dead_correct_network_audit = dict(sources)
        dead_correct_network_audit["XAgeUITestCase.swift"] = dead_correct_network_audit[
            "XAgeUITestCase.swift"
        ].replace(
            "    private func auditCurrentApplicationLaunch() {",
            '''    private func auditCurrentApplicationLaunch() {
        launchRequiresNetworkAudit = false
    }

    private func auditNeverCalled() {''',
            1,
        )
        for label, mutation in {
            "always-true-wait-helper": always_true_wait_helper,
            "dead-correct-network-audit": dead_correct_network_audit,
        }.items():
            with self.subTest(ui_support_mutation=label):
                self.assertTrue(
                    ui_test_policy_violations(
                        mutation,
                        enforce_support_digest=True,
                    )
                )

        app_source_root = REPO_ROOT / "Xjie" / "Xjie"
        chat_sources = {
            str(path.relative_to(app_source_root)): path.read_text(encoding="utf-8")
            for path in sorted(app_source_root.rglob("*.swift"))
        }
        chat_sources["Tests/ChatViewModelTests.swift"] = (
            REPO_ROOT / "Xjie" / "XjieTests" / "ChatViewModelTests.swift"
        ).read_text(encoding="utf-8")
        chat_sources["Tests/XAgeHighIntensityContextUITests.swift"] = (
            REPO_ROOT / "Xjie" / "XjieUITests" / "XAgeHighIntensityContextUITests.swift"
        ).read_text(encoding="utf-8")
        self.assertEqual(chat_quiescence_policy_violations(chat_sources), [])
        self.assertIn(
            'accessibilityIdentifier("xage.chat.lifecycle")',
            chat_sources["Views/Chat/ChatView.swift"],
        )
        self.assertIn('"[查看指南](https://example.com)"', combined)
        self.assertIn("app.buttons[expectedAssistantLinkLabel]", combined)

        observer_bypass = dict(chat_sources)
        observer_bypass["Views/Home/XAgeMainView.swift"] = observer_bypass[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            "scrollToBottom(proxy)",
            "withAnimation { proxy.scrollTo(Self.bottomAnchorID) }",
            1,
        )
        extra_trigger = dict(chat_sources)
        extra_trigger["Views/Home/XAgeMainView.swift"] = extra_trigger[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            "                XAgeChatInputBar(",
            """                .onChange(of: vm.messages.last?.id) { _, _ in
                    scrollToBottom(proxy)
                }

                XAgeChatInputBar(""",
            1,
        )
        outside_surface_bypass = dict(chat_sources)
        outside_source = outside_surface_bypass["Views/Home/XAgeMainView.swift"].replace(
            """                .padding(.horizontal, 24)
                .padding(.bottom, 20)
""",
            """                .padding(.horizontal, 24)
                .padding(.bottom, 20)
                .onChange(of: vm.messages.last?.id) { _, _ in
                    racyChatScroll(proxy)
                }
""",
            1,
        )
        outside_surface_bypass["Views/Home/XAgeMainView.swift"] = outside_source.replace(
            "private struct XAgeChatThinkingCard: View {",
            """private func racyChatScroll(_ proxy: ScrollViewProxy) {
    DispatchQueue.main.async {
        withAnimation { proxy.scrollTo("racy") }
    }
}

private struct XAgeChatThinkingCard: View {""",
            1,
        )
        shared_animation = dict(chat_sources)
        shared_animation["Views/Chat/ChatView.swift"] = shared_animation[
            "Views/Chat/ChatView.swift"
        ].replace(
            "withTransaction(transaction)",
            "withAnimation",
            1,
        )
        queued_xage_helper = dict(chat_sources)
        queued_xage_helper["Views/Home/XAgeMainView.swift"] = queued_xage_helper[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            "ChatAutoScroll.toBottom(Self.bottomAnchorID, using: proxy)",
            "Task { @MainActor in ChatAutoScroll.toBottom(Self.bottomAnchorID, using: proxy) }",
            1,
        )
        overload_bypass = dict(chat_sources)
        overload_bypass["Views/Chat/ChatAutoScrollOverload.swift"] = """
            import SwiftUI
            import Foundation
            extension ChatAutoScroll {
                static func toBottom(_ id: String, using proxy: ScrollViewProxy) {
                    proxy.enqueueAnimatedBottom(id)
                }
            }
            private extension ScrollViewProxy {
                func enqueueAnimatedBottom<ID: Hashable>(_ id: ID) {
                    let move: (ID, UnitPoint?) -> Void = scrollTo
                    let scheduler = DispatchQueue.main
                    scheduler.async {
                        var transaction = Transaction(animation: .easeOut(duration: 0.22))
                        transaction.disablesAnimations = false
                        withTransaction(transaction) { move(id, .bottom) }
                    }
                }
            }
        """
        transaction_shadow = dict(chat_sources)
        transaction_shadow["Views/Chat/ChatView.swift"] = transaction_shadow[
            "Views/Chat/ChatView.swift"
        ].replace("SwiftUI.withTransaction(transaction)", "withTransaction(transaction)", 1)
        transaction_shadow["Views/Chat/TransactionShadow.swift"] = """
            import SwiftUI
            import Foundation
            func withTransaction(_ transaction: Transaction, _ body: @escaping () -> Void) {
                let scheduler = DispatchQueue.main
                scheduler.async {
                    var animated = Transaction(animation: .easeOut(duration: 0.22))
                    animated.disablesAnimations = false
                    SwiftUI.withTransaction(animated) { body() }
                }
            }
        """
        queued_legacy_observer = dict(chat_sources)
        queued_legacy_observer["Views/Chat/ChatView.swift"] = queued_legacy_observer[
            "Views/Chat/ChatView.swift"
        ].replace(
            'ChatAutoScroll.toBottom("bottom", using: proxy)',
            'Task { @MainActor in ChatAutoScroll.toBottom("bottom", using: proxy) }',
            1,
        )
        deferred_xage_observer = dict(chat_sources)
        deferred_xage_observer["Views/Home/XAgeMainView.swift"] = deferred_xage_observer[
            "Views/Home/XAgeMainView.swift"
        ].replace("scrollToBottom(proxy)", "deferChatScroll(scrollToBottom(proxy))", 1)
        deferred_xage_observer["Views/Chat/DeferredChatScroll.swift"] = """
            func deferChatScroll(_ operation: @autoclosure @escaping () -> Void) {
                let work = operation
                Task { @MainActor in work() }
            }
        """
        on_change_overload = dict(chat_sources)
        on_change_overload["Views/Chat/DeferredOnChange.swift"] = """
            import SwiftUI
            extension View {
                func onChange(of value: Int, _ action: @escaping (Int, Int) -> Void) -> some View {
                    task { @MainActor in action(value, value) }
                }
            }
        """
        uikit_scroll_bypass = dict(chat_sources)
        uikit_scroll_bypass["Views/Home/XAgeMainView.swift"] = uikit_scroll_bypass[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            "scrollView.addGestureRecognizer(self.panGesture)",
            """scrollView.addGestureRecognizer(self.panGesture)
                        scrollView.setContentOffset(
                            CGPoint(x: 0, y: scrollView.contentSize.height),
                            animated: true
                        )""",
            1,
        )
        uikit_bridge_bypass = dict(chat_sources)
        uikit_bridge_bypass["Views/Chat/AdjacentScrollBridge.swift"] = """
            import SwiftUI
            struct AdjacentScrollBridge: UIViewRepresentable {
                func makeUIView(context: Context) -> UIView { UIView() }
                func updateUIView(_ uiView: UIView, context: Context) {
                    guard let scrollView = uiView.superview as? UIScrollView else { return }
                    UIView.animate {
                        scrollView.bounds.origin.y = scrollView.contentSize.height
                    }
                }
            }
        """
        scroll_position_bypass = dict(chat_sources)
        scroll_position_bypass["Views/Chat/AdjacentScrollPosition.swift"] = """
            import SwiftUI
            struct AdjacentScrollPosition: ViewModifier {
                @Binding var position: ScrollPosition
                func body(content: Content) -> some View {
                    content.scrollPosition($position)
                }
            }
        """
        always_plain = dict(chat_sources)
        always_plain["Views/Shared/MarkdownTextView.swift"] = always_plain[
            "Views/Shared/MarkdownTextView.swift"
        ].replace(
            "guard containsPotentialMarkdown(content),",
            "guard false,",
            1,
        )
        release_only_always_rich_markdown = dict(chat_sources)
        release_only_always_rich_markdown["Views/Shared/MarkdownTextView.swift"] = (
            release_only_always_rich_markdown["Views/Shared/MarkdownTextView.swift"].replace(
                "    static func render(_ content: String) -> AccessibleMarkdownRendering {",
                """    static func render(_ content: String) -> AccessibleMarkdownRendering {
        #if !DEBUG
        if let rendered = try? AttributedString(markdown: content) {
            return AccessibleMarkdownRendering(
                attributed: rendered,
                accessibilityText: String(rendered.characters),
                accessibilitySegments: accessibilitySegments(from: rendered)
            )
        }
        #endif""",
                1,
            )
        )
        narrow_delimiters = dict(chat_sources)
        narrow_delimiters["Views/Shared/MarkdownTextView.swift"] = narrow_delimiters[
            "Views/Shared/MarkdownTextView.swift"
        ].replace(
            '["*", "_", "~", "`", "[", "<", "\\\\", "&"]',
            '["**", "__", "~~", "`", "[", "<", "\\\\", "&"]',
            1,
        )
        no_autolinks = dict(chat_sources)
        no_autolinks["Views/Shared/MarkdownTextView.swift"] = no_autolinks[
            "Views/Shared/MarkdownTextView.swift"
        ].replace(
            "return content.range(of: autolinkCandidatePattern",
            "return false && content.range(of: autolinkCandidatePattern",
            1,
        )
        no_send_keyboard_dismiss = dict(chat_sources)
        no_send_keyboard_dismiss["Views/Home/XAgeMainView.swift"] = no_send_keyboard_dismiss[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            "        inputFocused.wrappedValue = false\n        XAgeKeyboard.dismiss()\n        Task { @MainActor in",
            "        inputFocused.wrappedValue = false\n        Task { @MainActor in",
            1,
        )
        animated_automation_progress = dict(chat_sources)
        animated_automation_progress["Views/Chat/ChatView.swift"] = animated_automation_progress[
            "Views/Chat/ChatView.swift"
        ].replace(
            '                Image(systemName: "ellipsis")',
            "                ProgressView()",
            1,
        )
        hardcoded_probe_focus = dict(chat_sources)
        hardcoded_probe_focus["Views/Chat/ChatView.swift"] = hardcoded_probe_focus[
            "Views/Chat/ChatView.swift"
        ].replace(
            '        let focused = inputFocused ? "true" : "false"',
            '        let focused = "false"',
            1,
        )
        inaccessible_markdown_link = dict(chat_sources)
        inaccessible_markdown_link["Views/Shared/MarkdownTextView.swift"] = (
            inaccessible_markdown_link["Views/Shared/MarkdownTextView.swift"].replace(
                "                    Link(destination: link) {",
                "                    Button(action: {}) {",
                1,
            )
        )
        duplicated_markdown_accessibility_tree = dict(chat_sources)
        duplicated_markdown_accessibility_tree["Views/Shared/MarkdownTextView.swift"] = (
            duplicated_markdown_accessibility_tree[
                "Views/Shared/MarkdownTextView.swift"
            ].replace(
                ".accessibilityRepresentation {",
                ".accessibilityChildren {",
                1,
            )
        )
        wrong_bottom_anchor = dict(chat_sources)
        wrong_bottom_anchor["Views/Home/XAgeMainView.swift"] = wrong_bottom_anchor[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            ".id(Self.bottomAnchorID)",
            '.id("wrong.chat.anchor")',
            1,
        )
        duplicate_hardcoded_xage_anchor = dict(chat_sources)
        duplicate_hardcoded_xage_anchor["Views/Home/XAgeMainView.swift"] = (
            duplicate_hardcoded_xage_anchor["Views/Home/XAgeMainView.swift"].replace(
                "                            ForEach(vm.messages) { msg in",
                """                            Color.clear.id("xage.chat.bottom")
                            ForEach(vm.messages) { msg in""",
                1,
            )
        )
        wrong_legacy_bottom_anchor = dict(chat_sources)
        wrong_legacy_bottom_anchor["Views/Chat/ChatView.swift"] = wrong_legacy_bottom_anchor[
            "Views/Chat/ChatView.swift"
        ].replace(
            '.id("bottom")',
            '.id("wrong.legacy.anchor")',
            1,
        )
        reorder_xage_bottom_anchor = dict(chat_sources)
        xage_sentinel = """                            Color.clear
                                .frame(height: 1)
                                .id(Self.bottomAnchorID)"""
        reordered_xage_source = reorder_xage_bottom_anchor[
            "Views/Home/XAgeMainView.swift"
        ].replace(xage_sentinel, "", 1)
        reorder_xage_bottom_anchor["Views/Home/XAgeMainView.swift"] = reordered_xage_source.replace(
            "                            if vm.sending {",
            xage_sentinel + "\n\n                            if vm.sending {",
            1,
        )
        reorder_legacy_bottom_anchor = dict(chat_sources)
        legacy_sentinel = '                    Color.clear.frame(height: 1).id("bottom")'
        reordered_legacy_source = reorder_legacy_bottom_anchor[
            "Views/Chat/ChatView.swift"
        ].replace(legacy_sentinel, "", 1)
        reorder_legacy_bottom_anchor["Views/Chat/ChatView.swift"] = reordered_legacy_source.replace(
            "                    if vm.sending {",
            legacy_sentinel + "\n\n                    if vm.sending {",
            1,
        )
        noop_legacy_keyboard_dismiss = dict(chat_sources)
        noop_legacy_keyboard_dismiss["Views/Chat/ChatView.swift"] = noop_legacy_keyboard_dismiss[
            "Views/Chat/ChatView.swift"
        ].replace(
            """    private static func hideKeyboard() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
        )
    }""",
            "    private static func hideKeyboard() {}",
            1,
        )
        noop_xage_keyboard_dismiss = dict(chat_sources)
        noop_xage_keyboard_dismiss["Views/Home/XAgeMainView.swift"] = noop_xage_keyboard_dismiss[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            """    static func dismiss() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
    }""",
            "    static func dismiss() {}",
            1,
        )
        bypass_legacy_composition_submit = dict(chat_sources)
        bypass_legacy_composition_submit["Views/Chat/ChatView.swift"] = (
            bypass_legacy_composition_submit["Views/Chat/ChatView.swift"].replace(
                "        textView.isScrollEnabled = true",
                "        textView.returnKeyType = .send\n        textView.isScrollEnabled = true",
                1,
            )
        )
        bypass_thinking_indicator_use = dict(chat_sources)
        bypass_thinking_indicator_use["Views/Home/XAgeMainView.swift"] = (
            bypass_thinking_indicator_use["Views/Home/XAgeMainView.swift"].replace(
                'ChatProgressIndicator(tint: Color(hex: "18AFA7"))',
                "ProgressView()",
                1,
            )
        )
        animate_assistant_orb = dict(chat_sources)
        animate_assistant_orb["Views/Home/XAgeMainView.swift"] = (
            animate_assistant_orb["Views/Home/XAgeMainView.swift"].replace(
                """                )
                .frame(width: 20, height: 20)
            Capsule()""",
                """                )
                .frame(width: 20, height: 20)
                .symbolEffect(.pulse)
            Capsule()""",
                1,
            )
        )
        adjacent_progress_bypass = dict(chat_sources)
        adjacent_progress_bypass["Views/Home/XAgeMainView.swift"] = (
            adjacent_progress_bypass["Views/Home/XAgeMainView.swift"].replace(
                "                            if vm.sending {",
                """                            if vm.sending { ProgressView() }
                            if vm.sending {""",
                1,
            )
        )
        animate_thinking_indicator_use = dict(chat_sources)
        animate_thinking_indicator_use["Views/Home/XAgeMainView.swift"] = (
            animate_thinking_indicator_use["Views/Home/XAgeMainView.swift"].replace(
                'ChatProgressIndicator(tint: Color(hex: "18AFA7"))',
                'ChatProgressIndicator(tint: Color(hex: "18AFA7")).symbolEffect(.pulse)',
                1,
            )
        )
        bypass_upload_indicator_use = dict(chat_sources)
        bypass_upload_indicator_use["Views/Home/XAgeMainView.swift"] = (
            bypass_upload_indicator_use["Views/Home/XAgeMainView.swift"].replace(
                'ChatProgressIndicator(tint: Color(hex: "159D8F"))',
                "ProgressView()",
                1,
            )
        )
        bypass_xage_keyboard_submit = dict(chat_sources)
        bypass_xage_keyboard_submit["Views/Home/XAgeMainView.swift"] = (
            bypass_xage_keyboard_submit["Views/Home/XAgeMainView.swift"].replace(
                "                .focused(inputFocused)\n                .accessibilityIdentifier(\"xage.chat.input\")",
                """                .focused(inputFocused)
                .submitLabel(.send)
                .onSubmit(sendCurrentInput)
                .accessibilityIdentifier("xage.chat.input")""",
                1,
            )
        )
        bypass_xage_send_button = dict(chat_sources)
        bypass_xage_send_button["Views/Home/XAgeMainView.swift"] = bypass_xage_send_button[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            """            Button {
                sendCurrentInput()
            } label: {
                Image(systemName: "paperplane.fill")""",
            """            Button {
                Task { await vm.sendMessage() }
            } label: {
                Image(systemName: "paperplane.fill")""",
            1,
        )
        add_xage_return_shortcut = dict(chat_sources)
        add_xage_return_shortcut["Views/Home/XAgeMainView.swift"] = add_xage_return_shortcut[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            """            .accessibilityIdentifier("xage.chat.send")
            .accessibilityLabel("发送")""",
            """            .accessibilityIdentifier("xage.chat.send")
            .accessibilityLabel("发送")
            .keyboardShortcut(.return, modifiers: [])""",
            1,
        )
        add_legacy_return_shortcut = dict(chat_sources)
        add_legacy_return_shortcut["Views/Chat/ChatView.swift"] = add_legacy_return_shortcut[
            "Views/Chat/ChatView.swift"
        ].replace(
            """            .disabled(!canSend)
            .accessibilityLabel("发送")""",
            """            .disabled(!canSend)
            .accessibilityLabel("发送")
            .keyboardShortcut(.defaultAction)""",
            1,
        )
        animate_xage_message_layout = dict(chat_sources)
        animate_xage_message_layout["Views/Home/XAgeMainView.swift"] = animate_xage_message_layout[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            """                            Color.clear
                                .frame(height: 1)
                                .id(Self.bottomAnchorID)
                        }
                        .padding(.horizontal, 24)""",
            """                            Color.clear
                                .frame(height: 1)
                                .id(Self.bottomAnchorID)
                        }
                        .animation(.easeOut(duration: 0.22), value: vm.messages.count)
                        .padding(.horizontal, 24)""",
            1,
        )
        release_only_xage_animation = dict(chat_sources)
        release_only_xage_animation["Views/Home/XAgeMainView.swift"] = (
            release_only_xage_animation["Views/Home/XAgeMainView.swift"].replace(
                "                        .padding(.bottom, 96)",
                """                        .modifier(ChatReleaseAnimationModifier(value: vm.messages.count))
                        .padding(.bottom, 96)""",
                1,
            )
        )
        release_only_xage_animation["Views/Chat/ChatReleaseAnimationModifier.swift"] = """
            import SwiftUI
            struct ChatReleaseAnimationModifier: ViewModifier {
                let value: Int
                @ViewBuilder func body(content: Content) -> some View {
                    #if DEBUG
                    content
                    #else
                    content.animation(.easeOut, value: value)
                    #endif
                }
            }
        """
        release_only_assistant_ax_hidden = dict(chat_sources)
        release_only_assistant_ax_hidden["Views/Home/XAgeMainView.swift"] = (
            release_only_assistant_ax_hidden["Views/Home/XAgeMainView.swift"].replace(
                """                                )
                                .id(msg.id)""",
                """                                )
                                .modifier(ChatReleaseAXModifier())
                                .id(msg.id)""",
                1,
            )
        )
        release_only_assistant_ax_hidden["Views/Chat/ChatReleaseAXModifier.swift"] = """
            import SwiftUI
            struct ChatReleaseAXModifier: ViewModifier {
                @ViewBuilder func body(content: Content) -> some View {
                    #if DEBUG
                    content
                    #else
                    content.accessibilityHidden(true)
                    #endif
                }
            }
        """
        automation_only_assistant_ax_visible = dict(chat_sources)
        automation_only_assistant_ax_visible["Views/Home/XAgeMainView.swift"] = (
            automation_only_assistant_ax_visible["Views/Home/XAgeMainView.swift"].replace(
                """                                )
                                .id(msg.id)""",
                """                                )
                                .modifier(ChatUITestOnlyAXModifier())
                                .id(msg.id)""",
                1,
            )
        )
        automation_only_assistant_ax_visible["Views/Chat/ChatUITestOnlyAXModifier.swift"] = """
            import SwiftUI
            struct ChatUITestOnlyAXModifier: ViewModifier {
                @ViewBuilder func body(content: Content) -> some View {
                    if UIAutomationMode.isEnabled(arguments: ProcessInfo.processInfo.arguments) {
                        content
                    } else {
                        content.accessibilityHidden(true)
                    }
                }
            }
        """
        outer_xage_test_flag_ax_hidden = dict(chat_sources)
        outer_xage_test_flag_ax_hidden["Views/Home/XAgeMainView.swift"] = (
            outer_xage_test_flag_ax_hidden["Views/Home/XAgeMainView.swift"].replace(
                """                        XAgeConversationSurface(
                            selectedSection: $selectedSection,
                            historyRequest: chatHistoryRequest
                        )
                            .tag(XAgeTopSection.chat)""",
                """                        XAgeConversationSurface(
                            selectedSection: $selectedSection,
                            historyRequest: chatHistoryRequest
                        )
                            .tag(XAgeTopSection.chat)
                            .modifier(ChatTestFlagAXModifier())""",
                1,
            )
        )
        outer_xage_test_flag_ax_hidden["Views/Chat/ChatTestFlagAXModifier.swift"] = """
            import SwiftUI
            struct ChatTestFlagAXModifier: ViewModifier {
                @ViewBuilder func body(content: Content) -> some View {
                    if ProcessInfo.processInfo.arguments.contains("XJIE_UI_TEST_STUB_NETWORK") {
                        content
                    } else {
                        content.accessibilityHidden(true)
                    }
                }
            }
        """
        outer_legacy_test_flag_ax_hidden = dict(chat_sources)
        outer_legacy_test_flag_ax_hidden["Views/Home/HomeView.swift"] = (
            outer_legacy_test_flag_ax_hidden["Views/Home/HomeView.swift"].replace(
                "NavigationLink(destination: ChatView(isEmbedded: true)) {",
                "NavigationLink(destination: ChatView(isEmbedded: true).modifier(ChatTestFlagAXModifier())) {",
                1,
            )
        )
        outer_legacy_test_flag_ax_hidden["Views/Chat/ChatTestFlagAXModifier.swift"] = """
            import SwiftUI
            struct ChatTestFlagAXModifier: ViewModifier {
                @ViewBuilder func body(content: Content) -> some View {
                    if ProcessInfo.processInfo.arguments.contains("XJIE_UI_TEST_STUB_NETWORK") {
                        content
                    } else {
                        content.accessibilityHidden(true)
                    }
                }
            }
        """
        move_existing_debug_pair_around_xage_consumers = dict(chat_sources)
        moved_debug_source = move_existing_debug_pair_around_xage_consumers[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            '''    #if DEBUG
    private static let resetArgument = "XJIE_UI_TEST_RESET_DATA_CARDS"
    private static var didApplyUITestReset = false
    #endif
''',
            "",
            1,
        )
        moved_debug_source = moved_debug_source.replace(
            "                        XAgeConversationSurface(",
            """                        #if DEBUG
                        XAgeConversationSurface(""",
            1,
        )
        move_existing_debug_pair_around_xage_consumers["Views/Home/XAgeMainView.swift"] = (
            moved_debug_source.replace(
                "                            .tag(XAgeTopSection.xAge)",
                """                            .tag(XAgeTopSection.xAge)
                        #endif""",
                1,
            )
        )
        outer_xage_group_test_flag_hidden = dict(chat_sources)
        xage_consumer_pair = '''                        XAgeConversationSurface(
                            selectedSection: $selectedSection,
                            historyRequest: chatHistoryRequest
                        )
                            .tag(XAgeTopSection.chat)

                        XAgeHealthspanView(
                            selectedSection: $selectedSection,
                            infoRequest: xAgeInfoRequest,
                            scores: compositeScores
                        )
                            .tag(XAgeTopSection.xAge)'''
        outer_xage_group_test_flag_hidden["Views/Home/XAgeMainView.swift"] = (
            outer_xage_group_test_flag_hidden["Views/Home/XAgeMainView.swift"].replace(
                xage_consumer_pair,
                "                        Group {\n"
                + xage_consumer_pair
                + '''
                        }
                        .accessibilityHidden(
                            !CommandLine.arguments.contains("XJIE_" + "UI_TEST_STUB_NETWORK")
                        )''',
                1,
            )
        )
        outer_legacy_group_test_flag_hidden = dict(chat_sources)
        legacy_consumer_pair = '''            NavigationLink(destination: ChatView(isEmbedded: true)) {
                quickItem(icon: "bubble.left.and.text.bubble.right", label: "助手小捷")
            }
            NavigationLink(destination: HealthView()) {
                quickItem(icon: "list.clipboard", label: "健康数据")
            }'''
        outer_legacy_group_test_flag_hidden["Views/Home/HomeView.swift"] = (
            outer_legacy_group_test_flag_hidden["Views/Home/HomeView.swift"].replace(
                legacy_consumer_pair,
                "            Group {\n"
                + legacy_consumer_pair
                + '''
            }
            .accessibilityHidden(
                !CommandLine.arguments.contains("XJIE_" + "UI_TEST_STUB_NETWORK")
            )''',
                1,
            )
        )
        outside_input_return_shortcut = dict(chat_sources)
        outside_input_return_shortcut["Views/Home/XAgeMainView.swift"] = (
            outside_input_return_shortcut["Views/Home/XAgeMainView.swift"].replace(
                "                XAgeChatInputBar(",
                """                Button(action: { sendStarterPrompt(vm.inputValue) }) {
                    EmptyView()
                }
                .keyboardShortcut(.return, modifiers: [])

                XAgeChatInputBar(""",
                1,
            )
        )
        caller_level_on_submit = dict(chat_sources)
        caller_level_on_submit["Views/Home/XAgeMainView.swift"] = (
            caller_level_on_submit["Views/Home/XAgeMainView.swift"].replace(
                """                .padding(.horizontal, 24)
                .padding(.bottom, 20)""",
                """                .padding(.horizontal, 24)
                .padding(.bottom, 20)
                .onSubmit { sendStarterPrompt(vm.inputValue) }""",
                1,
            )
        )
        bypass_assistant_markdown_consumer = dict(chat_sources)
        bypass_assistant_markdown_consumer["Views/Home/XAgeMainView.swift"] = (
            bypass_assistant_markdown_consumer["Views/Home/XAgeMainView.swift"].replace(
                "AccessibleMarkdownText(text: message.content)",
                "Text(verbatim: message.content)",
                1,
            )
        )
        hide_assistant_markdown_consumer = dict(chat_sources)
        hide_assistant_markdown_consumer["Views/Home/XAgeMainView.swift"] = (
            hide_assistant_markdown_consumer["Views/Home/XAgeMainView.swift"].replace(
                """                        AccessibleMarkdownText(text: message.content)
                    }
                }
                    .font""",
                """                        AccessibleMarkdownText(text: message.content)
                    }
                }
                    .accessibilityHidden(!isUser)
                    .font""",
                1,
            )
        )
        bypass_shared_markdown_consumer = dict(chat_sources)
        bypass_shared_markdown_consumer["Views/Shared/MarkdownTextView.swift"] = (
            bypass_shared_markdown_consumer["Views/Shared/MarkdownTextView.swift"].replace(
                "AccessibleMarkdownText(text: text)",
                "Text(verbatim: text)",
                1,
            )
        )
        bypass_ui_terminal_assertion = dict(chat_sources)
        bypass_ui_terminal_assertion["Tests/XAgeHighIntensityContextUITests.swift"] = (
            bypass_ui_terminal_assertion["Tests/XAgeHighIntensityContextUITests.swift"].replace(
                '        assertChatSettled(expectedMessageCount: expectedMessageCount, context: "发送问题：\\(text)")',
                "        RunLoop.current.run(until: Date().addingTimeInterval(0.1))",
                1,
            )
        )
        weaken_ui_link_action_assertion = dict(chat_sources)
        weaken_ui_link_action_assertion["Tests/XAgeHighIntensityContextUITests.swift"] = (
            weaken_ui_link_action_assertion["Tests/XAgeHighIntensityContextUITests.swift"].replace(
                '            XCTAssertTrue(link.isHittable, "富文本助手链接必须可以由用户激活")',
                "            _ = link.isHittable",
                1,
            )
        )
        remove_keyboard_submit_coverage = dict(chat_sources)
        remove_keyboard_submit_coverage["Tests/XAgeHighIntensityContextUITests.swift"] = (
            remove_keyboard_submit_coverage["Tests/XAgeHighIntensityContextUITests.swift"].replace(
                "        input.typeText(multilineContinuation)",
                "        _ = multilineContinuation",
                1,
            )
        )
        remove_multiline_terminal_assertion = dict(chat_sources)
        remove_multiline_terminal_assertion["Tests/XAgeHighIntensityContextUITests.swift"] = (
            remove_multiline_terminal_assertion["Tests/XAgeHighIntensityContextUITests.swift"].replace(
                '        assertChatSettled(expectedMessageCount: 2, context: "小屏长问题发送")',
                "        RunLoop.current.run(until: Date().addingTimeInterval(0.1))",
                1,
            )
        )
        bypass_legacy_keyboard_submit = dict(chat_sources)
        bypass_legacy_keyboard_submit["Views/Chat/ChatView.swift"] = bypass_legacy_keyboard_submit[
            "Views/Chat/ChatView.swift"
        ].replace(
            "                isEnabled: !vm.sending\n            )",
            """                isEnabled: !vm.sending,
                onSubmit: sendCurrentInput
            )""",
            1,
        )
        bypass_legacy_send_button = dict(chat_sources)
        bypass_legacy_send_button["Views/Chat/ChatView.swift"] = bypass_legacy_send_button[
            "Views/Chat/ChatView.swift"
        ].replace(
            """            Button {
                sendCurrentInput()
            } label: {
                Image(systemName: "paperplane.fill")""",
            """            Button {
                Task { await vm.sendMessage() }
            } label: {
                Image(systemName: "paperplane.fill")""",
            1,
        )
        remove_legacy_send_dismiss = dict(chat_sources)
        remove_legacy_send_dismiss["Views/Chat/ChatView.swift"] = remove_legacy_send_dismiss[
            "Views/Chat/ChatView.swift"
        ].replace(
            "        Self.hideKeyboard()\n        Task { @MainActor in",
            "        Task { @MainActor in",
            1,
        )
        remove_legacy_initial_prompt_dismiss = dict(chat_sources)
        remove_legacy_initial_prompt_dismiss["Views/Chat/ChatView.swift"] = (
            remove_legacy_initial_prompt_dismiss["Views/Chat/ChatView.swift"].replace(
                "        Self.hideKeyboard()\n        Task { @MainActor in\n            await vm.startPlanConversation(prompt: prompt)",
                "        Task { @MainActor in\n            await vm.startPlanConversation(prompt: prompt)",
                1,
            )
        )
        add_outbound_method_alias = dict(chat_sources)
        add_outbound_method_alias["Views/Chat/ChatView.swift"] = add_outbound_method_alias[
            "Views/Chat/ChatView.swift"
        ].replace(
            "    private var inputBar: some View {\n        let canSend",
            "    private var inputBar: some View {\n        let unauditedSend = vm.sendText\n        let canSend",
            1,
        )
        add_adjacent_outbound_sender = dict(chat_sources)
        add_adjacent_outbound_sender["Views/Chat/AdjacentSender.swift"] = """
            import Foundation
            func sendOutsideAuditedSurfaces(_ vm: ChatViewModel) async {
                await vm.sendText("unexpected")
            }
        """
        remove_xage_starter_dismiss = dict(chat_sources)
        remove_xage_starter_dismiss["Views/Home/XAgeMainView.swift"] = remove_xage_starter_dismiss[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            """    private func sendStarterPrompt(_ prompt: String) {
        dismissChatKeyboard()
        Task { await vm.sendText(prompt) }
    }""",
            """    private func sendStarterPrompt(_ prompt: String) {
        Task { await vm.sendText(prompt) }
    }""",
            1,
        )
        remove_upload_followup_dismiss = dict(chat_sources)
        remove_upload_followup_dismiss["Views/Home/XAgeMainView.swift"] = (
            remove_upload_followup_dismiss["Views/Home/XAgeMainView.swift"].replace(
                '''    private func uploadReports(_ files: [XAgeReportUploadFile]) {
        guard !files.isEmpty else { return }
        inputFocused = false
        XAgeKeyboard.dismiss()
        reportUploadVM.uploadDocType = "exam"''',
                '''    private func uploadReports(_ files: [XAgeReportUploadFile]) {
        guard !files.isEmpty else { return }
        reportUploadVM.uploadDocType = "exam"''',
                1,
            )
        )
        bypass_xage_retry_wiring = dict(chat_sources)
        bypass_xage_retry_wiring["Views/Home/XAgeMainView.swift"] = bypass_xage_retry_wiring[
            "Views/Home/XAgeMainView.swift"
        ].replace(
            "onRetry: { retryMessage(id: msg.id) }",
            "onRetry: { Task { await vm.retryMessage(id: msg.id) } }",
            1,
        )
        for label, mutation in {
            "direct-observer-bypass": observer_bypass,
            "unreviewed-extra-trigger": extra_trigger,
            "outside-surface-racy-helper": outside_surface_bypass,
            "animated-shared-helper": shared_animation,
            "queued-local-helper": queued_xage_helper,
            "overloaded-bare-scroll-reference": overload_bypass,
            "shadowed-transaction-function": transaction_shadow,
            "queued-legacy-observer": queued_legacy_observer,
            "deferred-xage-autoclosure": deferred_xage_observer,
            "overloaded-on-change": on_change_overload,
            "uikit-coordinator-animated-scroll": uikit_scroll_bypass,
            "adjacent-uikit-scroll-bridge": uikit_bridge_bypass,
            "adjacent-swiftui-scroll-position": scroll_position_bypass,
            "always-plain-markdown": always_plain,
            "release-only-always-rich-markdown": release_only_always_rich_markdown,
            "narrow-markdown-delimiters": narrow_delimiters,
            "disabled-foundation-autolinks": no_autolinks,
            "remove-explicit-send-dismiss": no_send_keyboard_dismiss,
            "restore-ui-automation-progress-animation": animated_automation_progress,
            "hardcode-lifecycle-focus": hardcoded_probe_focus,
            "remove-markdown-link-action": inaccessible_markdown_link,
            "duplicate-markdown-accessibility-tree": duplicated_markdown_accessibility_tree,
            "detach-bottom-anchor-sentinel": wrong_bottom_anchor,
            "duplicate-hardcoded-xage-anchor": duplicate_hardcoded_xage_anchor,
            "detach-legacy-bottom-anchor-sentinel": wrong_legacy_bottom_anchor,
            "reorder-xage-bottom-anchor-sentinel": reorder_xage_bottom_anchor,
            "reorder-legacy-bottom-anchor-sentinel": reorder_legacy_bottom_anchor,
            "noop-legacy-keyboard-dismiss": noop_legacy_keyboard_dismiss,
            "noop-xage-keyboard-dismiss": noop_xage_keyboard_dismiss,
            "consume-legacy-return-inside-text-view": bypass_legacy_composition_submit,
            "bypass-thinking-indicator-use": bypass_thinking_indicator_use,
            "animate-assistant-orb": animate_assistant_orb,
            "adjacent-progress-bypass": adjacent_progress_bypass,
            "animate-thinking-indicator-use": animate_thinking_indicator_use,
            "bypass-upload-indicator-use": bypass_upload_indicator_use,
            "consume-xage-return-as-send": bypass_xage_keyboard_submit,
            "bypass-xage-send-button": bypass_xage_send_button,
            "add-xage-return-shortcut": add_xage_return_shortcut,
            "add-legacy-return-shortcut": add_legacy_return_shortcut,
            "animate-xage-message-layout": animate_xage_message_layout,
            "release-only-xage-animation": release_only_xage_animation,
            "release-only-assistant-ax-hidden": release_only_assistant_ax_hidden,
            "automation-only-assistant-ax-visible": automation_only_assistant_ax_visible,
            "outer-xage-test-flag-ax-hidden": outer_xage_test_flag_ax_hidden,
            "outer-legacy-test-flag-ax-hidden": outer_legacy_test_flag_ax_hidden,
            "move-existing-debug-pair-around-xage-consumers": move_existing_debug_pair_around_xage_consumers,
            "outer-xage-group-test-flag-hidden": outer_xage_group_test_flag_hidden,
            "outer-legacy-group-test-flag-hidden": outer_legacy_group_test_flag_hidden,
            "outside-input-return-shortcut": outside_input_return_shortcut,
            "caller-level-on-submit": caller_level_on_submit,
            "bypass-assistant-markdown-consumer": bypass_assistant_markdown_consumer,
            "hide-assistant-markdown-consumer": hide_assistant_markdown_consumer,
            "bypass-shared-markdown-consumer": bypass_shared_markdown_consumer,
            "remove-ui-terminal-assertion": bypass_ui_terminal_assertion,
            "weaken-ui-link-action-assertion": weaken_ui_link_action_assertion,
            "remove-multiline-return-coverage": remove_keyboard_submit_coverage,
            "remove-multiline-terminal-assertion": remove_multiline_terminal_assertion,
            "consume-legacy-return-at-input-wiring": bypass_legacy_keyboard_submit,
            "bypass-legacy-send-button": bypass_legacy_send_button,
            "remove-legacy-send-dismiss": remove_legacy_send_dismiss,
            "remove-legacy-initial-prompt-dismiss": remove_legacy_initial_prompt_dismiss,
            "add-outbound-method-alias": add_outbound_method_alias,
            "add-adjacent-outbound-sender": add_adjacent_outbound_sender,
            "remove-xage-starter-dismiss": remove_xage_starter_dismiss,
            "remove-upload-followup-dismiss": remove_upload_followup_dismiss,
            "bypass-xage-retry-wiring": bypass_xage_retry_wiring,
        }.items():
            with self.subTest(chat_quiescence_mutation=label):
                self.assertTrue(chat_quiescence_policy_violations(mutation))

    def test_nested_or_direct_ui_application_bypass_is_rejected(self):
        valid_support = {
            "XAgeUITestCase.swift": """
                class XAgeUITestCase: XCTestCase {
                    var app: XCUIApplication!
                    var didLaunchAtLeastOnce = false
                    final override func setUpWithError() throws {}
                    final override func tearDownWithError() throws {
                        auditCurrentApplicationLaunch(); app.terminate()
                    }
                    final func launchApplication() { app.launch() }
                    final func relaunchApplication() { app.terminate() }
                    func auditCurrentApplicationLaunch() {}
                }
                private enum XAgeUITestApplicationFactory {
                    static func make() -> XCUIApplication { XCUIApplication() }
                }
            """,
            "FlowTests.swift": "class FlowTests: XAgeUITestCase { func testFlow() {} }",
        }
        self.assertEqual(ui_test_policy_violations(valid_support), [])
        bypass = dict(valid_support)
        bypass["Nested/BypassTests.swift"] = """
            class BypassTests: XCTestCase {
                func testBypass() { let app = XCUIApplication ( bundleIdentifier: "bad" ); app.launch() }
            }
        """
        self.assertTrue(ui_test_policy_violations(bypass))

        lifecycle_bypass = dict(valid_support)
        lifecycle_bypass["Nested/LifecycleBypassTests.swift"] = """
            class LifecycleBypassTests: XAgeUITestCase {
                override func tearDownWithError() throws {}
                func testBypass() {
                    let candidate = XAgeUITestApplicationFactory.make(
                        resetAuth: true,
                        resetDataCards: true
                    )
                    candidate.launch()
                }
            }
        """
        violations = ui_test_policy_violations(lifecycle_bypass)
        self.assertTrue(any("lifecycle" in item for item in violations))
        self.assertTrue(any("factory" in item for item in violations))

        for rogue_source in (
            """
                class CommentBypassTests: XAgeUITestCase {
                    func testBypass() {
                        let rogue = XCUIApplication/*gap*/()
                        rogue/*gap*/.launch()
                    }
                }
            """,
            """
                class EscapedBypassTests: XAgeUITestCase {
                    func testBypass() {
                        let rogue = `XCUIApplication`/*gap*/()
                        rogue/*gap*/.`launch`/*gap*/()
                    }
                }
            """,
            'class InterpolationBypassTests: XAgeUITestCase { '
            'func testBypass() { _ = "\\(XCUIApplication().description)" } }',
            """
                class ExplicitInitBypassTests: XAgeUITestCase {
                    func testBypass() { _ = XCUIApplication.init() }
                }
            """,
            """
                class ContextualInitBypassTests: XAgeUITestCase {
                    func testBypass() { let app: XCUIApplication = .init(); _ = app }
                }
            """,
            """
                class MethodReferenceBypassTests: XAgeUITestCase {
                    func testBypass() { let start = app.launch; start() }
                }
            """,
        ):
            bypass = dict(valid_support)
            bypass["Nested/LexerBypassTests.swift"] = rogue_source
            with self.subTest(rogue_source=rogue_source):
                self.assertTrue(ui_test_policy_violations(bypass))

    def test_production_network_calls_cannot_bypass_api_service_transport(self):
        source_root = REPO_ROOT / "Xjie" / "Xjie"
        sources = {
            str(path.relative_to(source_root)): path.read_text(encoding="utf-8")
            for path in source_root.rglob("*.swift")
        }
        ui_test_root = REPO_ROOT / "Xjie" / "XjieUITests"
        sources.update({
            "XjieUITests/" + str(path.relative_to(ui_test_root)): path.read_text(encoding="utf-8")
            for path in ui_test_root.rglob("*.swift")
        })
        self.assertEqual(production_session_violations(sources), [])
        self.assertEqual(guard.deterministic_system_boundary_violations(sources), [])
        for path, source in (
            ("Views/PathBypass.swift", "let monitor = NWPathMonitor()"),
            ("Views/PathBypass.swift", "let monitor = `NWPathMonitor`/*gap*/()"),
            ("Views/PathBypass.swift", "let monitor = NWPathMonitor.init()"),
            (
                "Views/PathBypass.swift",
                "let make: () -> NWPathMonitor = { .init() }; let monitor = make()",
            ),
            ("Views/HealthBypass.swift", "let store = HKHealthStore()"),
            ("Views/HealthBypass.swift", "let store = HKHealthStore.init()"),
            (
                "Views/HealthBypass.swift",
                "let make: () -> HKHealthStore = { .init() }; let store = make()",
            ),
            (
                "Views/NotificationBypass.swift",
                "let center = `UNUserNotificationCenter`/*gap*/.`current`/*gap*/()",
            ),
            (
                "Views/NotificationBypass.swift",
                "let factory = UNUserNotificationCenter.current; let center = factory()",
            ),
        ):
            mutated = dict(sources)
            mutated[path] = source
            with self.subTest(system_boundary_path=path, source=source):
                self.assertTrue(guard.deterministic_system_boundary_violations(mutated))
        swift_paths = {
            path.relative_to(REPO_ROOT).as_posix()
            for path in REPO_ROOT.rglob("*.swift")
            if path.is_file() and ".git" not in path.relative_to(REPO_ROOT).parts
        }
        project_source = (REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj").read_text(
            encoding="utf-8"
        )
        self.assertEqual(guard.swift_source_layout_violations(swift_paths, project_source), [])
        self.assertEqual(guard.xcode_release_build_setting_violations(project_source), [])

    def test_network_boundary_rejects_whitespace_bypasses_and_second_constructor(self):
        approved = {
            "Services/APIService.swift": """
                actor APIService: APIServiceProtocol {
                    static let shared = APIService()
                    let trustedSession: URLSession = URLSession(
                        configuration: APIService.makeSessionConfiguration()
                    )
                }
            """,
            "Utils/Utils.swift": """
                enum LocalFileDataLoader {
                    static func read(_ url: URL) throws -> Data {
                        guard url.isFileURL else { throw URLError(.unsupportedURL) }
                        return try Data(contentsOf: url)
                    }
                }
            """,
            "Views/NetworkWords.swift": """
                let note = "URLSession.shared Data(contentsOf:) WKWebView NWConnection"
                let raw = #"SFSafariViewController AVPlayer(url:)"#
                // URLSession.shared and Data(contentsOf:) are documentation only here.
            """,
        }
        self.assertEqual(production_session_violations(approved), [])
        for path, source in (
            ("Views/Bypass.swift", "let session = URLSession . shared"),
            ("Views/Bypass.swift", "let session = URLSession/*gap*/.shared"),
            ("Views/Bypass.swift", "let session = URLSession ( configuration: .default )"),
            ("Views/Bypass.swift", "let session = URLSession/*gap*/(configuration: .default)"),
            ("Views/Bypass.swift", "let session = Foundation.URLSession.init(configuration: .default)"),
            (
                "Views/Bypass.swift",
                "func makeRogue() -> URLSession { .init(configuration: .default) }",
            ),
            ("Views/Bypass.swift", "func makeRogue() -> URLSession { .shared }"),
            (
                "Views/Bypass.swift",
                "final class Rogue { var session: URLSession!; init() { "
                "session = .init(configuration: .ephemeral) } }",
            ),
            ("Views/Bypass.swift", "typealias Session = URLSession\nlet session = Session(configuration: .default)"),
            ("Views/Bypass.swift", "let constructor = URLSession.self\nlet session = constructor.init(configuration: .default)"),
            ("Services/APIService.swift", approved["Services/APIService.swift"] + "\nlet second = URLSession(configuration: .ephemeral)"),
            (
                "Services/APIService.swift",
                approved["Services/APIService.swift"]
                + "\nprivate let rogue: URLSession = .init(configuration: .ephemeral)"
                + "\nfunc escape(_ request: URLRequest) async throws {"
                + " _ = try await rogue.data(for: request) }",
            ),
            (
                "Services/APIService.swift",
                approved["Services/APIService.swift"]
                + "\nfunc escape(_ request: URLRequest) async throws {"
                + " let trustedSession: URLSession = .shared;"
                + " _ = try await trustedSession.data(for: request) }",
            ),
            ("Views/Bypass.swift", "let payload = try Data(contentsOf: URL(string: \"https://example.invalid\")!)"),
            ("Views/Bypass.swift", "let payload = try Data/*gap*/(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let payload: Data = try .init(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "typealias Payload = Data\nlet payload = try Payload(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let constructor = Data.self\nlet payload = try constructor.init(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let payload = NSData(contentsOf: URL(string: \"https://example.invalid\")!)"),
            ("Views/Bypass.swift", "let payload = NSString(contentsOf: remoteURL, encoding: 4)"),
            ("Views/Bypass.swift", "let payload = NSArray(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let payload = NSDictionary(contentsOf: remoteURL)"),
            ("Views/Bypass.swift", "let payload = try String(contentsOf: URL(string: \"https://example.invalid\")!)"),
            (
                "Views/Bypass.swift",
                'let rendered = "payload: \\(try Data(contentsOf: remoteURL))"',
            ),
            (
                "Views/Bypass.swift",
                'let rendered = #"payload: \\#(AVPlayer(url: remoteURL))"#',
            ),
            (
                "Views/Bypass.swift",
                'let rendered = "\\(/[)]/.wholeMatch(in: \")\") != nil '
                '? (try await URLSession.shared.data(from: remoteURL)).0.count : 0)"',
            ),
            (
                "Views/Bypass.swift",
                "let rogue = Foundation.`URLSession`.`shared`\n"
                "_ = try await rogue.`data`(from: remoteURL)",
            ),
            ("Views/Bypass.swift", "let connection = NWConnection(host: \"example.invalid\", port: 443, using: .tls)"),
            (
                "Views/Bypass.swift",
                "let connection = nw_connection_create(endpoint, parameters)\n"
                "nw_connection_start(connection)",
            ),
            (
                "Views/Bypass.swift",
                "let createSocket = Darwin.socket\nlet openConnection = Darwin.connect",
            ),
            ("Views/Bypass.swift", "let createSocket = CFSocketCreate"),
            ("Views/Bypass.swift", "let connectSocket = CFSocketConnectToAddress"),
            (
                "Views/Bypass.swift",
                "let createPair = CFStreamCreatePairWithSocket",
            ),
            (
                "Views/Bypass.swift",
                "let ftp = CFReadStreamCreateWithFTPURL",
            ),
            ("Views/Bypass.swift", "import CFNetwork"),
            (
                "Views/Bypass.swift",
                "let APIService = ShadowAPI()\n"
                "_ = try await APIService.shared.trustedSession.data(for: request)",
            ),
            (
                "Views/Bypass.swift",
                "let (APIService, ignored) = pair\n"
                "_ = try await APIService.shared.trustedSession.data(for: request)",
            ),
            (
                "Views/Bypass.swift",
                "for (APIService, ignored) in pairs { "
                "_ = try await APIService.shared.trustedSession.data(for: request) }",
            ),
            (
                "Views/Bypass.swift",
                "func rogue(_ APIService: ShadowAPI) async throws { "
                "_ = try await APIService.shared.trustedSession.data(for: request) }",
            ),
            (
                "Views/Bypass.swift",
                "func rogue(label APIService: ShadowAPI) async throws { "
                "_ = try await APIService.shared.trustedSession.data(for: request) }",
            ),
            (
                "Views/Bypass.swift",
                "let trustedSession = APIService.shared.trustedSession\n"
                "_ = try await trustedSession.data(for: request)",
            ),
            (
                "Views/Bypass.swift",
                "let task = APIService.shared.trustedSession.webSocketTask("
                "with: URL(string: \"wss://example.invalid/socket\")!)",
            ),
            (
                "Views/Bypass.swift",
                "let task = APIService.shared.trustedSession.streamTask("
                "withHostName: \"example.invalid\", port: 443)",
            ),
            (
                "Views/Bypass.swift",
                "let task = APIService.shared.trustedSession.downloadTask("
                "with: URL(string: \"https://example.invalid/file\")!)",
            ),
            (
                "Views/Bypass.swift",
                "let task = APIService.shared.trustedSession.uploadTask("
                "with: request, from: payload)",
            ),
            ("Views/Bypass.swift", "let browser = WKWebView()"),
            ("Views/Bypass.swift", "AsyncImage(url: URL(string: \"https://example.invalid\"))"),
            ("Views/Bypass.swift", "let player = AVPlayer(url: remoteURL)"),
            ("Views/Bypass.swift", "let asset = AVURLAsset(url: remoteURL)"),
            ("Views/Bypass.swift", "let browser = SFSafariViewController(url: remoteURL)"),
            ("Views/Bypass.swift", "let connection = NSURLConnection(request: request, delegate: nil)"),
            ("Views/Bypass.swift", "let result = try await session.data(for: request)"),
            (
                "XjieUITests/Bypass.swift",
                "let result = try await APIService.shared.trustedSession.data(for: request)",
            ),
            (
                "Utils/Utils.swift",
                approved["Utils/Utils.swift"].replace(
                    "guard url.isFileURL else { throw URLError(.unsupportedURL) }",
                    "let accepted = url",
                ),
            ),
        ):
            mutated = dict(approved)
            mutated[path] = source
            with self.subTest(path=path, source=source):
                self.assertTrue(production_session_violations(mutated))

        layout_paths = {
            "Xjie/Xjie/Services/APIService.swift",
            "Xjie/Xjie/Utils/Utils.swift",
            "Xjie/XjieTests/APIServiceTests.swift",
            "Xjie/XjieUITests/XAgeUITestCase.swift",
        }

        layout_files = (
            ("A0", "B0", "APIService.swift", "Xjie/Services/APIService.swift"),
            ("A1", "B1", "Utils.swift", "Xjie/Utils/Utils.swift"),
            ("A2", "B2", "APIServiceTests.swift", "XjieTests/APIServiceTests.swift"),
            ("A3", "B3", "XAgeUITestCase.swift", "XjieUITests/XAgeUITestCase.swift"),
        )
        build_files = "\n".join(
            f"{build_id} /* {name} in Sources */ = {{isa = PBXBuildFile; "
            f"fileRef = {reference_id} /* {name} */; }};"
            for build_id, reference_id, name, _path in layout_files
        )
        references = "\n".join(
            f"{reference_id} /* {name} */ = {{isa = PBXFileReference; "
            f"path = {path}; sourceTree = SOURCE_ROOT; }};"
            for _build_id, reference_id, name, path in layout_files
        )

        def source_phase(phase_id: str, build_ids: tuple[str, ...]) -> str:
            entries = "\n".join(f"{build_id} /* retained comment in Sources */," for build_id in build_ids)
            return f"""
                {phase_id} /* Sources */ = {{
                    isa = PBXSourcesBuildPhase;
                    files = (
                        {entries}
                    );
                }};
            """

        layout_project = f"""
            objects = {{
            /* Begin PBXBuildFile section */
            {build_files}
            /* End PBXBuildFile section */
            /* Begin PBXFileReference section */
            {references}
            /* End PBXFileReference section */
            /* Begin PBXGroup section */
            EROOT = {{
                isa = PBXGroup;
                children = (
                );
                sourceTree = "<group>";
            }};
            /* End PBXGroup section */
            H10001 = {{
                isa = PBXProject;
                buildConfigurationList = G10001;
                mainGroup = EROOT;
                targets = (F10001, F20001, F300000000000000000001,);
            }};
            J10001 = {{
                isa = PBXContainerItemProxy;
                containerPortal = H10001;
                proxyType = 1;
                remoteGlobalIDString = F10001;
            }};
            J300000000000000000001 = {{
                isa = PBXContainerItemProxy;
                containerPortal = H10001;
                proxyType = 1;
                remoteGlobalIDString = F10001;
            }};
            K10001 = {{isa = PBXTargetDependency; target = F10001; targetProxy = J10001;}};
            K300000000000000000001 = {{isa = PBXTargetDependency; target = F10001; targetProxy = J300000000000000000001;}};
            /* Begin PBXNativeTarget section */
            F10001 /* Xjie */ = {{
                isa = PBXNativeTarget;
                buildConfigurationList = G10003;
                buildPhases = (
                    F10002 /* Sources */,
                    D10001 /* Frameworks */,
                    F10003 /* Resources */,
                );
                buildRules = (
                );
                dependencies = (
                );
            }};
            F20001 /* XjieTests */ = {{
                isa = PBXNativeTarget;
                buildConfigurationList = G20003;
                buildPhases = (
                    F20002 /* Sources */,
                    D20001 /* Frameworks */,
                );
                buildRules = (
                );
                dependencies = (
                    K10001 /* PBXTargetDependency */,
                );
            }};
            F300000000000000000001 /* XjieUITests */ = {{
                isa = PBXNativeTarget;
                buildConfigurationList = G300000000000000000003;
                buildPhases = (
                    F300000000000000000002 /* Sources */,
                    D300000000000000000001 /* Frameworks */,
                );
                buildRules = (
                );
                dependencies = (
                    K300000000000000000001 /* PBXTargetDependency */,
                );
            }};
            /* End PBXNativeTarget section */
            D10001 = {{isa = PBXFrameworksBuildPhase; files = ();}};
            F10003 = {{isa = PBXResourcesBuildPhase;}};
            D20001 = {{isa = PBXFrameworksBuildPhase; files = ();}};
            D300000000000000000001 = {{isa = PBXFrameworksBuildPhase; files = ();}};
            /* Begin PBXSourcesBuildPhase section */
            {source_phase("F10002", ("A0", "A1"))}
            {source_phase("F20002", ("A2",))}
            {source_phase("F300000000000000000002", ("A3",))}
            /* End PBXSourcesBuildPhase section */
            }};
        """
        self.assertEqual(guard.swift_source_layout_violations(layout_paths, layout_project), [])
        self.assertTrue(guard.swift_source_layout_violations(
            layout_paths | {"Sources/Bypass.swift"},
            layout_project,
        ))
        foreign_target = layout_project.replace(
            "A1 /* retained comment in Sources */",
            "A2 /* retained comment in Sources */",
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, foreign_target))
        forged_comment = layout_project.replace(
            "fileRef = B1 /* Utils.swift */",
            "fileRef = B2 /* Utils.swift */",
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, forged_comment))
        swapped_target_phase = layout_project.replace(
            "F10002 /* Sources */,",
            "F20002 /* Sources */,",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, swapped_target_phase)
        )
        hidden_source_phase = layout_project.replace(
            "D10001 = {isa = PBXFrameworksBuildPhase; files = ();};",
            "D10001 = {isa = PBXFrameworksBuildPhase; files = ();};\n"
            "FEVIL = {isa = PBXSourcesBuildPhase; files = (A2,);};",
            1,
        ).replace(
            "D10001 /* Frameworks */,",
            "D10001 /* Frameworks */,\nFEVIL /* harmless-looking phase */,",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, hidden_source_phase)
        )
        swapped_configuration = layout_project.replace(
            "buildConfigurationList = G10003;",
            "buildConfigurationList = G20003;",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, swapped_configuration)
        )
        linked_framework = layout_project.replace(
            "D10001 = {isa = PBXFrameworksBuildPhase; files = ();};",
            "D10001 = {isa = PBXFrameworksBuildPhase; files = (EVIL,);};",
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, linked_framework))
        package_product = layout_project.replace(
            "buildRules = (",
            "packageProductDependencies = (EVIL_PACKAGE,);\n                buildRules = (",
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, package_product))
        package_reference = layout_project + "\npackageReferences = (EVIL_PACKAGE);"
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, package_reference))

        valid_app_phase = source_phase("F10002", ("A0", "A1"))
        reordered_app_phase = valid_app_phase.replace(
            "isa = PBXSourcesBuildPhase;",
            "buildActionMask = 2147483647;\n                    isa = PBXSourcesBuildPhase;",
            1,
        ).replace("A1 /* retained comment in Sources */,", "", 1)
        comment_spoof = layout_project.replace(
            valid_app_phase,
            "/*" + valid_app_phase + "*/\n" + reordered_app_phase,
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, comment_spoof))
        multiline_string_spoof = layout_project.replace(
            valid_app_phase,
            'FAKESTRING = "' + valid_app_phase + '";\n' + reordered_app_phase,
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, multiline_string_spoof)
        )
        single_line_string_spoof = layout_project.replace(
            "buildConfigurationList = G10003;",
            'note = "buildConfigurationList = G10003;";\n'
            "                buildConfigurationList = G20003;",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, single_line_string_spoof)
        )
        duplicate_target_configuration = layout_project.replace(
            "buildConfigurationList = G10003;",
            "buildConfigurationList = G10003;\n"
            "                buildConfigurationList = G20003;",
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(
                layout_paths, duplicate_target_configuration
            )
        )
        duplicate_source_files = layout_project.replace(
            valid_app_phase,
            valid_app_phase.replace(
                "                    );",
                "                    );\n                    files = ();",
                1,
            ),
            1,
        )
        self.assertTrue(
            guard.swift_source_layout_violations(layout_paths, duplicate_source_files)
        )
        hidden_aggregate = layout_project.replace(
            "F10001, F20001, F300000000000000000001,",
            "F10001, F20001, F300000000000000000001, EVILT,",
            1,
        ).replace(
            "target = F10001; targetProxy = J10001;",
            "target = EVILT; targetProxy = J10001;",
            1,
        ).replace(
            "/* End PBXSourcesBuildPhase section */",
            """
            EVILP = { files = (); shellScript = __XJIE_SAFE_TOKEN__; isa = PBXShellScriptBuildPhase; };
            EVILT = {
                buildConfigurationList = G10003;
                buildPhases = (EVILP,);
                buildRules = ();
                dependencies = ();
                isa = PBXAggregateTarget;
            };
            /* End PBXSourcesBuildPhase section */
            """,
            1,
        )
        self.assertTrue(guard.swift_source_layout_violations(layout_paths, hidden_aggregate))

        with tempfile.TemporaryDirectory() as filesystem_temp:
            repository = Path(filesystem_temp) / "repo"
            app_root = repository / "Xjie" / "Xjie"
            unit_root = repository / "Xjie" / "XjieTests"
            ui_root = repository / "Xjie" / "XjieUITests"
            project_file = repository / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj"
            scheme_file = (
                repository / "Xjie" / "Xjie.xcodeproj" / "xcshareddata"
                / "xcschemes" / "Xjie.xcscheme"
            )
            for directory in (app_root, unit_root, ui_root, project_file.parent, scheme_file.parent):
                directory.mkdir(parents=True, exist_ok=True)
            (app_root / "App.swift").write_text("struct App {}", encoding="utf-8")
            project_file.write_text("{}", encoding="utf-8")
            scheme_file.write_text("<Scheme/>", encoding="utf-8")
            self.assertEqual(
                guard.repository_filesystem_identity_violations(
                    repository,
                    (app_root, unit_root, ui_root),
                    (project_file, scheme_file),
                ),
                [],
            )
            outside = Path(filesystem_temp) / "outside"
            outside.mkdir()
            (outside / "Bypass.swift").write_text("struct Bypass {}", encoding="utf-8")
            (app_root / "LinkedSources").symlink_to(outside, target_is_directory=True)
            self.assertTrue(
                guard.repository_filesystem_identity_violations(
                    repository,
                    (app_root, unit_root, ui_root),
                    (project_file, scheme_file),
                )
            )
            (app_root / "LinkedSources").unlink()
            outside_plist = Path(filesystem_temp) / "outside.plist"
            outside_plist.write_text("{}", encoding="utf-8")
            (app_root / "Info.plist").symlink_to(outside_plist)
            self.assertTrue(
                guard.repository_filesystem_identity_violations(
                    repository,
                    (app_root, unit_root, ui_root),
                    (project_file, scheme_file),
                )
            )

    def test_release_commands_validate_executed_xcresult_tests(self):
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        for command_id, profile in (
            ("ios_unit", "ios_unit"),
            ("ios_ui_full", "ios_ui_full"),
            ("ios_ui_small", "ios_ui_small"),
        ):
            command = registry["commands"][command_id]
            self.assertIn("-resultBundlePath", command)
            self.assertIn("validate_xcresult.py", command)
            self.assertIn(f"--expected-profile {profile}", command)
            self.assertNotIn("--minimum-tests", command)

    def test_release_export_options_and_production_api_are_pinned(self):
        script = (REPO_ROOT / "scripts" / "release_testflight.sh").read_text(encoding="utf-8")
        self.assertIn('export_options="$candidate_repo/scripts/ExportOptions-TestFlight.plist"', script)
        self.assertIn('[[ "$api_base" == "https://www.jianjieaitech.com" ]]', script)
        self.assertIn("--release-build-settings-stdin", script)
        self.assertLess(
            script.index("--release-build-settings-stdin"),
            script.index("  clean archive "),
        )
        with (REPO_ROOT / "scripts" / "ExportOptions-TestFlight.plist").open("rb") as handle:
            options = plistlib.load(handle)
        self.assertEqual(options["destination"], "export")
        self.assertEqual(options["method"], "app-store-connect")
        self.assertEqual(options["teamID"], "52BRF299Y7")
        self.assertIs(options["manageAppVersionAndBuildNumber"], False)

        project = (REPO_ROOT / "Xjie" / "Xjie.xcodeproj" / "project.pbxproj").read_text(
            encoding="utf-8"
        )
        self.assertEqual(guard.xcode_release_build_setting_violations(project), [])

        for forbidden in (
            "EXCLUDED_SOURCE_FILE_NAMES = APIService.swift;",
            "INCLUDED_SOURCE_FILE_NAMES = SafeOnly.swift;",
            "COMPILER_FLAGS = \"-DDEBUG\";",
            "baseConfigurationReference = EVIL;",
            'OTHER_LDFLAGS = "-force_load /tmp/rogue.a";',
            "SWIFT_OBJC_BRIDGING_HEADER = /tmp/rogue.h;",
            "SWIFT_INCLUDE_PATHS = /tmp/rogue-modules;",
            "LIBRARY_SEARCH_PATHS = /tmp/rogue-libraries;",
            "FRAMEWORK_SEARCH_PATHS = /tmp/rogue-frameworks;",
        ):
            with self.subTest(forbidden_project_setting=forbidden):
                self.assertTrue(
                    guard.xcode_release_build_setting_violations(project + "\n" + forbidden)
                )

        release_prefix, release_body = project.split("G10006 /* Release */", 1)
        for forbidden in (
            'SWIFT_ACTIVE_COMPILATION_CONDITIONS = "$(inherited) DEBUG";',
            'OTHER_SWIFT_FLAGS = "-DDEBUG";',
            'GCC_PREPROCESSOR_DEFINITIONS = "DEBUG=1";',
            "ENABLE_TESTABILITY = YES;",
            'EXCLUDED_ARCHS[sdk=iphoneos*] = arm64;',
            'OTHER_CFLAGS = "-include /tmp/rogue.h";',
            'OTHER_CPLUSPLUSFLAGS = "-include /tmp/rogue.hpp";',
        ):
            with self.subTest(forbidden_release_setting=forbidden):
                mutated_release = release_body.replace(
                    "buildSettings = {",
                    "buildSettings = {\n\t\t\t\t" + forbidden,
                    1,
                )
                self.assertTrue(
                    guard.xcode_release_build_setting_violations(
                        release_prefix + "G10006 /* Release */" + mutated_release
                    )
                )

        swapped_list = project.replace(
            "G10005 /* Debug */,\n\t\t\t\tG10006 /* Release */",
            "G10006 /* Release */,\n\t\t\t\tG10005 /* Debug */",
            1,
        )
        self.assertTrue(guard.xcode_release_build_setting_violations(swapped_list))

        scheme = (
            REPO_ROOT
            / "Xjie"
            / "Xjie.xcodeproj"
            / "xcshareddata"
            / "xcschemes"
            / "Xjie.xcscheme"
        ).read_text(encoding="utf-8")
        self.assertEqual(guard.xcode_scheme_violations(scheme), [])
        for mutated_scheme in (
            scheme.replace(
                "<BuildActionEntries>",
                '<PreActions><ExecutionAction scriptText="exit 0"/></PreActions>'
                "<BuildActionEntries>",
                1,
            ),
            scheme.replace(
                '<ArchiveAction\n      buildConfiguration = "Release"',
                '<ArchiveAction\n      buildConfiguration = "Debug"',
                1,
            ),
            scheme.replace('skipped = "NO"', 'skipped = "YES"', 1),
            scheme.replace('BlueprintIdentifier = "F20001"', 'BlueprintIdentifier = "F10001"', 1),
            scheme.replace(
                '<Testables>',
                '<TestPlans><TestPlanReference reference="container:Bypass.xctestplan"/></TestPlans><Testables>',
                1,
            ),
        ):
            with self.subTest(mutated_scheme=mutated_scheme[:120]):
                self.assertTrue(guard.xcode_scheme_violations(mutated_scheme))

    def test_diff_check_fails_on_trailing_whitespace_inside_merge_commit(self):
        registry = json.loads(
            (REPO_ROOT / "quality" / "regression_contracts.json").read_text(encoding="utf-8")
        )
        command = registry["commands"]["diff_check"]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def git(*arguments: str) -> None:
                subprocess.run(
                    ["git", *arguments], cwd=root, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )

            git("init")
            git("config", "user.email", "quality@example.invalid")
            git("config", "user.name", "Quality Gate")
            git("checkout", "-b", "main")
            (root / "base.txt").write_text("base\n", encoding="utf-8")
            git("add", "base.txt")
            git("commit", "-m", "base")
            git("checkout", "-b", "feature")
            (root / "bad.txt").write_text("trailing whitespace   \n", encoding="utf-8")
            git("add", "bad.txt")
            git("commit", "-m", "bad whitespace")
            git("checkout", "main")
            (root / "main.txt").write_text("main\n", encoding="utf-8")
            git("add", "main.txt")
            git("commit", "-m", "advance main")
            git("merge", "--no-ff", "feature", "-m", "merge feature")
            result = subprocess.run(
                ["/bin/zsh", "-f", "-c", command], cwd=root, check=False,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trailing whitespace", result.stdout)

    def test_release_signoff_template_is_pending_and_unforgeable_by_default(self):
        template = json.loads(
            (REPO_ROOT / "quality" / "release_signoffs.example.json").read_text(encoding="utf-8")
        )
        self.assertTrue(str(template["head"]).startswith("REPLACE_WITH_"))
        self.assertTrue(str(template["tree"]).startswith("REPLACE_WITH_"))
        self.assertTrue(str(template["registry_blob"]).startswith("REPLACE_WITH_"))
        for item in template["items"]:
            self.assertEqual(item["status"], "pending")
            self.assertEqual(item["tester"], "")
            self.assertEqual(item["app_version"], "REPLACE_WITH_MARKETING_VERSION")
            self.assertEqual(item["app_build"], "REPLACE_WITH_CURRENT_PROJECT_VERSION")
            self.assertTrue(str(item["evidence_reference"]).startswith("填写"))
            self.assertEqual(item["evidence_sha256"], "")

    def test_ui_automation_disables_every_notification_center_entry_point(self):
        source_root = REPO_ROOT / "Xjie" / "Xjie"
        sources = {
            str(path.relative_to(source_root)): path.read_text(encoding="utf-8")
            for path in source_root.rglob("*.swift")
        }
        self.assertEqual(guard.deterministic_system_boundary_violations(sources), [])
        scheduler = sources["Services/NotificationScheduler.swift"]
        push = sources["Services/PushNotificationManager.swift"]
        app_delegate = sources["App/AppDelegate.swift"]
        self.assertGreaterEqual(scheduler.count("guard let center = Self.notificationCenter()"), 8)
        self.assertIn("PushNotificationManager.notificationCenter", scheduler)
        self.assertIn("shouldUseNotificationCenter", push)
        self.assertIn("PushNotificationManager.notificationCenter", app_delegate)
        self.assertIn("shouldConfigureSystemServices", app_delegate)
        whitespace_bypass = dict(sources)
        whitespace_bypass["Views/NotificationBypass.swift"] = (
            "let center = `UNUserNotificationCenter`/*gap*/ . `current` ( )"
        )
        self.assertTrue(
            guard.deterministic_system_boundary_violations(whitespace_bypass)
        )


if __name__ == "__main__":
    unittest.main()
