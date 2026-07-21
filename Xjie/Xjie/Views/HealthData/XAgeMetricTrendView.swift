import Charts
import SwiftUI

struct XAgeMetricTrendSample: Identifiable, Equatable {
    let id: String
    let date: Date
    let dateLabel: String
    let value: Double
    let displayValue: String
    let isAbnormal: Bool
}

enum XAgeMetricTrendContract {
    private static let pointSpacing: CGFloat = 52
    private static let horizontalPadding: CGFloat = 80
    private static let maximumChartWidth: CGFloat = 6_000

    static func samples(from trend: IndicatorTrend) -> [XAgeMetricTrendSample] {
        trend.points.enumerated().compactMap { index, point in
            guard point.value.isFinite, let date = date(from: point) else { return nil }
            return XAgeMetricTrendSample(
                id: "\(point.id)-\(index)",
                date: date,
                dateLabel: fullDateFormatter.string(from: date),
                value: point.value,
                displayValue: IndicatorTrendPresentationContract.displayValue(
                    for: point,
                    indicatorName: trend.name
                ),
                isAbnormal: point.abnormal
            )
        }
        .sorted {
            if $0.date == $1.date { return $0.id < $1.id }
            return $0.date < $1.date
        }
    }

    static func chartWidth(pointCount: Int, viewportWidth: CGFloat) -> CGFloat {
        let viewport = max(viewportWidth, 1)
        guard pointCount > 7 else { return viewport }
        return min(
            max(viewport, horizontalPadding + CGFloat(pointCount - 1) * pointSpacing),
            maximumChartWidth
        )
    }

    static func nearestIndex(to date: Date, in samples: [XAgeMetricTrendSample]) -> Int? {
        guard !samples.isEmpty else { return nil }
        return samples.indices.min { left, right in
            abs(samples[left].date.timeIntervalSince(date))
                < abs(samples[right].date.timeIntervalSince(date))
        }
    }

    static func steppedIndex(currentIndex: Int?, pointCount: Int, delta: Int) -> Int? {
        guard pointCount > 0 else { return nil }
        let current = currentIndex?.clamped(to: 0...(pointCount - 1)) ?? (pointCount - 1)
        return (current + delta).clamped(to: 0...(pointCount - 1))
    }

    private static func date(from point: TrendPoint) -> Date? {
        let raw = point.displayDate.trimmingCharacters(in: .whitespacesAndNewlines)
        if let parsed = dayFormatter.date(from: String(raw.prefix(10))) {
            return parsed
        }
        if let measuredAt = point.measured_at {
            return Utils.parseISO(measuredAt)
        }
        return nil
    }

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private static let fullDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy年M月d日"
        return formatter
    }()
}

struct XAgeMetricTrendView: View {
    let trend: IndicatorTrend?
    let fallbackUnit: String
    let accent: Color

    @State private var selectedID: String?

    private var samples: [XAgeMetricTrendSample] {
        trend.map(XAgeMetricTrendContract.samples(from:)) ?? []
    }

    private var selectedSample: XAgeMetricTrendSample? {
        if let selectedID,
           let selected = samples.first(where: { $0.id == selectedID }) {
            return selected
        }
        return samples.last
    }

    private var unit: String {
        trend?.unit?.trimmingCharacters(in: .whitespacesAndNewlines).nonEmpty ?? fallbackUnit
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("历史趋势")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text("\(samples.count) 个数据点")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Color(hex: "6C8194"))
            }

            if samples.isEmpty {
                emptyState
            } else {
                selectionSummary

                Text("轻点选择；长按拖动查看连续数据；左右滑动查看历史")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color(hex: "6C8194"))

                GeometryReader { geometry in
                    ScrollView(.horizontal, showsIndicators: true) {
                        chart
                            .frame(
                                width: XAgeMetricTrendContract.chartWidth(
                                    pointCount: samples.count,
                                    viewportWidth: geometry.size.width
                                ),
                                height: 204
                            )
                    }
                    .defaultScrollAnchor(.trailing)
                }
                .frame(height: 204)
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(Color.white.opacity(0.7))
                .overlay(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .stroke(Color.white.opacity(0.88), lineWidth: 1)
                )
        )
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(Color(hex: "8AA1B5"))
            Text("暂无可用历史趋势")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "496A83"))
            Text("同步、手动记录或确认报告后再查看；这里不会补造缺失数据。")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: 124)
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var selectionSummary: some View {
        if let selected = selectedSample {
            HStack(spacing: 8) {
                Text(selected.dateLabel)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
                Spacer(minLength: 8)
                Text(selected.displayValue)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(selected.isAbnormal ? .red : accent)
                if !unit.isEmpty {
                    Text(unit)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Color(hex: "70879D"))
                }
                if selected.isAbnormal {
                    Text("异常")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Capsule().fill(.red))
                }
            }
            .padding(.horizontal, 10)
            .frame(minHeight: 38)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(accent.opacity(0.08))
            )
            .accessibilityElement(children: .combine)
            .accessibilityLabel(
                "\(selected.dateLabel)，\(selected.displayValue)\(unit.isEmpty ? "" : " \(unit)")\(selected.isAbnormal ? "，异常" : "")"
            )
        }
    }

    private var chart: some View {
        Chart {
            if let trend,
               let first = samples.first,
               let last = samples.last,
               let low = trend.ref_low,
               let high = trend.ref_high,
               low.isFinite,
               high.isFinite,
               low <= high {
                RectangleMark(
                    xStart: .value("开始", first.date),
                    xEnd: .value("结束", last.date),
                    yStart: .value("参考下限", low),
                    yEnd: .value("参考上限", high)
                )
                .foregroundStyle(.green.opacity(0.08))
            }

            if samples.count >= 2,
               let trend,
               IndicatorTrendPresentationContract.shouldDrawContinuousLine(for: trend) {
                ForEach(samples) { sample in
                    LineMark(
                        x: .value("日期", sample.date),
                        y: .value("数值", sample.value)
                    )
                    .foregroundStyle(accent)
                    .lineStyle(StrokeStyle(lineWidth: 2.2, lineCap: .round, lineJoin: .round))
                }
            }

            ForEach(samples) { sample in
                PointMark(
                    x: .value("日期", sample.date),
                    y: .value("数值", sample.value)
                )
                .foregroundStyle(sample.isAbnormal ? .red : accent)
                .symbolSize(sample.isAbnormal ? 48 : 30)
            }

            if let selected = selectedSample {
                RuleMark(x: .value("当前选择", selected.date))
                    .foregroundStyle(accent.opacity(0.45))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 3]))
                PointMark(
                    x: .value("当前选择", selected.date),
                    y: .value("当前数值", selected.value)
                )
                .foregroundStyle(selected.isAbnormal ? .red : accent)
                .symbolSize(94)
            }
        }
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 5)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.4))
                AxisValueLabel {
                    if let date = value.as(Date.self) {
                        Text(Self.axisDateFormatter.string(from: date))
                            .font(.system(size: 9))
                    }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.35))
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        Text(Self.axisValue(number))
                            .font(.system(size: 9))
                    }
                }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle()
                    .fill(.clear)
                    .contentShape(Rectangle())
                    .simultaneousGesture(
                        SpatialTapGesture().onEnded { tap in
                            select(at: tap.location, proxy: proxy, geometry: geometry)
                        }
                    )
                    .simultaneousGesture(
                        LongPressGesture(minimumDuration: 0.28)
                            .sequenced(before: DragGesture(minimumDistance: 0))
                            .onChanged { phase in
                                if case .second(true, let drag?) = phase {
                                    select(at: drag.location, proxy: proxy, geometry: geometry)
                                }
                            }
                    )
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(chartAccessibilityLabel)
        .accessibilityHint("上下轻扫切换前一个或后一个数据点")
        .accessibilityAdjustableAction { direction in
            adjustSelection(direction)
        }
    }

    private func select(at location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) {
        guard let plotFrame = proxy.plotFrame else { return }
        let frame = geometry[plotFrame]
        let x = location.x - frame.origin.x
        guard x >= 0, x <= frame.width,
              let date: Date = proxy.value(atX: x),
              let index = XAgeMetricTrendContract.nearestIndex(to: date, in: samples) else { return }
        selectedID = samples[index].id
    }

    private func adjustSelection(_ direction: AccessibilityAdjustmentDirection) {
        let currentIndex = selectedSample.flatMap { selected in
            samples.firstIndex(where: { $0.id == selected.id })
        }
        let delta: Int
        switch direction {
        case .increment:
            delta = 1
        case .decrement:
            delta = -1
        @unknown default:
            return
        }
        guard let nextIndex = XAgeMetricTrendContract.steppedIndex(
            currentIndex: currentIndex,
            pointCount: samples.count,
            delta: delta
        ) else { return }
        selectedID = samples[nextIndex].id
    }

    private var chartAccessibilityLabel: String {
        var result = "\(trend?.name ?? "健康指标")趋势图，共\(samples.count)个数据点。"
        if let selected = selectedSample {
            result += "当前选择\(selected.dateLabel)，\(selected.displayValue)"
            if !unit.isEmpty { result += " \(unit)" }
            if selected.isAbnormal { result += "，异常" }
            result += "。"
        }
        return result + "左右滑动查看历史；轻点选择；长按拖动查看连续数据。"
    }

    private static let axisDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = "yy/MM/dd"
        return formatter
    }()

    private static func axisValue(_ value: Double) -> String {
        String(format: "%.2f", value)
            .replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}
