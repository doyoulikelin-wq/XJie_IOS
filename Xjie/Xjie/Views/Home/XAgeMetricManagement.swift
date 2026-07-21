import SwiftUI
import UIKit

/// 指标卡片与管理模块。
///
/// 负责 Apple 健康授权卡、指标卡、指标库管理、指标详情及手动录入表单。
/// 入参中的指标与趋势均由外部同步层提供；保存回调只负责通知页面刷新，不在视图内维护第二份业务数据源。
struct XAgeAppleHealthSyncCard: View {
    /// Apple 健康授权、状态和错误信息来源。
    @ObservedObject var viewModel: AppleHealthSyncViewModel
    /// `true` 显示首页紧凑授权卡，`false` 显示管理页完整状态。
    let compactAuthorization: Bool
    /// 用户点击授权或同步按钮后的异步动作。
    let onSyncAppleHealth: () async -> Void
    @Environment(\.openURL) private var openURL

    @ViewBuilder
    var body: some View {
        if compactAuthorization {
            authorizationBody
        } else {
            managementBody
        }
    }

    private var authorizationBody: some View {
        HStack(spacing: 12) {
            Image(systemName: "heart.text.square.fill")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(
                    Circle().fill(
                        LinearGradient(
                            colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                )

            VStack(alignment: .leading, spacing: 4) {
                Text("Apple 健康")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text("授权后可以更好地评估当前的身体指标")
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .fixedSize(horizontal: false, vertical: true)
                if viewModel.status != .idle {
                    Text(viewModel.statusTitle)
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .lineLimit(1)
                }
            }

            Spacer(minLength: 6)

            Button {
                Task { await onSyncAppleHealth() }
            } label: {
                Group {
                    if viewModel.isWorking {
                        ProgressView().tint(.white)
                    } else {
                        Text("授权")
                            .font(.system(size: 14, weight: .bold))
                    }
                }
                .foregroundStyle(.white)
                .frame(width: 62, height: 36)
                .background(
                    Capsule().fill(
                        LinearGradient(
                            colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                )
            }
            .buttonStyle(.plain)
            .disabled(viewModel.isWorking)
            .accessibilityIdentifier("xage.appleHealth.authorize.button")
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var managementBody: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .shadow(color: Color(hex: "20CDB1").opacity(0.22), radius: 12, x: 0, y: 7)
                    Image(systemName: "heart.text.square.fill")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Apple 健康同步")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(viewModel.statusSubtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineSpacing(2)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 8)

                Button {
                    Task { await onSyncAppleHealth() }
                } label: {
                    Group {
                        if viewModel.isWorking {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Text(viewModel.lastSyncedAt == nil ? "授权" : "同步")
                                .font(.system(size: 14, weight: .bold))
                        }
                    }
                    .foregroundStyle(.white)
                    .frame(width: 62, height: 34)
                    .background(
                        Capsule()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                }
                .buttonStyle(.plain)
                .disabled(viewModel.isWorking)
                .accessibilityIdentifier("xage.appleHealth.sync.button")
            }

            if showsSettingsButton {
                Button {
                    guard let settingsURL = URL(string: UIApplication.openSettingsURLString) else { return }
                    openURL(settingsURL)
                } label: {
                    Label("管理或恢复 Apple 健康权限", systemImage: "gearshape.fill")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .frame(maxWidth: .infinity)
                        .frame(minHeight: 34)
                        .background(XAgeCapsuleFill())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.appleHealth.openSettings")
            }

            XAgeAppleHealthSyncDetailDisclosure(viewModel: viewModel)

            HStack(spacing: 7) {
                XAgeSyncBadge(title: viewModel.statusTitle)
                if let response = viewModel.syncResponse {
                    if response.written > 0 {
                        XAgeSyncBadge(title: String(response.written) + " 项已写入")
                    } else if response.unchangedCount > 0 {
                        XAgeSyncBadge(title: String(response.unchangedCount) + " 项无变化")
                    } else {
                        XAgeSyncBadge(title: String(response.rejectedCount(requested: viewModel.samples.count)) + " 项未接收")
                    }
                } else {
                    XAgeSyncBadge(title: "只读授权")
                }
                XAgeSyncBadge(title: "\(viewModel.samples.count) 项本地数据")
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var showsSettingsButton: Bool {
        viewModel.shouldOfferHealthSettingsRecovery
    }
}

private struct XAgeAppleHealthSyncDetailDisclosure: View {
    private struct Detail: Identifiable {
        let id: String
        let title: String
        let message: String
    }

    @ObservedObject var viewModel: AppleHealthSyncViewModel

    var body: some View {
        if !details.isEmpty {
            DisclosureGroup {
                VStack(alignment: .leading, spacing: 9) {
                    ForEach(details) { detail in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(detail.title)
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(Color(hex: "365F80"))
                            Text(detail.message)
                                .font(.system(size: 12))
                                .foregroundStyle(Color(hex: "6C8194"))
                                .lineSpacing(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                .padding(.top, 8)
            } label: {
                Text("查看全部 " + String(details.count) + " 项读取/写入详情")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
            }
            .tint(Color(hex: "347FB7"))
            .accessibilityIdentifier("xage.appleHealth.sync.details")
        }
    }

    private var details: [Detail] {
        let readDetails = viewModel.readIssues.enumerated().map { index, issue in
            Detail(
                id: "read-" + String(index) + "-" + issue.metricID,
                title: issue.indicatorName,
                message: issue.message
            )
        }
        let writeDetails = (viewModel.syncResponse?.issues ?? []).enumerated().map { index, issue in
            let sample = viewModel.samples.indices.contains(issue.index) ? viewModel.samples[issue.index] : nil
            return Detail(
                id: "write-" + String(index) + "-" + String(issue.index),
                title: sample?.indicatorName ?? "第 " + String(issue.index + 1) + " 项服务器数据",
                message: Self.serverIssueMessage(issue.code)
            )
        }
        return readDetails + writeDetails
    }

    private static func serverIssueMessage(_ code: String) -> String {
        switch code {
        case "invalid_indicator_name":
            return "指标名称无效，服务器未接收。"
        case "invalid_value":
            return "数值无效，服务器未接收。"
        case "future_measured_at":
            return "测量时间晚于当前时间，服务器未接收。"
        case "source_id_conflict":
            return "样本标识与既有指标冲突，服务器为避免覆盖错误数据而拒绝写入。"
        default:
            return "服务器未接收（" + code + "），请稍后重试。"
        }
    }
}

private struct XAgeSyncBadge: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .lineLimit(1)
            .minimumScaleFactor(0.78)
            .frame(maxWidth: .infinity)
            .frame(height: 28)
            .background(XAgeCapsuleFill())
    }
}

struct XAgeMetricCard: View {
    let card: XAgeMetric
    let onOpen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [card.accent, Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 14, height: 14)
                Text(card.title)
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(card.accent)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(card.time)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(card.isStale ? Color(hex: "EF9A3D") : Color(hex: "6A8198"))
                    .lineLimit(1)
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "A0B1C0"))
                    .frame(width: 14)
            }

            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(card.value)
                    .font(.system(size: card.value.count > 4 ? 27 : 31, weight: .bold))
                    .foregroundStyle(card.isPlaceholder ? Color(hex: "6C8194") : (card.isStale ? Color(hex: "496A83") : Color(hex: "101C2F")))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                if !card.unit.isEmpty {
                    Text(card.unit)
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Color(hex: "70879D"))
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }

            Text(card.subtitle)
                .font(.system(size: 12))
                .foregroundStyle(card.isStale ? Color(hex: "9A6A28") : Color(hex: "5D7890"))
                .lineSpacing(2)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .contentShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .onTapGesture(perform: onOpen)
        .xAgeMetricCardAccessibility(
            sortMode: false,
            label: "\(card.title)，\(card.value) \(card.unit)，\(card.time)",
            hint: "打开指标详情"
        )
    }
}

struct XAgeMetricLibraryEntryCard: View {
    let availableCount: Int
    let totalCount: Int
    let onManage: () -> Void

    var body: some View {
        Button(action: onManage) {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .shadow(color: Color(hex: "20CDB1").opacity(0.24), radius: 12, x: 0, y: 7)
                    Circle()
                        .stroke(.white.opacity(0.58), lineWidth: 1)
                        .frame(width: 34, height: 34)
                    Image(systemName: "list.bullet.rectangle.portrait.fill")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 50, height: 50)

                VStack(alignment: .leading, spacing: 5) {
                    Text("数据卡片管理")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                    Text("\(totalCount) 项指标 · \(availableCount) 项可添加")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "5D7890"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                }

                Spacer(minLength: 8)

                HStack(spacing: 6) {
                    Text("管理")
                        .font(.system(size: 12, weight: .bold))
                    Image(systemName: "chevron.right")
                        .font(.system(size: 11, weight: .black))
                }
                .foregroundStyle(.white)
                .frame(width: 62, height: 32)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
                )
            }
            .padding(.horizontal, 18)
            .frame(height: 94)
            .background(XAgeGlassCardBackground(cornerRadius: 24))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("数据卡片管理，\(totalCount) 项指标，\(availableCount) 项可添加")
        .accessibilityIdentifier("xage.metric.library.manage")
    }
}

/// 数据卡片管理页面，统一处理置顶、排序、搜索和指标库添加。
struct XAgeMetricManagerPage: View {
    /// 首页当前置顶指标；排序和增删会直接回写该绑定。
    @Binding var pinnedMetrics: [XAgeMetric]
    /// 可浏览和搜索的完整指标分类。
    let catalogSections: [XAgeMetricCatalogSection]
    /// Apple 健康同步状态。
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    /// 用户主动同步 Apple 健康的动作。
    let onSyncAppleHealth: () async -> Void
    /// 指标顺序或集合改变后的持久化回调。
    let onMetricsChanged: () -> Void
    /// 打开某项指标详情的回调。
    let onOpenMetric: (XAgeMetric) -> Void
    @State private var searchText = ""
    @FocusState private var searchFocused: Bool

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(spacing: 0) {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("管理数据页长期关注的指标")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("置顶、排序、查看解释或添加新指标")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer(minLength: 8)

                    Text("\(pinnedMetrics.count) 置顶")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .padding(.horizontal, 12)
                        .frame(height: 32)
                        .background(XAgeCapsuleFill())
                }
                .accessibilityIdentifier("xage.metric.manager.page")
                .padding(.horizontal, 24)
                .padding(.top, 16)
                .padding(.bottom, 12)

                XAgeAppleHealthSyncCard(
                    viewModel: appleHealthSync,
                    compactAuthorization: false,
                    onSyncAppleHealth: onSyncAppleHealth
                )
                .padding(.horizontal, 24)
                .padding(.bottom, 12)
                .accessibilityIdentifier("xage.metric.manager.appleHealth")

                XAgeMetricSearchField(
                    text: $searchText,
                    placeholder: "搜索指标",
                    isFocused: $searchFocused
                )
                    .padding(.horizontal, 24)
                    .padding(.bottom, 12)
                    .accessibilityIdentifier("xage.metric.manager.search")

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        XAgeMetricSectionHeader(
                            title: "置顶",
                            subtitle: pinnedMetrics.isEmpty ? "点击下方加号把指标固定到数据页" : "使用箭头调整顺序，点击减号取消置顶",
                            icon: "pin.fill",
                            accent: Color(hex: "238AD6")
                        )

                        if filteredPinnedMetrics.isEmpty {
                            XAgeMetricEmptyRow(
                                title: pinnedMetrics.isEmpty ? "还没有置顶指标" : "置顶中没有匹配项",
                                subtitle: pinnedMetrics.isEmpty ? "从下面的候选列表选择需要长期关注的项目。" : "换一个关键词再试。"
                            )
                        } else {
                            ForEach(filteredPinnedMetrics) { metric in
                                let actualIndex = pinnedMetrics.firstIndex(where: { $0.id == metric.id }) ?? 0
                                XAgeMetricPinnedManagerRow(
                                    metric: metric,
                                    canMoveUp: actualIndex > 0,
                                    canMoveDown: actualIndex < pinnedMetrics.count - 1,
                                    onOpen: { openMetric(metric) },
                                    onUnpin: { unpin(metric) },
                                    onMoveUp: { moveMetric(from: actualIndex, by: -1) },
                                    onMoveDown: { moveMetric(from: actualIndex, by: 1) }
                                )
                                .id("pinned-\(metric.id)")
                                .accessibilityIdentifier("xage.metric.manager.pinned.\(metric.id)")
                            }
                        }

                        ForEach(filteredCandidateSections) { section in
                            XAgeMetricSectionHeader(
                                title: section.title,
                                subtitle: "\(section.metrics.count) 项可添加",
                                icon: section.icon,
                                accent: section.accent
                            )

                            ForEach(section.metrics) { metric in
                                XAgeMetricLibraryCandidateRow(
                                    metric: metric,
                                    isPinned: false,
                                    onOpen: { openMetric(metric) },
                                    onTogglePinned: { pin(metric) }
                                )
                                .id("manager-candidate-\(metric.id)")
                                .accessibilityIdentifier("xage.metric.manager.candidate.\(metric.id)")
                            }
                        }

                        if filteredCandidateSections.isEmpty && !searchText.isEmpty {
                            XAgeMetricEmptyRow(title: "没有匹配的候选指标", subtitle: "已置顶项目会显示在上方；也可以打开全部指标查看。")
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.bottom, 30)
                }
                .scrollIndicators(.hidden)
                .scrollDismissesKeyboard(.interactively)
                .accessibilityIdentifier("xage.metric.manager.scroll")
            }
        }
        .navigationTitle("数据卡片管理")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
        .toolbarBackground(.hidden, for: .navigationBar)
    }

    private var pinnedIDs: Set<String> {
        Set(pinnedMetrics.map(\.id))
    }

    private var normalizedSearchText: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private var filteredPinnedMetrics: [XAgeMetric] {
        filter(pinnedMetrics)
    }

    private var filteredCandidateSections: [XAgeMetricCatalogSection] {
        catalogSections.compactMap { section in
            let metrics = filter(section.metrics.filter { !pinnedIDs.contains($0.id) })
            guard !metrics.isEmpty else { return nil }
            return XAgeMetricCatalogSection(title: section.title, icon: section.icon, accent: section.accent, metrics: metrics)
        }
    }

    private func filter(_ metrics: [XAgeMetric]) -> [XAgeMetric] {
        guard !normalizedSearchText.isEmpty else { return metrics }
        return metrics.filter { metric in
            [
                metric.title,
                metric.subtitle,
                metric.time,
                metric.unit
            ]
            .joined(separator: " ")
            .lowercased()
            .contains(normalizedSearchText)
        }
    }

    private func pin(_ metric: XAgeMetric) {
        guard !pinnedMetrics.contains(where: { $0.id == metric.id }) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            pinnedMetrics.append(metric)
        }
        onMetricsChanged()
    }

    private func unpin(_ metric: XAgeMetric) {
        guard let index = pinnedMetrics.firstIndex(where: { $0.id == metric.id }) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            _ = pinnedMetrics.remove(at: index)
        }
        onMetricsChanged()
    }

    private func moveMetric(from index: Int, by delta: Int) {
        let target = index + delta
        guard pinnedMetrics.indices.contains(index), pinnedMetrics.indices.contains(target) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            pinnedMetrics.swapAt(index, target)
        }
        onMetricsChanged()
    }

    private func openMetric(_ metric: XAgeMetric) {
        searchFocused = false
        XAgeKeyboard.dismiss()
        onOpenMetric(metric)
    }
}

private struct XAgeMetricSheetHeader: View {
    let title: String
    let subtitle: String
    let countText: String
    let closeIcon: String
    let onClose: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 27, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }

            Spacer(minLength: 8)

            Text(countText)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "347FB7"))
                .frame(minWidth: 58)
                .padding(.horizontal, 10)
                .frame(height: 32)
                .background(XAgeCapsuleFill())

            Button(action: onClose) {
                Image(systemName: closeIcon)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .frame(width: 44, height: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel(closeIcon == "checkmark" ? "完成" : "关闭")
        }
    }
}

private struct XAgeMetricSearchField: View {
    @Binding var text: String
    let placeholder: String
    var isFocused: FocusState<Bool>.Binding

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "6C8194"))
            TextField(placeholder, text: $text)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .textFieldStyle(.plain)
                .submitLabel(.search)
                .focused(isFocused)
                .onSubmit {
                    isFocused.wrappedValue = false
                }
            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Color(hex: "8AA1B5"))
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .padding(.horizontal, -15)
                .buttonStyle(.plain)
                .accessibilityLabel("清除搜索")
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 44)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeMetricSectionHeader: View {
    let title: String
    let subtitle: String
    let icon: String
    let accent: Color

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 26, height: 26)
                .background(Circle().fill(accent))
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 4)
    }
}

private struct XAgeMetricPinnedManagerRow: View {
    let metric: XAgeMetric
    let canMoveUp: Bool
    let canMoveDown: Bool
    let onOpen: () -> Void
    let onUnpin: () -> Void
    let onMoveUp: () -> Void
    let onMoveDown: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onUnpin) {
                Image(systemName: "minus")
                    .font(.system(size: 12, weight: .black))
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .background {
                        Circle()
                            .fill(Color(hex: "A9B8C5").opacity(0.82))
                            .overlay(Circle().stroke(.white.opacity(0.72), lineWidth: 1))
                            .frame(width: 28, height: 28)
                    }
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("取消置顶\(metric.title)")
            .accessibilityIdentifier("xage.metric.manager.unpin.\(metric.id)")

            Button(action: onOpen) {
                HStack(spacing: 10) {
                    XAgeMetricRoundIcon(metric: metric)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(metric.title)
                            .font(.system(size: 16, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                            .lineLimit(1)
                        Text(metric.subtitle)
                            .font(.system(size: 12))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .lineLimit(1)
                            .minimumScaleFactor(0.82)
                    }
                    Spacer(minLength: 4)
                    Image(systemName: "info.circle")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(metric.accent)
                        .frame(width: 24, height: 44)
                }
                .contentShape(Rectangle())
            }
            .frame(maxWidth: .infinity)
            .buttonStyle(.plain)
            .accessibilityLabel("\(metric.title)解释")
            .accessibilityIdentifier("xage.metric.manager.detail.\(metric.id)")

            HStack(spacing: 2) {
                Button(action: onMoveUp) {
                    Image(systemName: "chevron.up")
                        .font(.system(size: 11, weight: .black))
                        .foregroundStyle(canMoveUp ? Color(hex: "347FB7") : Color(hex: "A9B8C5"))
                        .frame(width: 44, height: 44)
                        .background {
                            Circle()
                                .fill(.white.opacity(0.46))
                                .frame(width: 32, height: 32)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(!canMoveUp)
                .accessibilityLabel("上移\(metric.title)")
                .accessibilityIdentifier("xage.metric.manager.moveUp.\(metric.id)")

                Button(action: onMoveDown) {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11, weight: .black))
                        .foregroundStyle(canMoveDown ? Color(hex: "347FB7") : Color(hex: "A9B8C5"))
                        .frame(width: 44, height: 44)
                        .background {
                            Circle()
                                .fill(.white.opacity(0.46))
                                .frame(width: 32, height: 32)
                        }
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(!canMoveDown)
                .accessibilityLabel("下移\(metric.title)")
                .accessibilityIdentifier("xage.metric.manager.moveDown.\(metric.id)")
            }
        }
        .padding(.horizontal, 10)
        .frame(minHeight: 76)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityElement(children: .contain)
    }
}

private struct XAgeMetricLibraryCandidateRow: View {
    let metric: XAgeMetric
    let isPinned: Bool
    let onOpen: () -> Void
    let onTogglePinned: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onTogglePinned) {
                Image(systemName: isPinned ? "checkmark" : "pin.fill")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(isPinned ? .white : metric.accent)
                    .frame(width: 44, height: 44)
                    .background {
                        Circle()
                            .fill(isPinned ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing)) : AnyShapeStyle(.white.opacity(0.56)))
                            .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                            .frame(width: 30, height: 30)
                    }
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isPinned ? "取消置顶\(metric.title)" : "置顶\(metric.title)")
            .accessibilityIdentifier(isPinned ? "xage.metric.manager.unpin.\(metric.id)" : "xage.metric.manager.pin.\(metric.id)")

            Button(action: onOpen) {
                HStack(spacing: 10) {
                    XAgeMetricRoundIcon(metric: metric)
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Text(metric.title)
                                .font(.system(size: 16, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                                .lineLimit(1)
                            Text(metric.time)
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(metric.accent)
                                .lineLimit(1)
                        }
                        Text(metric.subtitle)
                            .font(.system(size: 12))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .lineLimit(1)
                            .minimumScaleFactor(0.82)
                    }
                    Spacer(minLength: 4)
                    Image(systemName: "info.circle")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(metric.accent)
                        .frame(width: 24, height: 44)
                }
                .contentShape(Rectangle())
            }
            .frame(maxWidth: .infinity)
            .buttonStyle(.plain)
            .accessibilityLabel("\(metric.title)详情")
            .accessibilityIdentifier("xage.metric.manager.detail.\(metric.id)")
        }
        .padding(.horizontal, 10)
        .frame(minHeight: 72)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityElement(children: .contain)
    }
}

private struct XAgeMetricRoundIcon: View {
    let metric: XAgeMetric

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    LinearGradient(
                        colors: [metric.accent, Color(hex: "20CDB1")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .shadow(color: metric.accent.opacity(0.18), radius: 10, x: 0, y: 5)
            Image(systemName: metric.libraryIconName)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white)
        }
        .frame(width: 42, height: 42)
    }
}

struct XAgeMetricEmptyRow: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(subtitle)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

struct XAgeMetricDetailSheet: View {
    let metric: XAgeMetric
    let trend: IndicatorTrend?
    let onManualRecord: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                            Image(systemName: iconName)
                                .font(.system(size: 18, weight: .bold))
                                .foregroundStyle(.white)
                        }
                        .frame(width: 48, height: 48)

                        VStack(alignment: .leading, spacing: 4) {
                            Text(metric.title)
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                                .lineLimit(1)
                            Text(statusTitle)
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(statusColor)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 4)
                                .background(XAgeCapsuleFill())
                        }

                        Spacer()

                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 36, height: 36)
                                .background(XAgeCapsuleFill())
                        }
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭\(metric.title)详情")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        HStack(alignment: .firstTextBaseline, spacing: 5) {
                            Text(metric.value)
                                .font(.system(size: metric.value.count > 4 ? 32 : 40, weight: .bold))
                                .foregroundStyle(metric.isPlaceholder ? Color(hex: "6C8194") : Color(hex: "101C2F"))
                                .lineLimit(1)
                                .minimumScaleFactor(0.72)
                            if !metric.unit.isEmpty {
                                Text(metric.unit)
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(Color(hex: "70879D"))
                            }
                            Spacer()
                        }
                        Text(metric.subtitle)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 10) {
                        XAgeMetricDetailRow(title: "数据来源", value: sourceLabel)
                        XAgeMetricDetailRow(title: "更新时间", value: updateLabel)
                        XAgeMetricDetailRow(title: "当前状态", value: statusTitle)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    XAgeMetricTrendView(
                        trend: trend,
                        fallbackUnit: metric.unit,
                        accent: metric.accent
                    )
                    .accessibilityIdentifier("xage.metric.trend")

                    Button {
                        onManualRecord()
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "square.and.pencil")
                                .font(.system(size: 15, weight: .bold))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("手动记录")
                                    .font(.system(size: 15, weight: .bold))
                                Text("录入后进入趋势，并刷新主界面")
                                    .font(.system(size: 11, weight: .medium))
                                    .opacity(0.86)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.system(size: 12, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .padding(.horizontal, 16)
                        .frame(height: 54)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                                .overlay(Capsule().stroke(.white.opacity(0.68), lineWidth: 1))
                        )
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.metric.manualEntry")
                    .accessibilityLabel("手动记录\(metric.title)")

                    Text(detailExplanation)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(statusColor)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }

    private var statusTitle: String {
        if metric.source == "other_source_catalog" { return "暂不支持自动同步" }
        if metric.isPlaceholder { return metric.time.contains("上传") ? "待上传" : "暂无数据" }
        if metric.source == "server_indicator_catalog" { return "已入库" }
        if metric.isStale { return "需更新" }
        return "已同步"
    }

    private var statusColor: Color {
        if metric.isPlaceholder { return Color(hex: "6C8194") }
        if metric.isStale { return Color(hex: "EF9A3D") }
        return metric.accent
    }

    private var sourceLabel: String {
        switch (metric.source ?? "").lowercased() {
        case "apple_health": return "Apple 健康"
        case "apple_health_catalog": return "Apple 健康可同步"
        case "other_source_catalog": return "其他来源"
        case "manual": return "手动记录"
        case "device": return "设备同步"
        case "cgm": return "CGM"
        case "document": return "报告趋势"
        case "server_catalog": return "服务器指标库"
        case "server_indicator_catalog": return "服务器已入库指标"
        default: return metric.isPlaceholder ? "暂无" : "服务端趋势"
        }
    }

    private var updateLabel: String {
        if let measuredAt = metric.measuredAt {
            return XAgeServerSyncFormat.shortDate(measuredAt)
        }
        return metric.time
    }

    private var detailExplanation: String {
        if metric.isPlaceholder {
            if metric.source == "apple_health_catalog" {
                return "这是小捷当前已实现的 Apple 健康读取项目。完成授权后可手动同步；只有同一账号明确同步过，App 才会在回到前台时刷新。"
            }
            if metric.source == "other_source_catalog" {
                return "当前版本不会从 Apple 健康自动读取这个指标，也不会在授权后承诺自动更新。你仍可手动记录、上传报告，或等待后续接入其他数据来源。"
            }
            if metric.source == "server_catalog" {
                return "这是服务器指标库候选项。上传报告或手动记录后，小捷会把该指标写入趋势，并用最新有效值更新数据页。"
            }
            return "当前没有这个指标的有效数据；同步 Apple 健康、手动记录或上传报告后，主界面会用真实数值替换占位。"
        }
        if metric.source == "server_indicator_catalog" {
            return "这个指标已经存在服务器历史记录。置顶后先展示历史点数量；上传报告、Apple 健康同步或手动记录产生新值后，数据页会按最新测量时间更新。"
        }
        if metric.isStale {
            return "这条数据已超过当前指标的时效窗口，保留为历史参考，不作为最新状态展示。"
        }
        return "这条数据来自\(sourceLabel)，按测量时间进入趋势，并用于当前数据页展示。"
    }

    private var iconName: String {
        metric.libraryIconName
    }
}

private enum XAgeManualMetricField: Int, CaseIterable {
    case indicator
    case value
    case unit
    case notes
}

/// 通用手动指标录入表单。
struct XAgeManualMetricEntrySheet: View {
    let metric: XAgeMetric
    let onCancel: () -> Void
    let onSaved: () -> Void
    @StateObject private var vm = ManualIndicatorViewModel()
    @State private var indicatorName: String
    @State private var valueText = ""
    @State private var unitText: String
    @State private var measuredAt = Date()
    @State private var initialMeasuredAt = Date()
    @State private var notes = ""
    @State private var showDiscardConfirmation = false
    @FocusState private var focusedField: XAgeManualMetricField?

    /// 创建手动录入表单。
    /// - Parameters:
    ///   - metric: 用于预填指标名称和单位的目标指标。
    ///   - onCancel: 无修改退出或确认放弃修改后的回调。
    ///   - onSaved: 服务端保存成功后的回调，通常用于刷新首页。
    init(metric: XAgeMetric, onCancel: @escaping () -> Void, onSaved: @escaping () -> Void) {
        let now = Date()
        self.metric = metric
        self.onCancel = onCancel
        self.onSaved = onSaved
        _indicatorName = State(initialValue: metric.title)
        _unitText = State(initialValue: metric.unit)
        _measuredAt = State(initialValue: now)
        _initialMeasuredAt = State(initialValue: now)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground()
                    .ignoresSafeArea()

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        Button {
                            requestCancel()
                        } label: {
                            Image(systemName: "chevron.left")
                                .font(.system(size: 16, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 44, height: 44)
                                .background {
                                    XAgeCapsuleFill()
                                        .frame(width: 36, height: 36)
                                }
                                .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(vm.saving)
                        .accessibilityLabel("返回\(metric.title)详情")
                        .accessibilityIdentifier("xage.metric.manualEntry.back")

                        ZStack {
                            Circle()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                            Image(systemName: "square.and.pencil")
                                .font(.system(size: 18, weight: .bold))
                                .foregroundStyle(.white)
                        }
                        .frame(width: 48, height: 48)

                        VStack(alignment: .leading, spacing: 3) {
                            Text("手动记录")
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            Text("保存后进入用户端趋势")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }

                        Spacer()
                    }
//                    手动记录体重模块
                    VStack(alignment: .leading, spacing: 12) {
                        XAgeManualMetricTextField(
                            title: "指标",
                            placeholder: "指标名称",
                            text: $indicatorName,
                            field: .indicator,
                            focusedField: $focusedField
                        )
                        .accessibilityIdentifier("xage.metric.manualEntry.indicator")
                        XAgeManualMetricTextField(
                            title: "数值（单位：千克）",
                            placeholder: "例如 120",
                            text: $valueText,
                            keyboardType: .decimalPad,
                            field: .value,
                            focusedField: $focusedField
                        )
                        .accessibilityIdentifier("xage.metric.manualEntry.value")
//                        XAgeManualMetricTextField(
//                            title: "单位",
//                            placeholder: "可选",
//                            text: $unitText,
//                            field: .unit,
//                            focusedField: $focusedField
//                        )
//                        .accessibilityIdentifier("xage.metric.manualEntry.unit")
                        DatePicker("测量时间", selection: $measuredAt, in: ...Date(), displayedComponents: [.date/*, .hourAndMinute*/])
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                            .padding(.horizontal, 14)
                            .frame(height: 52)
                            .background(XAgeCapsuleFill())
                            .simultaneousGesture(TapGesture().onEnded {
                                focusedField = nil
                            })
                        XAgeManualMetricTextField(
                            title: "备注",
                            placeholder: "可选，可填写测量场景或说明",
                            text: $notes,
                            field: .notes,
                            focusedField: $focusedField,
                            isMultiline: true
                        )
                        .accessibilityIdentifier("xage.metric.manualEntry.notes")
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    Text("手动记录会标记为“手动记录”来源。Apple 健康同日同步到同一指标时，会按来源和测量时间合并，主界面始终显示当前最有效的数据。")
                        .font(.system(size: 13))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())

                    Button {
                        focusedField = nil
                        XAgeKeyboard.dismiss()
                        Task { await save() }
                    } label: {
                        HStack(spacing: 8) {
                            if vm.saving {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(vm.saving ? "保存中" : "保存记录")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(!canSave || vm.saving)
                    .opacity(!canSave || vm.saving ? 0.55 : 1)
                    .accessibilityIdentifier("xage.metric.manualEntry.save")
                }
                    .padding(24)
                }
                .scrollIndicators(.hidden)
                .scrollDismissesKeyboard(.interactively)
            }
            .toolbar(.hidden, for: .navigationBar)
        }
        .interactiveDismissDisabled(hasUnsavedChanges || vm.saving)
        .presentationDragIndicator(hasUnsavedChanges || vm.saving ? .hidden : .visible)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if focusedField != nil {
                HStack(spacing: 16) {
                    Button {
                        moveFocus(by: -1)
                    } label: {
                        Text("上一项")
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .disabled(previousField == nil)
                    .accessibilityIdentifier("xage.metric.manualEntry.keyboard.previous")

                    Button {
                        moveFocus(by: 1)
                    } label: {
                        Text("下一项")
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .disabled(nextField == nil)
                    .accessibilityIdentifier("xage.metric.manualEntry.keyboard.next")

                    Spacer()

                    Button {
                        focusedField = nil
                        XAgeKeyboard.dismiss()
                    } label: {
                        Text("完成")
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("xage.metric.manualEntry.keyboard.done")
                }
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Color(hex: "1268BD"))
                .padding(.horizontal, 18)
                .frame(height: 52)
                .frame(maxWidth: .infinity)
                .background(.ultraThinMaterial)
                .overlay(alignment: .top) {
                    Divider().opacity(0.35)
                }
            }
        }
        .onChange(of: vm.savedOk) { _, saved in
            guard saved else { return }
            onSaved()
        }
        .alert("保存失败", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
        .alert("放弃本次记录？", isPresented: $showDiscardConfirmation) {
            Button("继续编辑", role: .cancel) {}
            Button("放弃修改", role: .destructive) {
                focusedField = nil
                XAgeKeyboard.dismiss()
                onCancel()
            }
        } message: {
            Text("已填写的内容不会保存。")
        }
    }

    private var canSave: Bool {
        !indicatorName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && parsedValue != nil
    }

    private var parsedValue: Double? {
        Double(valueText.replacingOccurrences(of: "，", with: ".").trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private var hasUnsavedChanges: Bool {
        indicatorName != metric.title ||
        !valueText.isEmpty ||
        unitText != metric.unit ||
        !notes.isEmpty ||
        abs(measuredAt.timeIntervalSince(initialMeasuredAt)) > 1
    }

    private var previousField: XAgeManualMetricField? {
        guard let focusedField,
              let index = XAgeManualMetricField.allCases.firstIndex(of: focusedField),
              index > XAgeManualMetricField.allCases.startIndex
        else { return nil }
        return XAgeManualMetricField.allCases[index - 1]
    }

    private var nextField: XAgeManualMetricField? {
        guard let focusedField,
              let index = XAgeManualMetricField.allCases.firstIndex(of: focusedField),
              index < XAgeManualMetricField.allCases.index(before: XAgeManualMetricField.allCases.endIndex)
        else { return nil }
        return XAgeManualMetricField.allCases[index + 1]
    }

    private func moveFocus(by offset: Int) {
        focusedField = offset < 0 ? previousField : nextField
    }

    private func requestCancel() {
        focusedField = nil
        XAgeKeyboard.dismiss()
        if hasUnsavedChanges {
            showDiscardConfirmation = true
        } else {
            onCancel()
        }
    }

    private func save() async {
        guard let value = parsedValue else { return }
        let trimmedUnit = unitText.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        await vm.submit(
            indicatorName: indicatorName.trimmingCharacters(in: .whitespacesAndNewlines),
            value: value,
            unit: trimmedUnit.isEmpty ? nil : trimmedUnit,
            measuredAt: measuredAt,
            notes: trimmedNotes.isEmpty ? nil : trimmedNotes
        )
    }
}

private struct XAgeManualMetricTextField: View {
    let title: String
    let placeholder: String
    @Binding var text: String
    var keyboardType: UIKeyboardType = .default
    let field: XAgeManualMetricField
    var focusedField: FocusState<XAgeManualMetricField?>.Binding
    var isMultiline = false

    var body: some View {
        HStack(alignment: isMultiline ? .top : .center, spacing: 12) {
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "5D7890"))
                .frame(width: 54, alignment: .leading)
                .padding(.top, isMultiline ? 12 : 0)
            TextField(placeholder, text: $text, axis: isMultiline ? .vertical : .horizontal)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .keyboardType(keyboardType)
                .textFieldStyle(.plain)
                .lineLimit(isMultiline ? 2...5 : 1...1)
                .multilineTextAlignment(isMultiline ? .leading : .trailing)
                .padding(.vertical, isMultiline ? 10 : 0)
                .focused(focusedField, equals: field)
                .submitLabel(field == .notes ? .done : .next)
                .onSubmit {
                    if let index = XAgeManualMetricField.allCases.firstIndex(of: field),
                       index < XAgeManualMetricField.allCases.index(before: XAgeManualMetricField.allCases.endIndex) {
                        focusedField.wrappedValue = XAgeManualMetricField.allCases[index + 1]
                    } else {
                        focusedField.wrappedValue = nil
                    }
                }
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 52)
        .background {
            if isMultiline {
                XAgeGlassCardBackground(cornerRadius: 22)
            } else {
                XAgeCapsuleFill()
            }
        }
    }
}

struct XAgeMetricDetailRow: View {
    let title: String
    let value: String

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color(hex: "5D7890"))
            Spacer(minLength: 12)
            Text(value)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "17324E"))
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .padding(11)
        .background(XAgeCapsuleFill())
    }
}
