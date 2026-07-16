from __future__ import annotations

import copy
import ast
import importlib.util
import hashlib
import io
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
import tempfile
import tarfile
import unittest
from pathlib import Path
from unittest import mock


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


def combine_manifest_xage_sources(sources: dict[str, str]) -> dict[str, str]:
    """Present split XAGE sources to the legacy static policy as one ordered unit."""

    manifest = json.loads(
        (REPO_ROOT / "quality" / "swift_source_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    source_prefix = "Xjie/Xjie/"
    relative_paths: list[str] = []
    for entry in manifest["sources"]:
        path = entry["path"]
        if not path.startswith(source_prefix):
            raise AssertionError(f"XAGE manifest source is outside the app root: {path}")
        relative_paths.append(path.removeprefix(source_prefix))
    combined = dict(sources)
    ordered_sources = [combined.pop(path) for path in relative_paths]
    combined["Views/Home/XAgeMainView.swift"] = "\n".join(ordered_sources)
    return combined


def conversation_module_policy_violations(xage_raw: str) -> list[str]:
    """Keep chat shortcuts on a fixed, typed, navigation-only allowlist."""

    violations: list[str] = []
    compact = re.sub(r"\s+", "", xage_raw)
    try:
        action_start = xage_raw.index("struct XAgeConversationNavigationAction")
        action_end = xage_raw.index(
            "private struct XAgeConversationModuleOpenKey",
            action_start,
        )
        action_source = xage_raw[action_start:action_end]
        presenter_start = xage_raw.index("    private func presentConversationModule")
        presenter_end = xage_raw.index(
            "    @ViewBuilder\n    private var quickActionDestination",
            presenter_start,
        )
        presenter_source = xage_raw[presenter_start:presenter_end]
        destination_start = presenter_end
        destination_end = xage_raw.index(
            "    private func quickActionNavigation",
            destination_start,
        )
        destination_source = xage_raw[destination_start:destination_end]
        row_start = xage_raw.index("private struct XAgeConversationModuleRow")
        row_end = xage_raw.index("private struct XAgeChatThinkingCard", row_start)
        row_source = xage_raw[row_start:row_end]
    except ValueError:
        return ["XAGE conversation module registry or typed navigation structure is missing"]

    expected_actions = [
        ("meals", "膳食", "fork.knife"),
        ("reports", "报告", "doc.text.fill"),
        ("medications", "用药", "pills.fill"),
        ("profile", "画像", "person.text.rectangle.fill"),
    ]
    actual_actions = re.findall(
        r'\.init\s*\(\s*destination:\s*\.([A-Za-z]+)\s*,\s*title:\s*"([^"]+)"\s*,'
        r'\s*systemImage:\s*"([^"]+)"\s*\)',
        action_source,
    )
    expected_registry = '''static let available: [Self] = [
        .init(destination: .meals, title: "膳食", systemImage: "fork.knife"),
        .init(destination: .reports, title: "报告", systemImage: "doc.text.fill"),
        .init(destination: .medications, title: "用药", systemImage: "pills.fill"),
        .init(destination: .profile, title: "画像", systemImage: "person.text.rectangle.fill")
    ]'''
    if actual_actions != expected_actions \
            or action_source.count(".init(") != len(expected_actions) \
            or re.sub(r"\s+", "", expected_registry) not in re.sub(r"\s+", "", action_source):
        violations.append(
            "conversation modules must remain the exact four real, centrally registered destinations"
        )

    expected_draft_preserving_open = '''func open(
        preserving draft: String,
        navigate: (Self) -> Void
    ) -> String {
        navigate(self)
        return draft
    }'''
    compact_action_source = re.sub(r"[\s;]+", "", action_source)
    if re.sub(r"[\s;]+", "", expected_draft_preserving_open) not in compact_action_source \
            or action_source.count("func open(") != 1:
        violations.append(
            "conversation module opening must navigate with the typed action and return the draft unchanged"
        )
    expected_dietary_handoff = '''func handoff(preserving draft: String) -> XAgeConversationModuleHandoff {
        XAgeConversationModuleHandoff(
            action: self,
            dietaryEntry: destination == .meals ? DietaryEntryHandoff.chatCopy(draft) : nil
        )
    }'''
    if re.sub(r"\s+", "", expected_dietary_handoff) not in re.sub(
        r"\s+", "", action_source
    ) or action_source.count("func handoff(") != 1:
        violations.append(
            "conversation module handoff must copy the draft only into the typed dietary candidate path"
        )

    typed_transport_requirements = (
        "privatestructXAgeConversationModuleOpenKey:EnvironmentKey{"
        "staticletdefaultValue:(XAgeConversationModuleHandoff)->Void={_in}}",
        "varxAgeOpenConversationModule:(XAgeConversationModuleHandoff)->Void",
        "@Environment(\\.xAgeOpenConversationModule)privatevaropenConversationModule",
        ".environment(\\.xAgeOpenConversationModule){presentConversationModule($0)}",
    )
    if any(requirement not in compact for requirement in typed_transport_requirements):
        violations.append(
            "conversation module routing must remain typed from the environment to the root presenter"
        )

    expected_surface_wiring = '''XAgeConversationModuleRow { action in
                    dismissChatKeyboard()
                    showAttachmentMenu = false
                    openConversationModule(action.handoff(preserving: vm.inputValue))
                }'''
    if xage_raw.count(expected_surface_wiring) != 1:
        violations.append(
            "conversation module taps must close transient input UI and preserve the unsent draft"
        )

    compact_presenter = re.sub(r"\s+", "", presenter_source)
    expected_presenter = '''private func presentConversationModule(_ handoff: XAgeConversationModuleHandoff) {
        guard XAgeConversationNavigationAction.available.contains(handoff.action) else { return }
        conversationModuleHandoff = handoff
        presentedQuickActionID = handoff.action.id
    }'''
    if compact_presenter != re.sub(r"\s+", "", expected_presenter):
        violations.append(
            "conversation module presenter must reject every action outside the typed registry"
        )

    compact_row = re.sub(r"\s+", "", row_source)
    row_requirements = (
        "letonOpen:(XAgeConversationNavigationAction)->Void",
        "ForEach(XAgeConversationNavigationAction.available){actionin",
        "Button{onOpen(action)}label:",
        ".frame(minHeight:44)",
        ".accessibilityIdentifier(\"xage.chat.module.\\(action.id)\")",
    )
    if any(requirement not in compact_row for requirement in row_requirements):
        violations.append(
            "conversation module row must consume only the central typed registry with accessible targets"
        )

    compact_destination = re.sub(r"\s+", "", destination_source)
    destination_requirements = (
        'case"meals":quickActionNavigation{ifletentry=conversationModuleHandoff?.dietaryEntry{'
        'MealsView(initialEntry:entry)}else{MealsView()}}',
        'case"reports","profile":XAgePanelDestinationView('
        'category:presentedQuickActionID=="profile"?.profile:.reports,',
        'case"medications":XAgeMedicationManagementView(onClose:closeQuickAction)',
    )
    if any(requirement not in compact_destination for requirement in destination_requirements):
        violations.append(
            "conversation module IDs must resolve to the existing meals, reports/profile, and medication views"
        )

    assignment_values = [
        value.strip()
        for value in re.findall(
            r"\bpresentedQuickActionID\s*(?<![=])=(?!=)\s*([^\n;}]+)",
            xage_raw,
        )
    ]
    if assignment_values != ['"reports"', "identifier", "handoff.action.id", "nil"]:
        violations.append(
            "quick-action routing may not accept an arbitrary tool or module name"
        )

    expected_symbol_inventory = {
        "XAgeConversationNavigationAction.available": 2,
        "xAgeOpenConversationModule": 3,
        "presentConversationModule": 2,
        "XAgeConversationModuleRow": 2,
        "XAgeConversationModuleHandoff": 7,
        "conversationModuleHandoff": 5,
    }
    for symbol, expected_count in expected_symbol_inventory.items():
        if xage_raw.count(symbol) != expected_count:
            violations.append(
                f"conversation module control-path inventory changed: {symbol}"
            )
    return violations


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
    violations.extend(conversation_module_policy_violations(xage_raw))

    try:
        surface_declaration = (
            "private struct XAgeConversationSurface"
            if "private struct XAgeConversationSurface" in xage_main
            else "struct XAgeConversationSurface"
        )
        surface_start = xage_main.index(surface_declaration)
        surface_end = xage_main.index("private struct XAgeChatThinkingCard", surface_start)
        surface = xage_main[surface_start:surface_end]
        surface_raw_start = xage_raw.index(surface_declaration)
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
        upload_card_start = xage_raw.index("struct XAgeChatUploadStatusCard")
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
        installer_start = xage_main.index("struct XAgeVerticalKeyboardDismissInstaller")
        installer_end = xage_main.index("struct XAgeDataCardPreferenceSnapshot", installer_start)
        keyboard_installer = xage_main[installer_start:installer_end]
        ui_settled_start = ui_tests_raw.index("    private func assertChatSettled")
        ui_settled_end = ui_tests_raw.index("    private func tapAndWait", ui_settled_start)
        ui_settled = ui_tests_raw[ui_settled_start:ui_settled_end]
        copy_helper_start = ui_tests_raw.index("    private func assertAssistantTextCanBeCopied")
        copy_helper_end = ui_tests_raw.index("    private func assertChatSettled", copy_helper_start)
        copy_helper = ui_tests_raw[copy_helper_start:copy_helper_end]
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
        "ViewModels/HealthReportCompletionViewModel.swift": ["#if DEBUG", "#endif"],
        "ViewModels/MedicationViewModel.swift": ["#if DEBUG", "#endif"],
        "ViewModels/MealsViewModel.swift": ["#if DEBUG", "#endif"],
        "Views/Chat/ChatView.swift": [
            "#if DEBUG", "#else", "#endif", "#if DEBUG", "#else", "#endif",
        ],
        "Views/Health/HealthView.swift": [
            "#if canImport(ActivityKit)", "#endif", "#if canImport(ActivityKit)", "#endif",
            "#if canImport(ActivityKit)", "#endif",
        ],
        "Views/HealthData/XAgeTrustedScorePresentation.swift": [
            "#if DEBUG", "#else", "#endif", "#if DEBUG", "#endif",
        ],
        "Views/Home/XAgeMainView.swift": [
            "#if DEBUG", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
            "#if DEBUG", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
            "#if DEBUG", "#endif", "#if DEBUG", "#endif", "#if DEBUG", "#endif",
            "#if targetEnvironment(simulator)", "#else", "#endif",
        ],
        "Views/Login/LoginView.swift": [
            "#if DEBUG", "#endif", "#if DEBUG", "#endif",
        ],
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
            "2f0d534c5e883b60f673b82c0d8d65b3386b9fb10722368b246d17fe75e5dc91",
            "030e008f921c491543bf8cf2ceb4555ef333df5e08c1f147e2ccfd1c5f31173f",
            "d57d182995c7f08b9360a17be67e5e111a30b665beedf5e3d74dc149f14fd874",
        ],
        "Services/APIServiceProtocol.swift": ["b386e61e68f784a98b4ab387d95cf37a77fcd6b544561893d5729dfa124efd35"],
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
        "ViewModels/HealthReportCompletionViewModel.swift": [
            "5ed80082f3f9cdefcc7e9773a42e360ae3456cfea43e325251a638f68a2c8922",
        ],
        "ViewModels/MedicationViewModel.swift": ["89d3dde353599e5ddfcfa887d97e4da9a2a83b9fde243e4f3cbb291e880299cd"],
        "ViewModels/MealsViewModel.swift": ["8cf2bc0020de335d340f826dd1c8f4375aa5901f3a39209a9634898df83d5766"],
        "Views/Chat/ChatView.swift": [
            "b67871bc47b04de422983585f1a1b622ab8a81dbd20560e4ecfc61833824ad34",
            "d020059ceb9e967d67486a8a4efb7b616b9aca660546a62094c1e6aa871d6894",
        ],
        "Views/Health/HealthView.swift": [
            "bc9cfef21bc3405cf0212437e8091427f215f7a59c79c4b7bd89f4cfa32ff606",
            "2e168d87896ab53827adbd89bfb80a6d113c70351590c4abb0b4f01e2fecf2c4",
            "dfea3bed6699089c65b123b6d2cfb31051e2966254cce4b99f34b0f3420f94cf",
        ],
        "Views/HealthData/XAgeTrustedScorePresentation.swift": [
            "6b2be574fb126ec630640f6ba73f8d3a673bf47ffaac371a0b5f8e51b9022f62",
            "846946ff4015df4de20c6151e2c6a6715f19b902d898893fefe367ecf4c3f88f",
        ],
        "Views/Home/XAgeMainView.swift": [
            "660dfffdc8d561f3fc3a2548ef8591585bd6ea56572ab85cc3dcaf210dd8e8d7",
            "5c6210f8db5f805e8dfe21d7db95f96c7bb9c75357888ffe51fe603d77db2ae9",
            "331114a38cfb1b39ef3a7b69025192d5a96ee6f3d368e708ed2ec96353ac71dc",
            "c7f03b17e74fe46b940c6485043871606de6472a3ebeea36396cc6c26f01bcdb",
            "556291b9a48d8852073833b58f40bc190079d581295975257e486f43096fff1c",
            "e1b64a48681f27649e4e5cc45d257077f81f6d7be97d7347fc97fa8b8b243143",
            "9ab6b6de6ca78124a890b6923e31136434d0d37dad2ec087d4e538c05d73239e",
            "c0f74029121ddc3a8a6bd407b237d0a84e92e900038e129416a24b8603bd6a96",
            "bbdf5d7a721411b94fd038c422c4e18af13cfd9f7104a4d0fc50bf6596be499b",
            "83cc2fde4ee34dc0cadb724470b0ef62f8016a4a081460de68c88f4d25044b74",
        ],
        "Views/Login/LoginView.swift": [
            "72668378d9b29d93f0a92faad53acfe46fd9fb8d0226df9215c5b95d6949134d",
            "b6227006825aeca2af8b3cef6aaf5718c37e1b9956c3108355f45cae0412a342",
        ],
    }
    expected_automation_identifiers = {
        "App/AppDelegate.swift": 1,
        "App/XjieApp.swift": 2,
        "Services/APIService.swift": 4,
        "Services/PushNotificationManager.swift": 1,
        "Utils/NetworkMonitor.swift": 1,
        "ViewModels/AppleHealthSyncViewModel.swift": 1,
        "Views/Chat/ChatView.swift": 2,
        "Views/Home/XAgeMainView.swift": 1,
    }
    expected_submit_identifier_inventory = {
        "keyboardShortcut": {},
        "onSubmit": {
            "Views/Health/HealthView.swift": 2,
            "Views/Home/ExerciseCard.swift": 2,
            "Views/Home/XAgeMainView.swift": 5,
            "Views/Login/LoginView.swift": 14,
            "Views/Medications/MedicationEditView.swift": 2,
            "Views/Settings/XAgeSupportComplianceViews.swift": 1,
        },
        "submitLabel": {
            "Views/Home/XAgeMainView.swift": 5,
            "Views/Login/LoginView.swift": 14,
            "Views/Settings/XAgeSupportComplianceViews.swift": 1,
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
        "Views/HealthData/XAgeTrustedScorePresentation.swift": 2,
        "Views/Home/XAgeMainView.swift": 3,
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
        "Views/HealthData/XAgeTrustedScorePresentation.swift": ["XJIE_UI_TEST_RICH_LOCAL_SCORE_INPUTS"],
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

    trusted_score_raw = production_raw_sources.get(
        "Views/HealthData/XAgeTrustedScorePresentation.swift",
        "",
    )
    trusted_score_requirements = (
        'var isTrustedForDisplay: Bool { isReady && serverSnapshotVersion != nil }',
        'var isTrustedForDisplay: Bool { isReady && serverSnapshotVersion != nil && XAgeTrustedScorePresentationPolicy.isXAgeConsumptionEnabled }',
        'static let authority = "server"',
        "static let isXAgeConsumptionEnabled = false",
        '''static func currentPresentation(arguments: [String] = ProcessInfo.processInfo.arguments) -> XAgeCompositeScores {
#if DEBUG
        let localResearch = arguments.contains(debugReadyLocalResearchArgument) ? debugReadyLocalResearchScores() : nil
        return presentation(localResearch: localResearch)
#else
        return presentation()
#endif
    }''',
        '''static func presentation(localResearch: XAgeCompositeScores? = nil) -> XAgeCompositeScores {
        _ = localResearch
        return unavailable
    }''',
    )
    if any(trusted_score_raw.count(requirement) != 1 for requirement in trusted_score_requirements):
        violations.append(
            "trusted score presentation must require a server snapshot, ignore local research, "
            "and keep XAge disabled"
        )

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

    expected_vertical_keyboard_installer_consumers = {
        "Views/Home/XAgeMainView.swift": 2,
    }
    for path, source in production_sources.items():
        consumer_count = len(
            re.findall(r"\bXAgeVerticalKeyboardDismissInstaller\s*\{", source)
        )
        if consumer_count != expected_vertical_keyboard_installer_consumers.get(path, 0):
            violations.append(
                f"vertical keyboard-dismiss installer consumer inventory changed: "
                f"{path}={consumer_count}"
            )
    expected_downward_keyboard_modifier_consumers = {
        "Views/Medications/MedicationReminderView.swift": 1,
        "Views/Medications/XAgeMedicationManagementView.swift": 3,
        "Views/PatientHistory/PatientHistoryView.swift": 1,
    }
    for path, source in production_sources.items():
        consumer_count = len(
            re.findall(r"\.\s*xAgeDismissKeyboardOnDownwardPull\b", source)
        )
        if consumer_count != expected_downward_keyboard_modifier_consumers.get(path, 0):
            violations.append(
                f"downward keyboard-dismiss modifier consumer inventory changed: "
                f"{path}={consumer_count}"
            )
    downward_keyboard_consumer_requirements = {
        "Views/Medications/MedicationReminderView.swift": (
            '''.xAgeDismissKeyboardOnDownwardPull(
                    verificationIdentifier: "xage.medication.reminder.pullDismiss.ready"
                ) {
                    timeFocused = false
                }''',
        ),
        "Views/Medications/XAgeMedicationManagementView.swift": (
            '''.xAgeDismissKeyboardOnDownwardPull {
                    focusedField = nil
                }''',
            '''.xAgeDismissKeyboardOnDownwardPull {
                    focused = false
                }''',
            '''.xAgeDismissKeyboardOnDownwardPull {
                    onKeyboardDismiss()
                }''',
            "onKeyboardDismiss: { focused = false }",
            "onKeyboardDismiss: { focused = nil }",
        ),
        "Views/PatientHistory/PatientHistoryView.swift": (
            '''.xAgeDismissKeyboardOnDownwardPull(
                    verificationIdentifier: "healthProfile.pullDismiss.ready"
                ) {
                    editorFocused = false
                }''',
            '''.keyboardType(.numbersAndPunctuation)
            .focused($editorFocused)
            .accessibilityIdentifier("healthProfile.goal.editor.startedOn")''',
        ),
    }
    for path, requirements in downward_keyboard_consumer_requirements.items():
        raw_source = production_raw_sources.get(path, "")
        for requirement in requirements:
            expected_count = 2 if requirement == "onKeyboardDismiss: { focused = false }" else 1
            if raw_source.count(requirement) != expected_count:
                violations.append(
                    f"downward keyboard-dismiss focus cleanup changed: {path}"
                )

    expected_scroll_members = {
        "Views/Chat/ChatView.swift": 1,
        "Views/HealthData/HealthDataView.swift": 1,
        "Views/Home/XAgeMainView.swift": 1,
        "Views/Medications/XAgeMedicationManagementView.swift": 1,
        "Views/PatientHistory/PatientHistoryView.swift": 7,
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
        "Views/Home/XAgeMainView.swift": 2,
        "Views/PatientHistory/PatientHistoryView.swift": 3,
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
        "Views/HealthData/HealthReportHistoryComponents.swift": 1,
        "Views/Home/XAgeMainView.swift": 23,
        "Views/Login/LoginView.swift": 2,
        "Views/Login/PasswordResetSheet.swift": 1,
        "Views/Meals/MealsView.swift": 2,
        "Views/Medications/XAgeMedicationManagementView.swift": 2,
        "Views/Settings/ChangePasswordSheet.swift": 1,
    }
    expected_uikit_scroll_identifiers = {
        "UIScrollView": {
            "Views/Home/XAgeMainView.swift": 2,
            "Views/Shared/OriginalFileView.swift": 4,
        },
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
    canonical_surface_raw = (
        "private " + surface_raw
        if surface_raw.startswith("struct XAgeConversationSurface")
        else surface_raw
    )
    xage_surface_digest = hashlib.sha256(
        re.sub(r"\s+", "", canonical_surface_raw).encode("utf-8")
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
    if xage_surface_digest != "8b33e949b139be3c9e9c82ae9faadb782164ee22e911f17a394d11acf26c50c1":
        violations.append("XAGE conversation surface changed outside its audited complete structure")
    if legacy_surface_digest != "c88de412afb3c11fe741a5f2d16d145881bd2c03146bc3a5ca81b69914288e4c":
        violations.append("legacy ChatView surface changed outside its audited complete structure")
    if tab_consumer_digest != "99021768495c27f86aad8bb1bd11536bb34066662b7bd11f2f188cdb2871ca22":
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
            "Views/Home/XAgeMainView.swift": 2,
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
            "Views/Home/XAgeMainView.swift": 2,
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
            "Views/Home/XAgeMainView.swift": 2,
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
enum XAgeKeyboard {
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
        "Views/Medications/XAgeMedicationManagementView.swift": 1,
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
    canonical_upload_card = (
        "private " + upload_card
        if upload_card.startswith("struct XAgeChatUploadStatusCard")
        else upload_card
    )
    upload_card_digest = hashlib.sha256(
        re.sub(r"\s+", "", canonical_upload_card).encode("utf-8")
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
    expected_upload_send = '''private func uploadReports(_ files: [XAgeReportUploadFile], source: String) {
        guard !files.isEmpty else { return }
        inputFocused = false
        XAgeKeyboard.dismiss()
        Task {
            _ = await reportUploadVM.uploadReport(
                files: files.map {
                    HealthReportUploadAssetInput(data: $0.data, fileName: $0.fileName)
                },
                source: source,
                subjectUserID: authManager.authenticatedNumericUserID,
                accountScope: authManager.accountScope
            )
        }
    }'''
    if surface_raw.count(expected_upload_send) != 1 \
            or "reportAnalysisPrompt" in surface_raw:
        violations.append(
            "report upload must dismiss the keyboard and must not auto-send unconfirmed "
            "report content into chat"
        )
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
                            .textSelection(.enabled)
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
    if bubble_digest != "e8f0f9ee0dc3a038a6f5e147ba3e0e36950f7d4ad710f87df25ffb19762612de":
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
    canonical_keyboard_installer = (
        "private " + keyboard_installer
        if keyboard_installer.startswith("struct XAgeVerticalKeyboardDismissInstaller")
        else keyboard_installer
    )
    installer_digest = hashlib.sha256(
        re.sub(r"\s+", "", canonical_keyboard_installer).encode("utf-8")
    ).hexdigest()
    if installer_digest != "29f713207a3803db6b2fd3ae9c33b6950479daae6c30636d63aa62c77cdbd30c":
        violations.append("XAGE vertical keyboard installer changed from the audited UIKit-only scroll-preserving form")

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
        let assistantReply = app.staticTexts["UI 自动化回复：\\(submittedPrompt)"]
        XCTAssertTrue(
            assistantReply.waitForExistence(timeout: 5),
            "小屏内容首次溢出后仍应显示确定性助手回复"
        )
        assertAssistantTextCanBeCopied(assistantReply, context: "普通助手回复")'''
    expected_ui_link_action_assertion = '''let link = app.buttons[expectedAssistantLinkLabel]
            XCTAssertTrue(
                link.waitForExistence(timeout: 5),
                "富文本助手回复必须向辅助功能树暴露可激活 Link 动作"
            )
            XCTAssertTrue(link.isHittable, "富文本助手链接必须可以由用户激活")'''
    expected_ui_link_copy_assertion = '''assertAssistantTextCanBeCopied(
                app.staticTexts["UI 自动化回复："],
                context: "含真实链接的富文本助手回复"
            )'''
    expected_reminder_pull_dismiss_assertion = '''app.descendants(matching: .any)["xage.medication.reminder.pullDismiss.ready"]
                .waitForExistence(timeout: 4)'''
    expected_profile_pull_dismiss_assertion = '''app.descendants(matching: .any)["healthProfile.pullDismiss.ready"]
                .waitForExistence(timeout: 4)'''
    expected_profile_nested_pull_start = '''let dragStart = valueEditor.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.35))'''
    expected_copy_helper = '''    private func assertAssistantTextCanBeCopied(
        _ text: XCUIElement,
        context: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertTrue(text.waitForExistence(timeout: 5), "\\(context)：助手正文应存在", file: file, line: line)
        text.press(forDuration: 1.1)
        let copy = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label IN %@", ["拷贝", "复制", "Copy"]))
            .firstMatch
        XCTAssertTrue(copy.waitForExistence(timeout: 4), "\\(context)：长按助手正文应出现复制操作", file: file, line: line)
        XCTAssertTrue(copy.isHittable, "\\(context)：复制操作应可点击", file: file, line: line)
        copy.tap()
    }

'''
    if ui_settled != expected_ui_settled \
            or copy_helper != expected_copy_helper \
            or ui_tests_raw.count(expected_ui_submit_and_settle) != 1 \
            or ui_tests_raw.count(expected_multiline_return_case) != 1 \
            or ui_tests_raw.count(expected_ui_link_action_assertion) != 1 \
            or ui_tests_raw.count(expected_ui_link_copy_assertion) != 1 \
            or ui_tests_raw.count(expected_reminder_pull_dismiss_assertion) != 1 \
            or ui_tests_raw.count(expected_profile_pull_dismiss_assertion) != 1 \
            or ui_tests_raw.count(expected_profile_nested_pull_start) != 1:
        violations.append(
            "continuous-chat UI must prove multiline Return editing, assistant copyability, "
            "and the exact app-owned terminal state after send"
        )
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


def backend_test_workspace_violations(workflow: str) -> list[str]:
    start_marker = "      - name: Run backend tests in the production image\n"
    end_marker = "      - name: Upload backend test result\n"
    if workflow.count(start_marker) != 1 or workflow.count(end_marker) != 1:
        return ["production-image backend test step boundaries changed"]
    block = workflow[
        workflow.index(start_marker):workflow.index(end_marker)
    ]
    violations: list[str] = []
    expected_docker_prelude = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "--network",
        "none",
    ]
    for mount in (
        "type=bind,source=$PWD/backend/deploy/production_deploy_guard.py,"
        "target=/workspace/backend/deploy/production_deploy_guard.py,readonly",
        "type=bind,source=$PWD/backend/deploy/production_container.json,"
        "target=/workspace/backend/deploy/production_container.json,readonly",
        "type=bind,source=$PWD/tools,target=/workspace/tools,readonly",
        "type=bind,source=$PWD/quality,target=/workspace/quality,readonly",
        "type=bind,source=$result_dir,target=/results",
    ):
        expected_docker_prelude.extend(("--mount", mount))
    expected_docker_prelude.extend(("--entrypoint", "/bin/bash", "$BACKEND_IMAGE"))
    docker_start = "          docker run --rm \\\n"
    image_line = '            "$BACKEND_IMAGE" \\\n'
    if block.count(docker_start) != 1 or block.count(image_line) != 1:
        violations.append("production-image backend docker command boundaries changed")
        return violations
    docker_prelude = block[
        block.index(docker_start):block.index(image_line) + len(image_line)
    ].replace("\\\n", "")
    try:
        observed_docker_prelude = shlex.split(docker_prelude, posix=True)
    except ValueError:
        violations.append("production-image backend docker command is not valid shell syntax")
        return violations
    if observed_docker_prelude != expected_docker_prelude:
        violations.append(
            "production-image backend docker invocation differs from the exact network, "
            "mount, entrypoint, and image allowlist"
        )
    runtime_prelude = (
        "            -ceu '\n"
        "              test ! -e /app/deploy\n"
        "              mkdir -p /workspace/backend\n"
    )
    if block.count(runtime_prelude) != 1:
        violations.append(
            "production image must execute the /app/deploy absence probe as the first shell command"
        )
    if len(re.findall(r"\bdocker\s+(?:container\s+)?run\b", block)) != 1:
        violations.append("production-image backend test step must invoke docker run exactly once")
    return violations


class ReleasePolicyTests(unittest.TestCase):
    def test_ci_covers_xage_backend_and_never_swallows_failures(self):
        workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        policy_job = workflow[
            workflow.index("  policy:\n"):workflow.index("  backend:\n")
        ]
        trigger_block = workflow[
            workflow.index("on:\n"):workflow.index("\npermissions:\n")
        ]
        self.assertEqual(workflow_fail_open_violations(workflow), [])
        self.assertEqual(
            trigger_block,
            "on:\n"
            "  push:\n"
            "    branches: [main]\n"
            "  pull_request:\n"
            "    branches: [main]\n",
        )
        self.assertNotIn("branches: [main, XAGE]", workflow)
        self.assertEqual(
            re.findall(r"^    runs-on:\s*(\S+)\s*$", policy_job, re.MULTILINE),
            ["macos-15"],
        )
        self.assertIn("/usr/bin/python3 -I tools/python_test_gate.py tools", policy_job)
        self.assertNotIn("regression_guard.py validate", policy_job)
        self.assertIn("/usr/bin/python3 -I tools/regression_guard.py check", policy_job)
        self.assertIn("Backend full regression", workflow)
        self.assertIn("python -I tools/python_test_gate.py backend", workflow)
        build_position = workflow.index("- name: Build the production backend image")
        installer_position = workflow.index(
            "- name: Run production bundle installer Linux runtime self-test"
        )
        launcher_position = workflow.index(
            "- name: Run production launcher Linux runtime self-test"
        )
        postgres_position = workflow.index(
            "- name: Run real PostgreSQL production catalog integration gate"
        )
        expand_postgres_position = workflow.index(
            "- name: Run real PostgreSQL expand-migration integration gate"
        )
        backend_test_position = workflow.index(
            "- name: Run backend tests in the production image"
        )
        self.assertLess(
            build_position,
            installer_position,
        )
        self.assertLess(installer_position, launcher_position)
        self.assertLess(launcher_position, postgres_position)
        self.assertLess(postgres_position, expand_postgres_position)
        self.assertLess(expand_postgres_position, backend_test_position)
        backend_job = workflow[
            workflow.index("  backend:\n"):workflow.index("  ios:\n")
        ]
        self.assertEqual(backend_test_workspace_violations(workflow), [])
        backend_test_block = workflow[
            workflow.index("      - name: Run backend tests in the production image\n"):
            workflow.index("      - name: Upload backend test result\n")
        ]
        self.assertEqual(backend_test_block.count("test ! -e /app/deploy"), 1)
        self.assertIn("cp -a /app/. /workspace/backend/", backend_test_block)
        backend_root = REPO_ROOT / "backend"
        tracked_paths = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        repository_import_candidates: set[str] = set()
        for tracked_path in tracked_paths:
            parts = Path(tracked_path).parts
            if len(parts) > 1:
                repository_import_candidates.add(parts[0])
            elif Path(tracked_path).suffix == ".py":
                repository_import_candidates.add(Path(tracked_path).stem)
            if parts and parts[0] == "backend" and len(parts) > 2:
                repository_import_candidates.add(parts[1])
            elif parts and parts[0] == "backend" and len(parts) == 2 \
                    and Path(parts[1]).suffix == ".py":
                repository_import_candidates.add(Path(parts[1]).stem)
        backend_test_import_roots: set[str] = set()
        deploy_import_consumers: set[str] = set()
        deploy_spec_consumers: set[str] = set()
        unresolved_dynamic_imports: list[str] = []
        for path in (backend_root / "tests").rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            relative_path = path.relative_to(backend_root / "tests").as_posix()
            module_constants: dict[str, str] = {}
            for statement in tree.body:
                if isinstance(statement, ast.Assign) \
                        and isinstance(statement.value, ast.Constant) \
                        and isinstance(statement.value.value, str):
                    for target in statement.targets:
                        if isinstance(target, ast.Name):
                            module_constants[target.id] = statement.value.value
                elif isinstance(statement, ast.AnnAssign) \
                        and isinstance(statement.target, ast.Name) \
                        and isinstance(statement.value, ast.Constant) \
                        and isinstance(statement.value.value, str):
                    module_constants[statement.target.id] = statement.value.value
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {alias.name.partition(".")[0] for alias in node.names}
                    backend_test_import_roots.update(roots)
                    if "deploy" in roots:
                        deploy_import_consumers.add(relative_path)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    root = node.module.partition(".")[0]
                    backend_test_import_roots.add(root)
                    if root == "deploy":
                        deploy_import_consumers.add(relative_path)
                elif isinstance(node, ast.Call):
                    call_name = ""
                    if isinstance(node.func, ast.Name):
                        call_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        call_name = node.func.attr
                    if call_name not in {"import_module", "__import__"} or not node.args:
                        continue
                    argument = node.args[0]
                    module_name = (
                        argument.value
                        if isinstance(argument, ast.Constant)
                        and isinstance(argument.value, str)
                        else module_constants.get(argument.id)
                        if isinstance(argument, ast.Name)
                        else None
                    )
                    if module_name is None:
                        unresolved_dynamic_imports.append(relative_path)
                        continue
                    root = module_name.partition(".")[0]
                    backend_test_import_roots.add(root)
                    if root == "deploy":
                        deploy_import_consumers.add(relative_path)
                elif isinstance(node, ast.Constant) \
                        and node.value == "production_container.json":
                    deploy_spec_consumers.add(relative_path)
        self.assertEqual(unresolved_dynamic_imports, [])
        self.assertEqual(
            backend_test_import_roots & repository_import_candidates,
            {"app", "deploy"},
        )
        self.assertEqual(
            deploy_import_consumers,
            {
                "unit/test_dietary_records_contract.py",
                "unit/test_health_report_completion.py",
                "unit/test_health_trust_expansion_schema.py",
            },
        )
        self.assertEqual(
            deploy_spec_consumers,
            {"unit/test_health_report_completion.py"},
        )
        dockerfile = (backend_root / "Dockerfile").read_text(encoding="utf-8")
        dockerfile_copy_or_add = [
            line.strip()
            for line in dockerfile.splitlines()
            if line.lstrip().upper().startswith(("COPY ", "ADD "))
        ]
        self.assertEqual(
            dockerfile_copy_or_add,
            [
                "COPY requirements.lock ./",
                "COPY pyproject.toml alembic.ini ./",
                "COPY app ./app",
                "COPY static ./static",
                "COPY tests ./tests",
            ],
        )
        self.assertIn("fetch-depth: 0", backend_job)
        self.assertIn(
            "tools/production_expand_migration_postgres_selftest.py",
            backend_job,
        )
        self.assertIn(
            "-I /workspace/tools/production_bundle_installer_linux_selftest.py",
            workflow,
        )
        self.assertIn(
            "tools/production_launcher_linux_selftest.py \\\n"
            "            --docker-image \"$BACKEND_IMAGE\"",
            workflow,
        )
        self.assertNotRegex(policy_job, r"(?m)^\s+python3\s+-I\s+")
        self.assertIn("name: quality-gate", workflow)
        self.assertIn("set -o pipefail", workflow)
        self.assertNotIn("|| true", workflow)
        self.assertNotIn("    paths:", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertNotIn("run_regression_gate.py fast", workflow)
        self.assertNotIn("run_regression_gate.py impacted", workflow)
        self.assertNotRegex(workflow, r"uses:\s+[^\s]+@v\d")
        self.assertIn("xcode-version: '26.3'", workflow)
        for mutation in (
            workflow.replace("set -euo pipefail", "set +e", 1),
            workflow.replace(
                "- name: Run backend tests in the production image",
                "- name: Run backend tests in the production image\n        continue-on-error: true",
            ),
            workflow.replace(
                "- name: Run backend tests in the production image",
                "- name: Run backend tests in the production image\n        if: false",
            ),
            workflow.replace("echo \"All required regression gates passed.\"", "exit 0"),
            workflow.replace(
                "/usr/bin/python3 -I tools/python_test_gate.py tools",
                "/usr/bin/python3 -I tools/python_test_gate.py tools && echo tools-passed",
                1,
            ),
        ):
            with self.subTest(mutation=mutation):
                self.assertTrue(workflow_fail_open_violations(mutation))
        deploy_guard_mount = (
            '--mount "type=bind,source=$PWD/backend/deploy/production_deploy_guard.py,'
            'target=/workspace/backend/deploy/production_deploy_guard.py,readonly"'
        )
        deploy_spec_mount = (
            '--mount "type=bind,source=$PWD/backend/deploy/production_container.json,'
            'target=/workspace/backend/deploy/production_container.json,readonly"'
        )
        for mutation in (
            workflow.replace(deploy_guard_mount, "", 1),
            workflow.replace(deploy_spec_mount, "", 1),
            workflow.replace(
                deploy_guard_mount,
                deploy_guard_mount.replace(",readonly", ""),
                1,
            ),
            workflow.replace(
                deploy_spec_mount,
                deploy_spec_mount.replace(
                    "target=/workspace/backend/deploy/production_container.json",
                    "target=/workspace/deploy/production_container.json",
                ),
                1,
            ),
            workflow.replace(
                deploy_guard_mount,
                '--mount "type=bind,source=$PWD/backend/deploy,'
                'target=/workspace/backend/deploy,readonly"',
                1,
            ),
            workflow.replace(
                deploy_guard_mount,
                deploy_guard_mount
                + " \\\n            --mount type=bind,source=$PWD/backend/deploy,"
                "target=/workspace/backend/deploy,readonly",
                1,
            ),
            workflow.replace(
                deploy_guard_mount,
                deploy_guard_mount
                + " \\\n            --mount 'type=bind,source=$PWD/backend/deploy,"
                "target=/workspace/backend/deploy,readonly'",
                1,
            ),
            workflow.replace(
                deploy_guard_mount,
                deploy_guard_mount
                + " \\\n            -v $PWD/backend/deploy:/workspace/backend/deploy:ro",
                1,
            ),
            workflow.replace(
                deploy_guard_mount,
                "--network host \\\n            " + deploy_guard_mount,
                1,
            ),
            workflow.replace(
                deploy_guard_mount,
                "--network=host \\\n            " + deploy_guard_mount,
                1,
            ),
            workflow.replace("test ! -e /app/deploy", ":", 1),
            workflow.replace(
                "              test ! -e /app/deploy\n",
                "              : # test ! -e /app/deploy\n",
                1,
            ),
            workflow.replace(
                "              test ! -e /app/deploy\n",
                "              if false; then\n"
                "              test ! -e /app/deploy\n"
                "              fi\n",
                1,
            ),
        ):
            with self.subTest(workspace_mutation=mutation):
                self.assertTrue(backend_test_workspace_violations(mutation))

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
        self.assertNotIn("run_regression_gate.py fast", script)
        self.assertNotIn("run_regression_gate.py impacted", script)
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
        self.assertEqual(hooks.count("/usr/bin/python3 -I tools/regression_guard.py"), 2)
        self.assertNotIn("regression_guard.py validate", hooks)
        self.assertNotIn("--no-verify", hooks)

    def test_pre_push_allows_candidate_push_before_release_evidence(self):
        hook = (REPO_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
        self.assertNotIn("regression_guard.py validate", hook)
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
        self.assertIn('git merge-base "$local_sha" refs/remotes/origin/main', pre_push)
        self.assertNotIn("refs/remotes/origin/XAGE", pre_push)
        self.assertRegex(
            pre_push,
            r'case "\$remote_ref" in\n\s+refs/heads/main\|refs/heads/XAGE\)',
        )
        self.assertLess(
            pre_push.index('case "$remote_ref" in'),
            pre_push.index('if [ "$local_sha" = "$zero" ]'),
        )
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

        zero = "0" * 40
        head = subprocess.run(
            ["/usr/bin/git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        for protected_ref, local_sha in (
            ("refs/heads/main", head),
            ("refs/heads/main", zero),
            ("refs/heads/XAGE", head),
            ("refs/heads/XAGE", zero),
        ):
            with self.subTest(protected_ref=protected_ref, local_sha=local_sha):
                protected = subprocess.run(
                    ["/bin/sh", str(REPO_ROOT / ".githooks" / "pre-push")],
                    cwd=REPO_ROOT,
                    input=f"refs/heads/local {local_sha} {protected_ref} {head}\n",
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertNotEqual(protected.returncode, 0, msg=protected.stdout)
                self.assertIn("Direct updates or deletions", protected.stdout)

        feature_delete = subprocess.run(
            ["/bin/sh", str(REPO_ROOT / ".githooks" / "pre-push")],
            cwd=REPO_ROOT,
            input=f"(delete) {zero} refs/heads/codex/old-feature {head}\n",
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(feature_delete.returncode, 0, msg=feature_delete.stdout)

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
        chat_sources = combine_manifest_xage_sources({
            str(path.relative_to(app_source_root)): path.read_text(encoding="utf-8")
            for path in sorted(app_source_root.rglob("*.swift"))
        })
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

        weaken_report_fixture_confirmation = dict(chat_sources)
        weaken_report_fixture_confirmation["Services/APIService.swift"] = (
            weaken_report_fixture_confirmation["Services/APIService.swift"].replace(
                "guard isValidReportConfirmation(requestBodyData(from: request)) else {",
                "guard requestBodyData(from: request) != nil else {",
                1,
            )
        )
        expose_medication_test_wait_in_release = dict(chat_sources)
        expose_medication_test_wait_in_release["ViewModels/MedicationViewModel.swift"] = (
            expose_medication_test_wait_in_release["ViewModels/MedicationViewModel.swift"].replace(
                """    #if DEBUG
    func waitForConfirmationInsightsForTesting() async {
        let task = confirmationTask
        await task?.value
    }
    #endif""",
                """    func waitForConfirmationInsightsForTesting() async {
        let task = confirmationTask
        await task?.value
    }""",
                1,
            )
        )
        enable_unversioned_xage = dict(chat_sources)
        enable_unversioned_xage["Views/HealthData/XAgeTrustedScorePresentation.swift"] = (
            enable_unversioned_xage["Views/HealthData/XAgeTrustedScorePresentation.swift"].replace(
                "static let isXAgeConsumptionEnabled = false",
                "static let isXAgeConsumptionEnabled = true",
                1,
            )
        )
        display_local_research_score = dict(chat_sources)
        display_local_research_score["Views/HealthData/XAgeTrustedScorePresentation.swift"] = (
            display_local_research_score["Views/HealthData/XAgeTrustedScorePresentation.swift"].replace(
                """        _ = localResearch
        return unavailable""",
                "        return localResearch ?? unavailable",
                1,
            )
        )
        drop_server_snapshot_requirement = dict(chat_sources)
        drop_server_snapshot_requirement["Views/HealthData/XAgeTrustedScorePresentation.swift"] = (
            drop_server_snapshot_requirement["Views/HealthData/XAgeTrustedScorePresentation.swift"].replace(
                "var isTrustedForDisplay: Bool { isReady && serverSnapshotVersion != nil }",
                "var isTrustedForDisplay: Bool { isReady }",
                1,
            )
        )
        restore_report_upload_auto_send = dict(chat_sources)
        restore_report_upload_auto_send["Views/Home/XAgeMainView.swift"] = (
            restore_report_upload_auto_send["Views/Home/XAgeMainView.swift"].replace(
                """        Task {
            _ = await reportUploadVM.uploadReport(""",
                """        Task {
            await vm.sendText("分析刚上传的报告")
            _ = await reportUploadVM.uploadReport(""",
                1,
            )
        )
        remove_assistant_text_selection = dict(chat_sources)
        remove_assistant_text_selection["Views/Home/XAgeMainView.swift"] = (
            remove_assistant_text_selection["Views/Home/XAgeMainView.swift"].replace(
                """
                            .textSelection(.enabled)""",
                "",
                1,
            )
        )
        remove_plain_assistant_copy_assertion = dict(chat_sources)
        remove_plain_assistant_copy_assertion["Tests/XAgeHighIntensityContextUITests.swift"] = (
            remove_plain_assistant_copy_assertion[
                "Tests/XAgeHighIntensityContextUITests.swift"
            ].replace(
                '        assertAssistantTextCanBeCopied(assistantReply, context: "普通助手回复")',
                "        _ = assistantReply",
                1,
            )
        )
        remove_link_assistant_copy_assertion = dict(chat_sources)
        remove_link_assistant_copy_assertion["Tests/XAgeHighIntensityContextUITests.swift"] = (
            remove_link_assistant_copy_assertion[
                "Tests/XAgeHighIntensityContextUITests.swift"
            ].replace(
                """            assertAssistantTextCanBeCopied(
                app.staticTexts["UI 自动化回复："],
                context: "含真实链接的富文本助手回复"
            )""",
                '            _ = app.staticTexts["UI 自动化回复："]',
                1,
            )
        )
        weaken_downward_keyboard_direction = dict(chat_sources)
        weaken_downward_keyboard_direction["Views/Home/XAgeMainView.swift"] = (
            weaken_downward_keyboard_direction["Views/Home/XAgeMainView.swift"].replace(
                "return velocity.y > 0 && abs(velocity.y) > abs(velocity.x) * 1.2",
                "return abs(velocity.y) > abs(velocity.x) * 1.2",
                1,
            )
        )
        reintroduce_scroll_blocking_swiftui_drag = dict(chat_sources)
        reintroduce_scroll_blocking_swiftui_drag["Views/Home/XAgeMainView.swift"] = (
            reintroduce_scroll_blocking_swiftui_drag["Views/Home/XAgeMainView.swift"].replace(
                """        content
            .background {""",
                """        content
            .simultaneousGesture(
                DragGesture(minimumDistance: 12, coordinateSpace: .local)
                    .onEnded { value in
                        let vertical = value.translation.height
                        guard vertical > 20,
                              abs(vertical) > abs(value.translation.width) * 1.2 else { return }
                        dismissKeyboard()
                    }
            )
            .background {""",
                1,
            )
        )
        remove_reminder_pull_verification = dict(chat_sources)
        remove_reminder_pull_verification["Views/Medications/MedicationReminderView.swift"] = (
            remove_reminder_pull_verification[
                "Views/Medications/MedicationReminderView.swift"
            ].replace(
                """.xAgeDismissKeyboardOnDownwardPull(
                    verificationIdentifier: "xage.medication.reminder.pullDismiss.ready"
                ) {
                    timeFocused = false
                }""",
                """.xAgeDismissKeyboardOnDownwardPull {
                    timeFocused = false
                }""",
                1,
            )
        )
        drop_shared_sheet_focus_cleanup = dict(chat_sources)
        drop_shared_sheet_focus_cleanup["Views/Medications/XAgeMedicationManagementView.swift"] = (
            drop_shared_sheet_focus_cleanup[
                "Views/Medications/XAgeMedicationManagementView.swift"
            ].replace(
                "onKeyboardDismiss: { focused = nil }",
                "onKeyboardDismiss: {}",
                1,
            )
        )
        add_rogue_downward_keyboard_consumer = dict(chat_sources)
        add_rogue_downward_keyboard_consumer["Views/Medications/RogueDismissConsumer.swift"] = """
            import SwiftUI
            struct RogueDismissConsumer: View {
                var body: some View {
                    ScrollView { EmptyView() }
                        .xAgeDismissKeyboardOnDownwardPull {}
                }
            }
        """
        remove_reminder_pull_ui_assertion = dict(chat_sources)
        remove_reminder_pull_ui_assertion["Tests/XAgeHighIntensityContextUITests.swift"] = (
            remove_reminder_pull_ui_assertion[
                "Tests/XAgeHighIntensityContextUITests.swift"
            ].replace(
                """        XCTAssertTrue(
            app.descendants(matching: .any)["xage.medication.reminder.pullDismiss.ready"]
                .waitForExistence(timeout: 4),
            "提醒表单必须把纵向下拉退键盘 hook 安装在滚动内容中"
        )
""",
                "",
                1,
            )
        )
        remove_profile_pull_verification = dict(chat_sources)
        remove_profile_pull_verification["Views/PatientHistory/PatientHistoryView.swift"] = (
            remove_profile_pull_verification[
                "Views/PatientHistory/PatientHistoryView.swift"
            ].replace(
                """.xAgeDismissKeyboardOnDownwardPull(
                    verificationIdentifier: "healthProfile.pullDismiss.ready"
                ) {
                    editorFocused = false
                }""",
                """.xAgeDismissKeyboardOnDownwardPull {
                    editorFocused = false
                }""",
                1,
            )
        )
        remove_profile_pull_ui_assertion = dict(chat_sources)
        remove_profile_pull_ui_assertion["Tests/XAgeHighIntensityContextUITests.swift"] = (
            remove_profile_pull_ui_assertion[
                "Tests/XAgeHighIntensityContextUITests.swift"
            ].replace(
                """        XCTAssertTrue(
            app.descendants(matching: .any)["healthProfile.pullDismiss.ready"]
                .waitForExistence(timeout: 4),
            "健康画像必须把纵向下拉退键盘 hook 安装在滚动内容中"
        )
""",
                "",
                1,
            )
        )
        remove_profile_started_on_focus = dict(chat_sources)
        remove_profile_started_on_focus["Views/PatientHistory/PatientHistoryView.swift"] = (
            remove_profile_started_on_focus[
                "Views/PatientHistory/PatientHistoryView.swift"
            ].replace(
                """.keyboardType(.numbersAndPunctuation)
            .focused($editorFocused)
            .accessibilityIdentifier("healthProfile.goal.editor.startedOn")""",
                """.keyboardType(.numbersAndPunctuation)
            .accessibilityIdentifier("healthProfile.goal.editor.startedOn")""",
                1,
            )
        )
        weaken_profile_nested_pull_start = dict(chat_sources)
        weaken_profile_nested_pull_start["Tests/XAgeHighIntensityContextUITests.swift"] = (
            weaken_profile_nested_pull_start[
                "Tests/XAgeHighIntensityContextUITests.swift"
            ].replace(
                "let dragStart = valueEditor.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.35))",
                "let dragStart = profileScroll.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.30))",
                1,
            )
        )

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
                            infoRequest: xAgeInfoRequest
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
                            .textSelection(.enabled)
                    }
                }
                    .font""",
                """                        AccessibleMarkdownText(text: message.content)
                            .textSelection(.enabled)
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
                '''    private func uploadReports(_ files: [XAgeReportUploadFile], source: String) {
        guard !files.isEmpty else { return }
        inputFocused = false
        XAgeKeyboard.dismiss()
        Task {''',
                '''    private func uploadReports(_ files: [XAgeReportUploadFile], source: String) {
        guard !files.isEmpty else { return }
        Task {''',
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
        replace_fixed_conversation_module = dict(chat_sources)
        replace_fixed_conversation_module["Views/Home/XAgeMainView.swift"] = (
            replace_fixed_conversation_module["Views/Home/XAgeMainView.swift"].replace(
                '.init(destination: .profile, title: "画像", systemImage: "person.text.rectangle.fill")',
                '.init(destination: .profile, title: "工具", systemImage: "globe")',
                1,
            )
        )
        discard_conversation_draft = dict(chat_sources)
        discard_conversation_draft["Views/Home/XAgeMainView.swift"] = (
            discard_conversation_draft["Views/Home/XAgeMainView.swift"].replace(
                "navigate(self); return draft",
                'navigate(self); return ""',
                1,
            )
        )
        weaken_conversation_navigation_type = dict(chat_sources)
        weaken_conversation_navigation_type["Views/Home/XAgeMainView.swift"] = (
            weaken_conversation_navigation_type["Views/Home/XAgeMainView.swift"].replace(
                "var xAgeOpenConversationModule: (XAgeConversationModuleHandoff) -> Void",
                "var xAgeOpenConversationModule: (String) -> Void",
                1,
            )
        )
        remove_conversation_module_allowlist = dict(chat_sources)
        remove_conversation_module_allowlist["Views/Home/XAgeMainView.swift"] = (
            remove_conversation_module_allowlist["Views/Home/XAgeMainView.swift"].replace(
                "        guard XAgeConversationNavigationAction.available.contains(handoff.action) else { return }\n",
                "",
                1,
            )
        )
        bypass_central_conversation_registry = dict(chat_sources)
        bypass_central_conversation_registry["Views/Home/XAgeMainView.swift"] = (
            bypass_central_conversation_registry["Views/Home/XAgeMainView.swift"].replace(
                "ForEach(XAgeConversationNavigationAction.available) { action in",
                "ForEach([XAgeConversationNavigationAction(id: \"meals\", title: \"膳食\", systemImage: \"fork.knife\")]) { action in",
                1,
            )
        )
        add_arbitrary_conversation_tool_route = dict(chat_sources)
        add_arbitrary_conversation_tool_route["Views/Home/XAgeMainView.swift"] = (
            add_arbitrary_conversation_tool_route["Views/Home/XAgeMainView.swift"].replace(
                "    @ViewBuilder\n    private var quickActionDestination: some View {",
                '''    private func presentConversationTool(named toolName: String) {
        presentedQuickActionID = toolName
    }

    @ViewBuilder
    private var quickActionDestination: some View {''',
                1,
            )
        )
        chat_policy_mutations = {
            "weaken-report-fixture-confirmation": weaken_report_fixture_confirmation,
            "expose-medication-test-wait-in-release": expose_medication_test_wait_in_release,
            "enable-unversioned-xage": enable_unversioned_xage,
            "display-local-research-score": display_local_research_score,
            "drop-server-snapshot-requirement": drop_server_snapshot_requirement,
            "restore-report-upload-auto-send": restore_report_upload_auto_send,
            "remove-assistant-text-selection": remove_assistant_text_selection,
            "remove-plain-assistant-copy-assertion": remove_plain_assistant_copy_assertion,
            "remove-link-assistant-copy-assertion": remove_link_assistant_copy_assertion,
            "weaken-downward-keyboard-direction": weaken_downward_keyboard_direction,
            "reintroduce-scroll-blocking-swiftui-drag": reintroduce_scroll_blocking_swiftui_drag,
            "remove-reminder-pull-verification": remove_reminder_pull_verification,
            "drop-shared-sheet-focus-cleanup": drop_shared_sheet_focus_cleanup,
            "add-rogue-downward-keyboard-consumer": add_rogue_downward_keyboard_consumer,
            "remove-reminder-pull-ui-assertion": remove_reminder_pull_ui_assertion,
            "remove-profile-pull-verification": remove_profile_pull_verification,
            "remove-profile-pull-ui-assertion": remove_profile_pull_ui_assertion,
            "remove-profile-started-on-focus": remove_profile_started_on_focus,
            "weaken-profile-nested-pull-start": weaken_profile_nested_pull_start,
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
            "replace-fixed-conversation-module": replace_fixed_conversation_module,
            "discard-conversation-draft": discard_conversation_draft,
            "weaken-conversation-navigation-type": weaken_conversation_navigation_type,
            "remove-conversation-module-allowlist": remove_conversation_module_allowlist,
            "bypass-central-conversation-registry": bypass_central_conversation_registry,
            "add-arbitrary-conversation-tool-route": add_arbitrary_conversation_tool_route,
        }
        self.assertEqual(len(chat_policy_mutations), 91)
        for label, mutation in chat_policy_mutations.items():
            with self.subTest(chat_quiescence_mutation=label):
                self.assertNotEqual(
                    mutation,
                    chat_sources,
                    "static-policy mutation fixture must alter the current production source",
                )
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
        deploy_path = REPO_ROOT / "scripts" / "deploy_literature.sh"
        deploy = deploy_path.read_text(encoding="utf-8")
        deploy_launcher_path = REPO_ROOT / "scripts" / "launch_production_deploy.py"
        deploy_launcher_source = deploy_launcher_path.read_text(encoding="utf-8")
        deploy_launcher_selftest_path = (
            REPO_ROOT / "tools" / "production_launcher_linux_selftest.py"
        )
        deploy_launcher_selftest_source = deploy_launcher_selftest_path.read_text(
            encoding="utf-8"
        )
        expand_postgres_selftest_path = (
            REPO_ROOT / "tools" / "production_expand_migration_postgres_selftest.py"
        )
        expand_postgres_selftest_source = expand_postgres_selftest_path.read_text(
            encoding="utf-8"
        )
        catalog_postgres_selftest_path = (
            REPO_ROOT / "tools" / "production_catalog_postgres_selftest.py"
        )
        catalog_postgres_selftest_source = catalog_postgres_selftest_path.read_text(
            encoding="utf-8"
        )
        compile(deploy_launcher_source, str(deploy_launcher_path), "exec")
        compile(
            expand_postgres_selftest_source,
            str(expand_postgres_selftest_path),
            "exec",
        )
        compile(
            catalog_postgres_selftest_source,
            str(catalog_postgres_selftest_path),
            "exec",
        )
        expand_postgres_selftest_spec = importlib.util.spec_from_file_location(
            "release_policy_expand_postgres_selftest",
            expand_postgres_selftest_path,
        )
        assert (
            expand_postgres_selftest_spec is not None
            and expand_postgres_selftest_spec.loader is not None
        )
        expand_postgres_selftest = importlib.util.module_from_spec(
            expand_postgres_selftest_spec
        )
        sys.modules[expand_postgres_selftest_spec.name] = expand_postgres_selftest
        expand_postgres_selftest_spec.loader.exec_module(expand_postgres_selftest)
        pre_dump_check = (
            "CHECK (((value_kind)::text = ANY ((ARRAY['numeric'::character varying, "
            "'category'::character varying])::text[])))"
        )
        restored_check = (
            "CHECK (((value_kind)::text = ANY (ARRAY[('numeric'::character varying)::text, "
            "('category'::character varying)::text])))"
        )
        changed_check = restored_check.replace("'category'", "'changed'", 1)
        self.assertEqual(
            expand_postgres_selftest.canonicalize_dump_restore_check_definition(
                pre_dump_check
            ),
            expand_postgres_selftest.canonicalize_dump_restore_check_definition(
                restored_check
            ),
        )
        self.assertNotEqual(
            expand_postgres_selftest.canonicalize_dump_restore_check_definition(
                pre_dump_check
            ),
            expand_postgres_selftest.canonicalize_dump_restore_check_definition(
                changed_check
            ),
        )
        self.assertEqual(
            expand_postgres_selftest.canonicalize_dump_restore_check_definition(
                "CHECK ((version >= 1))"
            ),
            "CHECK ((version >= 1))",
        )
        self.assertNotIn("--file=-", deploy)
        self.assertNotIn('"--file=-"', expand_postgres_selftest_source)
        catalog_postgres_selftest_spec = importlib.util.spec_from_file_location(
            "release_policy_catalog_postgres_selftest",
            catalog_postgres_selftest_path,
        )
        assert (
            catalog_postgres_selftest_spec is not None
            and catalog_postgres_selftest_spec.loader is not None
        )
        catalog_postgres_selftest = importlib.util.module_from_spec(
            catalog_postgres_selftest_spec
        )
        sys.modules[catalog_postgres_selftest_spec.name] = catalog_postgres_selftest
        catalog_postgres_selftest_spec.loader.exec_module(catalog_postgres_selftest)
        self.assertEqual(
            catalog_postgres_selftest.EXPECTED_MANIFEST_COUNTS,
            {"migrations": 25, "tables": 95},
        )
        self.assertEqual(
            catalog_postgres_selftest.EXPECTED_CATALOG_COUNTS,
            {
                "tables": 95,
                "columns": 1159,
                "sequences": 93,
                "enums": 5,
                "constraints": 498,
                "primary_constraints": 95,
                "foreign_constraints": 145,
                "unique_constraints": 103,
                "check_constraints": 155,
                "indexes": 359,
                "constraint_backed_indexes": 198,
                "explicit_indexes": 161,
                "partial_indexes": 1,
            },
        )
        backend_main = (REPO_ROOT / "backend" / "app" / "main.py").read_text(
            encoding="utf-8"
        )
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
        self.assertNotIn("dict(os.environ)", deploy_launcher_source)
        for expand_selftest_required in (
            'OLD_BACKEND_SHA = "aefcf46198ed586753dae29a79e17964d5996e7f"',
            'OLD_HEAD = "0021_device_indicator_identity"',
            'CANDIDATE_HEAD = "0025_dietary_records"',
            '"0022_health_trust_contracts.py"',
            '"0023_trusted_medication_loop.py"',
            '"0024_health_profile_report_completion.py"',
            '"0025_dietary_records.py"',
            "safe_extract_git_archive",
            '"--format=custom"',
            '"--exit-on-error"',
            "stamp_materialized_old_head",
            "CREATE TABLE public.alembic_version",
            "canonicalize_dump_restore_catalog",
            "reference catalog Alembic boundary changed",
            "expects_alembic=True",
            "render_expand_transaction_runner",
            "fail_after_upgrade=True",
            "validate_expand_catalog_transition",
            "render_expand_old_app_compat_probe",
            "create_restore_volume",
            "capacity_and_initialize_restore_volume",
            "data_volume=restore_volume_name",
            "remove_restore_volume",
            "old_image_crud=true",
            "run_trusted_medication_contract_probe",
            "duplicate tenant idempotency key",
            "cross-tenant plan event",
            "non-temporal adverse-reaction attribution",
            "run_dietary_concurrency_contract_probe",
            "dietary concurrency fixture identity exceeds the real schema",
            "same-event text provider ran more than once",
            "same-event photo provider ran more than once",
            "different-event draft confirmation",
            "same-event record reuse",
            "same-event record update",
            "same-event record delete",
            "different-event record update",
            "different-event record delete",
            '"same_endpoint_conflicts": 5',
            '"long_statuses_verified": True',
        ):
            self.assertIn(expand_selftest_required, expand_postgres_selftest_source)
        for catalog_selftest_required in (
            '"migrations": 25',
            '"tables": 95',
            'EXPECTED_ALEMBIC_HEAD = "0025_dietary_records"',
            '"columns": 1159',
            '"constraints": 498',
            '"indexes": 359',
        ):
            self.assertIn(catalog_selftest_required, catalog_postgres_selftest_source)
        for launcher_required in (
            'LAUNCH_AUTHORITY = "/etc/xjie-production-deploy/launch-authority"',
            "BROKER_FD = 8",
            "LEGACY_LOCK_FD = 10",
            'LOCK_PARENT = "/run/lock"',
            'LEGACY_LOCK_DIRECTORY = "/home/mayl/.locks"',
            "os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW",
            'ANONYMOUS_PIPE_PATTERN = re.compile(r"pipe:\\[([0-9]+)\\]\\Z")',
            'MIGRATION_REVISION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\\Z")',
            'os.readlink(f"/proc/self/fd/{descriptor}")',
            'fail(purpose + " must be an anonymous pipe, not a named FIFO")',
            'require_anonymous_pipe(descriptor, "GitHub token stdin")',
            '"bundle-installer doctor authority"',
            "stable_root_file(LAUNCH_AUTHORITY, 0o400)",
            "fcntl.LOCK_EX | fcntl.LOCK_NB",
            "reject_live_lease(directory_descriptor)",
            "open_legacy_deployment_lock(principal)",
            "set_parent_death_signal(parent_pid)",
            "os.setsid()",
            "os.killpg(child_pid, signum)",
            "signal.pthread_sigmask(signal.SIG_SETMASK, [])",
            "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))",
            "disable_process_dumping()",
            "os.initgroups(DEPLOY_PRINCIPAL, principal.pw_gid)",
            "os.setgid(principal.pw_gid)",
            "os.setuid(principal.pw_uid)",
            '"XJIE_DEPLOY_BROKER_FD": str(BROKER_FD)',
            '"XJIE_DEPLOY_LEGACY_LOCK_FD": str(LEGACY_LOCK_FD)',
            "close_unapproved_descriptors({BROKER_FD, LEGACY_LOCK_FD})",
            "close_unapproved_descriptors(inherited_descriptors)",
            'raise SystemExit("deployment descriptor layout is unsafe")',
            "socket.SO_PASSCRED",
            "socket.SCM_CREDENTIALS",
            "sender_hierarchy != (child_pid, child_pid)",
            "broker_verify_official_candidate",
            "broker_validate_backend_junit",
            "schema-migration chain digest or final head is invalid",
            "gate.ensure_no_git_repository_redirects()",
            "gate.ensure_no_network_verification_redirects()",
            "gate.ensure_official_remote_tip(expected_sha, registry)",
            "gate.require_remote_quality_gate(expected_sha, registry)",
            "gate.require_merged_pull_request(expected_sha, registry)",
            "gate.require_all_branch_protections(",
            "expected_tests = gate._load_expected_backend_tests()",
            "expected_skips = gate.BACKEND_FULL_ALLOWED_SKIPS",
            "candidate backend exact inventory verified:",
            "os.execve(",
        ):
            self.assertIn(launcher_required, deploy_launcher_source)
        self.assertIsNone(
            re.search(
                r'identity\s*!=\s*\{\s*["\']executed["\']\s*:\s*\d+',
                deploy_launcher_source,
            ),
            "production launcher must derive backend evidence counts from the tracked inventory",
        )
        for selftest_required in (
            "def load_live_script_api(path, run_name, anchor_name):",
            "namespace = anchor.__globals__",
            "def test_read_until_line_reports_observed_tail():",
            "observed tail={tail!r}",
            "def test_docker_cleanup_harness_nounset_defaults():",
            'reference_server_role=""',
            "restore_volume_owned=0",
            "supervised_service_ids=()",
            "def test_credential_pipe_identity():",
            "os.mkfifo(fifo_path, 0o600)",
            'API["read_token_from_standard_input"](',
            'API["consume_installer_doctor_authority"](["--doctor"])',
            'GUARD_API["deployment_name"](',
            '"revision": "0023_candidate"',
            '"per-file migration digest drift"',
            '"non-linear migration chain"',
            "test_credential_pipe_identity()",
        ):
            self.assertIn(selftest_required, deploy_launcher_selftest_source)
        self.assertIn(
            'result.returncode == 143',
            deploy_launcher_selftest_source,
        )
        self.assertIn(
            'output == "NOUNSET_STATE_OK\\n"',
            deploy_launcher_selftest_source,
        )
        self.assertIn("observed[-8:]", deploy_launcher_selftest_source)
        self.assertIn("line[-512:]", deploy_launcher_selftest_source)
        self.assertLess(
            deploy_launcher_source.index("os.initgroups("),
            deploy_launcher_source.index("os.setgid("),
        )
        self.assertLess(
            deploy_launcher_source.index("os.setgid("),
            deploy_launcher_source.index("os.setuid("),
        )
        self.assertLess(
            deploy_launcher_source.index("os.setuid("),
            deploy_launcher_source.index("os.execve("),
        )
        launcher_probe = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import os,runpy,sys,tempfile; "
                "m=runpy.run_path(sys.argv[1],run_name='xjie_launcher_test'); "
                "m['os'].readlink=lambda p:'pipe:['+str(os.fstat(int(p.rsplit('/',1)[1])).st_ino)+']'; "
                "r,w=os.pipe(); os.write(w,b'synthetic-token\\0'); os.close(w); "
                "assert bytes(m['read_token_from_standard_input'](['a'*40,'deploy'],r))==b'synthetic-token'; "
                "os.close(r); "
                "f=tempfile.TemporaryFile(); "
                "failed=False; "
                "\ntry: m['read_token_from_standard_input'](['a'*40,'deploy'],f.fileno())"
                "\nexcept SystemExit: failed=True"
                "\nassert failed",
                str(deploy_launcher_path),
            ],
            check=False,
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(launcher_probe.returncode, 0, msg=launcher_probe.stdout)
        launcher_selftest_namespace_probe = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                "import runpy,sys; "
                "m=runpy.run_path(sys.argv[1],run_name='xjie_launcher_selftest_probe'); "
                "a=m['API']; g=m['GUARD_API']; "
                "assert a is a['broker_approve_expand_migration'].__globals__; "
                "assert g is g['deployment_name'].__globals__; "
                "m['test_read_until_line_reports_observed_tail'](); "
                "m['test_docker_cleanup_harness_nounset_defaults']()",
                str(deploy_launcher_selftest_path),
            ],
            check=False,
            env={},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(
            launcher_selftest_namespace_probe.returncode,
            0,
            msg=launcher_selftest_namespace_probe.stdout,
        )

        deploy_spec_path = REPO_ROOT / "backend" / "deploy" / "production_container.json"
        deploy_guard_path = (
            REPO_ROOT / "backend" / "deploy" / "production_deploy_guard.py"
        )
        deploy_guard_spec = importlib.util.spec_from_file_location(
            "release_policy_production_deploy_guard", deploy_guard_path
        )
        assert deploy_guard_spec is not None and deploy_guard_spec.loader is not None
        deploy_guard = importlib.util.module_from_spec(deploy_guard_spec)
        sys.modules[deploy_guard_spec.name] = deploy_guard
        deploy_guard_spec.loader.exec_module(deploy_guard)
        self.assertNotIn(
            "--file=-",
            deploy_guard.DEPLOY_ROLE_COMMANDS["schema-backup"][1],
        )
        deploy_guard_source = deploy_guard_path.read_text(encoding="utf-8")
        preserved_items = [{"name": "existing", "definition": "same"}]
        expanded_items = [
            *preserved_items,
            {"name": "declared_addition", "definition": "new"},
        ]
        old_item_map, expanded_item_map = deploy_guard._expand_require_preserved_items(
            preserved_items,
            expanded_items,
            "name",
            "test catalog item",
        )
        self.assertEqual(
            deploy_guard._expand_added_item_names(
                old_item_map,
                expanded_item_map,
                "test catalog item",
            ),
            {"declared_addition"},
        )
        self.assertIn(
            "owner_table not in declared_new_tables",
            deploy_guard_source,
        )
        for required_guard_primitive in (
            "os.O_EXCL",
            "os.O_NOFOLLOW",
            "os.fstat(descriptor)",
            "os.replace(",
            "os.fsync(parent_descriptor)",
        ):
            self.assertIn(required_guard_primitive, deploy_guard_source)
        expected_production_spec = {
            "schema_version": 2,
            "container_name": "xjie-api",
            "image_repository": "xjie-backend",
            "secret_env_file": "/home/mayl/.config/xjie/backend.env",
            "restart_policy": "unless-stopped",
            "published_ports": ["127.0.0.1:8000:8000"],
            "extra_hosts": ["host.docker.internal:host-gateway"],
            "supervised_roles": ["celery-worker", "celery-beat"],
            "database_probe_image": "postgres:16.14-alpine3.23@sha256:bb0628a764d870fed40e71423339e24111bed4a40b614ee68dcbd8981ed6474e",
            "container_health_url": "http://127.0.0.1:8000/healthz",
            "public_health_url": "https://www.jianjieaitech.com/healthz",
        }
        production_spec = json.loads(deploy_spec_path.read_text(encoding="utf-8"))
        self.assertEqual(production_spec, expected_production_spec)
        self.assertEqual(deploy_guard.PINNED_SPEC, expected_production_spec)
        self.assertEqual(deploy_guard.load_spec(deploy_spec_path), expected_production_spec)
        self.assertEqual(
            deploy_guard.JOURNAL_STATES,
            (
                "prepared",
                "old_stopped",
                "old_renamed",
                "candidate_renamed",
                "candidate_started",
            ),
        )
        expected_journal_keys = (
            "schema_version",
            "state",
            "expected_sha",
            "trusted_bundle_sha256",
            "container_name",
            "backup_name",
            "candidate_name",
            "old_container_id",
            "candidate_container_id",
            "old_image_id",
            "candidate_image_id",
        )
        self.assertEqual(deploy_guard.JOURNAL_SCHEMA_VERSION, 2)
        self.assertEqual(deploy_guard.JOURNAL_KEYS, expected_journal_keys)
        self.assertEqual(
            deploy_guard.emitted_spec_values(production_spec),
            [
                "xjie-api",
                "xjie-backend",
                "/home/mayl/.config/xjie/backend.env",
                "postgres:16.14-alpine3.23@sha256:bb0628a764d870fed40e71423339e24111bed4a40b614ee68dcbd8981ed6474e",
                "http://127.0.0.1:8000/healthz",
                "https://www.jianjieaitech.com/healthz",
            ],
        )
        widened_spec = copy.deepcopy(production_spec)
        widened_spec["published_ports"] = ["8000:8000"]
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.emitted_spec_values(widened_spec)

        with tempfile.TemporaryDirectory() as deployment_temp:
            deployment_root = Path(deployment_temp)
            spec_values_output = deployment_root / "spec-values.bin"
            deploy_guard.write_nul_records(
                spec_values_output,
                deploy_guard.emitted_spec_values(production_spec),
            )
            self.assertEqual(spec_values_output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                spec_values_output.read_bytes().split(b"\0"),
                [
                    b"xjie-api",
                    b"xjie-backend",
                    b"/home/mayl/.config/xjie/backend.env",
                    b"postgres:16.14-alpine3.23@sha256:bb0628a764d870fed40e71423339e24111bed4a40b614ee68dcbd8981ed6474e",
                    b"http://127.0.0.1:8000/healthz",
                    b"https://www.jianjieaitech.com/healthz",
                    b"",
                ],
            )
            emitted_spec_cli_output = deployment_root / "spec-values-cli.bin"
            with mock.patch("builtins.print") as emit_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "emit-spec",
                            "--spec", str(deploy_spec_path),
                            "--output", str(emitted_spec_cli_output),
                        ]
                    ),
                    0,
                )
                emit_print.assert_not_called()
            self.assertEqual(
                emitted_spec_cli_output.read_bytes(), spec_values_output.read_bytes()
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.write_nul_records(spec_values_output, ["must-not-overwrite"])
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.write_nul_records(
                    deployment_root / "nul-injection.bin", ["safe", "unsafe\0value"]
                )

            source_snapshot_root = deployment_root / "exact-source"
            (source_snapshot_root / "backend").mkdir(parents=True)
            regular_payload = b"print('exact source')\n"
            executable_payload = b"#!/bin/sh\nexit 0\n"
            regular_source = source_snapshot_root / "backend" / "app.py"
            executable_source = source_snapshot_root / "deploy.sh"
            regular_source.write_bytes(regular_payload)
            regular_source.chmod(0o600)
            executable_source.write_bytes(executable_payload)
            executable_source.chmod(0o700)

            def git_blob_id(payload):
                return hashlib.sha1(
                    b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
                ).hexdigest()

            tree_manifest = deployment_root / "exact-tree.bin"
            tree_manifest.write_bytes(
                b"100644 blob "
                + git_blob_id(regular_payload).encode("ascii")
                + b"\tbackend/app.py\0"
                + b"100755 blob "
                + git_blob_id(executable_payload).encode("ascii")
                + b"\tdeploy.sh\0"
            )
            tree_manifest.chmod(0o600)
            self.assertEqual(
                deploy_guard.validate_source_snapshot(
                    tree_manifest, source_snapshot_root
                ),
                2,
            )
            with mock.patch("builtins.print") as source_snapshot_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "validate-source-snapshot",
                            "--manifest", str(tree_manifest),
                            "--source-root", str(source_snapshot_root),
                        ]
                    ),
                    0,
                )
                source_snapshot_print.assert_called_once_with(
                    "source snapshot matches exact Git tree: files=2"
                )
            regular_source.write_bytes(b"$Format:%H$\n")
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.validate_source_snapshot(
                    tree_manifest, source_snapshot_root
                )
            regular_source.write_bytes(regular_payload)
            regular_source.unlink()
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.validate_source_snapshot(
                    tree_manifest, source_snapshot_root
                )
            regular_source.write_bytes(regular_payload)
            regular_source.chmod(0o600)
            extra_source = source_snapshot_root / "exported-only.txt"
            extra_source.write_text("unsafe", encoding="utf-8")
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.validate_source_snapshot(
                    tree_manifest, source_snapshot_root
                )
            extra_source.unlink()
            executable_source.chmod(0o600)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.validate_source_snapshot(
                    tree_manifest, source_snapshot_root
                )
            executable_source.chmod(0o700)
            hardlink_source = source_snapshot_root / "hardlink.txt"
            os.link(regular_source, hardlink_source)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.validate_source_snapshot(
                    tree_manifest, source_snapshot_root
                )
            hardlink_source.unlink()
            self.assertEqual(
                deploy_guard.validate_source_snapshot(
                    tree_manifest, source_snapshot_root
                ),
                2,
            )

            env_source = deployment_root / "backend.env"
            env_snapshot = deployment_root / "backend.snapshot.env"
            synthetic_env_payload = (
                b"DATABASE_URL=postgresql+psycopg://app:synthetic-app-password@app.invalid/xjie\n"
                b"DATABASE_PROBE_URL=postgresql+psycopg://probe:synthetic-password@app.invalid/xjie\n"
                b"DATABASE_MIGRATION_URL=postgresql+psycopg://migration:synthetic-migration-password@app.invalid/xjie\n"
                b"JWT_SECRET=synthetic-key\n"
            )
            synthetic_application_payload = (
                b"DATABASE_URL=postgresql+psycopg://app:synthetic-app-password@app.invalid/xjie\n"
                b"JWT_SECRET=synthetic-key\n"
            )
            env_source.write_bytes(synthetic_env_payload)
            env_source.chmod(0o600)
            snapshot_spec = copy.deepcopy(expected_production_spec)
            snapshot_spec["secret_env_file"] = str(env_source)
            with mock.patch.object(deploy_guard, "PINNED_SPEC", snapshot_spec):
                deploy_guard.snapshot_env_file(
                    snapshot_spec, str(env_source), env_snapshot
                )
            self.assertEqual(env_snapshot.read_bytes(), synthetic_application_payload)
            self.assertEqual(env_snapshot.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                deploy_guard.parse_env_file(env_snapshot),
                {
                    "DATABASE_URL": "postgresql+psycopg://app:synthetic-app-password@app.invalid/xjie",
                    "JWT_SECRET": "synthetic-key",
                },
            )
            probe_env_snapshot = deployment_root / "database-probe.snapshot.env"
            with mock.patch.object(deploy_guard, "PINNED_SPEC", snapshot_spec):
                deploy_guard.snapshot_database_probe_env_file(
                    snapshot_spec,
                    str(env_source),
                    env_snapshot,
                    probe_env_snapshot,
                )
            self.assertEqual(
                deploy_guard.parse_env_file(probe_env_snapshot),
                {
                    "PGHOST": "app.invalid",
                    "PGPORT": "5432",
                    "PGUSER": "probe",
                    "PGPASSWORD": "synthetic-password",
                    "PGDATABASE": "xjie",
                    "PGOPTIONS": "-c default_transaction_read_only=on",
                    "XJIE_EXPECTED_DATABASE": "xjie",
                },
            )
            self.assertNotIn(b"JWT_SECRET", probe_env_snapshot.read_bytes())
            self.assertNotIn(b"DATABASE_MIGRATION_URL", env_snapshot.read_bytes())
            self.assertNotIn(b"DATABASE_MIGRATION_URL", probe_env_snapshot.read_bytes())
            migration_env_snapshot = (
                deployment_root / "database-migration.snapshot.env"
            )
            with mock.patch.object(deploy_guard, "PINNED_SPEC", snapshot_spec):
                deploy_guard.snapshot_database_migration_env_file(
                    snapshot_spec,
                    str(env_source),
                    env_snapshot,
                    migration_env_snapshot,
                )
            self.assertEqual(
                deploy_guard.parse_env_file(migration_env_snapshot),
                {
                    "PGHOST": "app.invalid",
                    "PGPORT": "5432",
                    "PGUSER": "migration",
                    "PGPASSWORD": "synthetic-migration-password",
                    "PGDATABASE": "xjie",
                },
            )
            self.assertNotIn(b"JWT_SECRET", migration_env_snapshot.read_bytes())
            self.assertNotIn(b"DATABASE_URL", migration_env_snapshot.read_bytes())
            duplicate_migration_role_env = (
                deployment_root / "duplicate-migration-role.env"
            )
            duplicate_migration_role_env.write_bytes(
                synthetic_env_payload.replace(
                    b"migration:synthetic-migration-password",
                    b"probe:synthetic-migration-password",
                )
            )
            duplicate_migration_role_env.chmod(0o600)
            duplicate_migration_role_spec = copy.deepcopy(
                expected_production_spec
            )
            duplicate_migration_role_spec["secret_env_file"] = str(
                duplicate_migration_role_env
            )
            with mock.patch.object(
                deploy_guard,
                "PINNED_SPEC",
                duplicate_migration_role_spec,
            ):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.snapshot_database_migration_env_file(
                        duplicate_migration_role_spec,
                        str(duplicate_migration_role_env),
                        env_snapshot,
                        deployment_root / "duplicate-migration-role.snapshot.env",
                    )
            same_role_env = deployment_root / "same-role-backend.env"
            same_role_env.write_bytes(
                b"DATABASE_URL=postgresql+psycopg://app:synthetic-app-password@app.invalid/xjie\n"
                b"DATABASE_PROBE_URL=postgresql+psycopg://app:synthetic-probe-password@app.invalid/xjie\n"
                b"JWT_SECRET=synthetic-key\n"
            )
            same_role_env.chmod(0o600)
            same_role_spec = copy.deepcopy(expected_production_spec)
            same_role_spec["secret_env_file"] = str(same_role_env)
            with mock.patch.object(deploy_guard, "PINNED_SPEC", same_role_spec):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.snapshot_database_probe_env_file(
                        same_role_spec,
                        str(same_role_env),
                        env_snapshot,
                        deployment_root / "same-role-probe.snapshot.env",
                    )
            endpoint_variants = (
                (
                    "host",
                    "postgresql+psycopg://probe:synthetic-password@other.invalid/xjie",
                ),
                (
                    "port",
                    "postgresql+psycopg://probe:synthetic-password@app.invalid:5433/xjie",
                ),
                (
                    "database",
                    "postgresql+psycopg://probe:synthetic-password@app.invalid/other",
                ),
                (
                    "escaped-host",
                    "postgresql+psycopg://probe:synthetic-password@bad%20host.invalid/xjie",
                ),
                (
                    "illegal-label",
                    "postgresql+psycopg://probe:synthetic-password@-bad.invalid/xjie",
                ),
                (
                    "invalid-query-utf8",
                    "postgresql+psycopg://probe:synthetic-password@app.invalid/xjie?sslmode=%FF",
                ),
            )
            for endpoint_label, endpoint_url in endpoint_variants:
                endpoint_source = deployment_root / (
                    "endpoint-{0}.env".format(endpoint_label)
                )
                endpoint_source.write_bytes(
                    (
                        "DATABASE_URL=postgresql+psycopg://app:synthetic-app-password@app.invalid/xjie\n"
                        "DATABASE_PROBE_URL={0}\n"
                        "JWT_SECRET=synthetic-key\n"
                    ).format(endpoint_url).encode("utf-8")
                )
                endpoint_source.chmod(0o600)
                endpoint_spec = copy.deepcopy(expected_production_spec)
                endpoint_spec["secret_env_file"] = str(endpoint_source)
                with mock.patch.object(deploy_guard, "PINNED_SPEC", endpoint_spec):
                    with self.subTest(endpoint=endpoint_label), self.assertRaises(
                        deploy_guard.DeployGuardError
                    ):
                        deploy_guard.snapshot_database_probe_env_file(
                            endpoint_spec,
                            str(endpoint_source),
                            env_snapshot,
                            deployment_root
                            / ("endpoint-{0}.snapshot".format(endpoint_label)),
                        )
            changed_source = deployment_root / "changed-after-snapshot.env"
            changed_source.write_bytes(
                b"DATABASE_URL=postgresql+psycopg://app:synthetic-app-password@app.invalid/xjie\n"
                b"DATABASE_PROBE_URL=postgresql+psycopg://probe:synthetic-password@app.invalid/xjie\n"
                b"JWT_SECRET=changed-after-snapshot\n"
            )
            changed_source.chmod(0o600)
            changed_spec = copy.deepcopy(expected_production_spec)
            changed_spec["secret_env_file"] = str(changed_source)
            with mock.patch.object(deploy_guard, "PINNED_SPEC", changed_spec):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.snapshot_database_probe_env_file(
                        changed_spec,
                        str(changed_source),
                        env_snapshot,
                        deployment_root / "changed-source-probe.snapshot.env",
                    )
            with mock.patch.object(deploy_guard, "PINNED_SPEC", snapshot_spec):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.snapshot_env_file(
                        snapshot_spec, str(env_source), env_snapshot
                    )
            env_source.chmod(0o640)
            with mock.patch.object(deploy_guard, "PINNED_SPEC", snapshot_spec):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.snapshot_env_file(
                        snapshot_spec,
                        str(env_source),
                        deployment_root / "wrong-mode.snapshot",
                    )
            env_source.chmod(0o600)
            env_link = deployment_root / "backend-link.env"
            env_link.symlink_to(env_source)
            linked_spec = copy.deepcopy(snapshot_spec)
            linked_spec["secret_env_file"] = str(env_link)
            with mock.patch.object(deploy_guard, "PINNED_SPEC", linked_spec):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.snapshot_env_file(
                        linked_spec,
                        str(env_link),
                        deployment_root / "linked.snapshot",
                    )
            with mock.patch.object(
                deploy_guard.os, "geteuid", return_value=os.geteuid() + 1
            ):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.read_owner_only_bytes(
                        env_source, "synthetic env", maximum_bytes=1024
                    )
            env_hardlink = deployment_root / "backend-hardlink.env"
            os.link(env_source, env_hardlink)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.read_owner_only_bytes(
                    env_source, "synthetic env", maximum_bytes=1024
                )
            env_hardlink.unlink()
            real_fstat = os.fstat
            fstat_calls = []

            def changed_after_read(descriptor):
                metadata = real_fstat(descriptor)
                fstat_calls.append(descriptor)
                if len(fstat_calls) == 2:
                    changed = mock.Mock()
                    for attribute in (
                        "st_dev", "st_ino", "st_mode", "st_nlink", "st_uid",
                        "st_size", "st_mtime_ns", "st_ctime_ns",
                    ):
                        setattr(changed, attribute, getattr(metadata, attribute))
                    changed.st_mtime_ns += 1
                    return changed
                return metadata

            with mock.patch.object(
                deploy_guard.os, "fstat", side_effect=changed_after_read
            ):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.read_owner_only_bytes(
                        env_source, "synthetic env", maximum_bytes=1024
                    )

            cli_snapshot = deployment_root / "cli.snapshot.env"
            snapshot_spec_path = deployment_root / "snapshot-spec.json"
            snapshot_spec_path.write_text(
                json.dumps(snapshot_spec, ensure_ascii=False), encoding="utf-8"
            )
            with mock.patch.object(deploy_guard, "PINNED_SPEC", snapshot_spec), mock.patch(
                "builtins.print"
            ) as snapshot_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "snapshot-env",
                            "--spec", str(snapshot_spec_path),
                            "--source", str(env_source),
                            "--output", str(cli_snapshot),
                        ]
                    ),
                    0,
                )
                snapshot_print.assert_not_called()
            self.assertEqual(cli_snapshot.read_bytes(), synthetic_application_payload)
            cli_probe_snapshot = deployment_root / "cli.database-probe.env"
            with mock.patch.object(deploy_guard, "PINNED_SPEC", snapshot_spec), mock.patch(
                "builtins.print"
            ) as probe_snapshot_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "snapshot-database-probe-env",
                            "--spec", str(snapshot_spec_path),
                            "--source", str(env_source),
                            "--application-env", str(cli_snapshot),
                            "--output", str(cli_probe_snapshot),
                        ]
                    ),
                    0,
                )
                probe_snapshot_print.assert_not_called()
            self.assertEqual(
                cli_probe_snapshot.read_bytes(),
                b"PGHOST=app.invalid\n"
                b"PGPORT=5432\n"
                b"PGUSER=probe\n"
                b"PGPASSWORD=synthetic-password\n"
                b"PGDATABASE=xjie\n"
                b"PGOPTIONS=-c default_transaction_read_only=on\n"
                b"XJIE_EXPECTED_DATABASE=xjie\n",
            )

            def layer_tar(entries):
                output = io.BytesIO()
                with tarfile.open(
                    fileobj=output, mode="w", format=tarfile.PAX_FORMAT
                ) as archive:
                    for entry in entries:
                        info = tarfile.TarInfo(entry["path"])
                        kind = entry.get("kind", "file")
                        if kind == "file":
                            payload = entry.get("payload", b"")
                            info.size = len(payload)
                            archive.addfile(info, io.BytesIO(payload))
                        elif kind == "directory":
                            info.type = tarfile.DIRTYPE
                            archive.addfile(info)
                        elif kind == "symlink":
                            info.type = tarfile.SYMTYPE
                            info.linkname = entry["target"]
                            archive.addfile(info)
                        elif kind == "character":
                            info.type = tarfile.CHRTYPE
                            info.devmajor = entry.get("devmajor", 1)
                            info.devminor = entry.get("devminor", 3)
                            archive.addfile(info)
                        else:
                            raise AssertionError(kind)
                return output.getvalue()

            image_counter = 0

            def docker_save_fixture(entries, *, image_env=None):
                nonlocal image_counter
                image_counter += 1
                config_payload = json.dumps(
                    {"config": {"Env": image_env or ["PATH=/usr/local/bin"]}},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                config_digest = hashlib.sha256(config_payload).hexdigest()
                image_id = "sha256:" + config_digest
                config_name = config_digest + ".json"
                layer_name = "layer-{0}/layer.tar".format(image_counter)
                manifest_payload = json.dumps(
                    [
                        {
                            "Config": config_name,
                            "RepoTags": ["xjie-backend:test"],
                            "Layers": [layer_name],
                        }
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
                archive_path = deployment_root / "image-{0}.tar".format(image_counter)
                with tarfile.open(archive_path, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                    for name, payload in (
                        (config_name, config_payload),
                        (layer_name, layer_tar(entries)),
                        ("manifest.json", manifest_payload),
                    ):
                        info = tarfile.TarInfo(name)
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))
                archive_path.chmod(0o600)
                inspect_path = deployment_root / "image-{0}.json".format(image_counter)
                inspect_payload = [
                    {
                        "Id": image_id,
                        "Config": {"Env": image_env or ["PATH=/usr/local/bin"]},
                    }
                ]
                inspect_path.write_text(json.dumps(inspect_payload), encoding="utf-8")
                inspect_path.chmod(0o600)
                return archive_path, inspect_path, inspect_payload[0], image_id

            safe_archive, safe_inspect_path, safe_inspect, safe_image_id = (
                docker_save_fixture(
                    [
                        {"path": "app/main.py", "payload": b"print('safe')\n"},
                        {
                            "path": "usr/local/lib/python/site-packages/certifi/cacert.pem",
                            "payload": b"-----BEGIN CERTIFICATE-----\npublic-ca\n",
                        },
                        {"path": "var/run", "kind": "symlink", "target": "/run"},
                    ]
                )
            )
            runtime_environment = deploy_guard.parse_env_file(env_snapshot)
            self.assertEqual(
                deploy_guard.validate_candidate_image_secret_boundary(
                    safe_inspect, runtime_environment, safe_image_id
                ),
                safe_image_id,
            )
            deploy_guard.scan_owner_only_image_archive(
                safe_archive, runtime_environment, safe_image_id
            )
            with mock.patch("builtins.print") as scan_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "scan-image",
                            "--image-inspect", str(safe_inspect_path),
                            "--image-archive", str(safe_archive),
                            "--env-file", str(env_snapshot),
                            "--expected-image-id", safe_image_id,
                        ]
                    ),
                    0,
                )
                scan_print.assert_not_called()

            for label, image_environment in (
                (
                    "runtime key baked into Config.Env",
                    ["PATH=/usr/local/bin", "DATABASE_URL=baked-value"],
                ),
                (
                    "duplicate Config.Env key",
                    ["PATH=/usr/local/bin", "PATH=/second-location"],
                ),
                (
                    "unrelated sensitive Config.Env key",
                    ["PATH=/usr/local/bin", "UNRELATED_API_KEY=hardcoded-secret"],
                ),
            ):
                _, _, invalid_inspect, invalid_image_id = docker_save_fixture(
                    [{"path": "app/main.py", "payload": b"safe\n"}],
                    image_env=image_environment,
                )
                with self.subTest(image_environment_boundary=label), self.assertRaises(
                    deploy_guard.DeployGuardError
                ):
                    deploy_guard.validate_candidate_image_secret_boundary(
                        invalid_inspect, runtime_environment, invalid_image_id
                    )

            unsafe_layer_cases = (
                (
                    "marker after former four MiB prefix",
                    [
                        {
                            "path": "opt/late.bin",
                            "payload": b"x" * (4 * 1024 * 1024 + 17)
                            + b"-----BEGIN PRIVATE KEY",
                        }
                    ],
                ),
                (
                    "path traversal",
                    [{"path": "../escape", "payload": b"unsafe"}],
                ),
                (
                    "unsafe link traversal",
                    [
                        {
                            "path": "app/escape",
                            "kind": "symlink",
                            "target": "../../outside",
                        }
                    ],
                ),
                (
                    "special device",
                    [{"path": "app/device", "kind": "character"}],
                ),
                (
                    "duplicate path",
                    [
                        {"path": "app/repeated", "payload": b"first"},
                        {"path": "app/repeated", "payload": b"second"},
                    ],
                ),
                (
                    "forbidden env filename",
                    [{"path": "opt/service/.env", "payload": b"not-a-secret"}],
                ),
            )
            for label, entries in unsafe_layer_cases:
                archive_path, _, _, image_id = docker_save_fixture(entries)
                with self.subTest(image_archive_boundary=label), self.assertRaises(
                    deploy_guard.DeployGuardError
                ):
                    deploy_guard.scan_owner_only_image_archive(
                        archive_path, runtime_environment, image_id
                    )

            with mock.patch.object(
                deploy_guard,
                "MAX_IMAGE_ARCHIVE_BYTES",
                safe_archive.stat().st_size - 1,
            ):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.scan_owner_only_image_archive(
                        safe_archive, runtime_environment, safe_image_id
                    )

            safe_archive.chmod(0o640)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.scan_owner_only_image_archive(
                    safe_archive, runtime_environment, safe_image_id
                )
            safe_archive.chmod(0o600)

            expected_sha = "a" * 40
            old_image_id = "sha256:" + "1" * 64
            candidate_image_id = "sha256:" + "2" * 64
            image_reference = "xjie-backend:main-" + expected_sha
            deployment_run_id = "b" * 32
            snapshot_path = str(env_snapshot)
            self.assertEqual(
                deploy_guard.deployment_name(deployment_run_id, "schema-old"),
                "xjie-api-deploy-{0}-schema-old".format(deployment_run_id),
            )
            candidate_name = "xjie-api-deploy-{0}-candidate".format(
                deployment_run_id
            )
            candidate_args = deploy_guard.create_arguments(
                production_spec,
                candidate_name,
                candidate_image_id,
                snapshot_path,
                expected_sha,
                image_reference=image_reference,
                env_source=production_spec["secret_env_file"],
                run_id=deployment_run_id,
                role="candidate",
            )
            self.assertEqual(
                candidate_args,
                [
                    "container", "create", "--name", candidate_name,
                    "--env-file", snapshot_path,
                    "--restart", "unless-stopped",
                    "--publish", "127.0.0.1:8000:8000",
                    "--add-host", "host.docker.internal:host-gateway",
                    *deploy_guard.deployment_label_arguments(
                        candidate_name,
                        candidate_image_id,
                        expected_sha,
                        deployment_run_id,
                        "candidate",
                    ),
                    candidate_image_id,
                ],
            )
            self.assertEqual(
                deploy_guard.SUPERVISED_SERVICE_ROLES,
                frozenset({"celery-worker", "celery-beat"}),
            )
            worker_name = deploy_guard.deployment_name(
                deployment_run_id, "celery-worker"
            )
            worker_command = deploy_guard.DEPLOY_ROLE_COMMANDS["celery-worker"][1]
            worker_args = deploy_guard.create_arguments(
                production_spec,
                worker_name,
                candidate_image_id,
                snapshot_path,
                expected_sha,
                list(worker_command),
                image_reference=image_reference,
                env_source=production_spec["secret_env_file"],
                run_id=deployment_run_id,
                role="celery-worker",
            )
            self.assertIn("--restart", worker_args)
            self.assertNotIn("--publish", worker_args)
            self.assertIn("--read-only", worker_args)
            self.assertEqual(worker_args[-len(worker_command) :], list(worker_command))
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.create_arguments(
                    production_spec,
                    worker_name,
                    candidate_image_id,
                    snapshot_path,
                    expected_sha,
                    [*worker_command[:-1], "--without-heartbeat"],
                    image_reference=image_reference,
                    env_source=production_spec["secret_env_file"],
                    run_id=deployment_run_id,
                    role="celery-worker",
                )
            heads_name = "xjie-api-deploy-{0}-alembic-heads".format(
                deployment_run_id
            )
            one_shot_args = deploy_guard.create_arguments(
                production_spec,
                heads_name,
                candidate_image_id,
                snapshot_path,
                expected_sha,
                ["alembic", "heads", "--verbose"],
                image_reference=image_reference,
                env_source=production_spec["secret_env_file"],
                run_id=deployment_run_id,
                role="alembic-heads",
            )
            self.assertNotIn("--restart", one_shot_args)
            self.assertNotIn("--publish", one_shot_args)
            self.assertEqual(
                one_shot_args[-4:],
                [candidate_image_id, "alembic", "heads", "--verbose"],
            )
            database_schema_name = "xjie-api-deploy-{0}-database-schema".format(
                deployment_run_id
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.create_arguments(
                    production_spec,
                    database_schema_name,
                    candidate_image_id,
                    snapshot_path,
                    expected_sha,
                    [
                        "--no-psqlrc", "--quiet", "--tuples-only", "--no-align",
                        "--set", "ON_ERROR_STOP=1",
                    ],
                    image_reference=image_reference,
                    env_source=production_spec["secret_env_file"],
                    run_id=deployment_run_id,
                    role="database-schema",
                )
            lifecycle_cli_output = deployment_root / "lifecycle-labels.bin"
            with mock.patch("builtins.print") as lifecycle_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "emit-lifecycle-labels",
                            "--name", candidate_name,
                            "--image", candidate_image_id,
                            "--expected-sha", expected_sha,
                            "--run-id", deployment_run_id,
                            "--role", "candidate",
                            "--output", str(lifecycle_cli_output),
                        ]
                    ),
                    0,
                )
                lifecycle_print.assert_not_called()
            self.assertEqual(
                lifecycle_cli_output.read_bytes().split(b"\0")[:-1],
                [
                    item.encode("utf-8")
                    for item in deploy_guard.deployment_label_arguments(
                        candidate_name,
                        candidate_image_id,
                        expected_sha,
                        deployment_run_id,
                        "candidate",
                    )
                ],
            )
            for label, overrides in (
                ("foreign container name", {"name": "other-api-candidate"}),
                ("mutable image tag", {"image": image_reference}),
                ("foreign image reference", {"image_reference": "other:main-" + expected_sha}),
                ("foreign env source", {"env_source": "/tmp/other.env"}),
                ("unsnapshotted env", {"env_file": production_spec["secret_env_file"]}),
                ("wrong run ID type", {"run_id": True}),
                ("wrong lifecycle role", {"role": "alembic-current"}),
            ):
                arguments = {
                    "spec": production_spec,
                    "name": candidate_name,
                    "image": candidate_image_id,
                    "env_file": snapshot_path,
                    "expected_sha": expected_sha,
                    "image_reference": image_reference,
                    "env_source": production_spec["secret_env_file"],
                    "run_id": deployment_run_id,
                    "role": "candidate",
                }
                arguments.update(overrides)
                with self.subTest(create_identity=label), self.assertRaises(
                    deploy_guard.DeployGuardError
                ):
                    deploy_guard.create_arguments(**arguments)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.create_arguments(
                    production_spec,
                    heads_name,
                    candidate_image_id,
                    snapshot_path,
                    expected_sha,
                    ["alembic", "upgrade", "head"],
                    image_reference=image_reference,
                    env_source=production_spec["secret_env_file"],
                    run_id=deployment_run_id,
                    role="alembic-heads",
                )

            journal_path = deployment_root / "deployment-journal.json"
            journal = {
                "schema_version": deploy_guard.JOURNAL_SCHEMA_VERSION,
                "state": "prepared",
                "expected_sha": expected_sha,
                "trusted_bundle_sha256": "9" * 64,
                "container_name": "xjie-api",
                "backup_name": "xjie-api-backup-main-a",
                "candidate_name": "xjie-api-candidate-a",
                "old_container_id": "3" * 64,
                "candidate_container_id": "4" * 64,
                "old_image_id": old_image_id,
                "candidate_image_id": candidate_image_id,
            }
            deploy_guard.write_journal(journal_path, journal)
            self.assertEqual(journal_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(tuple(json.loads(journal_path.read_text())), deploy_guard.JOURNAL_KEYS)
            self.assertEqual(deploy_guard.load_journal(journal_path), journal)
            for state in (
                "old_stopped",
                "old_renamed",
                "candidate_renamed",
                "candidate_started",
            ):
                journal = {**journal, "state": state}
                deploy_guard.write_journal(journal_path, journal)
                self.assertEqual(deploy_guard.load_journal(journal_path), journal)
            journal_values_path = deployment_root / "journal-values.bin"
            deploy_guard.write_nul_records(
                journal_values_path,
                deploy_guard.emitted_journal_values(journal),
            )
            self.assertEqual(journal_values_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                journal_values_path.read_bytes().split(b"\0")[:-1],
                [str(journal[key]).encode("utf-8") for key in (
                    "state",
                    "expected_sha",
                    "trusted_bundle_sha256",
                    "container_name",
                    "backup_name",
                    "candidate_name",
                    "old_container_id",
                    "candidate_container_id",
                    "old_image_id",
                    "candidate_image_id",
                )],
            )
            invalid_journal_path = deployment_root / "invalid-journal.json"
            prepared_journal = {**journal, "state": "prepared"}
            deploy_guard.write_journal(invalid_journal_path, prepared_journal)
            self.assertEqual(
                list(deployment_root.glob(".invalid-journal.json.tmp.*")), []
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.write_journal(
                    invalid_journal_path,
                    {**prepared_journal, "state": "candidate_renamed"},
                )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.write_journal(
                    invalid_journal_path,
                    {**prepared_journal, "state": "old_stopped", "backup_name": "xjie-api-backup-changed"},
                )
            for invalid_bundle_digest in (True, "9" * 63, "A" * 64):
                with self.subTest(
                    invalid_journal_bundle_digest=invalid_bundle_digest
                ), self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.validate_journal(
                        {
                            **prepared_journal,
                            "trusted_bundle_sha256": invalid_bundle_digest,
                        }
                    )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.write_journal(
                    invalid_journal_path,
                    {
                        **prepared_journal,
                        "state": "old_stopped",
                        "trusted_bundle_sha256": "8" * 64,
                    },
                )
            invalid_journal_path.chmod(0o644)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.load_journal(invalid_journal_path)
            invalid_journal_path.chmod(0o600)
            journal_link = deployment_root / "journal-link.json"
            journal_link.symlink_to(invalid_journal_path)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.load_journal(journal_link)

            self.assertEqual(
                deploy_guard.RECOVERY_ACTIONS,
                (
                    "stop_official_candidate",
                    "quarantine_official_candidate",
                    "rename_backup_to_official",
                    "start_official",
                    "verify_named_candidate_quarantined",
                    "verify_official_old",
                ),
            )

            def recovery_inspect(name, container_id, image_id, running):
                return {
                    "Id": container_id,
                    "Image": image_id,
                    "Name": "/" + name,
                    "State": {"Running": running},
                }

            official_old_running = recovery_inspect(
                "xjie-api", "3" * 64, old_image_id, True
            )
            official_old_stopped = recovery_inspect(
                "xjie-api", "3" * 64, old_image_id, False
            )
            backup_old = recovery_inspect(
                "xjie-api-backup-main-a", "3" * 64, old_image_id, False
            )
            named_candidate = recovery_inspect(
                "xjie-api-candidate-a", "4" * 64, candidate_image_id, False
            )
            official_candidate_stopped = recovery_inspect(
                "xjie-api", "4" * 64, candidate_image_id, False
            )
            official_candidate_running = recovery_inspect(
                "xjie-api", "4" * 64, candidate_image_id, True
            )
            recovery_cases = (
                (
                    "prepared",
                    official_old_running,
                    None,
                    named_candidate,
                    ["verify_named_candidate_quarantined", "verify_official_old"],
                ),
                (
                    "old_stopped",
                    official_old_stopped,
                    None,
                    named_candidate,
                    [
                        "start_official",
                        "verify_named_candidate_quarantined",
                        "verify_official_old",
                    ],
                ),
                (
                    "old_renamed",
                    None,
                    backup_old,
                    named_candidate,
                    [
                        "rename_backup_to_official",
                        "start_official",
                        "verify_named_candidate_quarantined",
                        "verify_official_old",
                    ],
                ),
                (
                    "candidate_renamed",
                    official_candidate_stopped,
                    backup_old,
                    None,
                    [
                        "quarantine_official_candidate",
                        "rename_backup_to_official",
                        "start_official",
                        "verify_named_candidate_quarantined",
                        "verify_official_old",
                    ],
                ),
                (
                    "candidate_started",
                    official_candidate_running,
                    backup_old,
                    None,
                    [
                        "stop_official_candidate",
                        "quarantine_official_candidate",
                        "rename_backup_to_official",
                        "start_official",
                        "verify_named_candidate_quarantined",
                        "verify_official_old",
                    ],
                ),
            )
            for state, official, backup, candidate, expected_actions in recovery_cases:
                with self.subTest(recovery_state=state):
                    self.assertEqual(
                        deploy_guard.plan_recovery(
                            {**prepared_journal, "state": state},
                            official=official,
                            backup=backup,
                            named_candidate=candidate,
                        ),
                        expected_actions,
                    )

            corrupt_backup = recovery_inspect(
                "xjie-api-backup-main-a", "5" * 64, old_image_id, False
            )
            for label, backup in (
                ("missing backup", None),
                ("corrupt backup", corrupt_backup),
            ):
                with self.subTest(healthy_candidate_without_old=label), self.assertRaises(
                    deploy_guard.DeployGuardError
                ):
                    deploy_guard.plan_recovery(
                        {**prepared_journal, "state": "candidate_started"},
                        official=official_candidate_running,
                        backup=backup,
                    )
            unknown_official = recovery_inspect(
                "xjie-api", "6" * 64, old_image_id, True
            )
            invalid_running = copy.deepcopy(official_old_running)
            invalid_running["State"]["Running"] = 1
            for label, official in (
                ("unknown identity", unknown_official),
                ("non-boolean Running", invalid_running),
            ):
                with self.subTest(invalid_recovery_inspect=label), self.assertRaises(
                    deploy_guard.DeployGuardError
                ):
                    deploy_guard.plan_recovery(
                        prepared_journal,
                        official=official,
                        named_candidate=named_candidate,
                    )

            official_path = deployment_root / "official.json"
            candidate_path = deployment_root / "named-candidate.json"
            official_path.write_text(json.dumps([official_old_running]), encoding="utf-8")
            candidate_path.write_text(json.dumps([named_candidate]), encoding="utf-8")
            recovery_output = deployment_root / "recovery-plan.bin"
            self.assertEqual(
                deploy_guard.main(
                    [
                        "plan-recovery",
                        "--journal", str(invalid_journal_path),
                        "--official", str(official_path),
                        "--named-candidate", str(candidate_path),
                        "--output", str(recovery_output),
                    ]
                ),
                0,
            )
            self.assertEqual(
                recovery_output.read_bytes().split(b"\0")[:-1],
                [b"verify_named_candidate_quarantined", b"verify_official_old"],
            )
            unsafe_output = deployment_root / "unsafe-recovery-plan.bin"
            healthy_candidate_path = deployment_root / "healthy-candidate.json"
            healthy_candidate_path.write_text(
                json.dumps([official_candidate_running]), encoding="utf-8"
            )
            with mock.patch("builtins.print"):
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "plan-recovery",
                            "--journal", str(journal_path),
                            "--official", str(healthy_candidate_path),
                            "--output", str(unsafe_output),
                        ]
                    ),
                    1,
                )
            self.assertFalse(unsafe_output.exists())
            deploy_guard.clear_journal(journal_path)
            self.assertFalse(journal_path.exists())

            cli_journal_path = deployment_root / "cli-journal.json"
            cli_journal_output = deployment_root / "cli-journal.bin"
            journal_cli_identity = [
                "--expected-sha", expected_sha,
                "--trusted-bundle-sha256", "9" * 64,
                "--container-name", "xjie-api",
                "--backup-name", "xjie-api-backup-main-a",
                "--candidate-name", "xjie-api-candidate-a",
                "--old-container-id", "3" * 64,
                "--candidate-container-id", "4" * 64,
                "--old-image-id", old_image_id,
                "--candidate-image-id", candidate_image_id,
            ]
            self.assertEqual(
                deploy_guard.main(
                    [
                        "write-journal",
                        "--journal", str(cli_journal_path),
                        "--state", "prepared",
                        *journal_cli_identity,
                    ]
                ),
                0,
            )
            self.assertEqual(
                deploy_guard.main(
                    [
                        "read-journal",
                        "--journal", str(cli_journal_path),
                        "--output", str(cli_journal_output),
                    ]
                ),
                0,
            )
            self.assertEqual(
                cli_journal_output.read_bytes().split(b"\0")[:-1],
                [str(prepared_journal[key]).encode("utf-8") for key in expected_journal_keys[1:]],
            )
            self.assertEqual(
                deploy_guard.main(
                    ["clear-journal", "--journal", str(cli_journal_path)]
                ),
                0,
            )
            self.assertFalse(cli_journal_path.exists())

            orphan_run_id = "d" * 32
            reference_image_id = "sha256:" + "4" * 64
            reference_password = "a" * 64
            reference_socket_source = (
                "/dev/shm/xjie-deploy-1000/runtime/reference-pg-socket"
            )

            def orphan_inspect(
                role,
                identity_character,
                *,
                running=False,
                current_name=None,
                revision=expected_sha,
                image_id=candidate_image_id,
                run_id=orphan_run_id,
            ):
                if (
                    image_id == candidate_image_id
                    and role in (
                        "schema-reference-server",
                        "schema-reference-catalog",
                        "schema-backup",
                        "schema-backup-toc",
                        "schema-restore",
                        "schema-restore-capacity",
                        "schema-restore-volume-init",
                        "schema-restore-server",
                    )
                ):
                    image_id = reference_image_id
                original_name = "xjie-api-deploy-{0}-{1}".format(
                    run_id, role
                )
                entrypoint, command = (
                    (None, deploy_guard.CANDIDATE_COMMAND)
                    if role == "candidate"
                    else deploy_guard.DEPLOY_ROLE_COMMANDS[role]
                )
                interactive = role in deploy_guard.INTERACTIVE_ROLES
                hardened = role in deploy_guard.HARDENED_PROBE_ROLES
                isolated = role in deploy_guard.ISOLATED_NETWORK_ROLES
                image_environment = [
                    "PATH=/usr/local/bin:/usr/bin",
                    "PYTHONDONTWRITEBYTECODE=1",
                    "PYTHONUNBUFFERED=1",
                ]
                environment = list(image_environment)
                if role in ("schema-reference-server", "schema-restore-server"):
                    environment = [
                        "PATH=/usr/local/bin:/usr/bin",
                        "PGDATA=/var/lib/postgresql/data/pgdata",
                        "POSTGRES_USER=xjie_reference",
                        "POSTGRES_PASSWORD={0}".format(reference_password),
                        "POSTGRES_DB=xjie_reference",
                        "POSTGRES_INITDB_ARGS=--auth-local=scram-sha-256 --auth-host=scram-sha-256",
                    ]
                elif role == "schema-reference-materializer":
                    environment.append(
                        "XJIE_REFERENCE_DATABASE_URL="
                        "postgresql+psycopg://xjie_reference:{0}"
                        "@/xjie_reference?host=/var/run/postgresql".format(
                            reference_password
                        )
                    )
                elif role == "schema-reference-catalog":
                    environment = [
                        "PATH=/usr/local/bin:/usr/bin",
                        "PGDATA=/var/lib/postgresql/data",
                        "PGHOST=/var/run/postgresql",
                        "PGPORT=5432",
                        "PGUSER=xjie_reference",
                        "PGPASSWORD={0}".format(reference_password),
                        "PGDATABASE=xjie_reference",
                        "PGOPTIONS=-c default_transaction_read_only=on",
                        "XJIE_EXPECTED_DATABASE=xjie_reference",
                    ]
                elif role == "database-schema":
                    environment = [
                        "PATH=/usr/local/bin:/usr/bin",
                        "PGDATA=/var/lib/postgresql/data",
                        "PGHOST=synthetic-db.invalid",
                        "PGPORT=5432",
                        "PGUSER=probe",
                        "PGPASSWORD=synthetic-password",
                        "PGDATABASE=xjie",
                        "PGOPTIONS=-c default_transaction_read_only=on",
                        "XJIE_EXPECTED_DATABASE=xjie",
                    ]
                elif role in deploy_guard.PRODUCTION_MIGRATION_ROLES:
                    environment = [
                        "PATH=/usr/local/bin:/usr/bin",
                        "PGDATA=/var/lib/postgresql/data",
                        "PGHOST=synthetic-db.invalid",
                        "PGPORT=5432",
                        "PGUSER=migration",
                        "PGPASSWORD=synthetic-migration-password",
                        "PGDATABASE=xjie",
                    ]
                    if role == "schema-migration-production":
                        environment.extend(
                            [
                                "PYTHONDONTWRITEBYTECODE=1",
                                "PYTHONUNBUFFERED=1",
                            ]
                        )
                elif role in deploy_guard.EXPAND_SOCKET_ROLES:
                    environment = [
                        "PATH=/usr/local/bin:/usr/bin",
                        "PGHOST=/var/run/postgresql",
                        "PGPORT=5432",
                        "PGUSER={0}".format(
                            "xjie_reference"
                            if role == "schema-restore"
                            else "xjie_migration_rehearsal"
                        ),
                        "PGPASSWORD={0}".format(
                            reference_password
                            if role == "schema-restore"
                            else "b" * 64
                        ),
                        "PGDATABASE=xjie_reference",
                    ]
                    if role != "schema-restore":
                        environment.extend(
                            [
                                "PYTHONDONTWRITEBYTECODE=1",
                                "PYTHONUNBUFFERED=1",
                            ]
                        )
                elif role == "schema-backup-toc":
                    environment = ["PATH=/usr/local/bin:/usr/bin"]
                elif role in (
                    "schema-restore-capacity",
                    "schema-restore-volume-init",
                ):
                    environment = [
                        "PATH=/usr/local/bin:/usr/bin",
                        "PGDATA=/var/lib/postgresql/data",
                    ]
                elif role in deploy_guard.RUNTIME_ENV_ROLES:
                    environment.append(
                        "DATABASE_URL=postgresql+psycopg://synthetic-db.invalid/xjie"
                    )
                host_config = {
                    "RestartPolicy": {
                        "Name": (
                            "unless-stopped"
                            if role in deploy_guard.LONG_RUNNING_ROLES
                            else "no"
                        ),
                        "MaximumRetryCount": 0,
                    },
                    "PortBindings": (
                        {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}
                        if role == "candidate"
                        else {}
                    ),
                    "ExtraHosts": (
                        ["host.docker.internal:host-gateway"]
                        if role in deploy_guard.RUNTIME_ENV_ROLES
                        or role in deploy_guard.PRODUCTION_MIGRATION_ROLES
                        else None
                    ),
                    "NetworkMode": "none" if isolated else "bridge",
                    "ReadonlyRootfs": hardened,
                    "AutoRemove": role in deploy_guard.AUTO_REMOVE_ROLES,
                    "Privileged": False,
                    "PublishAllPorts": False,
                    "Binds": None,
                    "Tmpfs": (
                        dict(deploy_guard.DATABASE_PROBE_TMPFS)
                        if role == "database-schema"
                        else dict(deploy_guard.REFERENCE_SERVER_TMPFS)
                        if role == "schema-reference-server"
                        else dict(deploy_guard.RESTORE_SERVER_TMPFS)
                        if role == "schema-restore-server"
                        else dict(deploy_guard.REFERENCE_MATERIALIZER_TMPFS)
                        if role == "schema-reference-materializer"
                        else dict(deploy_guard.REFERENCE_CATALOG_TMPFS)
                        if role == "schema-reference-catalog"
                        else dict(deploy_guard.SUPERVISED_SERVICE_TMPFS)
                        if role in deploy_guard.SUPERVISED_SERVICE_ROLES
                        else dict(deploy_guard.SCHEMA_PROBE_TMPFS)
                        if hardened
                        else None
                    ),
                    "CapAdd": (
                        ["CHOWN"]
                        if role == "schema-restore-volume-init"
                        else None
                    ),
                    "CapDrop": ["ALL"] if hardened else None,
                    "SecurityOpt": ["no-new-privileges"] if hardened else None,
                    "DeviceCgroupRules": None,
                    "DeviceRequests": None,
                    "Devices": None,
                    "Links": None,
                    "VolumesFrom": None,
                }
                constrained_resources = deploy_guard.REFERENCE_ROLE_RESOURCES.get(role)
                if constrained_resources is not None:
                    _, _, memory_limit, pids_limit = constrained_resources
                    host_config.update(
                        Memory=memory_limit,
                        MemorySwap=memory_limit,
                        PidsLimit=pids_limit,
                    )
                if role in deploy_guard.REFERENCE_SCHEMA_ROLES or role in (
                    deploy_guard.EXPAND_SOCKET_ROLES
                    | {"schema-backup-toc"}
                    | deploy_guard.RESTORE_VOLUME_CONTAINER_ROLES
                ):
                    host_config["LogConfig"] = {"Type": "none", "Config": {}}
                container_id = (
                    identity_character
                    if re.fullmatch(r"[0-9a-f]{64}", identity_character)
                    else identity_character * 64
                )
                network_name = "none" if isolated else "bridge"
                if role in deploy_guard.REFERENCE_SCHEMA_ROLES or role in (
                    deploy_guard.EXPAND_SOCKET_ROLES | {"schema-restore-server"}
                ):
                    mount_read_only = role not in (
                        "schema-reference-server",
                        "schema-restore-server",
                    )
                    mounts = [
                        {
                            "Type": "bind",
                            "Source": reference_socket_source,
                            "Destination": "/var/run/postgresql",
                            "Mode": "ro" if mount_read_only else "",
                            "RW": not mount_read_only,
                            "Propagation": "rprivate",
                        }
                    ]
                else:
                    mounts = []
                if role in deploy_guard.RESTORE_VOLUME_CONTAINER_ROLES:
                    volume_read_only = role == "schema-restore-capacity"
                    mounts.append(
                        {
                            "Type": "volume",
                            "Name": deploy_guard.deployment_name(
                                run_id,
                                deploy_guard.RESTORE_VOLUME_ROLE,
                            ),
                            "Source": (
                                "/var/lib/docker/volumes/"
                                + deploy_guard.deployment_name(
                                    run_id,
                                    deploy_guard.RESTORE_VOLUME_ROLE,
                                )
                                + "/_data"
                            ),
                            "Destination": "/var/lib/postgresql/data",
                            "Driver": "local",
                            "Mode": "ro" if volume_read_only else "",
                            "RW": not volume_read_only,
                            "Propagation": "",
                        }
                    )
                return {
                    "Id": container_id,
                    "Name": "/" + (current_name or original_name),
                    "Image": image_id,
                    "Config": {
                        "Image": image_id,
                        "Hostname": container_id[:12],
                        "User": (
                            constrained_resources[0]
                            if constrained_resources is not None
                            else ""
                        ),
                        "StopTimeout": (
                            constrained_resources[1]
                            if constrained_resources is not None
                            else None
                        ),
                        "Entrypoint": None if entrypoint is None else list(entrypoint),
                        "Cmd": list(command),
                        "AttachStdin": interactive,
                        "AttachStdout": True,
                        "AttachStderr": True,
                        "OpenStdin": interactive,
                        "StdinOnce": interactive,
                        "Tty": False,
                        "Env": environment,
                        "Labels": deploy_guard.deployment_labels(
                            original_name,
                            image_id,
                            revision,
                            run_id,
                            role,
                        ),
                    },
                    "HostConfig": host_config,
                    "Mounts": mounts,
                    "NetworkSettings": {"Networks": {network_name: {}}},
                    "State": {"Running": running},
                }

            orphan_roles = deploy_guard.DEPLOY_ROLES
            valid_orphans = [
                orphan_inspect(
                    role,
                    "{0:064x}".format(index + 5),
                    running=role in ("alembic-heads", "schema-reference-server"),
                )
                for index, role in enumerate(orphan_roles)
            ]
            orphan_plan = deploy_guard.plan_orphan_cleanup(valid_orphans)
            self.assertEqual(orphan_plan[0], "orphan-cleanup-v1")
            self.assertTrue(
                deploy_guard.RESTORE_VOLUME_CONTAINER_ROLES.issubset(
                    deploy_guard.ISOLATED_NETWORK_ROLES
                )
            )
            self.assertFalse(
                deploy_guard.RESTORE_VOLUME_CONTAINER_ROLES
                & deploy_guard.RUNTIME_ENV_ROLES
            )
            self.assertFalse(
                deploy_guard.RESTORE_VOLUME_CONTAINER_ROLES
                & deploy_guard.PRODUCTION_MIGRATION_ROLES
            )
            volume_role_container = copy.deepcopy(
                valid_orphans[orphan_roles.index("backend-test")]
            )
            volume_role_name = deploy_guard.deployment_name(
                orphan_run_id,
                deploy_guard.RESTORE_VOLUME_ROLE,
            )
            volume_role_container["Name"] = "/" + volume_role_name
            volume_role_container["Config"]["Labels"] = (
                deploy_guard.deployment_labels(
                    volume_role_name,
                    volume_role_container["Image"],
                    expected_sha,
                    orphan_run_id,
                    deploy_guard.RESTORE_VOLUME_ROLE,
                )
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup([volume_role_container])
            self.assertEqual(len(orphan_plan), 1 + 7 * len(orphan_roles))
            self.assertNotIn("synthetic-db", "\0".join(orphan_plan))
            for binding_index in range(
                deploy_guard.ORPHAN_PLAN_RECORD_SIZE,
                len(orphan_plan),
                deploy_guard.ORPHAN_PLAN_RECORD_SIZE,
            ):
                self.assertRegex(
                    orphan_plan[binding_index],
                    r"\A[0-9a-f]{32}:[0-9a-f]{64}\Z",
                )

            protected_official = orphan_inspect(
                "candidate", "c", running=True, current_name="xjie-api"
            )
            old_backup = orphan_inspect(
                "candidate",
                "e",
                current_name="xjie-api-backup-main-aaaaaaaaaaaa-20260714123045",
                run_id="e" * 32,
            )
            old_backup_plan = deploy_guard.plan_orphan_cleanup([old_backup])
            self.assertEqual(
                deploy_guard.plan_orphan_cleanup(
                    [protected_official, old_backup]
                ),
                old_backup_plan,
            )
            self.assertEqual(old_backup_plan, ["orphan-cleanup-v1"])
            self.assertEqual(
                deploy_guard.plan_orphan_cleanup([protected_official]),
                ["orphan-cleanup-v1"],
            )
            protected_worker = orphan_inspect(
                "celery-worker", "1", running=True
            )
            protected_beat = orphan_inspect("celery-beat", "2", running=True)
            self.assertEqual(
                deploy_guard.plan_orphan_cleanup(
                    [protected_official, protected_worker, protected_beat]
                ),
                ["orphan-cleanup-v1"],
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup(
                    [protected_official, protected_worker]
                )

            current_backup = orphan_inspect(
                "candidate",
                "9",
                current_name="xjie-api-backup-main-cccccccccccc-20260714123047",
                run_id="9" * 32,
            )
            backup_retention_plan = deploy_guard.plan_backup_retention(
                [protected_official, current_backup, old_backup],
                current_backup["Id"],
            )
            self.assertEqual(len(backup_retention_plan), 8)
            self.assertEqual(backup_retention_plan[0], "backup-retention-v1")
            self.assertEqual(backup_retention_plan[1], "remove_expired_backup")
            self.assertEqual(backup_retention_plan[2], old_backup["Id"])
            self.assertEqual(backup_retention_plan[5], "candidate")
            self.assertEqual(
                deploy_guard.plan_backup_retention(
                    [
                        protected_official,
                        protected_worker,
                        protected_beat,
                        current_backup,
                    ],
                    current_backup["Id"],
                ),
                ["backup-retention-v1"],
            )
            for invalid_retained_id in (True, "f" * 64):
                with self.subTest(
                    backup_retention="invalid retained ID",
                    retained_id=invalid_retained_id,
                ), self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.plan_backup_retention(
                        [protected_official, current_backup, old_backup],
                        invalid_retained_id,
                    )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_backup_retention(
                    [current_backup, old_backup], current_backup["Id"]
                )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_backup_retention(
                    [
                        protected_official,
                        current_backup,
                        valid_orphans[orphan_roles.index("backend-test")],
                    ],
                    current_backup["Id"],
                )

            for production_name in (
                "xjie-api",
                "xjie-api-backup-main-bbbbbbbbbbbb-20260714123046",
            ):
                protected_one_shot = orphan_inspect(
                    "backend-test",
                    "f",
                    current_name=production_name,
                    run_id="f" * 32,
                )
                with self.subTest(
                    orphan_cleanup="one-shot production name",
                    current_name=production_name,
                ), self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.plan_orphan_cleanup([protected_one_shot])

            stopped_official = copy.deepcopy(protected_official)
            stopped_official["State"]["Running"] = False
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup([stopped_official])
            running_backup = copy.deepcopy(old_backup)
            running_backup["State"]["Running"] = True
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup([running_backup])
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_backup_retention(
                    [protected_official, current_backup, running_backup],
                    current_backup["Id"],
                )

            invalid_orphan_mutations = (
                (
                    "missing lifecycle label",
                    "backend-test",
                    lambda value: value["Config"]["Labels"].pop(
                        deploy_guard.DEPLOY_LABEL_KEYS[-1]
                    ),
                ),
                (
                    "unknown lifecycle label",
                    "backend-test",
                    lambda value: value["Config"]["Labels"].update(
                        {deploy_guard.DEPLOY_LABEL_PREFIX + "future": "unsafe"}
                    ),
                ),
                (
                    "non-boolean running",
                    "backend-test",
                    lambda value: value["State"].update(Running=1),
                ),
                (
                    "changed image",
                    "backend-test",
                    lambda value: value.update(Image="sha256:" + "f" * 64),
                ),
                (
                    "changed name",
                    "backend-test",
                    lambda value: value.update(Name="/xjie-api-deploy-other"),
                ),
                (
                    "changed candidate command",
                    "candidate",
                    lambda value: value["Config"].update(Cmd=["sh"]),
                ),
                (
                    "changed one-shot command",
                    "backend-test",
                    lambda value: value["Config"].update(Cmd=["sh"]),
                ),
                (
                    "changed one-shot entrypoint",
                    "backend-test",
                    lambda value: value["Config"].update(Entrypoint=None),
                ),
                (
                    "changed hostname",
                    "backend-test",
                    lambda value: value["Config"].update(Hostname="unsafe"),
                ),
                (
                    "closed probe stdin",
                    "database-schema",
                    lambda value: value["Config"].update(OpenStdin=False),
                ),
                (
                    "detached probe stdin",
                    "database-schema",
                    lambda value: value["Config"].update(AttachStdin=False),
                ),
                (
                    "changed probe stdin-once",
                    "database-schema",
                    lambda value: value["Config"].update(StdinOnce=False),
                ),
                (
                    "unexpected candidate stdin",
                    "candidate",
                    lambda value: value["Config"].update(OpenStdin=True),
                ),
                (
                    "detached stdout",
                    "backend-test",
                    lambda value: value["Config"].update(AttachStdout=False),
                ),
                (
                    "changed restart policy",
                    "candidate",
                    lambda value: value["HostConfig"].update(
                        RestartPolicy={"Name": "no", "MaximumRetryCount": 0}
                    ),
                ),
                (
                    "changed candidate ports",
                    "candidate",
                    lambda value: value["HostConfig"].update(PortBindings={}),
                ),
                (
                    "removed runtime extra host",
                    "alembic-heads",
                    lambda value: value["HostConfig"].update(ExtraHosts=None),
                ),
                (
                    "changed one-shot network mode",
                    "backend-test",
                    lambda value: value["HostConfig"].update(NetworkMode="bridge"),
                ),
                (
                    "changed attached network",
                    "candidate",
                    lambda value: value["NetworkSettings"].update(
                        Networks={"unsafe": {}}
                    ),
                ),
                (
                    "removed schema tmpfs",
                    "database-schema",
                    lambda value: value["HostConfig"].update(Tmpfs=None),
                ),
                (
                    "removed schema capability drop",
                    "database-schema",
                    lambda value: value["HostConfig"].update(CapDrop=None),
                ),
                (
                    "added capability",
                    "backend-test",
                    lambda value: value["HostConfig"].update(CapAdd=["NET_ADMIN"]),
                ),
                (
                    "removed no-new-privileges",
                    "database-schema",
                    lambda value: value["HostConfig"].update(SecurityOpt=None),
                ),
                (
                    "changed auto-remove",
                    "schema-old",
                    lambda value: value["HostConfig"].update(AutoRemove=True),
                ),
                (
                    "privileged container",
                    "backend-test",
                    lambda value: value["HostConfig"].update(Privileged=True),
                ),
                (
                    "publish all ports",
                    "backend-test",
                    lambda value: value["HostConfig"].update(PublishAllPorts=True),
                ),
                (
                    "writable schema root",
                    "database-schema",
                    lambda value: value["HostConfig"].update(ReadonlyRootfs=False),
                ),
                (
                    "host bind mount",
                    "backend-test",
                    lambda value: value["HostConfig"].update(Binds=["/tmp:/tmp"]),
                ),
                (
                    "device request",
                    "backend-test",
                    lambda value: value["HostConfig"].update(DeviceRequests=[{}]),
                ),
                (
                    "container mount",
                    "backend-test",
                    lambda value: value.update(Mounts=[{"Type": "bind"}]),
                ),
                (
                    "duplicate environment name",
                    "backend-test",
                    lambda value: value["Config"]["Env"].append(
                        "PYTHONUNBUFFERED=0"
                    ),
                ),
                (
                    "missing image environment invariant",
                    "backend-test",
                    lambda value: value["Config"].update(
                        Env=[
                            item
                            for item in value["Config"]["Env"]
                            if not item.startswith("PYTHONUNBUFFERED=")
                        ]
                    ),
                ),
                (
                    "runtime secret in isolated role",
                    "backend-test",
                    lambda value: value["Config"]["Env"].append(
                        "API_TOKEN=synthetic"
                    ),
                ),
                (
                    "changed database probe user",
                    "database-schema",
                    lambda value: value["Config"].update(User="0:0"),
                ),
                (
                    "changed database probe memory",
                    "database-schema",
                    lambda value: value["HostConfig"].update(
                        Memory=128 * 1024 * 1024
                    ),
                ),
                (
                    "changed reference server stop timeout",
                    "schema-reference-server",
                    lambda value: value["Config"].update(StopTimeout=30),
                ),
                (
                    "changed reference materializer user",
                    "schema-reference-materializer",
                    lambda value: value["Config"].update(User="0:0"),
                ),
                (
                    "changed reference catalog pids",
                    "schema-reference-catalog",
                    lambda value: value["HostConfig"].update(PidsLimit=129),
                ),
                (
                    "reference daemon logging enabled",
                    "schema-reference-server",
                    lambda value: value["HostConfig"].update(
                        LogConfig={"Type": "json-file", "Config": {}}
                    ),
                ),
                (
                    "reference socket destination changed",
                    "schema-reference-catalog",
                    lambda value: value["Mounts"][0].update(
                        Destination="/tmp/postgresql"
                    ),
                ),
                (
                    "reference socket mode changed",
                    "schema-reference-materializer",
                    lambda value: value["Mounts"][0].update(Mode="", RW=True),
                ),
                (
                    "reference socket propagation changed",
                    "schema-reference-server",
                    lambda value: value["Mounts"][0].update(Propagation="rshared"),
                ),
                (
                    "reference catalog credential changed",
                    "schema-reference-catalog",
                    lambda value: value["Config"]["Env"].__setitem__(
                        value["Config"]["Env"].index(
                            "PGPASSWORD={0}".format(reference_password)
                        ),
                        "PGPASSWORD=not-a-random-reference-password",
                    ),
                ),
                (
                    "restore capacity volume became writable",
                    "schema-restore-capacity",
                    lambda value: value["Mounts"][0].update(
                        Mode="", RW=True
                    ),
                ),
                (
                    "restore initializer lost sole capability",
                    "schema-restore-volume-init",
                    lambda value: value["HostConfig"].update(CapAdd=None),
                ),
                (
                    "restore server volume name changed",
                    "schema-restore-server",
                    lambda value: value["Mounts"][1].update(
                        Name="unknown-volume"
                    ),
                ),
                (
                    "restore server regained PGDATA tmpfs",
                    "schema-restore-server",
                    lambda value: value["HostConfig"]["Tmpfs"].update(
                        {
                            "/var/lib/postgresql/data": (
                                "rw,size=256m,uid=70,gid=70,mode=0700"
                            )
                        }
                    ),
                ),
            )
            for label, source_role, mutate in invalid_orphan_mutations:
                source_index = orphan_roles.index(source_role)
                invalid_orphan = copy.deepcopy(valid_orphans[source_index])
                mutate(invalid_orphan)
                with self.subTest(orphan_cleanup=label), self.assertRaises(
                    deploy_guard.DeployGuardError
                ):
                    deploy_guard.plan_orphan_cleanup([invalid_orphan])

            stopped_reference_server = copy.deepcopy(
                valid_orphans[orphan_roles.index("schema-reference-server")]
            )
            stopped_reference_server["State"].update(Running=False, ExitCode=137)
            self.assertEqual(
                len(deploy_guard.plan_orphan_cleanup([stopped_reference_server])),
                8,
            )
            mismatched_reference_socket = copy.deepcopy(
                valid_orphans[orphan_roles.index("schema-reference-catalog")]
            )
            mismatched_reference_socket["Mounts"][0]["Source"] = (
                "/dev/shm/xjie-deploy-1001/runtime/reference-pg-socket"
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup(
                    [
                        valid_orphans[
                            orphan_roles.index("schema-reference-server")
                        ],
                        mismatched_reference_socket,
                    ]
                )
            mismatched_reference_password = copy.deepcopy(
                valid_orphans[
                    orphan_roles.index("schema-reference-materializer")
                ]
            )
            mismatched_reference_password["Config"]["Env"][-1] = (
                "XJIE_REFERENCE_DATABASE_URL="
                "postgresql+psycopg://xjie_reference:{0}"
                "@/xjie_reference?host=/var/run/postgresql".format("b" * 64)
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup(
                    [
                        valid_orphans[
                            orphan_roles.index("schema-reference-server")
                        ],
                        mismatched_reference_password,
                    ]
                )

            default_network_alias = copy.deepcopy(
                valid_orphans[orphan_roles.index("alembic-current")]
            )
            default_network_alias["HostConfig"]["NetworkMode"] = "default"
            default_network_alias["NetworkSettings"]["Networks"] = {"default": {}}
            self.assertEqual(
                len(deploy_guard.plan_orphan_cleanup([default_network_alias])),
                8,
            )

            changed_runtime_environment = copy.deepcopy(valid_orphans[0])
            changed_runtime_environment["Config"]["Env"][-1] = (
                "DATABASE_URL=postgresql+psycopg://other.invalid/xjie"
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup(
                    [
                        changed_runtime_environment,
                        valid_orphans[orphan_roles.index("alembic-heads")],
                    ]
                )

            changed_image_environment = copy.deepcopy(
                valid_orphans[orphan_roles.index("backend-test")]
            )
            changed_image_environment["Config"]["Env"].append(
                "FEATURE_FLAG=changed"
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup(
                    [
                        changed_image_environment,
                        valid_orphans[orphan_roles.index("schema-old")],
                    ]
                )

            candidate_with_extra_environment = copy.deepcopy(valid_orphans[0])
            candidate_with_extra_environment["Config"]["Env"].append(
                "FEATURE_FLAG=enabled"
            )
            changed_environment_plan = deploy_guard.plan_orphan_cleanup(
                [candidate_with_extra_environment]
            )
            original_candidate_plan = deploy_guard.plan_orphan_cleanup(
                [valid_orphans[0]]
            )
            self.assertNotEqual(
                changed_environment_plan[-1], original_candidate_plan[-1]
            )
            self.assertNotIn("FEATURE_FLAG", "\0".join(changed_environment_plan))

            running_candidate = copy.deepcopy(valid_orphans[0])
            running_candidate["State"]["Running"] = True
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.plan_orphan_cleanup([running_candidate])

            orphan_inspects_path = deployment_root / "orphan-inspects.json"
            orphan_plan_path = deployment_root / "orphan-plan.bin"
            orphan_inspects_path.write_text(
                json.dumps(valid_orphans, separators=(",", ":")),
                encoding="utf-8",
            )
            orphan_inspects_path.chmod(0o600)
            self.assertEqual(
                deploy_guard.main(
                    [
                        "plan-orphan-cleanup",
                        "--inspects", str(orphan_inspects_path),
                        "--output", str(orphan_plan_path),
                    ]
                ),
                0,
            )
            self.assertEqual(
                orphan_plan_path.read_bytes().split(b"\0")[:-1],
                [item.encode("utf-8") for item in orphan_plan],
            )
            backup_retention_inspects_path = (
                deployment_root / "backup-retention-inspects.json"
            )
            backup_retention_plan_path = deployment_root / "backup-retention-plan.bin"
            backup_retention_inspects_path.write_text(
                json.dumps(
                    [protected_official, current_backup, old_backup],
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            backup_retention_inspects_path.chmod(0o600)
            self.assertEqual(
                deploy_guard.main(
                    [
                        "plan-backup-retention",
                        "--inspects", str(backup_retention_inspects_path),
                        "--retained-backup-id", current_backup["Id"],
                        "--output", str(backup_retention_plan_path),
                    ]
                ),
                0,
            )
            self.assertEqual(
                backup_retention_plan_path.read_bytes().split(b"\0")[:-1],
                [item.encode("utf-8") for item in backup_retention_plan],
            )
            orphan_inspects_path.chmod(0o640)
            rejected_plan_path = deployment_root / "rejected-orphan-plan.bin"
            with mock.patch("builtins.print"):
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "plan-orphan-cleanup",
                            "--inspects", str(orphan_inspects_path),
                            "--output", str(rejected_plan_path),
                        ]
                    ),
                    1,
                )
            self.assertFalse(rejected_plan_path.exists())

        expected_sha = "a" * 40
        old_image_id = "sha256:" + "1" * 64
        candidate_image_id = "sha256:" + "2" * 64
        deployment_run_id = "b" * 32
        candidate_name = "xjie-api-deploy-{0}-candidate".format(
            deployment_run_id
        )
        old_host_config = {
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            "PortBindings": {"8000/tcp": [{"HostIp": "", "HostPort": "8000"}]},
            "ExtraHosts": ["host.docker.internal:host-gateway"],
            "UnknownFutureSetting": False,
        }
        candidate_host_config = copy.deepcopy(old_host_config)
        candidate_host_config["PortBindings"] = {
            "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]
        }
        old_image_config = {
            "Cmd": ["uvicorn", "old.app:app"],
            "Entrypoint": None,
            "User": "",
            "WorkingDir": "/app",
            "Healthcheck": None,
            "ExposedPorts": {"8000/tcp": {}},
            "Volumes": None,
            "OnBuild": None,
            "ArgsEscaped": False,
            "StopSignal": None,
            "Shell": None,
            "Labels": None,
            "Env": ["PATH=/old/bin", "IMAGE_DEFAULT=old"],
        }
        candidate_image_config = {
            "Cmd": ["uvicorn", "new.app:app"],
            "Entrypoint": None,
            "User": "10001",
            "WorkingDir": "/srv/app",
            "Healthcheck": None,
            "ExposedPorts": {"8000/tcp": {}},
            "Volumes": None,
            "OnBuild": None,
            "ArgsEscaped": False,
            "StopSignal": "SIGTERM",
            "Shell": None,
            "Labels": {"org.opencontainers.image.revision": expected_sha},
            "Env": ["PATH=/new/bin", "IMAGE_DEFAULT=new"],
        }

        def network_fixture(container_id, container_name, address):
            return {
                "bridge": {
                    "IPAMConfig": None,
                    "Links": None,
                    "Aliases": [container_name, container_id[:12]],
                    "MacAddress": "02:42:ac:11:00:" + address,
                    "DriverOpts": None,
                    "GwPriority": 0,
                    "NetworkID": "network-" + address,
                    "EndpointID": "endpoint-" + address,
                    "Gateway": "172.17.0.1",
                    "IPAddress": "172.17.0." + str(int(address, 16)),
                    "IPPrefixLen": 16,
                    "IPv6Gateway": "",
                    "GlobalIPv6Address": "",
                    "GlobalIPv6PrefixLen": 0,
                    "DNSNames": [container_name, container_id[:12]],
                }
            }

        def container_fixture(
            container_id,
            container_name,
            image_id,
            image_config,
            runtime_env,
            host_config,
            address,
        ):
            config = copy.deepcopy(image_config)
            config["Env"] = [*config["Env"], *runtime_env]
            config.update(
                Hostname=container_id[:12],
                Domainname="",
                AttachStdin=False,
                AttachStdout=True,
                AttachStderr=True,
                OpenStdin=False,
                StdinOnce=False,
                Tty=False,
                MacAddress="",
                NetworkDisabled=False,
                StopTimeout=None,
                Image=image_id,
            )
            return {
                "Id": container_id,
                "Name": "/" + container_name,
                "Image": image_id,
                "Config": config,
                "HostConfig": copy.deepcopy(host_config),
                "Mounts": [],
                "NetworkSettings": {
                    "Networks": network_fixture(container_id, container_name, address)
                },
            }

        old_image = {"Id": old_image_id, "Config": old_image_config}
        candidate_image = {"Id": candidate_image_id, "Config": candidate_image_config}
        runtime_env = ["DATABASE_URL=synthetic", "JWT_SECRET=synthetic"]
        env_values = {"DATABASE_URL": "synthetic", "JWT_SECRET": "synthetic"}
        old_container = container_fixture(
            "1" * 64,
            "xjie-api",
            old_image_id,
            old_image_config,
            runtime_env,
            old_host_config,
            "02",
        )
        candidate_container = container_fixture(
            "2" * 64,
            candidate_name,
            candidate_image_id,
            candidate_image_config,
            runtime_env,
            candidate_host_config,
            "03",
        )
        candidate_container["Config"]["Labels"].update(
            deploy_guard.deployment_labels(
                candidate_name,
                candidate_image_id,
                expected_sha,
                deployment_run_id,
                "candidate",
            )
        )

        def validate_recreation(old_value, candidate_value):
            deploy_guard.validate_inspects(
                production_spec,
                old_value,
                old_image,
                candidate_value,
                candidate_image,
                env_values,
                expected_sha,
            )

        validate_recreation(old_container, candidate_container)
        managed_old_container = copy.deepcopy(old_container)
        managed_old_original_name = "xjie-api-deploy-{0}-candidate".format(
            "c" * 32
        )
        managed_old_container["Config"]["Labels"] = deploy_guard.deployment_labels(
            managed_old_original_name,
            old_image_id,
            "c" * 40,
            "c" * 32,
            "candidate",
        )
        managed_old_image = copy.deepcopy(old_image)
        managed_old_image["Config"]["Labels"] = {
            "org.opencontainers.image.revision": "c" * 40
        }
        managed_old_container["Config"]["Labels"].update(
            managed_old_image["Config"]["Labels"]
        )
        deploy_guard.validate_inspects(
            production_spec,
            managed_old_container,
            managed_old_image,
            candidate_container,
            candidate_image,
            env_values,
            expected_sha,
        )
        for old_host_ip in ("0.0.0.0", "127.0.0.1"):
            compatible_old = copy.deepcopy(old_container)
            compatible_old["HostConfig"]["PortBindings"]["8000/tcp"][0]["HostIp"] = old_host_ip
            validate_recreation(compatible_old, candidate_container)

        candidate_mutations = (
            (
                "old command copied into candidate",
                lambda item: item["Config"].update(Cmd=["uvicorn", "old.app:app"]),
            ),
            (
                "new image environment default replaced",
                lambda item: item["Config"].update(
                    Env=["PATH=/old/bin", "IMAGE_DEFAULT=old", *runtime_env]
                ),
            ),
            (
                "unmodeled host configuration lost",
                lambda item: item["HostConfig"].update(UnknownFutureSetting=True),
            ),
            (
                "loopback binding widened",
                lambda item: item["HostConfig"]["PortBindings"]["8000/tcp"][0].update(HostIp=""),
            ),
            (
                "candidate image revision changed",
                lambda item: item["Config"]["Labels"].update(
                    {"org.opencontainers.image.revision": "b" * 40}
                ),
            ),
            (
                "candidate lifecycle label removed",
                lambda item: item["Config"]["Labels"].pop(
                    deploy_guard.DEPLOY_LABEL_KEYS[-1]
                ),
            ),
            (
                "candidate lifecycle image binding changed",
                lambda item: item["Config"]["Labels"].update(
                    {deploy_guard.DEPLOY_LABEL_KEYS[7]: "sha256:" + "f" * 64}
                ),
            ),
            ("stdout attachment changed", lambda item: item["Config"].update(AttachStdout=False)),
            ("stderr attachment changed", lambda item: item["Config"].update(AttachStderr=False)),
            ("stop timeout changed", lambda item: item["Config"].update(StopTimeout=30)),
            ("hostname changed", lambda item: item["Config"].update(Hostname="custom-host")),
            ("domain changed", lambda item: item["Config"].update(Domainname="example.test")),
            ("static config MAC added", lambda item: item["Config"].update(MacAddress="02:42:00:00:00:09")),
            ("unknown Config field", lambda item: item["Config"].update(FutureRuntimeFlag=False)),
            (
                "unknown network field",
                lambda item: item["NetworkSettings"]["Networks"]["bridge"].update(FutureEndpointFlag=False),
            ),
            (
                "unknown IPAM field",
                lambda item: item["NetworkSettings"]["Networks"]["bridge"].update(
                    IPAMConfig={"FutureAddressMode": "unsafe"}
                ),
            ),
        )
        for label, mutate in candidate_mutations:
            invalid_candidate = copy.deepcopy(candidate_container)
            mutate(invalid_candidate)
            with self.subTest(deploy_recreation=label), self.assertRaises(
                deploy_guard.DeployGuardError
            ):
                validate_recreation(old_container, invalid_candidate)

        old_mutations = (
            (
                "non-loopback old bind cannot be normalized",
                lambda item: item["HostConfig"]["PortBindings"]["8000/tcp"][0].update(HostIp="192.0.2.10"),
            ),
            (
                "network alias would be lost",
                lambda item: item["NetworkSettings"]["Networks"]["bridge"]["Aliases"].append("production-alias"),
            ),
            (
                "static IP would be lost",
                lambda item: item["NetworkSettings"]["Networks"]["bridge"].update(
                    IPAMConfig={"IPv4Address": "172.17.0.40"}
                ),
            ),
            (
                "network links would be lost",
                lambda item: item["NetworkSettings"]["Networks"]["bridge"].update(Links=["db:db"]),
            ),
            (
                "network driver options would be lost",
                lambda item: item["NetworkSettings"]["Networks"]["bridge"].update(
                    DriverOpts={"com.example.option": "enabled"}
                ),
            ),
            (
                "per-network static MAC would be lost",
                lambda item: item["NetworkSettings"]["Networks"]["bridge"].update(
                    MacAddress="02:42:00:00:00:09"
                ),
            ),
            (
                "network DNS alias would be lost",
                lambda item: item["NetworkSettings"]["Networks"]["bridge"]["DNSNames"].append("production-dns"),
            ),
            ("old stop timeout override", lambda item: item["Config"].update(StopTimeout=20)),
        )
        for label, mutate in old_mutations:
            invalid_old = copy.deepcopy(old_container)
            mutate(invalid_old)
            with self.subTest(deploy_recreation=label), self.assertRaises(
                deploy_guard.DeployGuardError
            ):
                validate_recreation(invalid_old, candidate_container)
        self.assertEqual(
            deploy_guard.validate_migration_outputs(
                "Rev: 0021_device_indicator_identity (head)\n",
                "Current revision(s)\nRev: 0021_device_indicator_identity (head)\n",
            ),
            ["0021_device_indicator_identity"],
        )
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_migration_outputs(
                "Rev: 0021_device_indicator_identity (head)\n",
                "Current revision(s)\nRev: 0020_chat_request_receipts\n",
            )

        def synthetic_migration_manifest():
            return {
                "schema_version": 1,
                "migrations": [
                    {
                        "revision": "0001_base",
                        "down_revision": None,
                        "sha256": "1" * 64,
                    },
                    {
                        "revision": "0002_current",
                        "down_revision": "0001_base",
                        "sha256": "2" * 64,
                    },
                ],
                "heads": ["0002_current"],
                "model_schema": [
                    {
                        "name": "sample",
                        "schema": None,
                        "columns": [
                            {
                                "name": "id",
                                "type": {
                                    "class": "sqlalchemy.sql.sqltypes.Integer",
                                    "sql": "INTEGER",
                                    "cache_key": [
                                        {
                                            "class": "sqlalchemy.sql.sqltypes.Integer"
                                        }
                                    ],
                                    "attributes": {},
                                },
                                "nullable": False,
                                "primary_key": True,
                                "autoincrement": "auto",
                                "default": None,
                                "server_default": None,
                                "onupdate": None,
                                "server_onupdate": None,
                                "identity": None,
                                "computed": None,
                                "comment": None,
                            }
                        ],
                        "constraints": [
                            {
                                "kind": "primary_key",
                                "name": "pk_sample",
                                "columns": ["id"],
                                "references": [],
                                "options": {},
                                "expression": None,
                            }
                        ],
                        "indexes": [
                            {
                                "name": "ix_sample_id",
                                "unique": False,
                                "expressions": ["sample.id"],
                                "options": {},
                            }
                        ],
                    }
                ],
            }

        old_migration_manifest = synthetic_migration_manifest()
        candidate_migration_manifest = copy.deepcopy(old_migration_manifest)
        migration_heads_output = "Rev: 0002_current (head)\n"
        migration_current_output = (
            "Current revision(s)\nRev: 0002_current (head)\n"
        )
        self.assertEqual(
            deploy_guard.validate_no_migration_delta(
                old_migration_manifest,
                candidate_migration_manifest,
                migration_heads_output,
                migration_current_output,
            ),
            ["0002_current"],
        )

        rewritten_history = copy.deepcopy(candidate_migration_manifest)
        rewritten_history["migrations"][0]["sha256"] = "f" * 64
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_no_migration_delta(
                old_migration_manifest,
                rewritten_history,
                migration_heads_output,
                migration_current_output,
            )

        new_revision = copy.deepcopy(candidate_migration_manifest)
        new_revision["migrations"].append(
            {
                "revision": "0003_new",
                "down_revision": "0002_current",
                "sha256": "3" * 64,
            }
        )
        new_revision["heads"] = ["0003_new"]
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_no_migration_delta(
                old_migration_manifest,
                new_revision,
                "Rev: 0003_new (head)\n",
                "Current revision(s)\nRev: 0003_new (head)\n",
            )

        expand_source = b'''"""Synthetic additive migration."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.compat import JSONB

revision = "0003_expand"
down_revision = "0002_current"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "new_sample",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
    )
    op.create_index("ix_new_sample_id", "new_sample", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_new_sample_id", table_name="new_sample")
    op.drop_table("new_sample")
'''
        expand_candidate_manifest = copy.deepcopy(old_migration_manifest)
        expand_candidate_manifest["migrations"].append(
            {
                "revision": "0003_expand",
                "down_revision": "0002_current",
                "sha256": hashlib.sha256(expand_source).hexdigest(),
            }
        )
        expand_candidate_manifest["heads"] = ["0003_expand"]
        expand_plan = deploy_guard.validate_expand_migration_source(
            expand_source,
            old_migration_manifest,
            expand_candidate_manifest,
        )
        self.assertEqual(
            [item["op"] for item in expand_plan["operations"]],
            ["create_table", "create_index"],
        )
        self.assertEqual(
            deploy_guard.validate_expand_migration_plan(expand_plan),
            expand_plan,
        )
        second_expand_source = b'''"""Second synthetic additive migration."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.compat import JSONB

revision = "0004_expand"
down_revision = "0003_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "new_sample",
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_table(
        "new_sample_two",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
    )
    op.create_index("ix_new_sample_two_id", "new_sample_two", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_new_sample_two_id", table_name="new_sample_two")
    op.drop_table("new_sample_two")
'''
        chained_expand_manifest = copy.deepcopy(expand_candidate_manifest)
        chained_expand_manifest["migrations"].append(
            {
                "revision": "0004_expand",
                "down_revision": "0003_expand",
                "sha256": hashlib.sha256(second_expand_source).hexdigest(),
            }
        )
        chained_expand_manifest["heads"] = ["0004_expand"]
        chained_expand_plan = deploy_guard.validate_expand_migration_source(
            [expand_source, second_expand_source],
            old_migration_manifest,
            chained_expand_manifest,
        )
        self.assertEqual(
            [item["revision"] for item in chained_expand_plan["migrations"]],
            ["0003_expand", "0004_expand"],
        )
        self.assertEqual(
            [item["op"] for item in chained_expand_plan["operations"]],
            [
                "create_table",
                "create_index",
                "add_column",
                "create_table",
                "create_index",
            ],
        )
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_expand_migration_source(
                [second_expand_source, expand_source],
                old_migration_manifest,
                chained_expand_manifest,
            )
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_expand_migration_source(
                expand_source,
                old_migration_manifest,
                chained_expand_manifest,
            )
        chained_runner_source = deploy_guard.render_expand_transaction_runner(
            chained_expand_plan
        )
        self.assertIn('for number, (_migration, module) in enumerate(migrations, start=1):', chained_runner_source)
        self.assertIn("deterministic migration-chain transaction failpoint", chained_runner_source)
        runner_source = deploy_guard.render_expand_transaction_runner(expand_plan)
        compile(runner_source, "EXPAND_TRANSACTION_RUNNER.py", "exec")
        for runner_required in (
            "with engine.begin() as connection:",
            'transactional_ddl": True',
            "SELECT version_num FROM public.alembic_version FOR UPDATE",
            "UPDATE public.alembic_version SET version_num = %s",
            "module.op = Operations(context)",
            "migration SHA-256 changed after approval",
        ):
            self.assertIn(runner_required, runner_source)
        self.assertNotIn("app.db.migrations.env", runner_source)
        self.assertNotIn("alembic.command", runner_source)
        failed_runner_source = deploy_guard.render_expand_transaction_runner(
            expand_plan,
            fail_after_upgrade=True,
        )
        self.assertIn("FAIL_AFTER_UPGRADE = True", failed_runner_source)
        old_compat_source = deploy_guard.render_expand_old_app_compat_probe(
            old_migration_manifest,
            expand_plan,
        )
        compile(old_compat_source, "EXPAND_OLD_APP_COMPAT.py", "exec")
        for old_compat_required in (
            "pkgutil.walk_packages",
            "Base.metadata.tables.values()",
            "table.select().limit(0)",
            'Base.metadata.tables.get("user_account")',
            "user_account.insert().values(",
            "user_account.update()",
            "user_account.delete()",
        ):
            self.assertIn(old_compat_required, old_compat_source)
        expected_old_compat = deploy_guard.expected_expand_old_app_compat_result(
            old_migration_manifest,
            expand_plan,
        )
        self.assertEqual(
            deploy_guard.validate_expand_old_app_compat_result(
                expected_old_compat,
                old_migration_manifest,
                expand_plan,
            ),
            expected_old_compat,
        )
        for label, mutate_source in (
            (
                "drop table in upgrade",
                lambda value: value.replace(
                    b'op.create_table(\n        "new_sample",',
                    b'op.drop_table("sample")\n    op.create_table(\n        "new_sample",',
                ),
            ),
            (
                "raw SQL in upgrade",
                lambda value: value.replace(
                    b"def upgrade() -> None:\n",
                    b'def upgrade() -> None:\n    op.execute("SELECT 1")\n',
                ),
            ),
            (
                "dynamic helper",
                lambda value: value.replace(
                    b"def upgrade() -> None:\n",
                    b"def helper() -> None:\n    pass\n\ndef upgrade() -> None:\n",
                ),
            ),
            (
                "not null old column without safe default",
                lambda value: value.replace(
                    b"def upgrade() -> None:\n",
                    b'def upgrade() -> None:\n    op.add_column("sample", sa.Column("unsafe", sa.Text(), nullable=False))\n',
                ),
            ),
        ):
            changed_source = mutate_source(expand_source)
            changed_manifest = copy.deepcopy(expand_candidate_manifest)
            changed_manifest["migrations"][-1]["sha256"] = hashlib.sha256(
                changed_source
            ).hexdigest()
            with self.subTest(expand_policy=label), self.assertRaises(
                deploy_guard.DeployGuardError
            ):
                deploy_guard.validate_expand_migration_source(
                    changed_source,
                    old_migration_manifest,
                    changed_manifest,
                )
        rewritten_expand_history = copy.deepcopy(expand_candidate_manifest)
        rewritten_expand_history["migrations"][0]["sha256"] = "f" * 64
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_expand_migration_source(
                expand_source,
                old_migration_manifest,
                rewritten_expand_history,
            )
        branched_expand = copy.deepcopy(expand_candidate_manifest)
        branched_expand["migrations"][-1]["down_revision"] = "0001_base"
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_expand_migration_source(
                expand_source,
                old_migration_manifest,
                branched_expand,
            )

        expand_approval_plan = {
            "schema_version": deploy_guard.EXPAND_APPROVAL_PLAN_SCHEMA_VERSION,
            "expected_main_sha": "a" * 40,
            "trusted_bundle_sha256": "b" * 64,
            "old_manifest_sha256": expand_plan["old_manifest_sha256"],
            "old_head": expand_plan["old_head"],
            "candidate_manifest_sha256": expand_plan[
                "candidate_manifest_sha256"
            ],
            "candidate_head": expand_plan["candidate_head"],
            "migrations": expand_plan["migrations"],
            "migration_sha256": expand_plan["migration_sha256"],
            "operation_policy_sha256": expand_plan[
                "operation_policy_sha256"
            ],
            "old_catalog_sha256": "c" * 64,
            "candidate_catalog_sha256": "d" * 64,
        }
        self.assertEqual(
            deploy_guard.validate_expand_approval_plan(
                expand_approval_plan,
                expand_plan,
            ),
            expand_approval_plan,
        )
        with tempfile.TemporaryDirectory() as expand_temp:
            expand_root = Path(expand_temp)
            journal_path = expand_root / "expand-journal.json"
            backup_path = expand_root / "production-schema.dump"
            toc_path = expand_root / "production-schema.toc"
            backup_path.write_bytes(b"PGDMP" + b"synthetic-custom-backup")
            backup_path.chmod(0o600)
            toc_path.write_bytes(
                b"; synthetic pg_restore listing\n"
                b"1; 1259 1 TABLE public sample synthetic_owner\n"
            )
            toc_path.chmod(0o600)
            backup_attestation = deploy_guard.attest_expand_backup(
                backup_path,
                toc_path,
            )
            self.assertEqual(
                backup_attestation["backup_sha256"],
                hashlib.sha256(backup_path.read_bytes()).hexdigest(),
            )
            approved_journal = deploy_guard.build_expand_journal(
                expand_approval_plan,
                "e" * 64,
                expand_plan,
                str(backup_path),
                "sha256:" + "1" * 64,
                "sha256:" + "2" * 64,
            )
            deploy_guard.write_expand_journal(journal_path, approved_journal)
            self.assertEqual(
                deploy_guard.plan_expand_recovery(
                    approved_journal,
                    expand_plan["old_head"],
                    expand_approval_plan["old_catalog_sha256"],
                ),
                "resume_backup",
            )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.advance_expand_journal(
                    journal_path,
                    "restore_verified",
                )
            backup_journal = deploy_guard.advance_expand_journal(
                journal_path,
                "backup_verified",
                backup_attestation,
            )
            self.assertEqual(
                backup_journal["backup_sha256"],
                backup_attestation["backup_sha256"],
            )
            self.assertEqual(
                deploy_guard.validate_expand_backup_binding(
                    backup_journal,
                    backup_attestation,
                ),
                backup_attestation,
            )
            drifted_backup_attestation = dict(backup_attestation)
            drifted_backup_attestation["backup_sha256"] = "0" * 64
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.validate_expand_backup_binding(
                    backup_journal,
                    drifted_backup_attestation,
                )
            restore_run_id = "9" * 32
            restore_image_id = "sha256:" + "4" * 64
            restore_volume_name = deploy_guard.deployment_name(
                restore_run_id,
                deploy_guard.RESTORE_VOLUME_ROLE,
            )
            restore_volume_inspect = {
                "CreatedAt": "2026-07-15T00:00:00Z",
                "Driver": "local",
                "Labels": deploy_guard.deployment_labels(
                    restore_volume_name,
                    restore_image_id,
                    expand_approval_plan["expected_main_sha"],
                    restore_run_id,
                    deploy_guard.RESTORE_VOLUME_ROLE,
                ),
                "Mountpoint": (
                    "/var/lib/docker/volumes/"
                    + restore_volume_name
                    + "/_data"
                ),
                "Name": restore_volume_name,
                "Options": None,
                "Scope": "local",
            }
            restore_volume_attestation = (
                deploy_guard.build_expand_restore_volume_attestation(
                    restore_volume_inspect,
                    "268435456\n",
                    "8388608 1024\n",
                    backup_attestation,
                    expand_approval_plan["expected_main_sha"],
                    restore_run_id,
                    restore_image_id,
                )
            )
            self.assertEqual(
                deploy_guard.validate_expand_restore_volume_attestation(
                    restore_volume_attestation
                ),
                restore_volume_attestation,
            )
            self.assertEqual(
                tuple(restore_volume_attestation),
                deploy_guard.EXPAND_RESTORE_VOLUME_ATTESTATION_KEYS,
            )
            self.assertNotIn(
                "/var/lib/docker/volumes",
                json.dumps(restore_volume_attestation),
            )
            self.assertEqual(
                deploy_guard.plan_restore_volume_cleanup(
                    [restore_volume_inspect]
                )[0],
                deploy_guard.RESTORE_VOLUME_CLEANUP_PLAN_VERSION,
            )
            unsafe_restore_volume = copy.deepcopy(restore_volume_inspect)
            unsafe_restore_volume["Options"] = {"type": "nfs"}
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.validate_restore_volume_inspect(
                    unsafe_restore_volume
                )
            missing_restore_created_at = copy.deepcopy(restore_volume_inspect)
            missing_restore_created_at.pop("CreatedAt")
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.validate_restore_volume_inspect(
                    missing_restore_created_at
                )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.build_expand_restore_volume_attestation(
                    restore_volume_inspect,
                    "4294967296\n",
                    "1048576 1024\n",
                    backup_attestation,
                    expand_approval_plan["expected_main_sha"],
                    restore_run_id,
                    restore_image_id,
                )
            restore_journal = deploy_guard.advance_expand_journal(
                journal_path,
                "restore_verified",
                restore_volume_attestation=restore_volume_attestation,
            )
            self.assertEqual(
                restore_journal["restore_volume_name"],
                restore_volume_name,
            )
            self.assertEqual(
                deploy_guard.plan_expand_recovery(
                    restore_journal,
                    expand_plan["old_head"],
                    expand_approval_plan["old_catalog_sha256"],
                ),
                "start_transaction",
            )
            transaction_journal = deploy_guard.advance_expand_journal(
                journal_path,
                "production_transaction_started",
            )
            self.assertEqual(
                deploy_guard.plan_expand_recovery(
                    transaction_journal,
                    expand_plan["old_head"],
                    expand_approval_plan["old_catalog_sha256"],
                ),
                "retry_transaction",
            )
            self.assertEqual(
                deploy_guard.plan_expand_recovery(
                    transaction_journal,
                    expand_plan["candidate_head"],
                    expand_approval_plan["candidate_catalog_sha256"],
                ),
                "resume_post_transaction_attestation",
            )
            for observed_head, observed_catalog in (
                (
                    expand_plan["candidate_head"],
                    expand_approval_plan["old_catalog_sha256"],
                ),
                ("unrelated", expand_approval_plan["candidate_catalog_sha256"]),
            ):
                with self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.plan_expand_recovery(
                        transaction_journal,
                        observed_head,
                        observed_catalog,
                    )
            schema_journal = deploy_guard.advance_expand_journal(
                journal_path,
                "production_schema_attested",
            )
            self.assertEqual(
                deploy_guard.plan_expand_recovery(
                    schema_journal,
                    expand_plan["candidate_head"],
                    expand_approval_plan["candidate_catalog_sha256"],
                ),
                "resume_cutover",
            )
            deploy_guard.advance_expand_journal(journal_path, "cutover_started")
            complete_journal = deploy_guard.advance_expand_journal(
                journal_path,
                "completed",
            )
            evidence = deploy_guard.build_expand_evidence(
                complete_journal,
                expand_plan,
                "1" * 64,
                "2" * 64,
                "f" * 64,
                expand_approval_plan["candidate_catalog_sha256"],
            )
            self.assertEqual(tuple(evidence), deploy_guard.EXPAND_EVIDENCE_KEYS)
            self.assertEqual(evidence["schema_version"], 3)
            self.assertEqual(
                evidence["restore_volume_identity_sha256"],
                restore_volume_attestation["volume_identity_sha256"],
            )
            self.assertEqual(
                evidence["rehearsal_transaction_result_sha256"],
                "1" * 64,
            )
            self.assertEqual(
                evidence["old_app_compat_result_sha256"],
                "2" * 64,
            )
            evidence_path = expand_root / "expand-evidence.json"
            deploy_guard.write_expand_evidence(evidence_path, evidence)
            self.assertEqual(evidence_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                deploy_guard.load_owner_only_expand_evidence(
                    evidence_path,
                    evidence,
                ),
                evidence,
            )
            drifted_evidence = dict(evidence)
            drifted_evidence["post_catalog_sha256"] = "0" * 64
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.load_owner_only_expand_evidence(
                    evidence_path,
                    drifted_evidence,
                )
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.write_expand_evidence(evidence_path, evidence)
            deploy_guard.clear_expand_journal(journal_path)
            self.assertFalse(journal_path.exists())
            invalid_backup_path = expand_root / "invalid.dump"
            invalid_backup_path.write_bytes(b"not-a-custom-dump")
            invalid_backup_path.chmod(0o600)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.attest_expand_backup(invalid_backup_path, toc_path)
            backup_link = expand_root / "backup-link.dump"
            backup_link.symlink_to(backup_path)
            with self.assertRaises(deploy_guard.DeployGuardError):
                deploy_guard.attest_expand_backup(backup_link, toc_path)

        model_only_column = copy.deepcopy(candidate_migration_manifest)
        added_column = copy.deepcopy(
            model_only_column["model_schema"][0]["columns"][0]
        )
        added_column.update(
            {
                "name": "note",
                "nullable": True,
                "primary_key": False,
                "autoincrement": False,
            }
        )
        model_only_column["model_schema"][0]["columns"].append(added_column)
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_no_migration_delta(
                old_migration_manifest,
                model_only_column,
                migration_heads_output,
                migration_current_output,
            )

        branched_history = copy.deepcopy(candidate_migration_manifest)
        branched_history["migrations"].append(
            {
                "revision": "0003_branch",
                "down_revision": "0001_base",
                "sha256": "4" * 64,
            }
        )
        branched_history["heads"] = ["0003_branch"]
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_migration_manifest(branched_history)

        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_no_migration_delta(
                old_migration_manifest,
                candidate_migration_manifest,
                migration_heads_output,
                "Current revision(s)\nRev: 0001_base\n",
            )

        probe_source = deploy_guard.MIGRATION_PROBE_SOURCE
        compile(probe_source, "PROBE.py", "exec")
        self.assertIn('MODEL_ROOT.rglob("*.py")', probe_source)
        self.assertIn('modules = {"app.models"}', probe_source)
        self.assertIn("Base.metadata.tables.values()", probe_source)
        self.assertIn("dialect_value = value.dialect_impl(dialect)", probe_source)
        self.assertIn(
            'item_type = getattr(dialect_value, "item_type", None)',
            probe_source,
        )
        for forbidden_probe_capability in (
            "create_all",
            "app.main",
            "DATABASE_URL",
            "create_engine",
            "Session",
            "connect(",
            "urllib",
            "socket",
            "requests",
            "subprocess",
            "os.environ",
        ):
            self.assertNotIn(forbidden_probe_capability, probe_source)

        database_probe_manifest = copy.deepcopy(candidate_migration_manifest)
        enum_model_type = {
            "class": "sqlalchemy.sql.sqltypes.Enum",
            "sql": "sample_state",
            "cache_key": [],
            "attributes": {"enums": ["ready", "complete"]},
        }
        enum_column = copy.deepcopy(
            database_probe_manifest["model_schema"][0]["columns"][0]
        )
        enum_column.update(
            {
                "name": "state",
                "type": copy.deepcopy(enum_model_type),
                "nullable": False,
                "primary_key": False,
                "autoincrement": False,
            }
        )
        array_column = copy.deepcopy(enum_column)
        array_column.update(
            {
                "name": "states",
                "type": {
                    "class": "sqlalchemy.dialects.postgresql.array.ARRAY",
                    "sql": "sample_state[]",
                    "cache_key": [],
                    "attributes": {
                        "dimensions": 1,
                        "item_type": copy.deepcopy(enum_model_type),
                    },
                },
                "nullable": True,
            }
        )
        database_probe_manifest["model_schema"][0]["columns"].extend(
            [enum_column, array_column]
        )
        parent_column = copy.deepcopy(
            database_probe_manifest["model_schema"][0]["columns"][0]
        )
        parent_column.update(
            {
                "name": "parent_id",
                "nullable": True,
                "primary_key": False,
                "autoincrement": False,
            }
        )
        database_probe_manifest["model_schema"][0]["columns"].append(parent_column)
        database_probe_manifest["model_schema"][0]["columns"].sort(
            key=lambda item: item["name"]
        )
        database_probe_manifest["model_schema"][0]["constraints"].extend(
            [
                {
                    "kind": "check",
                    "name": "ck_sample_id",
                    "columns": ["id"],
                    "references": [],
                    "options": {},
                    "expression": "id > 0",
                },
                {
                    "kind": "foreign_key",
                    "name": "fk_sample_parent",
                    "columns": ["parent_id"],
                    "references": ["sample.id"],
                    "options": {
                        "deferrable": None,
                        "initially": None,
                        "match": None,
                        "ondelete": "SET NULL",
                        "onupdate": None,
                        "use_alter": False,
                    },
                    "expression": None,
                },
                {
                    "kind": "unique",
                    "name": "uq_sample_state",
                    "columns": ["state"],
                    "references": [],
                    "options": {},
                    "expression": None,
                },
            ]
        )
        database_probe_manifest["model_schema"][0]["constraints"].sort(
            key=lambda item: json.dumps(
                item, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            )
        )
        database_probe_manifest["model_schema"][0]["indexes"].append(
            {
                "name": "ix_sample_state_ready",
                "unique": False,
                "expressions": ["sample.state"],
                "options": {"postgresql_where": "sample.state = 'ready'"},
            }
        )
        database_probe_manifest["model_schema"][0]["indexes"].sort(
            key=lambda item: json.dumps(
                item, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            )
        )
        deploy_guard.validate_migration_manifest(database_probe_manifest)
        self.assertEqual(
            deploy_guard.DATABASE_SCHEMA_LEGACY_ALLOWLIST_VERSION, 1
        )
        self.assertEqual(
            deploy_guard.DATABASE_SCHEMA_LEGACY_PUBLIC_TABLES,
            ("alembic_version",),
        )
        for label, mutate in (
            (
                "unmanaged physical schema",
                lambda value: value["model_schema"][0].update(schema="tenant"),
            ),
            (
                "legacy allowlist collision",
                lambda value: value["model_schema"][0].update(
                    name="alembic_version"
                ),
            ),
            (
                "managed schema type coerced",
                lambda value: value["model_schema"][0].update(schema=7),
            ),
        ):
            invalid_manifest = copy.deepcopy(database_probe_manifest)
            mutate(invalid_manifest)
            with self.subTest(candidate_catalog=label), self.assertRaises(
                deploy_guard.DeployGuardError
            ):
                deploy_guard._manifest_table_identities(invalid_manifest)

        def catalog_type(
            schema,
            name,
            formatted,
            *,
            kind="b",
            category="N",
            dimensions=0,
            enum_labels=None,
            array_item=None,
        ):
            return {
                "schema": schema,
                "name": name,
                "formatted": formatted,
                "kind": kind,
                "category": category,
                "dimensions": dimensions,
                "enum_labels": enum_labels,
                "array_item": array_item,
            }

        sequence_owner = {
            "schema": "public",
            "table": "sample",
            "column": "id",
            "dependency": "a",
        }
        sample_sequence = {
            "schema": "public",
            "name": "sample_id_seq",
            "data_type": "integer",
            "start": 1,
            "increment": 1,
            "minimum": 1,
            "maximum": 2147483647,
            "cache": 1,
            "cycle": False,
            "owned_by": sequence_owner,
        }

        def physical_column(
            position,
            name,
            column_type,
            *,
            nullable,
            default=None,
            storage="p",
            owned_sequence=None,
        ):
            return {
                "position": position,
                "name": name,
                "type": column_type,
                "nullable": nullable,
                "default": default,
                "identity": "",
                "generated": "",
                "collation": None,
                "compression": "",
                "storage": storage,
                "owned_sequence": owned_sequence,
            }

        def physical_constraint(
            name,
            constraint_type,
            definition,
            columns,
            *,
            references=None,
        ):
            return {
                "name": name,
                "type": constraint_type,
                "definition": definition,
                "columns": columns,
                "references": references,
                "deferrable": False,
                "deferred": False,
                "validated": True,
                "no_inherit": False,
                "nulls_not_distinct": False,
            }

        def physical_index(
            name,
            definition,
            expressions,
            *,
            unique=False,
            constraint=None,
            predicate=None,
        ):
            return {
                "name": name,
                "unique": unique,
                "nulls_not_distinct": False,
                "clustered": False,
                "replica_identity": False,
                "valid": True,
                "ready": True,
                "live": True,
                "constraint": constraint,
                "method": "btree",
                "definition": definition,
                "predicate": predicate,
                "expressions": expressions,
                "include_columns": [],
                "options": [],
                "tablespace": None,
            }

        exact_database_catalog = {
            "schema_version": 3,
            "candidate_manifest_sha256": deploy_guard.candidate_manifest_sha256(
                database_probe_manifest
            ),
            "server_major": 16,
            "database_encoding": "UTF8",
            "database_collate": "C.UTF-8",
            "database_ctype": "C.UTF-8",
            "database_locale_provider": "c",
            "database_collation_version": None,
            "database_icu_locale": None,
            "database_icu_rules": None,
            "standard_conforming_strings": "on",
            "tables": [
                {
                    "schema": "public",
                    "name": "sample",
                    "kind": "r",
                    "persistence": "p",
                    "access_method": "heap",
                    "row_security": False,
                    "force_row_security": False,
                    "replica_identity": "d",
                    "options": [],
                    "columns": [
                        physical_column(
                            1,
                            "id",
                            catalog_type("pg_catalog", "int4", "integer"),
                            nullable=False,
                            default="nextval('sample_id_seq'::regclass)",
                            owned_sequence=sample_sequence,
                        ),
                        physical_column(
                            2,
                            "parent_id",
                            catalog_type("pg_catalog", "int4", "integer"),
                            nullable=True,
                        ),
                        physical_column(
                            3,
                            "state",
                            catalog_type(
                                "public",
                                "sample_state",
                                "sample_state",
                                kind="e",
                                category="E",
                                enum_labels=["ready", "complete"],
                            ),
                            nullable=False,
                        ),
                        physical_column(
                            4,
                            "states",
                            catalog_type(
                                "public",
                                "_sample_state",
                                "sample_state[]",
                                category="A",
                                dimensions=1,
                                array_item=catalog_type(
                                    "public",
                                    "sample_state",
                                    "sample_state",
                                    kind="e",
                                    category="E",
                                    enum_labels=["ready", "complete"],
                                ),
                            ),
                            nullable=True,
                            storage="x",
                        ),
                    ],
                    "constraints": [
                        physical_constraint(
                            "ck_sample_id", "c", "CHECK ((id > 0))", ["id"]
                        ),
                        physical_constraint(
                            "fk_sample_parent",
                            "f",
                            "FOREIGN KEY (parent_id) REFERENCES sample(id) ON DELETE SET NULL",
                            ["parent_id"],
                            references={
                                "schema": "public",
                                "table": "sample",
                                "columns": ["id"],
                            },
                        ),
                        physical_constraint(
                            "pk_sample", "p", "PRIMARY KEY (id)", ["id"]
                        ),
                        physical_constraint(
                            "uq_sample_state", "u", "UNIQUE (state)", ["state"]
                        ),
                    ],
                    "indexes": [
                        physical_index(
                            "ix_sample_id",
                            "CREATE INDEX ix_sample_id ON public.sample USING btree (id)",
                            ["id"],
                        ),
                        physical_index(
                            "ix_sample_state_ready",
                            "CREATE INDEX ix_sample_state_ready ON public.sample USING btree (state) WHERE (state = 'ready'::sample_state)",
                            ["state"],
                            predicate="(state = 'ready'::sample_state)",
                        ),
                        physical_index(
                            "pk_sample",
                            "CREATE UNIQUE INDEX pk_sample ON public.sample USING btree (id)",
                            ["id"],
                            unique=True,
                            constraint={"name": "pk_sample", "type": "p"},
                        ),
                        physical_index(
                            "uq_sample_state",
                            "CREATE UNIQUE INDEX uq_sample_state ON public.sample USING btree (state)",
                            ["state"],
                            unique=True,
                            constraint={"name": "uq_sample_state", "type": "u"},
                        ),
                    ],
                }
            ],
            "sequences": [sample_sequence],
            "enum_types": [
                {
                    "schema": "public",
                    "name": "sample_state",
                    "labels": ["ready", "complete"],
                }
            ],
        }
        self.assertEqual(
            deploy_guard.validate_reference_catalog(
                database_probe_manifest,
                copy.deepcopy(exact_database_catalog),
            ),
            exact_database_catalog,
        )
        default_collation_column = copy.deepcopy(
            exact_database_catalog["tables"][0]["columns"][1]
        )
        default_collation_column["collation"] = {
            "schema": "pg_catalog",
            "name": "default",
        }
        self.assertEqual(
            deploy_guard._validate_physical_column(
                default_collation_column,
                "synthetic default-collation column",
            ),
            default_collation_column,
        )
        expected_database_schema_result = (
            deploy_guard.expected_database_schema_result(
                database_probe_manifest,
                exact_database_catalog,
            )
        )
        self.assertEqual(
            deploy_guard.validate_database_schema(
                database_probe_manifest,
                exact_database_catalog,
                expected_database_schema_result,
            ),
            expected_database_schema_result,
        )
        database_catalog_mutations = (
            (
                "missing table",
                lambda value: value["tables"].pop(),
            ),
            (
                "owned sequence omitted",
                lambda value: value["tables"][0]["columns"][0].update(
                    owned_sequence=None
                ),
            ),
            (
                "invalid backing index",
                lambda value: value["tables"][0]["indexes"][2].update(
                    valid=False
                ),
            ),
            (
                "primary key removed",
                lambda value: value["tables"][0]["constraints"].pop(2),
            ),
            (
                "enum identity changed",
                lambda value: value["tables"][0]["columns"][2]["type"].update(
                    enum_labels=["ready", "failed"]
                ),
            ),
            (
                "extension base type schema",
                lambda value: value["tables"][0]["columns"][0]["type"].update(
                    schema="extension_schema"
                ),
            ),
            (
                "managed schema changed",
                lambda value: value["tables"][0].update(schema=None),
            ),
            (
                "duplicate table",
                lambda value: value["tables"].append(
                    copy.deepcopy(value["tables"][-1])
                ),
            ),
            (
                "custom column collation",
                lambda value: value["tables"][0]["columns"][1].update(
                    collation={"schema": "public", "name": "custom_collation"}
                ),
            ),
            (
                "locale provider coerced",
                lambda value: value.update(database_locale_provider=True),
            ),
            (
                "ICU locale coerced",
                lambda value: value.update(database_icu_locale=7),
            ),
        )
        for label, mutate in database_catalog_mutations:
            observed_catalog = copy.deepcopy(exact_database_catalog)
            mutate(observed_catalog)
            with self.subTest(database_catalog=label), self.assertRaises(
                deploy_guard.DeployGuardError
            ):
                deploy_guard.validate_reference_catalog(
                    database_probe_manifest,
                    observed_catalog,
                )

        physical_semantic_mutations = (
            (
                "server default changed",
                lambda value: value["tables"][0]["columns"][0].update(
                    default=None
                ),
            ),
            (
                "foreign key action changed",
                lambda value: value["tables"][0]["constraints"][1].update(
                    definition="FOREIGN KEY (parent_id) REFERENCES sample(id) ON DELETE CASCADE"
                ),
            ),
            (
                "unique constraint changed",
                lambda value: value["tables"][0]["constraints"][3].update(
                    definition="UNIQUE NULLS NOT DISTINCT (state)"
                ),
            ),
            (
                "check constraint changed",
                lambda value: value["tables"][0]["constraints"][0].update(
                    definition="CHECK ((id >= 0))"
                ),
            ),
            (
                "partial index predicate changed",
                lambda value: value["tables"][0]["indexes"][1].update(
                    predicate="(state = 'complete'::sample_state)"
                ),
            ),
            (
                "index options changed",
                lambda value: value["tables"][0]["indexes"][0].update(
                    options=["fillfactor=70"]
                ),
            ),
            (
                "database collation changed",
                lambda value: value.update(database_collate="en_US.UTF-8"),
            ),
            (
                "database collation version changed",
                lambda value: value.update(database_collation_version="2.36"),
            ),
        )
        reference_digest = deploy_guard.reference_catalog_sha256(
            exact_database_catalog
        )
        for label, mutate in physical_semantic_mutations:
            changed_catalog = copy.deepcopy(exact_database_catalog)
            mutate(changed_catalog)
            deploy_guard.validate_reference_catalog(
                database_probe_manifest,
                changed_catalog,
            )
            changed_digest = deploy_guard.reference_catalog_sha256(changed_catalog)
            self.assertNotEqual(changed_digest, reference_digest)
            mismatched_result = copy.deepcopy(expected_database_schema_result)
            mismatched_result["reference_catalog_sha256"] = changed_digest
            mismatched_result["observed_catalog_sha256"] = changed_digest
            with self.subTest(physical_catalog_binding=label), self.assertRaises(
                deploy_guard.DeployGuardError
            ):
                deploy_guard.validate_database_schema(
                    database_probe_manifest,
                    exact_database_catalog,
                    mismatched_result,
                )

        database_result_coercions = (
            ("schema_version", True),
            ("candidate_manifest_sha256", 7),
            ("reference_catalog_sha256", None),
            ("observed_catalog_sha256", None),
            ("server_major", True),
            ("table_count", True),
            ("table_count", "1"),
        )
        for field, invalid_value in database_result_coercions:
            invalid_result = copy.deepcopy(expected_database_schema_result)
            invalid_result[field] = invalid_value
            with self.subTest(database_result_type=field), self.assertRaises(
                deploy_guard.DeployGuardError
            ):
                deploy_guard.validate_database_schema(
                    database_probe_manifest,
                    exact_database_catalog,
                    invalid_result,
                )
        mismatched_database_digest = copy.deepcopy(expected_database_schema_result)
        mismatched_database_digest["observed_catalog_sha256"] = "f" * 64
        with self.assertRaises(deploy_guard.DeployGuardError):
            deploy_guard.validate_database_schema(
                database_probe_manifest,
                exact_database_catalog,
                mismatched_database_digest,
            )

        migration_probe_namespace = {"__name__": "xjie_migration_probe_policy_test"}
        exec(
            compile(
                deploy_guard.MIGRATION_PROBE_SOURCE,
                "MIGRATION_PROBE.py",
                "exec",
            ),
            migration_probe_namespace,
        )

        class SyntheticNumeric:
            precision = 24
            scale = 8
            asdecimal = True

            def __init__(self, cache_attributes):
                self._static_cache_key = (type(self), *cache_attributes)

            def compile(self, dialect):
                return "NUMERIC(24, 8)"

            def dialect_impl(self, dialect):
                return self

        type_value = migration_probe_namespace["_type_value"]
        cache_order_a = (
            ("precision", 24),
            ("scale", 8),
            ("asdecimal", True),
        )
        cache_order_b = tuple(reversed(cache_order_a))
        normalized_a = type_value(SyntheticNumeric(cache_order_a), object())
        normalized_b = type_value(SyntheticNumeric(cache_order_b), object())
        self.assertEqual(normalized_a, normalized_b)
        self.assertEqual(
            [item[0] for item in normalized_a["cache_key"][1:]],
            ["asdecimal", "precision", "scale"],
        )

        materializer_source = deploy_guard.render_reference_schema_materializer(
            database_probe_manifest
        )
        compile(materializer_source, "REFERENCE_SCHEMA_MATERIALIZER.py", "exec")
        for materializer_primitive in (
            "candidate_manifest != EXPECTED_MANIFEST",
            'Base.metadata.create_all(bind=connection, checkfirst=False)',
            'REFERENCE_URL_KEY = "XJIE_REFERENCE_DATABASE_URL"',
            'REFERENCE_SOCKET = "/var/run/postgresql"',
            'PASSWORD = re.compile(r"[0-9a-f]{64}\\Z")',
            'if "DATABASE_URL" in os.environ',
            "migrations, heads = _migration_schema()",
            '"model_schema": _model_schema()',
        ):
            self.assertIn(materializer_primitive, materializer_source)
        self.assertNotIn("__EXPECTED_MANIFEST_JSON_LITERAL__", materializer_source)
        embedded_manifest = re.search(
            r"EXPECTED_MANIFEST = json\.loads\((.+)\)\nPASSWORD =",
            materializer_source,
            re.DOTALL,
        )
        self.assertIsNotNone(embedded_manifest)
        self.assertEqual(
            json.loads(ast.literal_eval(embedded_manifest.group(1))),
            database_probe_manifest,
        )

        reference_probe_source = deploy_guard.render_reference_catalog_probe(
            database_probe_manifest
        )
        database_probe_source = deploy_guard.render_database_schema_probe(
            database_probe_manifest,
            exact_database_catalog,
        )
        self.assertTrue(database_probe_source.startswith("\\set ON_ERROR_STOP on\n"))
        for required_database_probe_primitive in (
            "\\getenv expected_database XJIE_EXPECTED_DATABASE",
            "BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;",
            "SET LOCAL search_path TO public, pg_catalog;",
            "current_setting('transaction_read_only') = 'on'",
            "current_setting('search_path') = 'public, pg_catalog'",
            "current_database() = :'expected_database'",
            "current_schema() = 'public'",
            "current_setting('standard_conforming_strings')",
            "pg_catalog.pg_class",
            "pg_catalog.pg_attribute",
            "pg_catalog.pg_type",
            "pg_catalog.pg_enum",
            "pg_catalog.pg_constraint",
            "pg_catalog.pg_index",
            "pg_catalog.pg_sequence",
            "pg_catalog.pg_attrdef",
            "pg_catalog.pg_proc",
            "pg_catalog.pg_collation",
            "pg_catalog.pg_operator",
            "pg_catalog.pg_opclass",
            "pg_catalog.pg_opfamily",
            "pg_catalog.pg_conversion",
            "pg_catalog.pg_extension",
            "pg_catalog.pg_get_expr",
            "pg_catalog.pg_get_constraintdef",
            "pg_catalog.pg_get_indexdef",
            "database_value.datlocprovider",
            "database_value.datcollversion",
            "database_value.daticulocale",
            "database_value.daticurules",
            "sequence_ownership",
            "constraint_records",
            "index_records",
            "role_attestation",
            "NOT role_value.rolsuper",
            "pg_catalog.has_database_privilege",
            "pg_catalog.has_schema_privilege",
            "pg_catalog.has_table_privilege",
            "pg_catalog.has_sequence_privilege",
            "relation.relname <> 'alembic_version'",
            "WITH ORDINALITY AS key_value(attribute_number, ordinality)",
            "observed.catalog = expected.catalog",
            "ROLLBACK;",
        ):
            self.assertIn(required_database_probe_primitive, database_probe_source)
            self.assertIn(
                required_database_probe_primitive,
                reference_probe_source
                if required_database_probe_primitive
                not in (
                    "\\getenv expected_database XJIE_EXPECTED_DATABASE",
                    "current_database() = :'expected_database'",
                    "role_attestation",
                    "NOT role_value.rolsuper",
                    "pg_catalog.has_database_privilege",
                    "pg_catalog.has_schema_privilege",
                    "pg_catalog.has_table_privilege",
                    "pg_catalog.has_sequence_privilege",
                    "observed.catalog = expected.catalog",
                )
                else database_probe_source,
            )
        for forbidden_database_probe_capability in (
            "sqlalchemy",
            "create_engine",
            "sitecustomize",
            "app.main",
            "app.models",
            "app.db",
            "DATABASE_URL",
            "os.environ",
            "\\include",
            "COPY ",
        ):
            self.assertNotIn(
                forbidden_database_probe_capability,
                database_probe_source,
            )
        for alembic_attestation_primitive in (
            "alembic_attestation AS (",
            "pg_catalog.has_table_privilege(\n              current_user, relation.oid, 'SELECT'",
            "attribute.attname = 'version_num'",
            "constraint_value.conname = 'alembic_version_pkc'",
            "AND constraint_value.connoinherit) = 1",
            "index_relation.relname = 'alembic_version_pkc'",
            "pg_catalog.count(*) FROM public.alembic_version",
            "pg_catalog.min(version_num) FROM public.alembic_version",
            "= '0002_current' AS valid",
        ):
            self.assertIn(alembic_attestation_primitive, database_probe_source)
            self.assertNotIn(alembic_attestation_primitive, reference_probe_source)
        self.assertNotIn(
            "AND NOT constraint_value.connoinherit) = 1",
            database_probe_source,
        )
        self.assertEqual(
            database_probe_source.count(
                "BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;"
            ),
            1,
        )
        self.assertEqual(database_probe_source.count("ROLLBACK;"), 1)
        self.assertLess(
            database_probe_source.index(
                "BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;"
            ),
            database_probe_source.index("WITH\nserver_identity AS"),
        )
        self.assertLess(
            database_probe_source.index("observed.catalog = expected.catalog"),
            database_probe_source.index("ROLLBACK;"),
        )
        for marker in (
            "__PHYSICAL_SCHEMA_CATALOG_SQL__",
            "__EXPECTED_REFERENCE_CATALOG_SQL__",
            "__CANDIDATE_MANIFEST_SHA256_SQL__",
            "__REFERENCE_CATALOG_SHA256_SQL__",
            "__EXPECTED_ALEMBIC_HEAD_SQL__",
        ):
            self.assertNotIn(marker, database_probe_source)
        catalog_start = database_probe_source.index(
            "$xjie_reference_catalog$"
        ) + len(
            "$xjie_reference_catalog$"
        )
        catalog_end = database_probe_source.index(
            "$xjie_reference_catalog$::pg_catalog.jsonb", catalog_start
        )
        self.assertEqual(
            json.loads(database_probe_source[catalog_start:catalog_end]),
            exact_database_catalog,
        )
        self.assertEqual(
            database_probe_source.count(
                expected_database_schema_result["reference_catalog_sha256"]
            ),
            2,
        )
        reordered_database_result = dict(
            reversed(list(expected_database_schema_result.items()))
        )
        self.assertEqual(
            deploy_guard.validate_database_schema(
                database_probe_manifest,
                exact_database_catalog,
                reordered_database_result,
            ),
            reordered_database_result,
        )
        with tempfile.TemporaryDirectory() as migration_probe_temp:
            migration_probe_root = Path(migration_probe_temp)

            def owner_only_text_file(name, value):
                path = migration_probe_root / name
                path.write_text(value, encoding="utf-8")
                path.chmod(0o600)
                return path

            old_manifest_path = owner_only_text_file(
                "old-manifest.json",
                json.dumps(old_migration_manifest, separators=(",", ":")),
            )
            candidate_manifest_path = owner_only_text_file(
                "candidate-manifest.json",
                json.dumps(candidate_migration_manifest, separators=(",", ":")),
            )
            database_probe_manifest_path = owner_only_text_file(
                "database-probe-manifest.json",
                json.dumps(database_probe_manifest, separators=(",", ":")),
            )
            production_sized_manifest = copy.deepcopy(database_probe_manifest)
            production_sized_manifest["model_schema"] = []
            for table_number in range(deploy_guard.REFERENCE_SCHEMA_TABLE_COUNT):
                table = copy.deepcopy(database_probe_manifest["model_schema"][0])
                table["name"] = "sample_{0:02d}".format(table_number)
                production_sized_manifest["model_schema"].append(table)
            deploy_guard.validate_migration_manifest(production_sized_manifest)
            production_sized_manifest_path = owner_only_text_file(
                "production-sized-manifest.json",
                json.dumps(production_sized_manifest, separators=(",", ":")),
            )
            reference_catalog_path = owner_only_text_file(
                "reference-catalog.json",
                json.dumps(exact_database_catalog, separators=(",", ":")),
            )
            heads_path = owner_only_text_file(
                "heads.txt", migration_heads_output
            )
            current_path = owner_only_text_file(
                "current.txt", migration_current_output
            )
            with mock.patch("builtins.print") as no_delta_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "validate-no-migration-delta",
                            "--old-manifest", str(old_manifest_path),
                            "--candidate-manifest", str(candidate_manifest_path),
                            "--heads", str(heads_path),
                            "--current", str(current_path),
                        ]
                    ),
                    0,
                )
                no_delta_print.assert_called_once_with(
                    "no migration delta; database is at head: 0002_current"
                )

            candidate_manifest_path.chmod(0o640)
            with mock.patch("builtins.print") as wrong_mode_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "validate-no-migration-delta",
                            "--old-manifest", str(old_manifest_path),
                            "--candidate-manifest", str(candidate_manifest_path),
                            "--heads", str(heads_path),
                            "--current", str(current_path),
                        ]
                    ),
                    1,
                )
                self.assertTrue(wrong_mode_print.called)
            candidate_manifest_path.chmod(0o600)

            probe_path = migration_probe_root / "PROBE.py"
            with mock.patch("builtins.print") as emit_probe_print:
                self.assertEqual(
                    deploy_guard.main(
                        ["emit-migration-probe", "--output", str(probe_path)]
                    ),
                    0,
                )
                emit_probe_print.assert_not_called()
            self.assertEqual(probe_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(probe_path.read_text(encoding="utf-8"), probe_source)
            with mock.patch("builtins.print") as exclusive_probe_print:
                self.assertEqual(
                    deploy_guard.main(
                        ["emit-migration-probe", "--output", str(probe_path)]
                    ),
                    1,
                )
                self.assertTrue(exclusive_probe_print.called)

            materializer_path = migration_probe_root / "MATERIALIZER.py"
            self.assertEqual(
                deploy_guard.main(
                    [
                        "emit-reference-schema-materializer",
                        "--candidate-manifest", str(database_probe_manifest_path),
                        "--output", str(materializer_path),
                    ]
                ),
                0,
            )
            self.assertEqual(materializer_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                materializer_path.read_text(encoding="utf-8"),
                materializer_source,
            )
            materializer_result = {
                "schema_version": 3,
                "candidate_manifest_sha256": (
                    deploy_guard.candidate_manifest_sha256(
                        production_sized_manifest
                    )
                ),
                "table_count": deploy_guard.REFERENCE_SCHEMA_TABLE_COUNT,
            }
            materializer_result_path = owner_only_text_file(
                "materializer-result.json",
                json.dumps(materializer_result, separators=(",", ":")) + "\n",
            )
            self.assertEqual(
                deploy_guard.load_owner_only_reference_materializer_result(
                    materializer_result_path,
                    production_sized_manifest,
                ),
                materializer_result,
            )
            with mock.patch("builtins.print") as materializer_result_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "validate-reference-materializer-result",
                            "--candidate-manifest",
                            str(production_sized_manifest_path),
                            "--result",
                            str(materializer_result_path),
                        ]
                    ),
                    0,
                )
                materializer_result_print.assert_called_once_with(
                    "reference schema materializer is exact: tables={0}".format(
                        deploy_guard.REFERENCE_SCHEMA_TABLE_COUNT
                    )
                )
            logged_materializer_result = owner_only_text_file(
                "logged-materializer-result.json",
                "candidate import log\n"
                + json.dumps(materializer_result, separators=(",", ":")),
            )
            drifted_materializer_result = copy.deepcopy(materializer_result)
            drifted_materializer_result["table_count"] = 52
            drifted_materializer_result_path = owner_only_text_file(
                "drifted-materializer-result.json",
                json.dumps(drifted_materializer_result, separators=(",", ":")),
            )
            oversized_materializer_result = owner_only_text_file(
                "oversized-materializer-result.json",
                " " * (deploy_guard.MAX_REFERENCE_MATERIALIZER_RESULT_BYTES + 1),
            )
            for rejected_materializer_result in (
                logged_materializer_result,
                drifted_materializer_result_path,
                oversized_materializer_result,
            ):
                with self.subTest(
                    materializer_result=rejected_materializer_result.name
                ), self.assertRaises(deploy_guard.DeployGuardError):
                    deploy_guard.load_owner_only_reference_materializer_result(
                        rejected_materializer_result,
                        production_sized_manifest,
                    )
            reference_probe_path = migration_probe_root / "REFERENCE_CATALOG.sql"
            self.assertEqual(
                deploy_guard.main(
                    [
                        "emit-reference-catalog-probe",
                        "--candidate-manifest", str(database_probe_manifest_path),
                        "--output", str(reference_probe_path),
                    ]
                ),
                0,
            )
            self.assertEqual(reference_probe_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                reference_probe_path.read_text(encoding="utf-8"),
                reference_probe_source,
            )

            database_result_path = owner_only_text_file(
                "database-catalog.json",
                json.dumps(
                    expected_database_schema_result,
                    separators=(",", ":"),
                ),
            )
            with mock.patch("builtins.print") as database_schema_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "validate-database-schema",
                            "--candidate-manifest", str(database_probe_manifest_path),
                            "--reference-catalog", str(reference_catalog_path),
                            "--database-catalog", str(database_result_path),
                        ]
                    ),
                    0,
                )
                database_schema_print.assert_called_once_with(
                    "database schema matches exact reference catalog: "
                    "tables={0} digest={1}".format(
                        expected_database_schema_result["table_count"],
                        expected_database_schema_result[
                            "reference_catalog_sha256"
                        ],
                    )
                )
            database_result_path.chmod(0o640)
            with mock.patch("builtins.print") as database_mode_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "validate-database-schema",
                            "--candidate-manifest", str(database_probe_manifest_path),
                            "--reference-catalog", str(reference_catalog_path),
                            "--database-catalog", str(database_result_path),
                        ]
                    ),
                    1,
                )
                self.assertTrue(database_mode_print.called)
            database_result_path.chmod(0o600)

            database_probe_path = migration_probe_root / "DATABASE_SCHEMA_PROBE.py"
            rejected_database_probe_path = (
                migration_probe_root / "REJECTED_DATABASE_SCHEMA_PROBE.py"
            )
            database_probe_manifest_path.chmod(0o640)
            with mock.patch("builtins.print") as manifest_mode_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "emit-database-schema-probe",
                            "--candidate-manifest", str(database_probe_manifest_path),
                            "--reference-catalog", str(reference_catalog_path),
                            "--output", str(rejected_database_probe_path),
                        ]
                    ),
                    1,
                )
                self.assertTrue(manifest_mode_print.called)
            self.assertFalse(rejected_database_probe_path.exists())
            database_probe_manifest_path.chmod(0o600)
            with mock.patch("builtins.print") as emit_database_probe_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "emit-database-schema-probe",
                            "--candidate-manifest", str(database_probe_manifest_path),
                            "--reference-catalog", str(reference_catalog_path),
                            "--output", str(database_probe_path),
                        ]
                    ),
                    0,
                )
                emit_database_probe_print.assert_not_called()
            self.assertEqual(database_probe_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                database_probe_path.read_text(encoding="utf-8"),
                database_probe_source,
            )
            with mock.patch("builtins.print") as database_probe_exclusive_print:
                self.assertEqual(
                    deploy_guard.main(
                        [
                            "emit-database-schema-probe",
                            "--candidate-manifest", str(database_probe_manifest_path),
                            "--reference-catalog", str(reference_catalog_path),
                            "--output", str(database_probe_path),
                        ]
                    ),
                    1,
                )
                self.assertTrue(database_probe_exclusive_print.called)

        for required in (
            "#!/bin/bash -p",
            'readonly OFFICIAL_ORIGIN_HTTPS="https://github.com/doyoulikelin-wq/XJie_IOS.git"',
            'readonly EXPECTED_SHA="${1:-}"',
            'readonly ACTION="${2:-deploy}"',
            'readonly RUNTIME_PARENT="/dev/shm"',
            '[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]',
            'readonly CANONICAL_BRANCH="main"',
            'readonly TRUSTED_ENTRYPOINT="/usr/local/sbin/xjie-production-deploy"',
            'readonly TRUSTED_LAUNCHER="/usr/local/sbin/xjie-production-launch"',
            'readonly TRUSTED_BUNDLE_DIR="/usr/local/libexec/xjie-production-deploy"',
            'readonly LAUNCH_AUTHORITY="/etc/xjie-production-deploy/launch-authority"',
            'readonly DEPLOY_PRINCIPAL="mayl"',
            'deploy_principal_uid=$(/usr/bin/id -u "$DEPLOY_PRINCIPAL")',
            '[[ "$EUID" -eq "$deploy_principal_uid" ]]',
            'assert_root_owned_file "$TRUSTED_LAUNCHER" 555',
            'assert_root_owned_file "$TRUSTED_ENTRYPOINT" 555',
            'assert_root_owned_file "$TRUSTED_SPEC" 444',
            'assert_root_owned_file "$TRUSTED_DEPLOY_GUARD" 444',
            'assert_root_owned_file "$TRUSTED_RELEASE_GATE" 444',
            'assert_root_owned_file "$TRUSTED_TEST_INVENTORY" 444',
            'assert_root_owned_file "$LAUNCH_AUTHORITY" 400',
            'trusted_bundle_sha256=$(compute_trusted_bundle_sha256)',
            '[[ "$journal_bundle" == "$trusted_bundle_sha256" ]]',
            'readonly DOCKER_HOST="unix:///var/run/docker.sock"',
            '-c core.hooksPath=/dev/null',
            'readonly GIT_NO_REPLACE_OBJECTS="1"',
            "unsafe_startup_name in TAR_OPTIONS GREP_OPTIONS POSIXLY_CORRECT BASH_COMPAT",
            '[[ "$inherited_name" == GIT_* || "$inherited_name" == DOCKER_*',
            '|| "$inherited_name" == LD_* || "$inherited_name" == DYLD_*',
            "unset SSL_CERT_FILE SSL_CERT_DIR REQUESTS_CA_BUNDLE CURL_CA_BUNDLE",
            'git init --bare --quiet --template=/dev/null "$official_git_dir"',
            'git --git-dir="$official_git_dir" fetch --no-tags --no-write-fetch-head',
            'git --git-dir="$official_git_dir" fsck --strict --no-dangling "$EXPECTED_SHA"',
            'git --git-dir="$official_git_dir" ls-tree -rz --full-tree "$EXPECTED_SHA"',
            "validate-source-snapshot",
            'ingest --confirm-ingest',
            'expand-deploy --confirm-expand-migration',
            "acquire_or_validate_deploy_lock",
            "validate_clean_launcher_authority",
            "broker_request PING >/dev/null",
            "socket.SO_PEERCRED",
            "peer_pid != int(expected_supervisor)",
            'broker_request "VERIFY ${EXPECTED_SHA}"',
            "broker_request JUNIT",
            '[[ "$(compute_trusted_launcher_sha256)" == "$XJIE_DEPLOY_LAUNCHER_SHA256" ]]',
            '[[ "$REMOTE_MAIN" == "$EXPECTED_SHA" ]]',
            'image_ref="${image_repository}:main-${EXPECTED_SHA}"',
            '--iidfile "$image_id_path"',
            "production_deploy_guard.py",
            "snapshot-env",
            "validate-inspects",
            "scan-image",
            'docker image save --output "$image_scan_archive" "$image_id"',
            "emit-migration-probe",
            "emit-reference-schema-materializer",
            "emit-reference-catalog-probe",
            "validate-reference-materializer-result",
            "emit-database-schema-probe",
            "validate-database-schema",
            "validate-no-migration-delta",
            "validate-expand-migration",
            "validate-expand-catalog-transition",
            "validate-expand-backup-binding",
            "validate-expand-restore-volume-inspect",
            "plan-expand-restore-volume-cleanup",
            "attest-expand-restore-volume",
            "emit-expand-old-app-compat-probe",
            "write-expand-evidence",
            "validate-expand-evidence",
            '--network none',
            '--read-only',
            '--cap-drop ALL',
            '--security-opt no-new-privileges',
            "plan-recovery",
            "plan-orphan-cleanup",
            "plan-backup-retention",
            "orphan-cleanup-v1",
            "backup-retention-v1",
            "com.jianjieaitech.xjie.deploy.scope=production-api",
            "schema-reference-server",
            "schema-reference-materializer",
            "schema-reference-catalog",
            "schema-restore-capacity",
            "schema-restore-volume-init",
            "schema-restore-server",
            "schema-restore-volume",
            "volume-nocopy",
            '--application-env "$env_snapshot"',
            "--log-driver none",
            'docker container rm --force --volumes "$container_id"',
            "stop_official_candidate",
            "quarantine_official_candidate",
            "rename_backup_to_official",
            "verify_named_candidate_quarantined",
            "verify_official_old",
            "cleanup_expired_backups",
            "write_cutover_journal prepared",
            "write_cutover_journal old_stopped",
            "write_cutover_journal old_renamed",
            "write_cutover_journal candidate_renamed",
            "write_cutover_journal candidate_started",
            '[[ "$(docker container inspect --format \'{{.RestartCount}}\' "$container_name")" == "0" ]]',
            "候选容器没有完成 30 秒连续稳定窗口",
            'verify_running_revision "$EXPECTED_SHA"',
            "Deployment did not complete; invoking the journal-bound recovery planner.",
        ):
            self.assertIn(required, deploy)
        for forbidden_deploy_behavior in (
            "alembic upgrade",
            "run_old_image_compatibility_smoke",
            'Path("/app")',
            "read(4 * 1024 * 1024)",
            "migrate|ingest|all",
            'ACTION" == "all',
            "read -r -p",
            "--ephemeral-default",
            "bash /home/mayl/deploy_literature.sh",
            "OFFICIAL_ORIGIN_SSH",
            "remove_official_candidate",
            "remove_named_candidate",
            "#!/usr/bin/env bash",
            "git fetch --no-tags origin",
            "git status --porcelain",
            'exec 9>"$LOCK_FILE"',
        ):
            self.assertNotIn(forbidden_deploy_behavior, deploy)
        self.assertNotIn("create_all", backend_main)
        self.assertNotIn("ALTER TABLE", backend_main.upper())
        self.assertNotIn('docker restart "${CONTAINER}"', deploy)
        self.assertNotIn("config.get(\"Cmd\")", deploy)
        self.assertNotIn("config.get(\"Env\")", deploy)
        lock = deploy.index('ok "已取得生产部署互斥锁"')
        locked_bundle = deploy.index(
            "trusted_bundle_sha256=$(compute_trusted_bundle_sha256)", lock
        )
        recovery = deploy.index("  recover_interrupted_cutover", lock)
        late_candidate_dependencies = deploy.index(
            "for command in cmp git grep tar", recovery
        )
        fetch = deploy.index(
            'git --git-dir="$official_git_dir" fetch --no-tags --no-write-fetch-head',
            recovery,
        )
        qualification = deploy.index(
            'step "执行候选代码前证明 exact-SHA bundle 与 root 预装受信副本逐字节一致"',
            fetch,
        )
        official_qualification = deploy.index(
            'step "验证 merged PR、官方 main 精确 tip/CI 与 main/XAGE 双分支保护"',
            qualification,
        )
        official_qualification_call = deploy.index(
            "verify_official_candidate", official_qualification
        )
        archive = deploy.index(
            'git --git-dir="$official_git_dir" archive --format=tar "$EXPECTED_SHA"',
            official_qualification_call,
        )
        ingest_branch = deploy.index('if [[ "$ACTION" == "ingest" ]]', official_qualification_call)
        ingest_exit = deploy.index("  exit 0", ingest_branch)
        orphan_cleanup = deploy.index("\ncleanup_prejournal_orphans\n", archive)
        env_snapshot_step = deploy.index(
            'step "创建 owner-only 不可变生产环境快照"', archive
        )
        build = deploy.index('step "构建 EXPECTED_SHA 候选镜像"', env_snapshot_step)
        image_scan = deploy.index(
            'step "扫描候选镜像全部历史 layer、Config.Env 与禁入秘密材料"', build
        )
        no_delta_manifest = deploy.index(
            'step "证明运行镜像与候选镜像没有 migration/model schema delta"',
            image_scan,
        )
        database_check = deploy.index(
            'step "验证生产数据库已处于候选 Alembic heads（普通 deploy 禁止 DDL）"',
            no_delta_manifest,
        )
        reference_catalog_materialization = deploy.index(
            'step "在断网临时 PostgreSQL 中物化候选模型的参考数据库结构"',
            database_check,
        )
        reference_materializer = deploy.index(
            "\n    run_reference_schema_materializer \\",
            reference_catalog_materialization,
        )
        reference_catalog_probe = deploy.index(
            "\n    run_reference_catalog_probe \\",
            reference_materializer,
        )
        reference_stop = deploy.index(
            "\n    stop_reference_database\n",
            reference_catalog_probe,
        )
        database_catalog_check = deploy.index(
            'step "只向 digest-pinned psql 提供生产凭据并核对参考 catalog"',
            reference_stop,
        )
        production_probe_snapshot = deploy.index(
            "snapshot-database-probe-env",
            database_catalog_check,
        )
        production_catalog_probe = deploy.index(
            "\n    run_database_schema_probe \\",
            production_probe_snapshot,
        )
        cutover = deploy.index('step "切换到候选镜像"', database_catalog_check)
        stability = deploy.index(
            'step "执行 30 秒连续稳定窗口与致命日志检查"', cutover
        )
        final_remote = deploy.index(
            'step "提交部署前最后回读官方候选资格"', stability
        )
        clear_journal = deploy.index(
            '/usr/bin/python3 -I "$deploy_guard" clear-journal', final_remote
        )
        commit = deploy.index("deployment_committed=1", clear_journal)
        committed_service_cleanup = deploy.index(
            "\n  cleanup_prejournal_orphans\n", commit
        )
        backup_retention = deploy.index("\n  cleanup_expired_backups\n", commit)
        self.assertLess(lock, recovery)
        self.assertLess(lock, locked_bundle)
        self.assertLess(locked_bundle, recovery)
        self.assertLess(recovery, late_candidate_dependencies)
        self.assertLess(late_candidate_dependencies, fetch)
        self.assertLess(recovery, fetch)
        self.assertLess(fetch, qualification)
        self.assertLess(qualification, official_qualification)
        self.assertLess(official_qualification_call, archive)
        self.assertLess(official_qualification_call, ingest_branch)
        self.assertLess(ingest_branch, ingest_exit)
        self.assertLess(ingest_exit, archive)
        self.assertLess(archive, orphan_cleanup)
        self.assertLess(orphan_cleanup, env_snapshot_step)
        self.assertLess(archive, env_snapshot_step)
        self.assertLess(env_snapshot_step, build)
        self.assertLess(build, image_scan)
        self.assertLess(image_scan, no_delta_manifest)
        self.assertLess(no_delta_manifest, database_check)
        self.assertLess(database_check, reference_catalog_materialization)
        self.assertLess(reference_catalog_materialization, reference_materializer)
        self.assertLess(reference_materializer, reference_catalog_probe)
        self.assertLess(reference_catalog_probe, reference_stop)
        self.assertLess(reference_stop, database_catalog_check)
        self.assertLess(database_catalog_check, production_probe_snapshot)
        self.assertLess(production_probe_snapshot, production_catalog_probe)
        self.assertLess(production_catalog_probe, cutover)
        self.assertLess(database_catalog_check, cutover)
        self.assertLess(cutover, stability)
        self.assertLess(stability, final_remote)
        self.assertLess(final_remote, clear_journal)
        self.assertLess(clear_journal, commit)
        self.assertLess(commit, committed_service_cleanup)
        self.assertLess(committed_service_cleanup, backup_retention)
        self.assertLess(commit, backup_retention)
        expand_gate = deploy.index(
            'step "验证 exact old history 与唯一线性 additive migration chain"',
            database_check,
        )
        expand_approval = deploy.index(
            'broker_request "MIGRATION ${EXPECTED_SHA}"',
            expand_gate,
        )
        expand_migration_identity = deploy.index(
            "snapshot-database-migration-env",
            expand_approval,
        )
        expand_backup = deploy.index(
            'step "创建 production pg_dump custom 备份并验证完整 TOC"',
            expand_migration_identity,
        )
        expand_restore = deploy.index(
            'step "在隔离 PG16 恢复真实备份、执行同一事务 runner、核对 catalog 与旧应用 CRUD"',
            expand_backup,
        )
        expand_backup_recheck = deploy.index(
            "validate-expand-backup-binding",
            expand_restore,
        )
        expand_database_size = deploy.index(
            "run_expand_database_size_probe",
            expand_backup_recheck,
        )
        expand_restore_volume_create = deploy.index(
            "create_restore_volume",
            expand_database_size,
        )
        expand_restore_capacity = deploy.index(
            "run_restore_volume_capacity_probe",
            expand_restore_volume_create,
        )
        expand_restore_volume_attestation = deploy.index(
            "attest-expand-restore-volume",
            expand_restore_capacity,
        )
        expand_restore_volume_init = deploy.index(
            "initialize_restore_volume",
            expand_restore_volume_attestation,
        )
        expand_rehearsal_transaction = deploy.index(
            'schema-migration-rehearsal "$image_id"',
            expand_restore_volume_init,
        )
        expand_old_compat = deploy.index(
            "validate-expand-old-app-compat-result",
            expand_rehearsal_transaction,
        )
        expand_restore_volume_remove = deploy.index(
            "remove_exact_restore_volume",
            expand_old_compat,
        )
        expand_restore_verified = deploy.index(
            '--journal "$expand_journal" --state restore_verified',
            expand_restore_volume_remove,
        )
        expand_production_transaction = deploy.index(
            'step "最终资格复核后以 migration role 执行唯一生产事务"',
            expand_old_compat,
        )
        expand_post_attestation = deploy.index(
            'step "事务后以只读角色精确证明 candidate head/catalog 且旧应用仍健康"',
            expand_production_transaction,
        )
        expand_cutover_boundary = deploy.index(
            'step "在任何容器切换前持久记录 expand cutover 边界"',
            expand_post_attestation,
        )
        expand_evidence = deploy.index(
            'step "绑定备份、事务、candidate catalog 与稳定切换的 exact evidence"',
            final_remote,
        )
        expand_completed = deploy.index(
            "--journal \"$expand_journal\" --state completed",
            expand_evidence,
        )
        self.assertLess(expand_gate, expand_approval)
        self.assertLess(expand_approval, expand_migration_identity)
        self.assertLess(expand_migration_identity, expand_backup)
        self.assertLess(expand_backup, expand_restore)
        self.assertLess(expand_restore, expand_backup_recheck)
        self.assertLess(expand_backup_recheck, expand_database_size)
        self.assertLess(expand_database_size, expand_restore_volume_create)
        self.assertLess(expand_restore_volume_create, expand_restore_capacity)
        self.assertLess(
            expand_restore_capacity,
            expand_restore_volume_attestation,
        )
        self.assertLess(
            expand_restore_volume_attestation,
            expand_restore_volume_init,
        )
        self.assertLess(expand_restore_volume_init, expand_rehearsal_transaction)
        self.assertLess(expand_rehearsal_transaction, expand_old_compat)
        self.assertLess(expand_old_compat, expand_restore_volume_remove)
        self.assertLess(expand_restore_volume_remove, expand_restore_verified)
        self.assertLess(expand_restore_verified, expand_production_transaction)
        self.assertLess(expand_production_transaction, expand_post_attestation)
        self.assertLess(expand_post_attestation, expand_cutover_boundary)
        self.assertLess(expand_cutover_boundary, cutover)
        self.assertLess(cutover, expand_evidence)
        self.assertLess(expand_evidence, expand_completed)
        self.assertLess(expand_completed, clear_journal)
        self.assertLess(official_qualification_call, build)
        self.assertLess(deploy.index("broker_request JUNIT", build), database_check)
        self.assertLess(
            deploy.index("validate-no-migration-delta"),
            deploy.index('docker container stop --time 30 "$old_container_id"'),
        )
        self.assertLess(
            deploy.index('docker container stop --time 30 "$old_container_id"', cutover),
            deploy.index('docker container start "$candidate_container_id"', cutover),
        )
        self.assertEqual(
            re.findall(
                r"write_cutover_journal (prepared|old_stopped|old_renamed|candidate_renamed|candidate_started)",
                deploy,
            ),
            [
                "prepared",
                "old_stopped",
                "old_renamed",
                "candidate_renamed",
                "candidate_started",
            ],
        )
        self.assertGreaterEqual(deploy.count("verify_official_candidate"), 5)
        self.assertEqual(deploy.count("cleanup_prejournal_orphans"), 4)
        self.assertEqual(deploy.count("cleanup_expired_backups"), 2)
        recovery_body = deploy[
            deploy.index("recover_interrupted_cutover()") : deploy.index(
                "emit_lifecycle_label_args()"
            )
        ]
        self.assertNotIn("container rm", recovery_body)
        self.assertNotIn("$source_root", recovery_body)
        self.assertNotIn("$secret_env_file", recovery_body)
        self.assertIn(
            'docker container rename "$journal_candidate_container_id" "$journal_candidate"',
            recovery_body,
        )
        full_batch_recheck = deploy.index(
            'docker container inspect "${managed_ids[@]}" >"$recheck_path"'
        )
        first_orphan_delete = deploy.index(
            'docker container rm --force --volumes "$container_id"', full_batch_recheck
        )
        self.assertLess(full_batch_recheck, first_orphan_delete)
        retention_body = deploy[
            deploy.index("cleanup_expired_backups()") : deploy.index("cleanup()")
        ]
        self.assertIn('docker container rm "$container_id"', retention_body)
        self.assertNotIn(
            'docker container rm --force "$container_id"', retention_body
        )
        with tempfile.TemporaryDirectory() as privileged_bash_temp:
            privileged_bash_root = Path(privileged_bash_temp)
            inherited_startup = privileged_bash_root / "BASH_ENV"
            marker = privileged_bash_root / "marker"
            inherited_startup.write_text(
                'printf inherited >"$XJIE_BASH_ENV_MARKER"\n', encoding="utf-8"
            )
            launcher = privileged_bash_root / "launcher"
            launcher.write_text("#!/bin/bash -p\nexit 0\n", encoding="utf-8")
            launcher.chmod(0o700)
            privileged_run = subprocess.run(
                [str(launcher)],
                check=False,
                env={
                    **os.environ,
                    "BASH_ENV": str(inherited_startup),
                    "XJIE_BASH_ENV_MARKER": str(marker),
                },
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.assertEqual(privileged_run.returncode, 0, msg=privileged_run.stdout)
            self.assertFalse(marker.exists())
        clean_environment = dict(os.environ)
        for rejected_name in (
            "TAR_OPTIONS",
            "GREP_OPTIONS",
            "POSIXLY_CORRECT",
            "BASH_COMPAT",
        ):
            clean_environment.pop(rejected_name, None)
        for rejected_name in (
            "TAR_OPTIONS",
            "GREP_OPTIONS",
            "POSIXLY_CORRECT",
            "BASH_COMPAT",
        ):
            with self.subTest(rejected_startup_environment=rejected_name):
                rejected_environment = dict(clean_environment)
                rejected_environment[rejected_name] = (
                    "--checkpoint=1" if rejected_name == "TAR_OPTIONS" else "1"
                )
                rejected_run = subprocess.run(
                    [str(deploy_path), "--doctor"],
                    check=False,
                    env=rejected_environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self.assertNotEqual(rejected_run.returncode, 0)
                self.assertIn("clean-environment launcher", rejected_run.stdout)
        inherited_function_environment = dict(clean_environment)
        inherited_function_environment["BASH_FUNC_xjie_injected%%"] = (
            "() { printf injected; }"
        )
        inherited_function_run = subprocess.run(
            [str(deploy_path), "--doctor"],
            check=False,
            env=inherited_function_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertNotEqual(inherited_function_run.returncode, 0)
        self.assertIn("clean launcher", inherited_function_run.stdout)
        syntax = subprocess.run(
            ["/bin/bash", "-n", str(deploy_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, msg=syntax.stdout)
        helper_compile = subprocess.run(
            [sys.executable, "-m", "py_compile", str(deploy_guard_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.assertEqual(helper_compile.returncode, 0, msg=helper_compile.stdout)

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
