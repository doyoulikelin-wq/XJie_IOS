import SwiftUI
import Charts

// MARK: - 指标趋势图卡片

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

    private var chartPoints: [(date: Date, value: Double, abnormal: Bool)] {
        trend.points.compactMap { p in
            guard let d = dateFormatter.date(from: p.date) else { return nil }
            return (date: d, value: p.value, abnormal: p.abnormal)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header
            HStack {
                Text(trend.name)
                    .font(.subheadline.bold())
                if let unit = trend.unit, !unit.isEmpty {
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
                if let last = trend.points.last {
                    Text(String(format: "%.1f", last.value))
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

            // Chart
            if chartPoints.count >= 2 {
                Chart {
                    // Reference range band
                    if let low = trend.ref_low, let high = trend.ref_high {
                        RectangleMark(
                            xStart: .value("start", chartPoints.first!.date),
                            xEnd: .value("end", chartPoints.last!.date),
                            yStart: .value("low", low),
                            yEnd: .value("high", high)
                        )
                        .foregroundStyle(.green.opacity(0.08))
                    }

                    // Reference lines
                    if let high = trend.ref_high {
                        RuleMark(y: .value("上限", high))
                            .lineStyle(StrokeStyle(lineWidth: 0.5, dash: [4, 4]))
                            .foregroundStyle(.red.opacity(0.4))
                            .annotation(position: .trailing, alignment: .leading) {
                                Text("上限")
                                    .font(.system(size: 8))
                                    .foregroundColor(.red.opacity(0.5))
                            }
                    }
                    if let low = trend.ref_low {
                        RuleMark(y: .value("下限", low))
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
                                        Text(String(format: "%.2f", sel.value))
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
                .frame(height: 160)
                .chartOverlay { proxy in
                    GeometryReader { geo in
                        Rectangle()
                            .fill(.clear)
                            .contentShape(Rectangle())
                            .gesture(
                                DragGesture(minimumDistance: 0)
                                    .onChanged { drag in
                                        let origin = geo[proxy.plotFrame!].origin
                                        let x = drag.location.x - origin.x
                                        guard let date: Date = proxy.value(atX: x) else { return }
                                        // Find nearest point
                                        var nearest = 0
                                        var minDist = Double.infinity
                                        for (i, pt) in chartPoints.enumerated() {
                                            let dist = abs(pt.date.timeIntervalSince(date))
                                            if dist < minDist {
                                                minDist = dist
                                                nearest = i
                                            }
                                        }
                                        selectedIndex = nearest
                                    }
                                    .onEnded { _ in
                                        // Keep selection visible; tap outside to dismiss
                                    }
                            )
                            .onTapGesture {
                                selectedIndex = nil
                            }
                    }
                }
            } else {
                Text("数据点不足，无法绘制趋势图")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .frame(height: 80)
                    .frame(maxWidth: .infinity)
            }

            // Data point count
            HStack {
                Image(systemName: "chart.line.uptrend.xyaxis")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                Text("\(trend.points.count) 个数据点")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                Spacer()
                if let first = trend.points.first, let last = trend.points.last {
                    Text("\(first.date) → \(last.date)")
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

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Section header
            HStack {
                Label("关注指标趋势", systemImage: "chart.line.uptrend.xyaxis")
                    .font(.headline)
                Spacer()
                Button {
                    showSelector = true
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "plus.circle")
                        Text("管理")
                    }
                    .font(.caption)
                    .foregroundColor(.appPrimary)
                }
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
