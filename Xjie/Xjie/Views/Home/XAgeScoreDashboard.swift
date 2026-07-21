import SwiftUI

/// 首页评分摘要与滚动外观模块。
///
/// 包含压力、恢复、炎症等评分的固定顶部摘要、详情路由枚举，以及数据页滚动位置跟踪组件。
/// 数据页专用滚动坐标空间，供顶部摘要收起逻辑读取偏移量。
enum XAgeDataScrollSpace {
    static let name = "xageDataScroll"
}

struct XAgeDataScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

struct XAgeDataScrollOffsetProbe: View {
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

/// 在 iOS 18 及以上监听滚动偏移，并通过回调交还给页面状态所有者。
struct XAgeDataScrollOffsetTracker: ViewModifier {
    /// 新的纵向内容偏移量回调，单位为点。
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

/// 数据页所有 sheet 的类型化路由，避免多个布尔值同时竞争展示。
enum XAgeDataSheet: Identifiable {
    case detail(XAgeDataKind)
    case scoreInfo(XAgeDataKind)
    case metricDetail(XAgeMetric)
    case manualEntry(XAgeMetric)

    var id: String {
        switch self {
        case .detail(let kind): return "detail-\(kind.id)"
        case .scoreInfo(let kind): return "score-info-\(kind.id)"
        case .metricDetail(let metric): return "metric-detail-\(metric.id)"
        case .manualEntry(let metric): return "manual-entry-\(metric.id)"
        }
    }
}

/// 数据页固定顶部区域，组合标题、评分圆环和今日摘要。
struct XAgeDataStickyHeader: View {
    /// `0...1` 的收起进度。
    let collapseProgress: CGFloat
    /// 服务端同步状态摘要。
    let caption: String
    /// 当前可展示的三项评分。
    let scores: XAgeCompositeScores
    /// 是否展示“今日状态”说明卡。
    let showsTodayStatus: Bool
    /// 用户点击评分圆环后的详情回调。
    let onSelectDetail: (XAgeDataKind) -> Void
    /// 用户点击评分说明按钮后的回调。
    let onSelectInfo: (XAgeDataKind) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12 - 4 * collapseProgress) {
            VStack(alignment: .leading, spacing: 4) {
                Text("今日健康数据")
                    .font(.system(size: 27 - 4 * collapseProgress, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .lineLimit(1)
//                暂时删去健康数据摘要部分，有点多余
//                Text(caption)
//                    .font(.system(size: 13))
//                    .foregroundStyle(Color(hex: "5D7B95"))
//                    .opacity(Double(1 - collapseProgress))
//                    .frame(height: 18 * (1 - collapseProgress), alignment: .top)
//                    .clipped()
            }
            .frame(height: 52 - 18 * collapseProgress, alignment: .topLeading)

            XAgeScoreRingPanel(
                collapseProgress: collapseProgress,
                scores: scores,
                onSelectDetail: onSelectDetail,
                onSelectInfo: onSelectInfo
            )

            if showsTodayStatus {
                XAgeScoreSummaryCard(compactProgress: collapseProgress, scores: scores)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}

/// 首页固定展示的评分种类。
enum XAgeDataKind: String, Identifiable {
    case pressure = "压力"
    case recovery = "恢复"
    case inflammation = "炎症"

    var id: String { rawValue }

    var tint: Color {
        switch self {
        case .pressure: return Color(hex: "2789D8")
        case .recovery: return Color(hex: "14B887")
        case .inflammation: return Color(hex: "EF9A3D")
        }
    }

    var accessibilityKey: String {
        switch self {
        case .pressure: return "pressure"
        case .recovery: return "recovery"
        case .inflammation: return "inflammation"
        }
    }
}

/// 单项评分圆环，同时承载数值、状态和可信展示语义。
struct XAgeScoreRing: View {
    /// 评分种类，决定标题、颜色和辅助功能 ID。
    let kind: XAgeDataKind
    /// 当前评分值、置信度、状态与可信展示标记。
    let metric: XAgeMetricScore
    /// 圆环直径，默认适配首页摘要。
    var ringSize: CGFloat = 86
    /// 点击圆环时打开详情；为 `nil` 时圆环只展示。
    var onSelect: (() -> Void)? = nil
    /// 点击信息按钮时打开评分说明。
    var onInfo: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: 7) {
            ringControl

            HStack(spacing: 3) {
                Text(kind.rawValue)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color(hex: "43657F"))
                    .lineLimit(1)
                if let onInfo {
                    Button(action: onInfo) {
                        Image(systemName: "info.circle.fill")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(kind.tint)
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                    }
                    .padding(.horizontal, -13)
                    .padding(.vertical, -13)
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.data.score.\(kind.accessibilityKey).info")
                    .accessibilityLabel("\(kind.rawValue)原理")
                }
            }
            .frame(height: 18)
        }
        .frame(maxWidth: .infinity)
    }

    @ViewBuilder
    private var ringControl: some View {
        if let onSelect {
            Button(action: onSelect) {
                ringGraphic
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(kind.rawValue)评分，\(metric.displayValue)")
            .accessibilityHint("打开\(kind.rawValue)详情")
            .accessibilityIdentifier("xage.data.score.\(kind.accessibilityKey)")
        } else {
            ringGraphic
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(kind.rawValue)评分，\(metric.displayValue)")
        }
    }

    private var ringGraphic: some View {
        let lineWidth = max(7, ringSize * 0.1)
        return ZStack {
            Circle()
                .trim(from: 0.04, to: 0.9)
                .stroke(Color.white.opacity(0.52), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .rotationEffect(.degrees(112))
            Circle()
                .trim(from: 0.04, to: 0.04 + 0.86 * CGFloat(metric.isReady ? metric.value : 0) / 100)
                .stroke(
                    AngularGradient(
                        colors: [kind.tint.opacity(0.35), kind.tint, Color.appAccent, kind.tint],
                        center: .center
                    ),
                    style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                )
                .rotationEffect(.degrees(112))
                .opacity(metric.isReady ? 1 : 0.28)
                .shadow(color: kind.tint.opacity(metric.isReady ? 0.22 : 0.08), radius: 8, x: 0, y: 3)
            Text(metric.displayValue)
                .font(.system(size: metric.isReady ? (ringSize >= 80 ? 25 : 22) : 20, weight: .bold))
                .foregroundStyle(Color(hex: "17324E"))
        }
        .frame(width: ringSize, height: ringSize)
        .contentShape(Circle())
    }
}

private struct XAgeScoreRingPanel: View {
    let collapseProgress: CGFloat
    let scores: XAgeCompositeScores
    let onSelectDetail: (XAgeDataKind) -> Void
    let onSelectInfo: (XAgeDataKind) -> Void

    var body: some View {
        let ringSize = 86 - 14 * collapseProgress
        HStack(spacing: 8) {
            XAgeScoreRing(
                kind: .pressure,
                metric: scores.pressure,
                ringSize: ringSize,
                onSelect: { onSelectDetail(.pressure) },
                onInfo: { onSelectInfo(.pressure) }
            )
            XAgeScoreRing(
                kind: .recovery,
                metric: scores.recovery,
                ringSize: ringSize,
                onSelect: { onSelectDetail(.recovery) },
                onInfo: { onSelectInfo(.recovery) }
            )
            XAgeScoreRing(
                kind: .inflammation,
                metric: scores.inflammation,
                ringSize: ringSize,
                onSelect: { onSelectDetail(.inflammation) },
                onInfo: { onSelectInfo(.inflammation) }
            )
        }
        .frame(maxWidth: .infinity)
        .frame(height: 122)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
    }
}

private struct XAgeScoreSummaryCard: View {
    let compactProgress: CGFloat
    let scores: XAgeCompositeScores

    private var badges: [(id: String, title: String, color: Color)] {
        [
            ("pressure", scores.pressure.badgeLabel, Color(hex: "2789D8")),
            ("recovery", scores.recovery.badgeLabel, Color(hex: "14B887")),
            ("inflammation", scores.inflammation.badgeLabel, Color(hex: "EF9A3D"))
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8 - 2 * compactProgress) {
            HStack(spacing: 8) {
                Text("今日状态")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Spacer(minLength: 4)
                HStack(spacing: 5) {
                    ForEach(badges, id: \.id) { item in
                        HStack(spacing: 3) {
                            Circle()
                                .fill(item.color)
                                .frame(width: 6, height: 6)
                            Text(item.title)
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(item.color)
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
            Text(scores.todaySummary)
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(2)
                .lineLimit(compactProgress > 0.7 ? 1 : 2)
                .accessibilityIdentifier("xage.score.trust.notice")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12 - 2 * compactProgress)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}
