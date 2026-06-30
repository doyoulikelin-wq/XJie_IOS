import SwiftUI

enum XAgeTopSection: String, CaseIterable, Identifiable {
    case data = "数据"
    case chat = "问答"
    case xAge = "X年龄"

    var id: String { rawValue }
}

struct XAgeMainView: View {
    @State private var selectedSection: XAgeTopSection = Self.initialSection()
    @State private var showMoreMenu = false
    @State private var dataSortMode = false

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
                        }
                    )
                    .padding(.top, 12)
                    .padding(.horizontal, 24)
                    .zIndex(2)

                    TabView(selection: $selectedSection) {
                        XAgeDataDashboardView(
                            selectedSection: $selectedSection,
                            sortMode: $dataSortMode
                        )
                            .tag(XAgeTopSection.data)
                        XAgeConversationSurface(selectedSection: $selectedSection)
                            .tag(XAgeTopSection.chat)
                        XAgeHealthspanView(selectedSection: $selectedSection)
                            .tag(XAgeTopSection.xAge)
                    }
                    .tabViewStyle(.page(indexDisplayMode: .never))
                }
            }
            .navigationBarHidden(true)
            .sheet(isPresented: $showMoreMenu) {
                XAgeLegacyMenu()
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
    @Binding var selectedSection: XAgeTopSection
    @Binding var sortMode: Bool
    @State private var selectedDetail: XAgeDataKind?
    @State private var metrics = XAgeMetric.defaultCards
    @State private var cardOffsets: [String: CGFloat] = [:]

    var body: some View {
        VStack(spacing: 0) {
            XAgeDataStickyHeader(
                collapseProgress: headerCollapseProgress,
                onSelectDetail: { selectedDetail = $0 }
            )
            .padding(.horizontal, 24)
            .padding(.top, 16)
            .padding(.bottom, 10)
            .zIndex(2)

            ZStack(alignment: .bottom) {
                ScrollView {
                    LazyVStack(spacing: 12) {
                        ForEach(Array(metrics.enumerated()), id: \.element.id) { index, card in
                            XAgeMetricCard(card: card, sortMode: sortMode) {
                                moveMetric(index, -1)
                            } onMoveDown: {
                                moveMetric(index, 1)
                            }
                            .background(
                                GeometryReader { proxy in
                                    Color.clear.preference(
                                        key: XAgeCardOffsetPreferenceKey.self,
                                        value: [card.id: proxy.frame(in: .named("xageDataCards")).minY]
                                    )
                                }
                            )
                            .modifier(
                                XAgeCardPeelEffect(
                                    progress: peelProgress(for: card.id),
                                    enabled: activePeelingCardID == card.id && !sortMode
                                )
                            )
                            .accessibilityIdentifier("xage.data.metric.\(card.id)")
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.top, 10)
                    .padding(.bottom, 178)
                }
                .coordinateSpace(name: "xageDataCards")
                .scrollIndicators(.hidden)
                .onPreferenceChange(XAgeCardOffsetPreferenceKey.self) { offsets in
                    cardOffsets = offsets
                }

                XAgeBottomDataPanel()
                    .zIndex(3)
            }
        }
        .sheet(item: $selectedDetail) { kind in
            XAgeDataDetailView(kind: kind)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
    }

    private var activePeelingCardID: String? {
        guard !sortMode else { return nil }
        return metrics.first { metric in
            (cardOffsets[metric.id] ?? .greatestFiniteMagnitude) > -126
        }?.id
    }

    private var headerCollapseProgress: CGFloat {
        guard !sortMode, let firstID = metrics.first?.id, let y = cardOffsets[firstID] else { return 0 }
        return min(1, max(0, -y / 92))
    }

    private func peelProgress(for id: String) -> CGFloat {
        guard activePeelingCardID == id, let y = cardOffsets[id], y < 0 else { return 0 }
        return min(1, max(0, -y / 126))
    }

    private func moveMetric(_ index: Int, _ direction: Int) {
        let target = index + direction
        guard metrics.indices.contains(index), metrics.indices.contains(target) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            metrics.swapAt(index, target)
        }
    }
}

private struct XAgeDataStickyHeader: View {
    let collapseProgress: CGFloat
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

            XAgeScoreSummaryCard(compactProgress: collapseProgress)
        }
    }
}

private struct XAgeCardOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: [String: CGFloat] = [:]

    static func reduce(value: inout [String: CGFloat], nextValue: () -> [String: CGFloat]) {
        value.merge(nextValue(), uniquingKeysWith: { $1 })
    }
}

private struct XAgeCardPeelEffect: ViewModifier {
    let progress: CGFloat
    let enabled: Bool

    func body(content: Content) -> some View {
        content
            .offset(y: enabled ? -34 * progress : 0)
            .rotation3DEffect(
                .degrees(Double(enabled ? -5 * progress : 0)),
                axis: (x: 1, y: 0, z: 0),
                anchor: .top,
                perspective: 0.58
            )
            .opacity(Double(enabled ? 1 - 0.78 * progress : 1))
            .zIndex(enabled ? 1 : 0)
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

private struct XAgeBottomDataPanel: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                ForEach(["健康数据", "运动睡眠", "就医资料", "健康信息"], id: \.self) { title in
                    Text(title)
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(title == "健康数据" ? Color(hex: "1268BD") : Color(hex: "5D7890"))
                        .frame(maxWidth: .infinity)
                        .frame(height: 30)
                        .background(
                            Capsule()
                                .fill(title == "健康数据" ? .white.opacity(0.72) : .white.opacity(0.34))
                        )
                }
            }

            HStack(spacing: 12) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 42)
                    .background(
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                VStack(alignment: .leading, spacing: 3) {
                    Text("上传报告")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text("体检报告、病历、化验单")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }
                Spacer()
                NavigationLink(destination: HealthDataView(focus: "upload")) {
                    Text("上传")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(width: 58, height: 34)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        )
                }
                .accessibilityIdentifier("xage.data.upload")
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(.white.opacity(0.5))
                    .overlay(
                        RoundedRectangle(cornerRadius: 22, style: .continuous)
                            .stroke(.white.opacity(0.72), lineWidth: 1)
                    )
            )
        }
        .padding(.horizontal, 20)
        .padding(.top, 28)
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
    @StateObject private var vm = ChatViewModel()
    @State private var selectedAnalysis: ChatMessageItem?
    @State private var selectedEvidence: ChatMessageItem?

    var body: some View {
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

            XAgeChatInputBar(vm: vm)
                .padding(.horizontal, 24)
                .padding(.bottom, 20)
        }
        .task { await vm.loadConversations(showErrors: false) }
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
        .alert("提示", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
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

            NavigationLink(destination: PatientHistoryView()) {
                XAgeStarterRow(icon: "doc.text", title: "整理病史摘要", subtitle: "诊断、用药、过敏信息", primary: true)
            }
            .buttonStyle(.plain)

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

    var body: some View {
        HStack(spacing: 8) {
            Button {} label: {
                Image(systemName: "mic.fill")
                    .frame(width: 32, height: 32)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "172033"))

            TextField("输入或长按说话", text: $vm.inputValue)
                .font(.system(size: 15))
                .textFieldStyle(.plain)
                .frame(height: 44)

            Button {} label: {
                Image(systemName: "camera.fill")
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "172033"))

            Button {} label: {
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
        }
        .padding(.horizontal, 10)
        .frame(height: 58)
        .background(XAgeGlassCardBackground(cornerRadius: 29))
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

private struct XAgeHealthspanView: View {
    @Binding var selectedSection: XAgeTopSection

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                Text("X年龄")
                    .font(.system(size: 25, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .padding(.top, 24)
                Text("下次更新：6天后")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "5D7B95"))

                HStack(spacing: 10) {
                    Image(systemName: "chevron.left")
                    Text("6月24日 - 6月30日")
                        .font(.system(size: 14, weight: .bold))
                    Image(systemName: "chevron.right")
                }
                .foregroundStyle(Color(hex: "347FB7"))
                .frame(width: 194, height: 34)
                .background(XAgeCapsuleFill())

                ZStack {
                    Circle()
                        .fill(
                            RadialGradient(colors: [Color(hex: "8EF7E6").opacity(0.24), Color(hex: "21B5FF").opacity(0.12), .clear], center: .center, startRadius: 20, endRadius: 170)
                        )
                        .frame(width: 314, height: 314)
                        .blur(radius: 8)
                    Image("x_age_particle_ring_blue_green")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 294, height: 294)
                        .accessibilityIdentifier("xage.particle.ring")
                    Circle()
                        .fill(.white.opacity(0.54))
                        .background(.ultraThinMaterial, in: Circle())
                        .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                        .frame(width: 178, height: 178)
                    VStack(spacing: 4) {
                        Text("29.9")
                            .font(.system(size: 50, weight: .bold))
                            .foregroundStyle(Color(hex: "12324F"))
                        Text("X年龄")
                            .font(.system(size: 16, weight: .bold))
                            .foregroundStyle(Color(hex: "45677F"))
                        Text("年轻 4.7 岁")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "10A88E"))
                    }
                }
                .frame(height: 312)
                .padding(.top, 8)

                XAgePaceCard()
                    .padding(.top, 2)

                VStack(alignment: .leading, spacing: 10) {
                    Text("稳定且健康")
                        .font(.system(size: 20, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text("炎症信号较低会减轻生物负担；压力升高会推快衰老进度；恢复因子（HRV、睡眠、静息心率）改善会拉慢进度。")
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(3)
                }
                .padding(18)
                .background(XAgeGlassCardBackground(cornerRadius: 26))
                .padding(.bottom, 26)
            }
            .padding(.horizontal, 24)
        }
        .scrollIndicators(.hidden)
    }
}

private struct XAgePaceCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("衰老进度")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text("0.8x")
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
                            .frame(width: 2, height: i % 10 == 0 ? 31 : 22)
                    }
                }
                RoundedRectangle(cornerRadius: 2)
                    .fill(LinearGradient(colors: [.white, Color(hex: "18C3B6")], startPoint: .top, endPoint: .bottom))
                    .frame(width: 4, height: 40)
                    .offset(x: 146)
                    .shadow(color: Color(hex: "18B9D0").opacity(0.24), radius: 8, x: 0, y: 4)
            }
            .frame(height: 44)

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
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeLegacyMenu: View {
    var body: some View {
        NavigationStack {
            List {
                NavigationLink("旧首页", destination: HomeView())
                NavigationLink("计划", destination: HealthPlanView())
                NavigationLink("多组学", destination: OmicsView())
                NavigationLink("设置", destination: SettingsView())
            }
            .navigationTitle("更多")
        }
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
