import AVFoundation
import Speech
import SwiftUI
import UIKit

enum XAgeTopSection: String, CaseIterable, Identifiable {
    case data = "数据"
    case chat = "问答"
    case xAge = "X年龄"

    var id: String { rawValue }
}

private extension View {
    @ViewBuilder
    func xAgeAccessibilitySelected(_ isSelected: Bool) -> some View {
        if isSelected {
            accessibilityAddTraits(.isSelected)
        } else {
            self
        }
    }
}

struct XAgeMainView: View {
    @State private var selectedSection: XAgeTopSection = Self.initialSection()
    @State private var showMoreMenu = false
    @State private var dataSortMode = false
    @State private var chatHistoryRequest = 0
    @State private var xAgeInfoRequest = 0

    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground()
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    XAgeTopBar(
                        selected: $selectedSection,
                        showMoreMenu: $showMoreMenu,
                        dataSortMode: dataSortMode,
                        onToggleDataSort: {
                            withAnimation(.spring(response: 0.28, dampingFraction: 0.88)) {
                                dataSortMode.toggle()
                            }
                        },
                        onOpenChatHistory: {
                            chatHistoryRequest += 1
                        },
                        onOpenXAgeInfo: {
                            xAgeInfoRequest += 1
                        }
                    )
                    .padding(.top, 12)
                    .padding(.horizontal, 24)
                    .zIndex(2)

                    TabView(selection: $selectedSection) {
                        XAgeDataDashboardView(
                            sortMode: $dataSortMode
                        )
                            .tag(XAgeTopSection.data)
                        XAgeConversationSurface(
                            selectedSection: $selectedSection,
                            historyRequest: chatHistoryRequest
                        )
                            .tag(XAgeTopSection.chat)
                        XAgeHealthspanView(
                            selectedSection: $selectedSection,
                            infoRequest: xAgeInfoRequest
                        )
                            .tag(XAgeTopSection.xAge)
                    }
                    .tabViewStyle(.page(indexDisplayMode: .never))
                }
            }
            .navigationBarHidden(true)
            .sheet(isPresented: $showMoreMenu) {
                XAgeMoreMenu(
                    selectedSection: $selectedSection,
                    dataSortMode: $dataSortMode
                )
                    .presentationDetents([.medium])
            }
        }
    }

    private static func initialSection() -> XAgeTopSection {
        #if DEBUG
        if let rawValue = ProcessInfo.processInfo.environment["XAGE_INITIAL_SECTION"] ?? launchArgumentValue(for: "XAGE_INITIAL_SECTION"),
           let section = XAgeTopSection.section(matching: rawValue) {
            return section
        }
        #endif
        return .data
    }

    #if DEBUG
    private static func launchArgumentValue(for key: String) -> String? {
        let arguments = ProcessInfo.processInfo.arguments
        for (index, argument) in arguments.enumerated() {
            if argument == key, arguments.indices.contains(index + 1) {
                return arguments[index + 1]
            }
            if argument.hasPrefix("\(key)=") {
                return String(argument.dropFirst(key.count + 1))
            }
        }
        return nil
    }
    #endif
}

#if DEBUG
private extension XAgeTopSection {
    static func section(matching value: String) -> XAgeTopSection? {
        switch value {
        case "data", "数据":
            return .data
        case "chat", "qa", "问答":
            return .chat
        case "xAge", "xage", "X年龄":
            return .xAge
        default:
            return nil
        }
    }
}
#endif

private struct XAgeTopBar: View {
    @Binding var selected: XAgeTopSection
    @Binding var showMoreMenu: Bool
    let dataSortMode: Bool
    let onToggleDataSort: () -> Void
    let onOpenChatHistory: () -> Void
    let onOpenXAgeInfo: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            Button {
                showMoreMenu = true
            } label: {
                ZStack(alignment: .topTrailing) {
                    Image(systemName: "line.3.horizontal")
                        .font(.system(size: 18, weight: .semibold))
                        .frame(width: 34, height: 34)
                    Circle()
                        .fill(Color(hex: "FF5B63"))
                        .frame(width: 7, height: 7)
                        .offset(x: 1, y: -1)
                }
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "173F64"))
            .accessibilityIdentifier("xage.more")

            HStack(spacing: 0) {
                ForEach(XAgeTopSection.allCases) { section in
                    Button {
                        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
                            selected = section
                        }
                    } label: {
                        Text(section.rawValue)
                            .font(.system(size: 15, weight: selected == section ? .bold : .medium))
                            .foregroundStyle(selected == section ? Color(hex: "1268BD") : Color(hex: "4E718E"))
                            .frame(width: section == .xAge ? 80 : 70, height: 38)
                            .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("xage.segment.\(section.id)")
                    .buttonStyle(.plain)
                    .background {
                        if selected == section {
                            RoundedRectangle(cornerRadius: 19, style: .continuous)
                                .fill(.white.opacity(0.72))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 19, style: .continuous)
                                        .stroke(.white.opacity(0.92), lineWidth: 1)
                                )
                                .shadow(color: Color(hex: "2FB6E3").opacity(0.16), radius: 16, x: 0, y: 8)
                        }
                    }
                }
            }
            .frame(width: 238, height: 48)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(.white.opacity(0.48))
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(.white.opacity(0.86), lineWidth: 1)
                    )
                    .shadow(color: Color(hex: "7CCAF5").opacity(0.16), radius: 22, x: 0, y: 10)
            )

            Button {
                if selected == .data {
                    onToggleDataSort()
                } else if selected == .chat {
                    onOpenChatHistory()
                } else if selected == .xAge {
                    onOpenXAgeInfo()
                }
            } label: {
                Group {
                    if selected == .data {
                        Text(dataSortMode ? "完成" : "排序")
                            .font(.system(size: 14, weight: .bold))
                            .frame(width: 52, height: 34)
                    } else if selected == .chat {
                        Image(systemName: "clock.arrow.circlepath")
                            .font(.system(size: 18, weight: .bold))
                            .frame(width: 38, height: 38)
                    } else {
                        Image(systemName: "info")
                            .font(.system(size: 14, weight: .bold))
                            .frame(width: 34, height: 34)
                    }
                }
                .background(
                    Capsule()
                        .fill(.white.opacity(0.48))
                        .overlay(Capsule().stroke(.white.opacity(0.86), lineWidth: 1))
                )
            }
            .buttonStyle(.plain)
            .foregroundStyle(selected == .chat ? Color(hex: "173F64") : Color(hex: "2A79BB"))
            .accessibilityIdentifier(selected == .data ? (dataSortMode ? "xage.data.sort.done" : "xage.data.sort") : (selected == .chat ? "xage.chat.history" : "xage.info"))
        }
    }
}

private struct XAgeDataDashboardView: View {
    @Binding var sortMode: Bool
    @StateObject private var appleHealthSync = AppleHealthSyncViewModel()
    @State private var activeSheet: XAgeDataSheet?
    @State private var metrics = XAgeMetric.defaultCards
    @State private var pendingMetricScrollID: String?
    @State private var isTodayStatusHidden = false

    var body: some View {
        VStack(spacing: 0) {
            XAgeDataStickyHeader(
                collapseProgress: 0,
                showsTodayStatus: !isTodayStatusHidden,
                onSelectDetail: { activeSheet = .detail($0) }
            )
            .padding(.horizontal, 24)
            .padding(.top, 16)
            .padding(.bottom, 10)
            .zIndex(2)

            ZStack(alignment: .bottom) {
                ScrollViewReader { proxy in
                    ScrollView {
                        XAgeDataScrollOffsetProbe()

                        LazyVStack(spacing: 12) {
                            if !sortMode {
                                XAgeAppleHealthSyncCard(viewModel: appleHealthSync)
                                    .accessibilityIdentifier("xage.appleHealth.sync")
                            }

                            ForEach(Array(metrics.enumerated()), id: \.element.id) { index, card in
                                XAgeMetricCard(card: card, sortMode: sortMode) {
                                    moveMetric(index, -1)
                                } onMoveDown: {
                                    moveMetric(index, 1)
                                }
                                .id(card.id)
                                .accessibilityIdentifier("xage.data.metric.\(card.id)")
                            }

                            if !sortMode {
                                XAgeAddMetricCard(availableCount: availableCandidateMetrics.count) {
                                    activeSheet = .metricPicker
                                }
                                .id("add-metric")
                                .accessibilityIdentifier("xage.data.metric.add")
                            }
                        }
                        .padding(.horizontal, 24)
                        .padding(.top, 10)
                        .padding(.bottom, sortMode ? 32 : 238)
                    }
                    .coordinateSpace(name: XAgeDataScrollSpace.name)
                    .scrollIndicators(.hidden)
                    .accessibilityIdentifier("xage.data.scroll")
                    .accessibilityScrollAction { edge in
                        switch edge {
                        case .bottom:
                            setTodayStatusHidden(true)
                        case .top:
                            setTodayStatusHidden(false)
                        default:
                            break
                        }
                    }
                    .modifier(
                        XAgeDataScrollOffsetTracker { offset in
                            updateTodayStatusVisibility(forOffset: offset)
                        }
                    )
                    .onPreferenceChange(XAgeDataScrollOffsetPreferenceKey.self) { minY in
                        updateTodayStatusVisibility(forOffset: max(0, -minY))
                    }
                    .onChange(of: metrics.count) { _, _ in
                        guard let metricID = pendingMetricScrollID else { return }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) {
                            withAnimation(.spring(response: 0.3, dampingFraction: 0.9)) {
                                proxy.scrollTo(metricID, anchor: .top)
                            }
                            pendingMetricScrollID = nil
                        }
                    }
                }

                if !sortMode {
                    XAgeBottomDataPanel(appleHealthSync: appleHealthSync)
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .zIndex(3)
                }
            }
        }
        .onChange(of: appleHealthSync.samples) { _, samples in
            mergeAppleHealthSamples(samples)
        }
        .sheet(item: $activeSheet) { sheet in
            switch sheet {
            case .detail(let kind):
                XAgeDataDetailView(kind: kind)
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
            case .metricPicker:
                XAgeMetricCandidateSheet(metrics: availableCandidateMetrics) { metric in
                    addMetric(metric)
                }
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
                .presentationContentInteraction(.scrolls)
                .interactiveDismissDisabled(true)
            }
        }
    }

    private func updateTodayStatusVisibility(forOffset scrollOffset: CGFloat) {
        let offset = max(0, scrollOffset)
        let shouldHide = isTodayStatusHidden ? offset > 8 : offset > 28
        guard shouldHide != isTodayStatusHidden else { return }
        setTodayStatusHidden(shouldHide)
    }

    private func setTodayStatusHidden(_ hidden: Bool) {
        guard hidden != isTodayStatusHidden else { return }
        withAnimation(.easeInOut(duration: 0.18)) {
            isTodayStatusHidden = hidden
        }
    }

    private var availableCandidateMetrics: [XAgeMetric] {
        let currentIDs = Set(metrics.map(\.id))
        return XAgeMetric.appleHealthCandidates.filter { !currentIDs.contains($0.id) }
    }

    private func addMetric(_ metric: XAgeMetric) {
        guard !metrics.contains(where: { $0.id == metric.id }) else { return }
        pendingMetricScrollID = metric.id
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            metrics.append(metric)
        }
    }

    private func moveMetric(_ index: Int, _ direction: Int) {
        let target = index + direction
        guard metrics.indices.contains(index), metrics.indices.contains(target) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            metrics.swapAt(index, target)
        }
    }

    private func mergeAppleHealthSamples(_ samples: [AppleHealthSyncSample]) {
        let synced = samples.compactMap { XAgeMetric.appleHealthMetric(from: $0) }
        guard !synced.isEmpty else { return }
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            for metric in synced {
                if let index = metrics.firstIndex(where: { $0.id == metric.id }) {
                    metrics[index] = metric
                } else {
                    metrics.append(metric)
                }
            }
        }
    }
}

private enum XAgeDataScrollSpace {
    static let name = "xageDataScroll"
}

private struct XAgeDataScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct XAgeDataScrollOffsetProbe: View {
    var body: some View {
        GeometryReader { proxy in
            Color.clear
                .preference(
                    key: XAgeDataScrollOffsetPreferenceKey.self,
                    value: proxy.frame(in: .named(XAgeDataScrollSpace.name)).minY
                )
        }
        .frame(height: 1)
        .accessibilityHidden(true)
    }
}

private struct XAgeDataScrollOffsetTracker: ViewModifier {
    let onOffsetChange: (CGFloat) -> Void

    func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content
                .onScrollGeometryChange(for: CGFloat.self) { geometry in
                    geometry.contentOffset.y
                } action: { _, newValue in
                    onOffsetChange(newValue)
                }
        } else {
            content
        }
    }
}

private enum XAgeDataSheet: Identifiable {
    case detail(XAgeDataKind)
    case metricPicker

    var id: String {
        switch self {
        case .detail(let kind): return "detail-\(kind.id)"
        case .metricPicker: return "metric-picker"
        }
    }
}

private struct XAgeDataStickyHeader: View {
    let collapseProgress: CGFloat
    let showsTodayStatus: Bool
    let onSelectDetail: (XAgeDataKind) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12 - 4 * collapseProgress) {
            VStack(alignment: .leading, spacing: 4) {
                Text("今日健康数据")
                    .font(.system(size: 27 - 4 * collapseProgress, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .lineLimit(1)
                Text("6月29日 · 自动同步")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "5D7B95"))
                    .opacity(Double(1 - collapseProgress))
                    .frame(height: 18 * (1 - collapseProgress), alignment: .top)
                    .clipped()
            }
            .frame(height: 52 - 18 * collapseProgress, alignment: .topLeading)

            XAgeScoreRingPanel(
                collapseProgress: collapseProgress,
                onSelectDetail: onSelectDetail
            )

            if showsTodayStatus {
                XAgeScoreSummaryCard(compactProgress: collapseProgress)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}

private enum XAgeDataKind: String, Identifiable {
    case pressure = "压力"
    case recovery = "恢复"
    case inflammation = "炎症"

    var id: String { rawValue }

    var score: Int {
        switch self {
        case .pressure: return 68
        case .recovery: return 82
        case .inflammation: return 57
        }
    }

    var tint: Color {
        switch self {
        case .pressure: return Color(hex: "2789D8")
        case .recovery: return Color(hex: "14B887")
        case .inflammation: return Color(hex: "EF9A3D")
        }
    }

    var summary: String {
        switch self {
        case .pressure: return "压力处于中等区间，夜间恢复质量和白天负荷是主要变量。"
        case .recovery: return "恢复状态良好，HRV、睡眠连续性和静息心率共同支持今天的行动能力。"
        case .inflammation: return "炎症需要关注，体温、RHR、呼吸率和实验室指标需要持续交叉确认。"
        }
    }

    var fields: [(String, String)] {
        switch self {
        case .pressure:
            return [
                ("HR残差", "+6 bpm"), ("HRV下降", "-12%"), ("RHR", "62 bpm"),
                ("呼吸率", "16.8"), ("体温", "+0.2°C"), ("睡眠债", "1.4h"),
                ("活动负荷", "中等"), ("EMA", "紧张")
            ]
        case .recovery:
            return [
                ("夜间HRV", "43 ms"), ("RHR", "58 bpm"), ("睡眠指标", "86%"),
                ("呼吸率", "15.9"), ("SpO2", "97%"), ("体温", "稳定"),
                ("前日负荷", "适中")
            ]
        case .inflammation:
            return [
                ("hsCRP/IL-6", "待补充"), ("CBC/NLR", "2.1"), ("体温异常", "轻微"),
                ("RHR异常", "+3 bpm"), ("HRV异常", "-8%"), ("呼吸异常", "否"),
                ("SpO2异常", "否"), ("多组学", "需复核")
            ]
        }
    }
}

private struct XAgeScoreRing: View {
    let kind: XAgeDataKind
    let score: Int
    var ringSize: CGFloat = 86

    var body: some View {
        let lineWidth = max(7, ringSize * 0.1)
        VStack(spacing: 7) {
            ZStack {
                Circle()
                    .trim(from: 0.04, to: 0.9)
                    .stroke(Color.white.opacity(0.52), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                    .rotationEffect(.degrees(112))
                Circle()
                    .trim(from: 0.04, to: 0.04 + 0.86 * CGFloat(score) / 100)
                    .stroke(
                        AngularGradient(
                            colors: [kind.tint.opacity(0.35), kind.tint, Color.appAccent, kind.tint],
                            center: .center
                        ),
                        style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                    )
                    .rotationEffect(.degrees(112))
                    .shadow(color: kind.tint.opacity(0.22), radius: 8, x: 0, y: 3)
                Text("\(score)")
                    .font(.system(size: ringSize >= 80 ? 25 : 22, weight: .bold))
                    .foregroundStyle(Color(hex: "17324E"))
            }
            .frame(width: ringSize, height: ringSize)

            Text(kind.rawValue)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Color(hex: "43657F"))
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct XAgeScoreRingPanel: View {
    let collapseProgress: CGFloat
    let onSelectDetail: (XAgeDataKind) -> Void

    var body: some View {
        let ringSize = 86 - 14 * collapseProgress
        HStack(spacing: 8) {
            XAgeScoreRing(kind: .pressure, score: 68, ringSize: ringSize)
                .onTapGesture { onSelectDetail(.pressure) }
                .accessibilityIdentifier("xage.data.score.pressure")
            XAgeScoreRing(kind: .recovery, score: 82, ringSize: ringSize)
                .onTapGesture { onSelectDetail(.recovery) }
                .accessibilityIdentifier("xage.data.score.recovery")
            XAgeScoreRing(kind: .inflammation, score: 57, ringSize: ringSize)
                .onTapGesture { onSelectDetail(.inflammation) }
                .accessibilityIdentifier("xage.data.score.inflammation")
        }
        .frame(maxWidth: .infinity)
        .frame(height: 122)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
    }
}

private struct XAgeScoreSummaryCard: View {
    let compactProgress: CGFloat

    private let badges = [
        ("压力中等", Color(hex: "2789D8")),
        ("恢复良好", Color(hex: "14B887")),
        ("炎症关注", Color(hex: "EF9A3D"))
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 8 - 2 * compactProgress) {
            HStack(spacing: 8) {
                Text("今日状态")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Spacer(minLength: 4)
                HStack(spacing: 5) {
                    ForEach(badges, id: \.0) { item in
                        HStack(spacing: 3) {
                            Circle()
                                .fill(item.1)
                                .frame(width: 6, height: 6)
                            Text(item.0)
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(item.1)
                                .lineLimit(1)
                        }
                        .frame(width: 60, height: 22)
                        .background(
                            Capsule()
                                .fill(.white.opacity(0.48))
                                .overlay(Capsule().stroke(.white.opacity(0.76), lineWidth: 1))
                        )
                    }
                }
            }
            Text("恢复较好，压力中等；炎症需要关注。今天优先补水、睡眠和低强度活动。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(2)
                .lineLimit(compactProgress > 0.7 ? 1 : 2)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12 - 2 * compactProgress)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeMetric: Identifiable {
    let id: String
    let title: String
    let value: String
    let unit: String
    let time: String
    let subtitle: String
    let accent: Color

    static let defaultCards = [
        XAgeMetric(id: "hrv", title: "心率变异性", value: "43", unit: "ms", time: "07:10", subtitle: "比 7 日均值低 8%，压力评分的主要贡献项。", accent: Color(hex: "7B4DFF")),
        XAgeMetric(id: "sleep", title: "睡眠", value: "7小时18分", unit: "", time: "昨夜", subtitle: "深睡和连续性良好，支持恢复评分保持绿色。", accent: Color(hex: "14B887")),
        XAgeMetric(id: "glucose", title: "血糖波动", value: "18", unit: "%", time: "餐后", subtitle: "餐后波动可控，建议继续核对晚餐碳水。", accent: Color(hex: "11A7C8")),
        XAgeMetric(id: "temp", title: "体温偏移", value: "+0.2", unit: "°C", time: "夜间", subtitle: "轻微偏高，结合炎症和睡眠信号观察。", accent: Color(hex: "EF9A3D"))
    ]

    static let appleHealthCandidates = [
        XAgeMetric(id: "steps", title: "步数", value: "8,240", unit: "步", time: "今日", subtitle: "活动量基线，可解释压力和恢复的日内变化。", accent: Color(hex: "238AD6")),
        XAgeMetric(id: "distance", title: "步行+跑步距离", value: "5.6", unit: "km", time: "今日", subtitle: "补充步数之外的移动距离和通勤负荷。", accent: Color(hex: "18B7D6")),
        XAgeMetric(id: "activeEnergy", title: "活动能量", value: "486", unit: "kcal", time: "今日", subtitle: "运动和日常活动消耗，用于判断恢复压力。", accent: Color(hex: "EF9A3D")),
        XAgeMetric(id: "exerciseMinutes", title: "运动分钟", value: "42", unit: "min", time: "今日", subtitle: "中高强度活动时间，辅助解释训练负荷。", accent: Color(hex: "14B887")),
        XAgeMetric(id: "flights", title: "爬楼层数", value: "9", unit: "层", time: "今日", subtitle: "反映爬升活动，补足平地步数的盲区。", accent: Color(hex: "4E8FE9")),
        XAgeMetric(id: "restingHeartRate", title: "静息心率", value: "58", unit: "bpm", time: "晨间", subtitle: "静息心率偏移可提示恢复、压力和感染风险。", accent: Color(hex: "F05B72")),
        XAgeMetric(id: "respiratoryRate", title: "呼吸频率", value: "15.9", unit: "次/分", time: "夜间", subtitle: "夜间呼吸频率用于恢复和异常筛查。", accent: Color(hex: "2A79C7")),
        XAgeMetric(id: "bloodOxygen", title: "血氧", value: "97", unit: "%", time: "夜间", subtitle: "血氧变化可辅助睡眠和呼吸风险判断。", accent: Color(hex: "7B4DFF")),
        XAgeMetric(id: "bloodPressure", title: "血压", value: "118/76", unit: "mmHg", time: "最近", subtitle: "可手动记录或由设备同步，形成心血管基线。", accent: Color(hex: "DB5B9B")),
        XAgeMetric(id: "bodyWeight", title: "体重", value: "62.4", unit: "kg", time: "今天", subtitle: "体重趋势帮助解释代谢和计划执行效果。", accent: Color(hex: "11A7C8")),
        XAgeMetric(id: "bodyFat", title: "体脂率", value: "23", unit: "%", time: "最近", subtitle: "身体成分变化可补充长期健康画像。", accent: Color(hex: "A47BEF")),
        XAgeMetric(id: "mindfulMinutes", title: "正念分钟", value: "8", unit: "min", time: "今天", subtitle: "正念记录作为压力管理和恢复行为输入。", accent: Color(hex: "20CDB1")),
        XAgeMetric(id: "daylight", title: "日照时间", value: "36", unit: "min", time: "今天", subtitle: "户外日照可影响节律、睡眠和情绪状态。", accent: Color(hex: "F3B349"))
    ]

    static func appleHealthMetric(from sample: AppleHealthSyncSample) -> XAgeMetric? {
        let fallback = appleHealthCandidates.first { $0.id == sample.metricID }
        let defaultMetric = defaultCards.first { $0.id == sample.metricID }
        let base = fallback ?? defaultMetric
        guard let base else { return nil }
        return XAgeMetric(
            id: sample.metricID,
            title: sample.indicatorName,
            value: sample.displayValue,
            unit: sample.displayUnit,
            time: "Apple 健康",
            subtitle: "\(sample.subtitle)，已同步到服务器并更新用户端趋势。",
            accent: base.accent
        )
    }
}

private struct XAgeAppleHealthSyncCard: View {
    @ObservedObject var viewModel: AppleHealthSyncViewModel

    var body: some View {
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
                        .lineLimit(2)
                        .minimumScaleFactor(0.84)
                }

                Spacer(minLength: 8)

                Button {
                    Task { await viewModel.requestAccessAndSync() }
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

            HStack(spacing: 7) {
                XAgeSyncBadge(title: viewModel.statusTitle)
                if let response = viewModel.syncResponse {
                    XAgeSyncBadge(title: "\(response.inserted + response.updated) 项已写入")
                } else {
                    XAgeSyncBadge(title: "只读授权")
                }
                XAgeSyncBadge(title: "\(viewModel.samples.count) 项本地数据")
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
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

private struct XAgeMetricCard: View {
    let card: XAgeMetric
    let sortMode: Bool
    let onMoveUp: () -> Void
    let onMoveDown: () -> Void

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
                    .foregroundStyle(Color(hex: "6A8198"))
                    .lineLimit(1)
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "A0B1C0"))
                    .frame(width: 14)
            }

            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(card.value)
                    .font(.system(size: card.value.count > 4 ? 27 : 31, weight: .bold))
                    .foregroundStyle(Color(hex: "101C2F"))
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

            if sortMode {
                HStack(spacing: 8) {
                    CapsuleButton(title: "上移", action: onMoveUp)
                    CapsuleButton(title: "下移", action: onMoveDown)
                    Spacer()
                    Image(systemName: "line.3.horizontal")
                        .foregroundStyle(Color(hex: "6C8194"))
                        .frame(width: 28, height: 28)
                        .background(Circle().fill(.white.opacity(0.44)))
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeAddMetricCard: View {
    let availableCount: Int
    let action: () -> Void

    var body: some View {
        Button(action: action) {
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
                        .stroke(.white.opacity(0.56), lineWidth: 1)
                        .frame(width: 32, height: 32)
                    Image(systemName: "plus")
                        .font(.system(size: 20, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 4) {
                    Text(availableCount == 0 ? "全部指标已添加" : "添加指标")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(availableCount == 0 ? "候选列表暂无新项目" : "从 Apple 健康候选项中选择")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }

                Spacer(minLength: 8)

                Text(availableCount == 0 ? "完成" : "\(availableCount)项")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 56, height: 30)
                    .background(XAgeCapsuleFill())
            }
            .padding(.horizontal, 18)
            .frame(height: 88)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(.white.opacity(0.42))
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(style: StrokeStyle(lineWidth: 1, dash: [7, 5]))
                            .foregroundStyle(.white.opacity(0.88))
                    )
                    .shadow(color: Color(hex: "73C8F0").opacity(0.14), radius: 22, x: 0, y: 12)
            )
        }
        .buttonStyle(.plain)
        .disabled(availableCount == 0)
        .opacity(availableCount == 0 ? 0.72 : 1)
    }
}

private struct XAgeMetricCandidateSheet: View {
    let metrics: [XAgeMetric]
    let onSelect: (XAgeMetric) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("添加指标")
                            .font(.system(size: 27, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                            .lineLimit(1)
                        Text("参照 Apple 健康可记录项目")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .lineLimit(1)
                    }

                    Spacer()

                    Text("\(metrics.count) 项")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .frame(width: 58, height: 32)
                        .background(XAgeCapsuleFill())

                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .frame(width: 34, height: 34)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("关闭")
                }

                if metrics.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("已添加全部候选指标")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("主界面下拉列表已经包含所有候选项。")
                            .font(.system(size: 13))
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))
                    Spacer()
                } else {
                    ScrollView {
                        LazyVStack(spacing: 10) {
                            ForEach(metrics) { metric in
                                Button {
                                    onSelect(metric)
                                    dismiss()
                                } label: {
                                    XAgeMetricCandidateRow(metric: metric)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.data.metric.candidate.\(metric.id)")
                            }
                        }
                        .padding(.bottom, 20)
                    }
                    .scrollIndicators(.hidden)
                }
            }
            .padding(24)
        }
    }
}

private struct XAgeMetricCandidateRow: View {
    let metric: XAgeMetric

    var body: some View {
        HStack(spacing: 12) {
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
                Image(systemName: iconName)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(.white)
            }
            .frame(width: 42, height: 42)

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

            Spacer(minLength: 8)

            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(metric.value)
                    .font(.system(size: metric.value.count > 4 ? 18 : 20, weight: .bold))
                    .foregroundStyle(Color(hex: "12324F"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                if !metric.unit.isEmpty {
                    Text(metric.unit)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }
            }
            .frame(width: 66, alignment: .trailing)

            Image(systemName: "checkmark")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 30, height: 30)
                .background(
                    Circle()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .overlay(Circle().stroke(.white.opacity(0.72), lineWidth: 1))
                )
        }
        .padding(.horizontal, 14)
        .frame(height: 72)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }

    private var iconName: String {
        switch metric.id {
        case "steps": return "figure.walk"
        case "distance": return "map.fill"
        case "activeEnergy": return "flame.fill"
        case "exerciseMinutes": return "timer"
        case "flights": return "figure.stairs"
        case "restingHeartRate": return "heart.fill"
        case "respiratoryRate": return "lungs.fill"
        case "bloodOxygen": return "drop.fill"
        case "bloodPressure": return "gauge"
        case "bodyWeight": return "scalemass.fill"
        case "bodyFat": return "percent"
        case "mindfulMinutes": return "brain.head.profile"
        case "daylight": return "sun.max.fill"
        default: return "plus"
        }
    }
}

private enum XAgeDataPanelCategory: String, CaseIterable, Identifiable {
    case reports = "报告"
    case daily = "日常"
    case medical = "就医"
    case profile = "画像"

    var id: String {
        switch self {
        case .reports: return "reports"
        case .daily: return "daily"
        case .medical: return "medical"
        case .profile: return "profile"
        }
    }

    var headline: String {
        switch self {
        case .reports: return "报告入库"
        case .daily: return "日常同步"
        case .medical: return "就医整理"
        case .profile: return "健康画像"
        }
    }

    var subtitle: String {
        switch self {
        case .reports: return "体检、化验、影像"
        case .daily: return "睡眠、步数、HRV"
        case .medical: return "诊断、处方、随访"
        case .profile: return "基础、慢病、过敏"
        }
    }

    var actionTitle: String {
        switch self {
        case .reports: return "上传"
        case .daily: return "查看"
        case .medical: return "整理"
        case .profile: return "完善"
        }
    }

    var iconName: String {
        switch self {
        case .reports: return "doc.text.fill"
        case .daily: return "waveform.path.ecg"
        case .medical: return "cross.case.fill"
        case .profile: return "person.text.rectangle.fill"
        }
    }

    var gradient: [Color] {
        switch self {
        case .reports: return [Color(hex: "238AD6"), Color(hex: "20CDB1")]
        case .daily: return [Color(hex: "18B7D6"), Color(hex: "34D6A6")]
        case .medical: return [Color(hex: "4E8FE9"), Color(hex: "7BD5F1")]
        case .profile: return [Color(hex: "2A79C7"), Color(hex: "6EE4C6")]
        }
    }

    var detailSummary: String {
        switch self {
        case .reports: return "把体检、化验和影像资料先入库，小捷会在后台识别结构化字段，并提示缺失项。"
        case .daily: return "聚合睡眠、步数、HRV 和训练负荷，用来解释当天压力、恢复和炎症评分变化。"
        case .medical: return "把诊断、处方和随访整理成连续时间线，方便下一次问诊前快速回顾。"
        case .profile: return "维护基础资料、慢病、过敏和长期用药，让问答和计划生成更贴近个人状态。"
        }
    }

    var stats: [XAgePanelStat] {
        switch self {
        case .reports:
            return [
                XAgePanelStat(title: "待识别", value: "3", unit: "份"),
                XAgePanelStat(title: "已结构化", value: "18", unit: "项"),
                XAgePanelStat(title: "完整度", value: "76", unit: "%")
            ]
        case .daily:
            return [
                XAgePanelStat(title: "睡眠", value: "7:18", unit: ""),
                XAgePanelStat(title: "步数", value: "8.2k", unit: ""),
                XAgePanelStat(title: "HRV", value: "43", unit: "ms")
            ]
        case .medical:
            return [
                XAgePanelStat(title: "诊断", value: "4", unit: "条"),
                XAgePanelStat(title: "处方", value: "2", unit: "组"),
                XAgePanelStat(title: "随访", value: "1", unit: "次")
            ]
        case .profile:
            return [
                XAgePanelStat(title: "基础", value: "92", unit: "%"),
                XAgePanelStat(title: "慢病", value: "2", unit: "项"),
                XAgePanelStat(title: "过敏", value: "1", unit: "项")
            ]
        }
    }

    var rows: [XAgePanelRow] {
        switch self {
        case .reports:
            return [
                XAgePanelRow(icon: "camera.fill", title: "拍照上传", subtitle: "体检报告、化验单、影像截图"),
                XAgePanelRow(icon: "doc.text.magnifyingglass", title: "AI 识别队列", subtitle: "抽取指标、异常值和参考范围"),
                XAgePanelRow(icon: "checkmark.seal.fill", title: "需要确认", subtitle: "核对姓名、日期和关键指标")
            ]
        case .daily:
            return [
                XAgePanelRow(icon: "heart.text.square.fill", title: "Apple Health", subtitle: "同步睡眠、步数、静息心率"),
                XAgePanelRow(icon: "waveform.path.ecg", title: "恢复信号", subtitle: "HRV、呼吸率和训练负荷"),
                XAgePanelRow(icon: "chart.line.uptrend.xyaxis", title: "趋势解释", subtitle: "连接日常变化与三项评分")
            ]
        case .medical:
            return [
                XAgePanelRow(icon: "list.clipboard.fill", title: "诊断摘要", subtitle: "按科室和时间整理病程"),
                XAgePanelRow(icon: "pills.fill", title: "处方核对", subtitle: "剂量、频次和注意事项"),
                XAgePanelRow(icon: "calendar.badge.clock", title: "随访提醒", subtitle: "复诊、复查和报告回传")
            ]
        case .profile:
            return [
                XAgePanelRow(icon: "person.fill", title: "基础资料", subtitle: "年龄、身高、体重和目标"),
                XAgePanelRow(icon: "tag.fill", title: "长期标签", subtitle: "慢病、家族史和风险因素"),
                XAgePanelRow(icon: "exclamationmark.shield.fill", title: "安全信息", subtitle: "过敏、禁忌和长期用药")
            ]
        }
    }
}

private struct XAgePanelStat: Identifiable {
    var id: String { title }
    let title: String
    let value: String
    let unit: String
}

private struct XAgePanelRow: Identifiable {
    var id: String { title }
    let icon: String
    let title: String
    let subtitle: String

    var key: String {
        switch title {
        case "拍照上传": return "upload"
        case "AI 识别队列": return "recognition"
        case "需要确认": return "confirm"
        case "Apple Health": return "apple-health"
        case "恢复信号": return "recovery"
        case "趋势解释": return "trend"
        case "诊断摘要": return "diagnosis"
        case "处方核对": return "prescription"
        case "随访提醒": return "follow-up"
        case "基础资料": return "basic"
        case "长期标签": return "tags"
        case "安全信息": return "safety"
        default: return title
        }
    }
}

private struct XAgeBottomDataPanel: View {
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @State private var selectedCategory: XAgeDataPanelCategory = .reports

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                ForEach(XAgeDataPanelCategory.allCases) { category in
                    Button {
                        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                            selectedCategory = category
                        }
                    } label: {
                        HStack(spacing: 5) {
                            XAgePanelCategoryGlyph(category: category, selected: selectedCategory == category)
                                .frame(width: 18, height: 18)
                            Text(category.rawValue)
                                .font(.system(size: 11, weight: .bold))
                                .lineLimit(1)
                                .minimumScaleFactor(0.82)
                        }
                            .foregroundStyle(selectedCategory == category ? Color(hex: "1268BD") : Color(hex: "5D7890"))
                            .frame(maxWidth: .infinity)
                            .frame(height: 36)
                            .background(
                                Capsule()
                                    .fill(selectedCategory == category ? .white.opacity(0.76) : .white.opacity(0.28))
                                    .overlay(
                                        Capsule()
                                            .stroke(.white.opacity(selectedCategory == category ? 0.88 : 0.46), lineWidth: 1)
                                    )
                            )
                    }
                    .buttonStyle(.plain)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(category.rawValue)
                    .accessibilityValue(selectedCategory == category ? "已选中" : "")
                    .xAgeAccessibilitySelected(selectedCategory == category)
                    .accessibilityIdentifier("xage.data.panel.category.\(category.id)")
                }
            }

            NavigationLink {
                destination(for: selectedCategory)
            } label: {
                HStack(spacing: 12) {
                    XAgePanelHeroAsset(category: selectedCategory)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(selectedCategory.headline)
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                            .lineLimit(1)
                        Text(selectedCategory.subtitle)
                            .font(.system(size: 12))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    Text(selectedCategory.actionTitle)
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(width: 62, height: 34)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: selectedCategory.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        )
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .background(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .fill(.white.opacity(0.58))
                        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                        .overlay(
                            RoundedRectangle(cornerRadius: 24, style: .continuous)
                                .stroke(.white.opacity(0.82), lineWidth: 1)
                        )
                )
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(selectedCategory.headline)、\(selectedCategory.subtitle)、\(selectedCategory.actionTitle)")
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier(selectedCategory == .reports ? "xage.data.upload" : "xage.data.panel.\(selectedCategory.id)")
        }
        .padding(.horizontal, 20)
        .padding(.top, 22)
        .padding(.bottom, 34)
        .frame(maxWidth: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 30, style: .continuous)
                .fill(.white.opacity(0.92))
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 30, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 30, style: .continuous)
                        .stroke(.white.opacity(0.9), lineWidth: 1)
                )
                .shadow(color: Color(hex: "7CCAF5").opacity(0.2), radius: 24, x: 0, y: -8)
        )
    }

    @ViewBuilder
    private func destination(for category: XAgeDataPanelCategory) -> some View {
        XAgePanelDestinationView(category: category, appleHealthSync: appleHealthSync)
    }
}

private struct XAgePanelCategoryGlyph: View {
    let category: XAgeDataPanelCategory
    let selected: Bool

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    selected
                    ? AnyShapeStyle(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                    : AnyShapeStyle(Color(hex: "B8DFF5").opacity(0.3))
                )
                .overlay(Circle().stroke(.white.opacity(selected ? 0.84 : 0.58), lineWidth: 0.8))

            glyph
                .foregroundStyle(selected ? .white : Color(hex: "347FB7"))
        }
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var glyph: some View {
        switch category {
        case .reports:
            VStack(spacing: 1.6) {
                ForEach([8.0, 5.8, 7.2], id: \.self) { width in
                    RoundedRectangle(cornerRadius: 1.2, style: .continuous)
                        .frame(width: width, height: 1.8)
                }
            }
        case .daily:
            HStack(alignment: .bottom, spacing: 1.5) {
                ForEach([5.0, 9.0, 6.0, 11.0], id: \.self) { height in
                    RoundedRectangle(cornerRadius: 1.2, style: .continuous)
                        .frame(width: 2, height: height)
                }
            }
        case .medical:
            Image(systemName: "cross.fill")
                .font(.system(size: 8.5, weight: .bold))
        case .profile:
            Image(systemName: "checkmark")
                .font(.system(size: 8.5, weight: .bold))
        }
    }
}

private struct XAgePanelHeroAsset: View {
    let category: XAgeDataPanelCategory

    var body: some View {
        ZStack {
            Circle()
                .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                .shadow(color: category.gradient.last?.opacity(0.24) ?? Color(hex: "20CDB1").opacity(0.24), radius: 12, x: 0, y: 7)
            Circle()
                .stroke(.white.opacity(0.42), lineWidth: 1)
                .frame(width: 34, height: 34)
            XAgePanelCategoryGlyph(category: category, selected: true)
                .frame(width: 24, height: 24)
            Image(systemName: category.iconName)
                .font(.system(size: 9, weight: .black))
                .foregroundStyle(.white.opacity(0.92))
                .offset(x: 12, y: -12)
        }
        .frame(width: 48, height: 48)
        .accessibilityHidden(true)
    }
}

private struct XAgePanelDestinationView: View {
    let category: XAgeDataPanelCategory
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var selectedRowID: String?
    @State private var completedActionIDs: Set<String> = []
    @State private var selectedTagIDs: Set<String> = []
    @State private var primaryActionCount = 0

    private var activeRow: XAgePanelRow {
        category.rows.first { $0.id == selectedRowID } ?? category.rows[0]
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 16) {
                    header
                        .padding(.top, 18)

                    VStack(alignment: .leading, spacing: 16) {
                        HStack(spacing: 14) {
                            XAgePanelHeroAsset(category: category)
                                .frame(width: 62, height: 62)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(category.headline)
                                    .font(.system(size: 27, weight: .bold))
                                    .foregroundStyle(Color(hex: "123E67"))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.82)
                                Text(category.subtitle)
                                    .font(.system(size: 14, weight: .semibold))
                                    .foregroundStyle(Color(hex: "5D7890"))
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }

                        Text(category.detailSummary)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    HStack(spacing: 9) {
                        ForEach(category.stats) { stat in
                            VStack(spacing: 5) {
                                Text(stat.title)
                                    .font(.system(size: 11, weight: .bold))
                                    .foregroundStyle(Color(hex: "6C8194"))
                                    .lineLimit(1)
                                HStack(alignment: .firstTextBaseline, spacing: 2) {
                                    Text(stat.value)
                                        .font(.system(size: 20, weight: .bold))
                                        .foregroundStyle(Color(hex: "12324F"))
                                        .lineLimit(1)
                                        .minimumScaleFactor(0.76)
                                    if !stat.unit.isEmpty {
                                        Text(stat.unit)
                                            .font(.system(size: 10, weight: .semibold))
                                            .foregroundStyle(Color(hex: "6C8194"))
                                    }
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .frame(height: 70)
                            .background(XAgeGlassCardBackground(cornerRadius: 22))
                        }
                    }

                    VStack(spacing: 10) {
                        ForEach(category.rows) { row in
                            let isSelected = activeRow.id == row.id
                            if category == .daily && row.title == "Apple Health" {
                                Button {
                                    select(row)
                                    Task { await appleHealthSync.requestAccessAndSync() }
                                } label: {
                                    XAgePanelActionRow(
                                        category: category,
                                        row: row,
                                        trailingTitle: appleHealthSync.isWorking ? nil : appleHealthSync.statusTitle,
                                        showsProgress: appleHealthSync.isWorking,
                                        isSelected: isSelected
                                    )
                                }
                                .buttonStyle(.plain)
                                .disabled(appleHealthSync.isWorking)
                                .accessibilityIdentifier("xage.appleHealth.destination.sync")
                            } else {
                                Button {
                                    select(row)
                                } label: {
                                    XAgePanelActionRow(
                                        category: category,
                                        row: row,
                                        trailingTitle: isSelected ? "查看中" : nil,
                                        isSelected: isSelected
                                    )
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.panel.\(category.id).row.\(row.key)")
                            }
                        }
                    }

                    XAgePanelInteractiveDetail(
                        category: category,
                        row: activeRow,
                        appleHealthSync: appleHealthSync,
                        completedActionIDs: $completedActionIDs,
                        selectedTagIDs: $selectedTagIDs,
                        primaryActionCount: $primaryActionCount
                    )

                    Button {
                        runPrimaryAction()
                    } label: {
                        Text(primaryButtonTitle)
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .frame(height: 46)
                            .background(
                                Capsule()
                                    .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                                    .shadow(color: (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.22), radius: 12, x: 0, y: 7)
                            )
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.panel.\(category.id).primary")
                    .padding(.top, 2)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 30)
            }
        }
        .navigationBarBackButtonHidden(true)
        .toolbar(.hidden, for: .navigationBar)
    }

    private var primaryButtonTitle: String {
        switch category {
        case .reports:
            return activeRow.title == "拍照上传" ? "开始入库" : "确认并入库"
        case .daily:
            return activeRow.title == "Apple Health" ? "同步日常数据" : "更新日常解释"
        case .medical:
            return activeRow.title == "随访提醒" ? "保存提醒" : "整理到时间线"
        case .profile:
            return activeRow.title == "安全信息" ? "保存安全信息" : "保存画像"
        }
    }

    private func select(_ row: XAgePanelRow) {
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            selectedRowID = row.id
        }
    }

    private func runPrimaryAction() {
        let row = activeRow
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            completedActionIDs.insert("primary-\(category.id)-\(row.key)-\(primaryActionCount)")
            primaryActionCount += 1
        }
        if category == .daily && row.title == "Apple Health" {
            Task { await appleHealthSync.requestAccessAndSync() }
        }
    }

    private var header: some View {
        HStack {
            Button {
                dismiss()
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 42, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Spacer()

            Text(category.rawValue)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))
                .frame(height: 34)
                .padding(.horizontal, 18)
                .background(XAgeCapsuleFill())

            Spacer()

            Image(systemName: category.iconName)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 42, height: 34)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
                )
        }
    }
}

private struct XAgePanelInteractiveDetail: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @Binding var completedActionIDs: Set<String>
    @Binding var selectedTagIDs: Set<String>
    @Binding var primaryActionCount: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.title)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(detailSubtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(2)
                }
                Spacer(minLength: 10)
                Text(primaryActionCount > 0 ? "已更新" : "可编辑")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 62, height: 28)
                    .background(XAgeCapsuleFill())
            }

            content
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityIdentifier("xage.panel.\(category.id).detail.\(row.key)")
    }

    private var detailSubtitle: String {
        switch category {
        case .reports:
            return "选择入口、检查识别队列，并确认关键报告字段。"
        case .daily:
            return "把可穿戴与日常信号转成今天的压力、恢复、炎症解释。"
        case .medical:
            return "把就医资料整理成时间线、处方核对和复查提醒。"
        case .profile:
            return "维护画像信息，让问答、计划和风险提示更贴近个人状态。"
        }
    }

    @ViewBuilder
    private var content: some View {
        switch category {
        case .reports:
            reportsContent
        case .daily:
            dailyContent
        case .medical:
            medicalContent
        case .profile:
            profileContent
        }
    }

    @ViewBuilder
    private var reportsContent: some View {
        if row.title == "拍照上传" {
            HStack(spacing: 9) {
                chip("拍照", icon: "camera.fill")
                chip("选 PDF", icon: "doc.fill")
                chip("相册", icon: "photo.fill")
            }
            toggleRow("姓名与报告一致", subtitle: "未匹配时会进入人工确认", key: "name")
            toggleRow("报告日期已读取", subtitle: "用于排列时间线和趋势", key: "date")
            toggleRow("18 项指标待入库", subtitle: "确认后写入用户端数据", key: "indicators")
        } else if row.title == "AI 识别队列" {
            progressLine("血常规", value: 0.92, trailing: "18 项")
            progressLine("肝肾功能", value: 0.68, trailing: "待核对")
            progressLine("影像摘要", value: 0.42, trailing: "OCR 中")
            HStack(spacing: 9) {
                chip("仅异常", icon: "exclamationmark.triangle.fill")
                chip("全部字段", icon: "list.bullet.rectangle")
            }
        } else {
            toggleRow("空腹血糖 5.8 mmol/L", subtitle: "偏高，建议进入趋势观察", key: "glucose")
            toggleRow("ALT 42 U/L", subtitle: "轻度偏高，等待复核", key: "alt")
            toggleRow("报告日期 6月28日", subtitle: "确认后会用于排序", key: "report-date")
        }
    }

    @ViewBuilder
    private var dailyContent: some View {
        if row.title == "Apple Health" {
            Text(appleHealthSync.statusSubtitle)
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                badge(appleHealthSync.statusTitle)
                badge("\(appleHealthSync.samples.count) 项")
                badge("只读授权")
            }
            Button {
                Task { await appleHealthSync.requestAccessAndSync() }
            } label: {
                HStack(spacing: 8) {
                    if appleHealthSync.isWorking {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .font(.system(size: 13, weight: .bold))
                    }
                    Text(appleHealthSync.isWorking ? "同步中" : "立即同步")
                        .font(.system(size: 13, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 38)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing))
                )
            }
            .buttonStyle(.plain)
            .disabled(appleHealthSync.isWorking)
            .accessibilityIdentifier("xage.panel.daily.detail.appleHealth.sync")
        } else if row.title == "恢复信号" {
            progressLine("HRV", value: 0.64, trailing: "43 ms")
            progressLine("静息心率", value: 0.72, trailing: "58 bpm")
            progressLine("呼吸频率", value: 0.58, trailing: "15 次/分")
            HStack(spacing: 9) {
                chip("用于恢复", icon: "heart.fill")
                chip("加入压力解释", icon: "bolt.heart.fill")
            }
        } else {
            toggleRow("睡眠债推高压力", subtitle: "昨夜少 42 分钟，压力 +6", key: "sleep")
            toggleRow("步数支撑恢复", subtitle: "8.2k 步，恢复 +4", key: "steps")
            toggleRow("HRV 低于 7 日均值", subtitle: "建议今天低强度活动", key: "hrv")
        }
    }

    @ViewBuilder
    private var medicalContent: some View {
        if row.title == "诊断摘要" {
            timelineRow("2026.06", title: "内分泌复查", detail: "空腹血糖偏高，建议三个月复查")
            timelineRow("2026.04", title: "体检中心", detail: "血脂轻度异常，生活方式干预")
            toggleRow("生成问诊前摘要", subtitle: "把关键诊断整理为一页卡片", key: "visit-summary")
        } else if row.title == "处方核对" {
            toggleRow("二甲双胍 0.5g", subtitle: "每日 2 次，餐后服用", key: "metformin")
            toggleRow("维生素 D", subtitle: "每日 1 次，避免重复补充", key: "vitamin-d")
            toggleRow("提醒医生复核剂量", subtitle: "结合肾功能和胃肠反应", key: "dose-check")
        } else {
            HStack(spacing: 9) {
                chip("下周", icon: "calendar")
                chip("一月内", icon: "calendar.badge.clock")
                chip("报告回传", icon: "tray.and.arrow.up.fill")
            }
            toggleRow("血脂复查", subtitle: "建议 2026.07.15 前完成", key: "lipid")
            toggleRow("把新报告带到问诊", subtitle: "上传后自动更新摘要", key: "upload-next")
        }
    }

    @ViewBuilder
    private var profileContent: some View {
        if row.title == "基础资料" {
            progressLine("资料完整度", value: 0.92, trailing: "92%")
            HStack(spacing: 9) {
                chip("减脂", icon: "target")
                chip("控糖", icon: "drop.fill")
                chip("提升睡眠", icon: "moon.fill")
            }
            toggleRow("同步体重到画像", subtitle: "来自 Apple 健康或手动记录", key: "weight")
        } else if row.title == "长期标签" {
            HStack(spacing: 9) {
                chip("高血糖", icon: "tag.fill")
                chip("血脂异常", icon: "tag.fill")
                chip("家族史", icon: "person.2.fill")
            }
            HStack(spacing: 9) {
                chip("久坐", icon: "figure.seated.side")
                chip("压力高", icon: "brain.head.profile")
            }
        } else {
            toggleRow("青霉素过敏", subtitle: "问诊和计划生成时优先提醒", key: "penicillin")
            toggleRow("长期用药提示", subtitle: "处方核对时避免冲突", key: "medicine")
            toggleRow("家庭共享需单独授权", subtitle: "默认不共享敏感健康资料", key: "family")
        }
    }

    private func chip(_ title: String, icon: String) -> some View {
        let selected = selectedTagIDs.contains(selectionKey(title))
        return Button {
            toggleTag(title)
        } label: {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .bold))
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .foregroundStyle(selected ? .white : Color(hex: "347FB7"))
            .frame(maxWidth: .infinity)
            .frame(height: 34)
            .background(
                Capsule()
                    .fill(selected ? AnyShapeStyle(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing)) : AnyShapeStyle(Color.white.opacity(0.62)))
                    .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
            )
        }
        .buttonStyle(.plain)
    }

    private func toggleRow(_ title: String, subtitle: String, key: String) -> some View {
        let done = completedActionIDs.contains(actionKey(key))
        return Button {
            toggleAction(key)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: done ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(done ? category.gradient.last ?? Color(hex: "20CDB1") : Color(hex: "9BB6C9"))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                    Text(subtitle)
                        .font(.system(size: 11))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)
                }
                Spacer(minLength: 6)
            }
            .padding(.horizontal, 12)
            .frame(height: 52)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(.white.opacity(done ? 0.72 : 0.48))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(done ? (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.35) : .white.opacity(0.7), lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
    }

    private func progressLine(_ title: String, value: CGFloat, trailing: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(trailing)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(.white.opacity(0.54))
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(14, proxy.size.width * min(max(value, 0), 1)))
                }
            }
            .frame(height: 8)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.white.opacity(0.48))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.7), lineWidth: 1))
        )
    }

    private func timelineRow(_ date: String, title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 4) {
                Circle()
                    .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 12, height: 12)
                Rectangle()
                    .fill(Color(hex: "B9DDF2").opacity(0.6))
                    .frame(width: 2, height: 34)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(date)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                Text(title)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text(detail)
                    .font(.system(size: 11))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.white.opacity(0.48))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.7), lineWidth: 1))
        )
    }

    private func badge(_ title: String) -> some View {
        Text(title)
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .lineLimit(1)
            .minimumScaleFactor(0.76)
            .frame(maxWidth: .infinity)
            .frame(height: 28)
            .background(XAgeCapsuleFill())
    }

    private func selectionKey(_ value: String) -> String {
        "\(category.id)-\(row.key)-tag-\(value)"
    }

    private func actionKey(_ value: String) -> String {
        "\(category.id)-\(row.key)-action-\(value)"
    }

    private func toggleTag(_ value: String) {
        let key = selectionKey(value)
        withAnimation(.spring(response: 0.22, dampingFraction: 0.88)) {
            var next = selectedTagIDs
            if next.contains(key) {
                next.remove(key)
            } else {
                next.insert(key)
            }
            selectedTagIDs = next
        }
    }

    private func toggleAction(_ value: String) {
        let key = actionKey(value)
        withAnimation(.spring(response: 0.22, dampingFraction: 0.88)) {
            var next = completedActionIDs
            if next.contains(key) {
                next.remove(key)
            } else {
                next.insert(key)
            }
            completedActionIDs = next
        }
    }
}

private struct XAgePanelActionRow: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    var trailingTitle: String?
    var showsProgress: Bool = false
    var isSelected: Bool = false

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: row.icon)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 38, height: 38)
                .background(
                    Circle()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .shadow(color: (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.18), radius: 10, x: 0, y: 5)
                )
            VStack(alignment: .leading, spacing: 3) {
                Text(row.title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(row.subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }
            Spacer(minLength: 8)
            if showsProgress {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 52, height: 30)
            } else if let trailingTitle {
                Text(trailingTitle)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.74)
                    .frame(width: 72, height: 30)
                    .background(XAgeCapsuleFill())
            } else {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 66)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(isSelected ? (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.58) : .clear, lineWidth: 1.2)
        )
    }
}

private struct XAgeDataDetailView: View {
    let kind: XAgeDataKind
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()
            ScrollView {
                VStack(spacing: 16) {
                    HStack {
                        Spacer()
                        Text(kind.rawValue)
                            .font(.system(size: 28, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .accessibilityLabel("关闭")
                    }
                    .padding(.top, 14)

                    XAgeScoreRing(kind: kind, score: kind.score)
                        .frame(width: 150)
                        .padding(.vertical, 10)

                    VStack(alignment: .leading, spacing: 12) {
                        Text("指标构成")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(kind.fields, id: \.0) { field in
                            HStack {
                                Text(field.0)
                                    .font(.system(size: 14, weight: .medium))
                                    .foregroundStyle(Color(hex: "496A83"))
                                Spacer()
                                Text(field.1)
                                    .font(.system(size: 14, weight: .bold))
                                    .foregroundStyle(Color(hex: "17324E"))
                            }
                            Divider().opacity(0.24)
                        }
                    }
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    Text(kind.summary)
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(3)
                        .padding(18)
                        .background(XAgeGlassCardBackground(cornerRadius: 24))
                }
                .padding(24)
            }
        }
    }
}

private struct XAgeConversationSurface: View {
    @Binding var selectedSection: XAgeTopSection
    let historyRequest: Int
    @StateObject private var vm = ChatViewModel()
    @StateObject private var reportUploadVM = HealthDataViewModel()
    @StateObject private var speechInput = XAgeSpeechInputManager()
    @State private var selectedAnalysis: ChatMessageItem?
    @State private var selectedEvidence: ChatMessageItem?
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showDocumentPicker = false
    @State private var showAttachmentMenu = false
    @State private var uploadQualityWarning: String?

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            if vm.messages.isEmpty {
                                XAgeChatWelcome(vm: vm)
                                    .padding(.top, 34)
                            }

                            ForEach(vm.messages) { msg in
                                XAgeChatBubble(
                                    message: msg,
                                    onRetry: { Task { await vm.retryMessage(id: msg.id) } },
                                    onAnalysis: { selectedAnalysis = msg },
                                    onEvidence: { selectedEvidence = msg }
                                )
                                .id(msg.id)
                            }

                            if reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil {
                                XAgeChatUploadStatusCard(
                                    uploading: reportUploadVM.uploading,
                                    title: reportUploadVM.uploading
                                        ? (reportUploadVM.uploadStage.isEmpty ? "正在上传报告…" : reportUploadVM.uploadStage)
                                        : "报告已上传，AI 正在识别",
                                    subtitle: reportUploadVM.backgroundTaskHint ?? "完成后会继续进入问答解读。"
                                )
                                .id("xage.upload.status")
                            }

                            if vm.sending {
                                HStack {
                                    Text(vm.thinkingHint.isEmpty ? "正在思考…" : vm.thinkingHint)
                                        .font(.system(size: 14, weight: .medium))
                                        .foregroundStyle(Color(hex: "5D7890"))
                                        .padding(.horizontal, 14)
                                        .padding(.vertical, 12)
                                        .background(XAgeGlassCardBackground(cornerRadius: 18))
                                    Spacer()
                                }
                            }
                        }
                        .padding(.horizontal, 24)
                        .padding(.bottom, 96)
                    }
                    .scrollIndicators(.hidden)
                    .onChange(of: vm.messages.count) { _, _ in
                        if let id = vm.messages.last?.id {
                            withAnimation { proxy.scrollTo(id, anchor: .bottom) }
                        }
                    }
                }

                XAgeChatInputBar(
                    vm: vm,
                    isRecording: speechInput.isRecording,
                    isUploading: reportUploadVM.uploading,
                    onMicTap: toggleSpeechInput,
                    onCameraTap: { showCamera = true },
                    onPlusTap: { withAnimation(.spring(response: 0.22, dampingFraction: 0.9)) { showAttachmentMenu.toggle() } }
                )
                .padding(.horizontal, 24)
                .padding(.bottom, 20)
            }

            if showAttachmentMenu {
                attachmentMenuOverlay
                    .transition(.opacity)
                    .zIndex(5)
            }
        }
        .task { await vm.loadConversations(showErrors: false) }
        .onChange(of: historyRequest) { _, _ in
            openHistorySheet()
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraImagePicker(
                onPick: { data, name in
                    uploadReport(data: data, fileName: name)
                },
                fileNamePrefix: "xage_report_camera"
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $showPhotoLibrary) {
            CameraImagePicker(
                onPick: { data, name in
                    uploadReport(data: data, fileName: name)
                },
                sourceType: .photoLibrary,
                fileNamePrefix: "xage_report_album"
            )
        }
        .sheet(isPresented: $showDocumentPicker) {
            DocumentPickerView(
                onPick: { data, fileName in
                    uploadReport(data: data, fileName: fileName)
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $vm.showHistory) {
            XAgeChatHistorySheet(vm: vm)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $selectedAnalysis) { msg in
            XAgeAnalysisSheet(message: msg)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $selectedEvidence) { msg in
            XAgeEvidenceSheet(message: msg)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .alert("语音输入", isPresented: Binding(
            get: { speechInput.errorMessage != nil },
            set: { if !$0 { speechInput.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(speechInput.errorMessage ?? "")
        }
        .alert("拍摄质量不足", isPresented: Binding(
            get: { uploadQualityWarning != nil },
            set: { if !$0 { uploadQualityWarning = nil } }
        )) {
            Button("重新拍摄") { uploadQualityWarning = nil; showCamera = true }
            Button("取消", role: .cancel) { uploadQualityWarning = nil }
        } message: {
            Text(uploadQualityWarning ?? "")
        }
        .alert("上传提示", isPresented: Binding(
            get: { reportUploadVM.infoMessage != nil },
            set: { if !$0 { reportUploadVM.infoMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(reportUploadVM.infoMessage ?? "")
        }
        .alert("上传失败", isPresented: Binding(
            get: { reportUploadVM.errorMessage != nil },
            set: { if !$0 { reportUploadVM.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(reportUploadVM.errorMessage ?? "")
        }
        .alert("提示", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    private var attachmentMenuOverlay: some View {
        ZStack(alignment: .bottomTrailing) {
            Color.black.opacity(0.001)
                .ignoresSafeArea()
                .onTapGesture {
                    withAnimation(.spring(response: 0.22, dampingFraction: 0.9)) {
                        showAttachmentMenu = false
                    }
                }

            XAgeAttachmentMenu(
                onDocument: { presentAttachmentActionAfterMenu(.documentPicker) },
                onPhotoLibrary: { presentAttachmentActionAfterMenu(.photoLibrary) },
                onNewChat: { presentAttachmentActionAfterMenu(.newChat) }
            )
            .padding(.trailing, 42)
            .padding(.bottom, 88)
        }
    }

    private enum XAgeAttachmentAction {
        case documentPicker
        case photoLibrary
        case newChat
    }

    private func presentAttachmentActionAfterMenu(_ action: XAgeAttachmentAction) {
        showAttachmentMenu = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            performAttachmentAction(action)
        }
    }

    private func performAttachmentAction(_ action: XAgeAttachmentAction) {
        switch action {
        case .documentPicker:
            showDocumentPicker = true
        case .photoLibrary:
            showPhotoLibrary = true
        case .newChat:
            vm.newChat()
        }
    }

    private func openHistorySheet() {
        guard selectedSection == .chat else { return }
        showAttachmentMenu = false
        vm.showHistory = true
        Task { await vm.loadConversations(showErrors: false) }
    }

    private func toggleSpeechInput() {
        if speechInput.isRecording {
            speechInput.stop()
            return
        }
        hideKeyboard()
        speechInput.start { recognizedText in
            vm.inputValue = recognizedText
        }
    }

    private func uploadReport(data: Data, fileName: String) {
        if let warning = validateReportImageQuality(data: data, fileName: fileName) {
            uploadQualityWarning = warning
            return
        }

        hideKeyboard()
        reportUploadVM.uploadDocType = "exam"
        Task {
            if let doc = await reportUploadVM.uploadFile(data: data, fileName: fileName) {
                let prompt = reportAnalysisPrompt(fileName: fileName, documentId: doc.id)
                if vm.sending {
                    vm.inputValue = prompt
                } else {
                    await vm.sendText(prompt)
                }
            }
        }
    }

    private func reportAnalysisPrompt(fileName: String, documentId: String) -> String {
        "我刚上传了一份体检/化验报告（\(fileName)，文档ID：\(documentId)）。请结合我的健康档案和这份报告的识别结果，帮我总结关键指标、异常项、趋势变化和下一步建议。若后台识别仍在进行，请先说明正在识别，并告诉我完成后应该重点关注哪些项目。"
    }

    private func validateReportImageQuality(data: Data, fileName: String) -> String? {
        let lower = fileName.lowercased()
        let isImage = [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"].contains { lower.hasSuffix($0) }
        guard isImage else { return nil }
        if data.count < 30 * 1024 {
            return "图片过小（小于 30KB），可能不是完整报告。请重新拍摄。"
        }
        if let img = UIImage(data: data) {
            let shortEdge = min(img.size.width, img.size.height) * img.scale
            if shortEdge < 600 {
                return "图片分辨率过低（短边 \(Int(shortEdge))px），识别可能失败。请重新拍摄。"
            }
        } else {
            return "未能读取图片数据，请重新拍摄或选择 PDF。"
        }
        return nil
    }

    private func hideKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }
}

private struct XAgeChatWelcome: View {
    @ObservedObject var vm: ChatViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 16) {
                XAgeAssistantOrb()
                    .frame(width: 40, height: 40)
                VStack(alignment: .leading, spacing: 4) {
                    Text("下午好，想问什么？")
                        .font(.system(size: 25, weight: .bold))
                        .foregroundStyle(Color(hex: "111827"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                    Text("小捷先帮你问清关键问题。")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "637083"))
                        .lineLimit(1)
                }
            }

            Spacer()
                .frame(height: 50)

            Text("你可以这样问")
                .font(.system(size: 21, weight: .bold))
                .foregroundStyle(Color(hex: "111827"))
                .lineLimit(1)

            Spacer()
                .frame(height: 28)

            Button {
                vm.inputValue = "帮我整理病史摘要"
                Task { await vm.sendMessage() }
            } label: {
                XAgeStarterRow(icon: "doc.text", title: "整理病史摘要", subtitle: "诊断、用药、过敏信息", primary: true)
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)

            Spacer()
                .frame(height: 32)

            Button {
                vm.inputValue = "帮我分析最近报告趋势"
                Task { await vm.sendMessage() }
            } label: {
                XAgeStarterRow(icon: "chart.bar", title: "分析报告趋势", subtitle: nil, primary: false)
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct XAgeStarterRow: View {
    let icon: String
    let title: String
    let subtitle: String?
    let primary: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(Color.appPrimary)
                .frame(width: 36, height: 36)
                .background(
                    Circle()
                        .fill(Color(hex: "E7FAFF").opacity(0.46))
                        .overlay(Circle().stroke(.white.opacity(0.62), lineWidth: 1))
                )
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "111827"))
                    .lineLimit(1)
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "637083"))
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            Image(systemName: "chevron.right")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Color(hex: "6F7F91").opacity(0.72))
                .frame(width: 24, height: 24)
        }
        .padding(.horizontal, 18)
        .frame(height: primary ? 84 : 66)
        .background(XAgeGlassCardBackground(cornerRadius: primary ? 34 : 33))
    }
}

private struct XAgeAssistantOrb: View {
    var body: some View {
        ZStack {
            Circle()
                .fill(.white.opacity(0.42))
                .shadow(color: Color(hex: "00C9A7").opacity(0.25), radius: 16, x: 0, y: 8)
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Color(hex: "00C9A7"), Color(hex: "1565C0")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: 20, height: 20)
            Capsule()
                .fill(.white.opacity(0.26))
                .frame(width: 10, height: 28)
                .blur(radius: 1)
                .offset(x: 8, y: -4)
        }
    }
}

private struct XAgeChatBubble: View {
    let message: ChatMessageItem
    let onRetry: () -> Void
    let onAnalysis: () -> Void
    let onEvidence: () -> Void

    var body: some View {
        let isUser = message.role == "user"
        HStack {
            if isUser { Spacer(minLength: 44) }
            VStack(alignment: isUser ? .trailing : .leading, spacing: 8) {
                Text(message.content)
                    .font(.system(size: isUser ? 19 : 15, weight: isUser ? .bold : .regular))
                    .foregroundStyle(isUser ? .white : Color(hex: "244E6D"))
                    .lineSpacing(2)
                    .padding(.horizontal, isUser ? 17 : 15)
                    .padding(.vertical, isUser ? 12 : 14)
                    .background(
                        RoundedRectangle(cornerRadius: isUser ? 32 : 20, style: .continuous)
                            .fill(isUser ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing)) : AnyShapeStyle(.white.opacity(0.56)))
                            .overlay(
                                RoundedRectangle(cornerRadius: isUser ? 32 : 20, style: .continuous)
                                    .stroke(.white.opacity(0.72), lineWidth: 1)
                            )
                    )
                    .fixedSize(horizontal: false, vertical: true)

                if let status = message.status {
                    HStack(spacing: 8) {
                        Text(status.rawValue)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(isUser ? .white.opacity(0.82) : Color(hex: "6C8194"))
                        if status == .failed {
                            Button("重试", action: onRetry)
                                .font(.system(size: 11, weight: .bold))
                        }
                    }
                }

                if !isUser {
                    HStack(spacing: 8) {
                        if let analysis = message.analysis, !analysis.isEmpty {
                            CapsuleButton(title: "查看分析", action: onAnalysis)
                        }
                        if !message.citations.isEmpty {
                            CapsuleButton(title: "证据展示", action: onEvidence)
                        }
                    }
                }
            }
            if !isUser { Spacer(minLength: 44) }
        }
    }
}

private struct XAgeChatInputBar: View {
    @ObservedObject var vm: ChatViewModel
    let isRecording: Bool
    let isUploading: Bool
    let onMicTap: () -> Void
    let onCameraTap: () -> Void
    let onPlusTap: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Button(action: onMicTap) {
                Image(systemName: isRecording ? "stop.circle.fill" : "mic.fill")
                    .frame(width: 32, height: 32)
            }
            .buttonStyle(.plain)
            .foregroundStyle(isRecording ? Color(hex: "12B59C") : Color(hex: "172033"))
            .accessibilityIdentifier("xage.chat.mic")
            .accessibilityLabel(isRecording ? "停止语音输入" : "语音输入")

            TextField("输入或长按说话", text: $vm.inputValue)
                .font(.system(size: 15))
                .textFieldStyle(.plain)
                .frame(height: 44)

            Button(action: onCameraTap) {
                Image(systemName: "camera.fill")
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "172033"))
            .disabled(isUploading)
            .accessibilityIdentifier("xage.chat.camera")
            .accessibilityLabel("拍照上传报告")

            Button(action: onPlusTap) {
                Image(systemName: "plus")
                    .font(.system(size: 19, weight: .semibold))
                    .frame(width: 32, height: 32)
                    .background(
                        Circle()
                            .fill(.white.opacity(0.58))
                            .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1))
                    )
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "172033"))
            .disabled(isUploading)
            .accessibilityIdentifier("xage.chat.plus")
            .accessibilityLabel("添加内容")

            Button {
                Task { await vm.sendMessage() }
            } label: {
                Image(systemName: "paperplane.fill")
                    .font(.system(size: 17, weight: .bold))
                    .offset(x: -1, y: 1)
                    .frame(width: 36, height: 36)
                    .background(
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "228DD8"), Color(hex: "1DC8AE")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                    .foregroundStyle(.white)
            }
            .buttonStyle(.plain)
            .disabled(vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vm.sending)
            .accessibilityIdentifier("xage.chat.send")
            .accessibilityLabel("发送")
        }
        .padding(.horizontal, 10)
        .frame(height: 58)
        .background(XAgeGlassCardBackground(cornerRadius: 29))
    }
}

private struct XAgeAttachmentMenu: View {
    let onDocument: () -> Void
    let onPhotoLibrary: () -> Void
    let onNewChat: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            Text("添加内容")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .frame(maxWidth: .infinity)
                .padding(.bottom, 2)

            menuButton(
                title: "选择 PDF / 图片报告",
                icon: "doc.badge.plus",
                identifier: "xage.chat.attachment.documents",
                action: onDocument
            )
            menuButton(
                title: "从相册上传报告",
                icon: "photo.on.rectangle.angled",
                identifier: "xage.chat.attachment.photos",
                action: onPhotoLibrary
            )
            menuButton(
                title: "新对话",
                icon: "plus.message.fill",
                identifier: "xage.chat.attachment.new",
                action: onNewChat
            )
        }
        .padding(12)
        .frame(width: 220)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
        .shadow(color: Color(hex: "7CCAF5").opacity(0.22), radius: 22, x: 0, y: 10)
        .accessibilityElement(children: .contain)
    }

    private func menuButton(
        title: String,
        icon: String,
        identifier: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: icon)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
                    .frame(width: 22, height: 22)
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .frame(height: 42)
            .background(XAgeCapsuleFill())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }
}

private struct XAgeChatHistorySheet: View {
    @ObservedObject var vm: ChatViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("历史对话")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("继续之前的健康问答")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer()

                    Button {
                        vm.showHistory = false
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "2A79BB"))
                            .frame(width: 36, height: 36)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.chat.history.close")
                    .accessibilityLabel("关闭历史对话")
                }

                ScrollView {
                    LazyVStack(spacing: 12) {
                        if vm.conversations.isEmpty {
                            emptyState
                        } else {
                            ForEach(vm.conversations) { conversation in
                                Button {
                                    Task {
                                        await vm.loadConversation(id: conversation.id)
                                        vm.showHistory = false
                                        dismiss()
                                    }
                                } label: {
                                    conversationRow(conversation)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.chat.history.row.\(conversation.id)")
                            }

                            if vm.hasMoreConversations {
                                Button {
                                    Task { await vm.loadMoreConversations() }
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(systemName: "arrow.down.circle.fill")
                                            .font(.system(size: 15, weight: .bold))
                                        Text("加载更多")
                                            .font(.system(size: 15, weight: .bold))
                                    }
                                    .foregroundStyle(Color(hex: "237FC4"))
                                    .frame(maxWidth: .infinity)
                                    .frame(height: 48)
                                    .background(XAgeCapsuleFill())
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.chat.history.more")
                            }
                        }
                    }
                    .padding(.bottom, 24)
                }
                .scrollIndicators(.hidden)
            }
            .padding(.horizontal, 24)
            .padding(.top, 24)
        }
        .accessibilityIdentifier("xage.chat.history.sheet")
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color(hex: "6CD8DA").opacity(0.22))
                    .frame(width: 54, height: 54)
                Image(systemName: "clock.arrow.circlepath")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
            }

            Text("暂无历史对话")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            Text("登录并完成问答后，会在这里继续查看历史记录。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "5D7890"))
                .multilineTextAlignment(.center)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 34)
        .padding(.horizontal, 18)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private func conversationRow(_ conversation: ChatConversation) -> some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color(hex: "25C8BE").opacity(0.18))
                    .frame(width: 42, height: 42)
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "159D8F"))
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(conversation.title ?? "健康问答")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)

                HStack(spacing: 8) {
                    Text("\(conversation.message_count ?? 0) 条消息")
                    if let timestamp = conversation.updated_at ?? conversation.created_at {
                        Text("·")
                        Text(Self.formatTimestamp(timestamp))
                    }
                }
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6F879B"))
            }

            Spacer(minLength: 8)

            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "8BA6BA"))
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private static func formatTimestamp(_ iso: String) -> String {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = fractional.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else {
            return String(iso.prefix(10))
        }

        let diff = Date().timeIntervalSince(date)
        if diff < 60 { return "刚刚" }
        if diff < 3600 { return "\(Int(diff / 60))分钟前" }
        if diff < 86400 { return "\(Int(diff / 3600))小时前" }
        if diff < 86400 * 7 { return "\(Int(diff / 86400))天前" }

        let formatter = DateFormatter()
        formatter.dateFormat = "MM-dd HH:mm"
        return formatter.string(from: date)
    }
}

private struct XAgeChatUploadStatusCard: View {
    let uploading: Bool
    let title: String
    let subtitle: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(.white.opacity(0.52))
                    .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1))
                    .frame(width: 34, height: 34)
                if uploading {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Image(systemName: "sparkles")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(Color(hex: "159D8F"))
                }
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)
                Text(subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityIdentifier("xage.chat.upload.status")
    }
}

@MainActor
private final class XAgeSpeechInputManager: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var onResult: ((String) -> Void)?

    func start(onResult: @escaping (String) -> Void) {
        guard !isRecording else { return }
        self.onResult = onResult
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                guard let self else { return }
                guard status == .authorized else {
                    self.errorMessage = "请在系统设置中允许语音识别权限。"
                    return
                }
                self.requestRecordPermission()
            }
        }
    }

    private func requestRecordPermission() {
        if #available(iOS 17.0, *) {
            AVAudioApplication.requestRecordPermission { [weak self] allowed in
                Task { @MainActor in
                    self?.handleRecordPermission(allowed)
                }
            }
        } else {
            AVAudioSession.sharedInstance().requestRecordPermission { [weak self] allowed in
                DispatchQueue.main.async {
                    self?.handleRecordPermission(allowed)
                }
            }
        }
    }

    private func handleRecordPermission(_ allowed: Bool) {
        guard allowed else {
            errorMessage = "请在系统设置中允许麦克风权限。"
            return
        }
        startRecording()
    }

    func stop() {
        stopRecording(cancelTask: true)
    }

    private func startRecording() {
        guard recognizer?.isAvailable == true else {
            errorMessage = "当前设备语音识别暂不可用。"
            return
        }

#if targetEnvironment(simulator)
        errorMessage = "模拟器无法进行真实语音输入，请在真机上使用麦克风。"
        return
#else
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest else { return }
        recognitionRequest.shouldReportPartialResults = true

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let inputNode = audioEngine.inputNode
            inputNode.removeTap(onBus: 0)
            let format = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak recognitionRequest] buffer, _ in
                recognitionRequest?.append(buffer)
            }

            audioEngine.prepare()
            try audioEngine.start()
            isRecording = true

            recognitionTask = recognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if let result {
                        self.onResult?(result.bestTranscription.formattedString)
                    }
                    if error != nil || result?.isFinal == true {
                        self.stopRecording(cancelTask: false)
                    }
                }
            }
        } catch {
            errorMessage = "语音输入启动失败：\(error.localizedDescription)"
            stopRecording(cancelTask: true)
        }
#endif
    }

    private func stopRecording(cancelTask: Bool) {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        if cancelTask {
            recognitionTask?.cancel()
        }
        recognitionRequest = nil
        recognitionTask = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}

private struct XAgeAnalysisSheet: View {
    let message: ChatMessageItem
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("详细分析")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color(hex: "123E67"))
                    Spacer()
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .frame(width: 34, height: 34)
                            .background(XAgeCapsuleFill())
                    }
                    .accessibilityLabel("关闭")
                }
                ScrollView {
                    MarkdownTextView(text: message.analysis ?? "当前回答没有额外分析。")
                        .padding(16)
                        .background(XAgeGlassCardBackground(cornerRadius: 22))
                }
                .scrollIndicators(.hidden)
            }
            .padding(24)
        }
    }
}

private struct XAgeEvidenceSheet: View {
    let message: ChatMessageItem
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Text("证据展示")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .accessibilityLabel("关闭")
                    }
                    ForEach(Array(message.citations.enumerated()), id: \.element.id) { index, citation in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text("[\(index + 1)]")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color.appPrimary)
                                Text(citation.evidence_level)
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Color.appAccent)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 3)
                                    .background(Capsule().fill(Color.appAccent.opacity(0.12)))
                                Spacer()
                                Text(citation.confidence)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(Color(hex: "6C8194"))
                            }
                            Text(citation.claim_text)
                                .font(.system(size: 14))
                                .foregroundStyle(Color(hex: "244E6D"))
                            Text("\(citation.short_ref) · \(citation.journal ?? "source") · \(citation.year.map(String.init) ?? "year")")
                                .font(.system(size: 12))
                                .foregroundStyle(Color(hex: "6C8194"))
                                .lineLimit(1)
                        }
                        .padding(14)
                        .background(XAgeGlassCardBackground(cornerRadius: 20))
                    }
                    if message.citations.isEmpty {
                        Text("当前回答暂无文献引用。")
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .padding(16)
                            .background(XAgeGlassCardBackground(cornerRadius: 20))
                    }
                }
                .padding(24)
            }
        }
    }
}

private struct XAgeSnapshot {
    let range: String
    let updateHint: String
    let age: String
    let delta: String
    let pace: Double
    let status: String
    let summary: String
}

private struct XAgeInfoSheet: View {
    let snapshot: XAgeSnapshot
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("X年龄说明")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(snapshot.range)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
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
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.info.close")
                    .accessibilityLabel("关闭 X年龄说明")
                }

                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 12) {
                        infoMetric(title: "当前", value: snapshot.age)
                        infoMetric(title: "差值", value: snapshot.delta)
                        infoMetric(title: "进度", value: String(format: "%.1fx", snapshot.pace))
                    }

                    Text("X年龄会综合压力、恢复、炎症和日常节律。数值越低代表当前健康信号对应的生物负担越轻；衰老进度低于 1.0x 表示近期节律正在拉慢风险累积。")
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(4)

                    Text(snapshot.summary)
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineSpacing(4)
                        .padding(14)
                        .background(XAgeCapsuleFill())
                }
                .padding(16)
                .background(XAgeGlassCardBackground(cornerRadius: 26))
            }
            .padding(24)
        }
    }

    private func infoMetric(title: String, value: String) -> some View {
        VStack(spacing: 5) {
            Text(value)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .lineLimit(1)
                .minimumScaleFactor(0.72)
            Text(title)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color(hex: "6F879B"))
        }
        .frame(maxWidth: .infinity)
        .frame(height: 58)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeHealthspanView: View {
    @Binding var selectedSection: XAgeTopSection
    let infoRequest: Int
    @State private var snapshotIndex = 1
    @State private var showInfo = false

    private let snapshots = [
        XAgeSnapshot(
            range: "6月17日 - 6月23日",
            updateHint: "已完成更新",
            age: "30.2",
            delta: "年轻 4.4 岁",
            pace: 0.9,
            status: "压力略高",
            summary: "HRV 短暂回落，压力信号推快衰老进度；睡眠时长稳定，抵消了一部分生物负担。"
        ),
        XAgeSnapshot(
            range: "6月24日 - 6月30日",
            updateHint: "下次更新：6天后",
            age: "29.9",
            delta: "年轻 4.7 岁",
            pace: 0.8,
            status: "稳定且健康",
            summary: "炎症信号较低会减轻生物负担；压力升高会推快衰老进度；恢复因子（HRV、睡眠、静息心率）改善会拉慢进度。"
        ),
        XAgeSnapshot(
            range: "7月1日 - 7月7日",
            updateHint: "预测中",
            age: "29.7",
            delta: "年轻 4.9 岁",
            pace: 0.7,
            status: "恢复改善",
            summary: "连续睡眠和活动节律改善时，恢复因子会继续拉慢衰老进度；如果炎症升高，预测会自动回调。"
        )
    ]

    private var snapshot: XAgeSnapshot {
        snapshots[snapshotIndex]
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                Text("X年龄")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .padding(.top, 12)
                Text(snapshot.updateHint)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "5D7B95"))

                HStack(spacing: 10) {
                    Button {
                        selectSnapshot(snapshotIndex - 1)
                    } label: {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 26, height: 26)
                    }
                    .buttonStyle(.plain)
                    .disabled(snapshotIndex == snapshots.startIndex)
                    .opacity(snapshotIndex == snapshots.startIndex ? 0.35 : 1)
                    .accessibilityIdentifier("xage.week.previous")
                    .accessibilityLabel("上一周")

                    Text(snapshot.range)
                        .font(.system(size: 14, weight: .bold))

                    Button {
                        selectSnapshot(snapshotIndex + 1)
                    } label: {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 26, height: 26)
                    }
                    .buttonStyle(.plain)
                    .disabled(snapshotIndex == snapshots.index(before: snapshots.endIndex))
                    .opacity(snapshotIndex == snapshots.index(before: snapshots.endIndex) ? 0.35 : 1)
                    .accessibilityIdentifier("xage.week.next")
                    .accessibilityLabel("下一周")
                }
                .foregroundStyle(Color(hex: "347FB7"))
                .padding(.horizontal, 6)
                .frame(height: 32)
                .background(XAgeCapsuleFill())

                ZStack {
                    Circle()
                        .fill(
                            RadialGradient(colors: [Color(hex: "8EF7E6").opacity(0.24), Color(hex: "21B5FF").opacity(0.12), .clear], center: .center, startRadius: 20, endRadius: 170)
                        )
                        .frame(width: 272, height: 272)
                        .blur(radius: 7)
                    Image("x_age_particle_ring_blue_green")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 254, height: 254)
                        .accessibilityIdentifier("xage.particle.ring")
                    Circle()
                        .fill(.white.opacity(0.54))
                        .background(.ultraThinMaterial, in: Circle())
                        .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                        .frame(width: 154, height: 154)
                    VStack(spacing: 4) {
                        Text(snapshot.age)
                            .font(.system(size: 44, weight: .bold))
                            .foregroundStyle(Color(hex: "12324F"))
                        Text("X年龄")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "45677F"))
                        Text(snapshot.delta)
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "10A88E"))
                    }
                }
                .frame(height: 262)
                .padding(.top, 2)

                XAgePaceCard(pace: snapshot.pace)

                VStack(alignment: .leading, spacing: 7) {
                    Text(snapshot.status)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(snapshot.summary)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(2)
                        .lineLimit(3)
                }
                .padding(14)
                .background(XAgeGlassCardBackground(cornerRadius: 26))
                .padding(.bottom, 20)
            }
            .padding(.horizontal, 24)
        }
        .scrollIndicators(.hidden)
        .onChange(of: infoRequest) { _, _ in
            guard selectedSection == .xAge else { return }
            showInfo = true
        }
        .sheet(isPresented: $showInfo) {
            XAgeInfoSheet(snapshot: snapshot)
                .presentationDetents([.medium])
                .presentationDragIndicator(.visible)
        }
    }

    private func selectSnapshot(_ index: Int) {
        guard snapshots.indices.contains(index) else { return }
        withAnimation(.spring(response: 0.28, dampingFraction: 0.86)) {
            snapshotIndex = index
        }
    }
}

private struct XAgePaceCard: View {
    let pace: Double

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("衰老进度")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(String(format: "%.1fx", pace))
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(Color(hex: "17324E"))
            }
            HStack {
                Text("慢")
                Spacer()
                Text("快")
            }
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(Color(hex: "6A8197"))

            ZStack(alignment: .leading) {
                HStack(spacing: 4) {
                    ForEach(0..<44, id: \.self) { i in
                        RoundedRectangle(cornerRadius: 1)
                            .fill(Color(hex: "577990").opacity(i % 10 == 0 ? 0.52 : 0.28))
                            .frame(width: 2, height: i % 10 == 0 ? 26 : 18)
                    }
                }
                RoundedRectangle(cornerRadius: 2)
                    .fill(LinearGradient(colors: [.white, Color(hex: "18C3B6")], startPoint: .top, endPoint: .bottom))
                    .frame(width: 4, height: 34)
                    .offset(x: markerOffset)
                    .shadow(color: Color(hex: "18B9D0").opacity(0.24), radius: 8, x: 0, y: 4)
            }
            .frame(height: 36)

            HStack {
                Text("-1.0x")
                Spacer()
                Text("1.0x")
                Spacer()
                Text("3.0x")
            }
            .font(.system(size: 12))
            .foregroundStyle(Color(hex: "6C8194"))
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var markerOffset: CGFloat {
        let clamped = min(max(pace, -1), 3)
        return CGFloat((clamped + 1) / 4) * 260
    }
}

private struct XAgeMoreMenu: View {
    @Binding var selectedSection: XAgeTopSection
    @Binding var dataSortMode: Bool
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Text("XAGE")
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(Color(hex: "123E67"))
                    Spacer()
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .frame(width: 34, height: 34)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("关闭")
                }

                VStack(spacing: 10) {
                    XAgeMoreMenuRow(
                        icon: "chart.line.uptrend.xyaxis",
                        title: XAgeTopSection.data.rawValue,
                        selected: selectedSection == .data
                    ) {
                        switchTo(.data)
                    }
                    XAgeMoreMenuRow(
                        icon: "bubble.left.and.bubble.right.fill",
                        title: XAgeTopSection.chat.rawValue,
                        selected: selectedSection == .chat
                    ) {
                        switchTo(.chat)
                    }
                    XAgeMoreMenuRow(
                        icon: "sparkles",
                        title: XAgeTopSection.xAge.rawValue,
                        selected: selectedSection == .xAge
                    ) {
                        switchTo(.xAge)
                    }
                }
                .padding(14)
                .background(XAgeGlassCardBackground(cornerRadius: 28))

                Spacer()
            }
            .padding(24)
        }
    }

    private func switchTo(_ section: XAgeTopSection) {
        dataSortMode = false
        withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
            selectedSection = section
        }
        dismiss()
    }
}

private struct XAgeMoreMenuRow: View {
    let icon: String
    let title: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: selected ? [Color(hex: "238AD6"), Color(hex: "20CDB1")] : [Color(hex: "7ABBE7"), Color(hex: "92DDCE")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    )

                Text(title)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))

                Spacer()

                if selected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "16A88E"))
                } else {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "7D9AB1"))
                }
            }
            .padding(.horizontal, 14)
            .frame(height: 64)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
        }
        .buttonStyle(.plain)
    }
}

private struct CapsuleButton: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "365F80"))
                .frame(width: 56, height: 30)
                .background(XAgeCapsuleFill())
        }
        .buttonStyle(.plain)
    }
}

private struct XAgeGlassCardBackground: View {
    var cornerRadius: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white.opacity(0.56))
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.84), lineWidth: 1)
            )
            .shadow(color: Color(hex: "73C8F0").opacity(0.18), radius: 28, x: 0, y: 14)
    }
}

private struct XAgeCapsuleFill: View {
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.58))
            .background(.ultraThinMaterial, in: Capsule())
            .overlay(Capsule().stroke(.white.opacity(0.88), lineWidth: 1))
            .shadow(color: Color(hex: "7ACAF5").opacity(0.12), radius: 14, x: 0, y: 7)
    }
}

private struct XAgeLiquidBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(hex: "E8F7FF"), Color(hex: "D5ECFF"), Color(hex: "F7FCFF")],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            Circle()
                .fill(Color(hex: "61E7E1").opacity(0.28))
                .frame(width: 235, height: 235)
                .blur(radius: 26)
                .offset(x: -150, y: -260)
            Circle()
                .fill(Color(hex: "8CC8FF").opacity(0.32))
                .frame(width: 260, height: 300)
                .blur(radius: 30)
                .offset(x: 160, y: -320)
            Circle()
                .fill(Color(hex: "C9C2FF").opacity(0.22))
                .frame(width: 230, height: 260)
                .blur(radius: 34)
                .offset(x: 135, y: 150)
            Rectangle()
                .fill(.white.opacity(0.2))
                .frame(width: 88)
                .blur(radius: 22)
                .rotationEffect(.degrees(5))
                .offset(x: -6)
        }
    }
}
