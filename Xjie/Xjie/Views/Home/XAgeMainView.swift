import SwiftUI

enum XAgeTopSection: String, CaseIterable, Identifiable {
    case data = "数据"
    case chat = "问答"
    case xAge = "X年龄"

    var id: String { rawValue }
}

struct XAgeMainView: View {
    @State private var selectedSection: XAgeTopSection = .data
    @State private var showMoreMenu = false

    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground()
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    XAgeTopBar(
                        selected: $selectedSection,
                        showMoreMenu: $showMoreMenu
                    )
                    .padding(.top, 12)
                    .padding(.horizontal, 24)
                    .zIndex(2)

                    TabView(selection: $selectedSection) {
                        XAgeDataDashboardView(selectedSection: $selectedSection)
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
}

private struct XAgeTopBar: View {
    @Binding var selected: XAgeTopSection
    @Binding var showMoreMenu: Bool

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

            Button {} label: {
                Image(systemName: "info")
                    .font(.system(size: 14, weight: .bold))
                    .frame(width: 34, height: 34)
                    .background(
                        Circle()
                            .fill(.white.opacity(0.48))
                            .overlay(Circle().stroke(.white.opacity(0.86), lineWidth: 1))
                    )
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "2A79BB"))
            .accessibilityIdentifier("xage.info")
        }
    }
}

private struct XAgeDataDashboardView: View {
    @Binding var selectedSection: XAgeTopSection
    @State private var sortMode = false
    @State private var selectedDetail: XAgeDataKind?
    @State private var metrics = XAgeMetric.defaultCards
    @State private var cardOffsets: [String: CGFloat] = [:]

    var body: some View {
        VStack(spacing: 0) {
            XAgeDataStickyHeader(
                sortMode: sortMode,
                collapseProgress: headerCollapseProgress,
                onToggleSort: {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.88)) {
                        sortMode.toggle()
                    }
                },
                onSelectDetail: { selectedDetail = $0 }
            )
            .padding(.horizontal, 24)
            .padding(.top, 20)
            .padding(.bottom, 8)
            .zIndex(2)

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

                    XAgeBottomDataPanel()
                        .padding(.top, 6)
                        .padding(.bottom, 24)
                }
                .padding(.horizontal, 24)
                .padding(.top, 10)
            }
            .coordinateSpace(name: "xageDataCards")
            .scrollIndicators(.hidden)
            .onPreferenceChange(XAgeCardOffsetPreferenceKey.self) { offsets in
                cardOffsets = offsets
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
    let sortMode: Bool
    let collapseProgress: CGFloat
    let onToggleSort: () -> Void
    let onSelectDetail: (XAgeDataKind) -> Void

    var body: some View {
        VStack(spacing: 10 - 3 * collapseProgress) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("今日数据")
                        .font(.system(size: 27 - 4 * collapseProgress, weight: .bold))
                        .foregroundStyle(Color(hex: "123E67"))
                    Text("三项评分固定可见，卡片逐张滚动查看")
                        .font(.system(size: 13))
                        .foregroundStyle(Color(hex: "5D7B95"))
                        .opacity(Double(1 - collapseProgress))
                        .frame(height: 17 * (1 - collapseProgress), alignment: .top)
                        .clipped()
                }
                Spacer()
                Button(sortMode ? "完成" : "排序", action: onToggleSort)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 54, height: 34)
                    .background(XAgeCapsuleFill())
                    .accessibilityIdentifier(sortMode ? "xage.data.sort.done" : "xage.data.sort")
            }

            HStack(spacing: 10) {
                XAgeScoreRing(kind: .pressure, score: 68)
                    .onTapGesture { onSelectDetail(.pressure) }
                    .accessibilityIdentifier("xage.data.score.pressure")
                XAgeScoreRing(kind: .recovery, score: 82)
                    .onTapGesture { onSelectDetail(.recovery) }
                    .accessibilityIdentifier("xage.data.score.recovery")
                XAgeScoreRing(kind: .inflammation, score: 57)
                    .onTapGesture { onSelectDetail(.inflammation) }
                    .accessibilityIdentifier("xage.data.score.inflammation")
            }
            .frame(height: 122)

            XAgeScoreSummaryCard()
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

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                Circle()
                    .trim(from: 0.04, to: 0.9)
                    .stroke(Color.white.opacity(0.48), style: StrokeStyle(lineWidth: 9, lineCap: .round))
                    .rotationEffect(.degrees(112))
                Circle()
                    .trim(from: 0.04, to: 0.04 + 0.86 * CGFloat(score) / 100)
                    .stroke(
                        AngularGradient(
                            colors: [kind.tint.opacity(0.35), kind.tint, Color.appAccent, kind.tint],
                            center: .center
                        ),
                        style: StrokeStyle(lineWidth: 9, lineCap: .round)
                    )
                    .rotationEffect(.degrees(112))
                    .shadow(color: kind.tint.opacity(0.22), radius: 8, x: 0, y: 3)
                Text("\(score)")
                    .font(.system(size: 25, weight: .bold))
                    .foregroundStyle(Color(hex: "17324E"))
            }
            .frame(width: 90, height: 90)

            Text(kind.rawValue)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Color(hex: "43657F"))
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct XAgeScoreSummaryCard: View {
    private let badges = [
        ("压力中等", Color(hex: "2789D8")),
        ("恢复良好", Color(hex: "14B887")),
        ("炎症关注", Color(hex: "EF9A3D"))
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("今日状态")
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            HStack(spacing: 8) {
                ForEach(badges, id: \.0) { item in
                    Text(item.0)
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(item.1)
                        .frame(maxWidth: .infinity)
                        .frame(height: 28)
                        .background(
                            Capsule()
                                .fill(.white.opacity(0.46))
                                .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
                        )
                }
            }
            Text("今天先保持低波动饮食和轻中等活动，晚间观察 HRV 与静息心率是否回到个人基线。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(2)
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeMetric: Identifiable {
    let id: String
    let title: String
    let value: String
    let unit: String
    let subtitle: String
    let accent: Color

    static let defaultCards = [
        XAgeMetric(id: "hrv", title: "心率变异性", value: "43", unit: "ms", subtitle: "比 7 日均值低 8%，压力评分的主要贡献项。", accent: Color(hex: "2789D8")),
        XAgeMetric(id: "sleep", title: "睡眠恢复", value: "7.2", unit: "h", subtitle: "深睡和连续性良好，支持恢复评分保持绿色。", accent: Color(hex: "14B887")),
        XAgeMetric(id: "glucose", title: "血糖波动", value: "18", unit: "%", subtitle: "餐后波动可控，建议继续核对晚餐碳水。", accent: Color(hex: "11A7C8")),
        XAgeMetric(id: "temp", title: "体温偏移", value: "+0.2", unit: "°C", subtitle: "轻微偏高，结合炎症和睡眠信号观察。", accent: Color(hex: "EF9A3D"))
    ]
}

private struct XAgeMetricCard: View {
    let card: XAgeMetric
    let sortMode: Bool
    let onMoveUp: () -> Void
    let onMoveDown: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 5) {
                    Text(card.title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(card.subtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "657E94"))
                        .lineLimit(2)
                }
                Spacer()
                HStack(alignment: .firstTextBaseline, spacing: 3) {
                    Text(card.value)
                        .font(.system(size: 30, weight: .bold))
                        .foregroundStyle(Color(hex: "101C2F"))
                    Text(card.unit)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Color(hex: "70879D"))
                }
                .fixedSize()
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
        .padding(16)
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
                        .frame(height: 28)
                        .background(
                            Capsule()
                                .fill(title == "健康数据" ? .white.opacity(0.7) : .white.opacity(0.22))
                        )
                }
            }

            HStack(spacing: 12) {
                Image(systemName: "icloud.and.arrow.up")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 42, height: 42)
                    .background(Circle().fill(.white.opacity(0.58)))
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
                        .foregroundStyle(Color(hex: "1268BD"))
                        .frame(width: 62, height: 36)
                        .background(XAgeCapsuleFill())
                }
                .accessibilityIdentifier("xage.data.upload")
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
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
                                .padding(.top, 26)
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
        .task { await vm.loadConversations() }
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
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 12) {
                AssistantAvatar(size: 48, bordered: true)
                VStack(alignment: .leading, spacing: 4) {
                    Text("助手小捷")
                        .font(.system(size: 23, weight: .bold))
                        .foregroundStyle(Color(hex: "123E67"))
                    Text("先问一个具体问题，我会给出可执行建议。")
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hex: "5D7B95"))
                }
            }

            VStack(spacing: 10) {
                NavigationLink(destination: PatientHistoryView()) {
                    XAgeStarterRow(icon: "stethoscope", title: "整理病史摘要", subtitle: "诊断、用药、过敏和异常检查", action: "整理")
                }
                .buttonStyle(.plain)

                Button {
                    vm.inputValue = "最近空腹血糖偏高，要怎么调整？"
                    Task { await vm.sendMessage() }
                } label: {
                    XAgeStarterRow(icon: "waveform.path.ecg", title: "解读血糖波动", subtitle: "结合 TIR、异常时段和饮食记录", action: "提问")
                }
                .buttonStyle(.plain)
                .disabled(vm.sending)

                Button {
                    vm.inputValue = "帮我做一个低负担饮食建议"
                    Task { await vm.sendMessage() }
                } label: {
                    XAgeStarterRow(icon: "fork.knife", title: "低负担饮食建议", subtitle: "按当前健康资料给出下一餐选择", action: "提问")
                }
                .buttonStyle(.plain)
                .disabled(vm.sending)
            }
        }
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
    }
}

private struct XAgeStarterRow: View {
    let icon: String
    let title: String
    let subtitle: String
    let action: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Color.appPrimary)
                .frame(width: 38, height: 38)
                .background(Circle().fill(.white.opacity(0.52)))
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "657E94"))
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            Text(action)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "1268BD"))
                .frame(width: 48, height: 28)
                .background(XAgeCapsuleFill())
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.white.opacity(0.38))
        )
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
            .foregroundStyle(Color(hex: "2A79BB"))

            TextField("输入或长按说话", text: $vm.inputValue)
                .font(.system(size: 15))
                .textFieldStyle(.plain)
                .frame(height: 44)

            Button {} label: {
                Image(systemName: "camera.fill")
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "2A79BB"))

            Button {} label: {
                Image(systemName: "plus")
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "2A79BB"))

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
            .opacity(vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vm.sending ? 0.55 : 1)
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
