import SwiftUI
import Charts

// MARK: - 指标趋势图卡片

enum IndicatorTrendPresentationContract {
    static func shouldDrawContinuousLine(for trend: IndicatorTrend) -> Bool {
        !trend.points.contains(where: \.isCategoricalValue)
    }

    static func displayValue(for point: TrendPoint, indicatorName: String) -> String {
        if let displayValue = point.preferredDisplayValue {
            return displayValue
        }
        if let categoryValue = XAgeHealthMetricRegistryContract.categoryDisplayValue(
            forIndicatorName: indicatorName,
            value: point.value
        ) {
            return categoryValue
        }
        if point.value.rounded() == point.value {
            return String(Int(point.value))
        }
        return String(format: "%.2f", point.value)
            .replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }
}

struct IndicatorTrendCard: View {
    let trend: IndicatorTrend
    @ObservedObject var vm: IndicatorTrendViewModel
    @State private var selectedIndex: Int? = nil
    @State private var showExplanation = false

    private var dateFormatter: DateFormatter {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }

    private var displayFormatter: DateFormatter {
        let f = DateFormatter()
        f.dateFormat = "yy/MM"
        return f
    }

    private var detailFormatter: DateFormatter {
        let f = DateFormatter()
        f.dateFormat = "yyyy年M月d日"
        return f
    }

    private var isCategoricalTrend: Bool {
        !IndicatorTrendPresentationContract.shouldDrawContinuousLine(for: trend)
    }

    private var orderedPoints: [TrendPoint] {
        trend.points.sorted {
            pointSortDate($0) < pointSortDate($1)
        }
    }

    private var latestPoint: TrendPoint? {
        orderedPoints.last
    }

    private var validReferenceRange: (low: Double, high: Double)? {
        guard let low = trend.ref_low,
              let high = trend.ref_high,
              low.isFinite,
              high.isFinite,
              low <= high else { return nil }
        return (low, high)
    }

    private var chartPoints: [(date: Date, value: Double, abnormal: Bool, displayValue: String)] {
        orderedPoints.compactMap { point in
            guard let date = chartDate(point.displayDate) else { return nil }
            return (
                date: date,
                value: point.value,
                abnormal: point.abnormal,
                displayValue: IndicatorTrendPresentationContract.displayValue(
                    for: point,
                    indicatorName: trend.name
                )
            )
        }
    }

    private func chartDate(_ raw: String) -> Date? {
        if let date = dateFormatter.date(from: raw) {
            return date
        }
        guard raw.count >= 10 else { return nil }
        return dateFormatter.date(from: String(raw.prefix(10)))
    }

    private func pointSortDate(_ point: TrendPoint) -> Date {
        if let localDay = chartDate(point.displayDate) {
            return localDay
        }
        if let measuredAt = point.measured_at,
           let measuredDate = Utils.parseISO(measuredAt) {
            return measuredDate
        }
        return .distantPast
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header
            HStack {
                Text(trend.name)
                    .font(.subheadline.bold())
                if !isCategoricalTrend, let unit = trend.unit, !unit.isEmpty {
                    Text("(\(unit))")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Button {
                    showExplanation.toggle()
                    if showExplanation {
                        Task { await vm.fetchExplanation(for: trend.name) }
                    }
                } label: {
                    Image(systemName: "info.circle")
                        .font(.caption)
                        .foregroundColor(.appPrimary)
                }
                Spacer()
                if let last = latestPoint {
                    Text(IndicatorTrendPresentationContract.displayValue(for: last, indicatorName: trend.name))
                        .font(.subheadline.bold())
                        .foregroundColor(last.abnormal ? .red : .appPrimary)
                }
            }

            // Explanation
            if showExplanation {
                if let exp = vm.explanations[trend.name] {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(exp.brief)
                            .font(.caption)
                            .foregroundColor(.appText)
                        if let range = exp.normal_range, !range.isEmpty {
                            Text("参考范围: \(range)")
                                .font(.caption2)
                                .foregroundColor(.appMuted)
                        }
                        if let meaning = exp.clinical_meaning, !meaning.isEmpty {
                            Text(meaning)
                                .font(.caption2)
                                .foregroundColor(.appMuted)
                        }
                    }
                    .padding(8)
                    .background(Color.appPrimary.opacity(0.05))
                    .cornerRadius(6)
                } else {
                    HStack {
                        ProgressView().controlSize(.small)
                        Text("加载解释中...").font(.caption).foregroundColor(.appMuted)
                    }
                }
            }

            // Categorical HealthKit samples are discrete events. Showing them as
            // a numeric line would imply an order and interpolation that do not exist.
            if isCategoricalTrend {
                categoryEventTimeline
            } else if chartPoints.count >= 2 {
                GeometryReader { viewport in
                    ScrollView(.horizontal, showsIndicators: true) {
                        Chart {
                    // Reference range band
                    if let range = validReferenceRange {
                        RectangleMark(
                            xStart: .value("start", chartPoints.first!.date),
                            xEnd: .value("end", chartPoints.last!.date),
                            yStart: .value("low", range.low),
                            yEnd: .value("high", range.high)
                        )
                        .foregroundStyle(.green.opacity(0.08))
                    }

                    // Reference lines
                    if let range = validReferenceRange {
                        RuleMark(y: .value("上限", range.high))
                            .lineStyle(StrokeStyle(lineWidth: 0.5, dash: [4, 4]))
                            .foregroundStyle(.red.opacity(0.4))
                            .annotation(position: .trailing, alignment: .leading) {
                                Text("上限")
                                    .font(.system(size: 8))
                                    .foregroundColor(.red.opacity(0.5))
                            }
                    }
                    if let range = validReferenceRange {
                        RuleMark(y: .value("下限", range.low))
                            .lineStyle(StrokeStyle(lineWidth: 0.5, dash: [4, 4]))
                            .foregroundStyle(.blue.opacity(0.4))
                            .annotation(position: .trailing, alignment: .leading) {
                                Text("下限")
                                    .font(.system(size: 8))
                                    .foregroundColor(.blue.opacity(0.5))
                            }
                    }

                    // Line
                    ForEach(Array(chartPoints.enumerated()), id: \.offset) { _, pt in
                        LineMark(
                            x: .value("日期", pt.date),
                            y: .value("数值", pt.value)
                        )
                        .foregroundStyle(Color.appPrimary)
                        .lineStyle(StrokeStyle(lineWidth: 2))
                    }

                    // Points
                    ForEach(Array(chartPoints.enumerated()), id: \.offset) { _, pt in
                        PointMark(
                            x: .value("日期", pt.date),
                            y: .value("数值", pt.value)
                        )
                        .foregroundStyle(pt.abnormal ? .red : Color.appPrimary)
                        .symbolSize(pt.abnormal ? 40 : 24)
                    }

                    // Selection indicator
                    if let idx = selectedIndex, idx < chartPoints.count {
                        let sel = chartPoints[idx]
                        RuleMark(x: .value("选中", sel.date))
                            .lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
                            .foregroundStyle(.gray.opacity(0.6))
                        PointMark(
                            x: .value("选中", sel.date),
                            y: .value("选中值", sel.value)
                        )
                        .foregroundStyle(sel.abnormal ? .red : Color.appPrimary)
                        .symbolSize(80)
                        .annotation(position: .automatic, spacing: 6) {
                                let color: Color = sel.abnormal ? .red : .appPrimary
                                VStack(spacing: 2) {
                                    Text(detailFormatter.string(from: sel.date))
                                        .font(.system(size: 11))
                                        .foregroundColor(color)
                                    HStack(spacing: 2) {
                                        Text(sel.displayValue)
                                            .font(.system(size: 13, weight: .semibold))
                                            .foregroundColor(color)
                                        if let unit = trend.unit, !unit.isEmpty {
                                            Text(unit)
                                                .font(.system(size: 10))
                                                .foregroundColor(color)
                                        }
                                    }
                                    if sel.abnormal {
                                        Text("异常")
                                            .font(.system(size: 9, weight: .medium))
                                            .foregroundColor(.white)
                                            .padding(.horizontal, 4)
                                            .padding(.vertical, 1)
                                            .background(Capsule().fill(.red))
                                    }
                                }
                                .padding(6)
                                .background(
                                    RoundedRectangle(cornerRadius: 6)
                                        .fill(.ultraThinMaterial)
                                        .shadow(color: .black.opacity(0.1), radius: 2, y: 1)
                                )
                            }
                    }
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: 5)) { value in
                        AxisValueLabel {
                            if let d = value.as(Date.self) {
                                Text(displayFormatter.string(from: d))
                                    .font(.system(size: 9))
                            }
                        }
                        AxisGridLine()
                    }
                }
                .chartYAxis {
                    AxisMarks(position: .leading) { value in
                        AxisValueLabel {
                            if let v = value.as(Double.self) {
                                Text(String(format: "%.1f", v))
                                    .font(.system(size: 9))
                            }
                        }
                        AxisGridLine(stroke: StrokeStyle(lineWidth: 0.3))
                    }
                }
                        .frame(
                            width: XAgeMetricTrendContract.chartWidth(
                                pointCount: chartPoints.count,
                                viewportWidth: viewport.size.width
                            ),
                            height: 160
                        )
                .chartOverlay { proxy in
                    GeometryReader { geo in
                        Rectangle()
                            .fill(.clear)
                            .contentShape(Rectangle())
                            .simultaneousGesture(
                                SpatialTapGesture().onEnded { tap in
                                    selectChartPoint(at: tap.location, proxy: proxy, geometry: geo)
                                }
                            )
                            .simultaneousGesture(
                                LongPressGesture(minimumDuration: 0.28)
                                    .sequenced(before: DragGesture(minimumDistance: 0))
                                    .onChanged { phase in
                                        if case .second(true, let drag?) = phase {
                                            selectChartPoint(at: drag.location, proxy: proxy, geometry: geo)
                                        }
                                    }
                            )
                    }
                }
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(numericChartAccessibilityLabel)
                        .accessibilityHint("上下轻扫切换前一个或后一个数据点")
                        .accessibilityAdjustableAction { direction in
                            adjustChartSelection(direction)
                        }
                    }
                    .defaultScrollAnchor(.trailing)
                }
                .frame(height: 160)
            } else {
                XAgeMetricTrendView(
                    trend: trend,
                    fallbackUnit: trend.unit ?? "",
                    accent: .appPrimary
                )
            }

            // Data point count
            HStack {
                Image(systemName: isCategoricalTrend ? "list.bullet.rectangle" : "chart.line.uptrend.xyaxis")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                Text(isCategoricalTrend ? "\(trend.points.count) 条健康事件" : "\(trend.points.count) 个数据点")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                Spacer()
                if let first = orderedPoints.first, let last = orderedPoints.last {
                    Text("\(first.displayDate) → \(last.displayDate)")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
            }
        }
        .padding(12)
        .background(Color(.systemBackground))
        .cornerRadius(12)
        .shadow(color: .black.opacity(0.05), radius: 4, y: 2)
    }

    private func selectChartPoint(at location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) {
        guard let plotFrame = proxy.plotFrame else { return }
        let frame = geometry[plotFrame]
        let x = location.x - frame.origin.x
        guard x >= 0, x <= frame.width,
              let date: Date = proxy.value(atX: x) else { return }
        selectedIndex = chartPoints.indices.min { left, right in
            abs(chartPoints[left].date.timeIntervalSince(date))
                < abs(chartPoints[right].date.timeIntervalSince(date))
        }
    }

    private func adjustChartSelection(_ direction: AccessibilityAdjustmentDirection) {
        let delta: Int
        switch direction {
        case .increment: delta = 1
        case .decrement: delta = -1
        @unknown default: return
        }
        selectedIndex = XAgeMetricTrendContract.steppedIndex(
            currentIndex: selectedIndex,
            pointCount: chartPoints.count,
            delta: delta
        )
    }

    private var numericChartAccessibilityLabel: String {
        let index = selectedIndex ?? chartPoints.indices.last
        guard let index, chartPoints.indices.contains(index) else {
            return "\(trend.name)趋势图，暂无可用数据"
        }
        let point = chartPoints[index]
        let unit = trend.unit?.isEmpty == false ? " \(trend.unit!)" : ""
        return "\(trend.name)趋势图，共\(chartPoints.count)个数据点。当前选择\(detailFormatter.string(from: point.date))，\(point.displayValue)\(unit)\(point.abnormal ? "，异常" : "")"
    }

    private var categoryEventTimeline: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: 10) {
                ForEach(orderedPoints) { point in
                    VStack(alignment: .leading, spacing: 7) {
                        Text(point.displayDate)
                            .font(.caption2)
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                        Text(IndicatorTrendPresentationContract.displayValue(for: point, indicatorName: trend.name))
                            .font(.caption.weight(.semibold))
                            .foregroundColor(point.abnormal ? .red : .appPrimary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                        if point.abnormal {
                            Text("异常")
                                .font(.system(size: 9, weight: .medium))
                                .foregroundColor(.white)
                                .padding(.horizontal, 5)
                                .padding(.vertical, 2)
                                .background(Capsule().fill(.red))
                        }
                    }
                    .frame(width: 112, alignment: .leading)
                    .padding(10)
                    .background(
                        RoundedRectangle(cornerRadius: 9)
                            .fill((point.abnormal ? Color.red : Color.appPrimary).opacity(0.08))
                    )
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(
                        "\(point.displayDate)，\(IndicatorTrendPresentationContract.displayValue(for: point, indicatorName: trend.name))"
                    )
                }
            }
            .padding(.vertical, 2)
        }
        .frame(minHeight: 88)
    }
}

// MARK: - 指标选择器

struct IndicatorSelectorSheet: View {
    @ObservedObject var vm: IndicatorTrendViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var pendingNames: Set<String> = []

    // Group indicators by category
    private var grouped: [(String, [IndicatorInfo])] {
        var dict: [String: [IndicatorInfo]] = [:]
        for ind in vm.allIndicators {
            let cat = ind.category ?? "其他"
            dict[cat, default: []].append(ind)
        }
        return dict.sorted { $0.key < $1.key }
    }

    var body: some View {
        NavigationStack {
            Group {
                if vm.allIndicators.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "info.circle")
                            .font(.system(size: 36))
                            .foregroundColor(.secondary)
                        Text("还没有可关注的指标")
                            .font(.headline)
                        Text("请先在「健康数据」页面上传体检报告（PDF / 图片）。\nAI 识别完成后，带有数值的指标（如 ALT、血糖、胆固醇等）会自动出现在这里。")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 24)
                        Text("提示：「偏高/偏低」等定性描述不计入趋势，只有数值型结果才会进入指标库。")
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 32)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List {
                        ForEach(grouped, id: \.0) { category, indicators in
                            Section(category) {
                                ForEach(indicators) { ind in
                                    Button {
                                        if pendingNames.contains(ind.name) {
                                            pendingNames.remove(ind.name)
                                        } else {
                                            pendingNames.insert(ind.name)
                                        }
                                    } label: {
                                        HStack {
                                            Image(systemName: pendingNames.contains(ind.name) ? "checkmark.circle.fill" : "circle")
                                                .foregroundColor(pendingNames.contains(ind.name) ? .appPrimary : .secondary)
                                            Text(ind.name)
                                                .foregroundColor(.primary)
                                            Spacer()
                                            Text("\(ind.count)次")
                                                .font(.caption)
                                                .foregroundColor(.secondary)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("选择关注指标")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") {
                        Task { await vm.applySelection(pendingNames) }
                        dismiss()
                    }
                }
            }
        }
        .onAppear {
            pendingNames = Set(vm.watchedNames)
        }
    }
}

// MARK: - 指标趋势区域（嵌入 HealthView）

struct IndicatorTrendSection: View {
    @ObservedObject var vm: IndicatorTrendViewModel
    @State private var showSelector = false
    @State private var showManual = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Section header
            HStack {
                Label("关注指标趋势", systemImage: "chart.line.uptrend.xyaxis")
                    .font(.headline)
                Spacer()
                Button {
                    showManual = true
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "plus.circle.fill")
                        Text("手动录入")
                    }
                    .font(.caption)
                    .foregroundColor(.appPrimary)
                }
                Button {
                    showSelector = true
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "slider.horizontal.3")
                        Text("管理")
                    }
                    .font(.caption)
                    .foregroundColor(.appPrimary)
                }
            }
            .sheet(isPresented: $showManual) {
                ManualIndicatorSheet { Task { await vm.fetchIndicators() } }
            }

            if vm.trendLoading {
                ProgressView("加载趋势数据...")
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 20)
            } else if vm.trends.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "chart.line.uptrend.xyaxis")
                        .font(.title2)
                        .foregroundColor(.secondary)
                    Text("暂未关注任何指标")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                    Button("添加关注指标") {
                        showSelector = true
                    }
                    .font(.caption)
                    .foregroundColor(.appPrimary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 20)
            } else {
                ForEach(vm.trends) { trend in
                    IndicatorTrendCard(trend: trend, vm: vm)
                }
            }
        }
        .sheet(isPresented: $showSelector) {
            IndicatorSelectorSheet(vm: vm)
        }
    }
}
