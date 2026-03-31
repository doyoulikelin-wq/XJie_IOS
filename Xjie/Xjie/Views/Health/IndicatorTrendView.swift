import SwiftUI
import Charts

// MARK: - 指标趋势图卡片

struct IndicatorTrendCard: View {
    let trend: IndicatorTrend

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
                Spacer()
                if let last = trend.points.last {
                    Text(String(format: "%.1f", last.value))
                        .font(.subheadline.bold())
                        .foregroundColor(last.abnormal ? .red : .appPrimary)
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
            List {
                ForEach(grouped, id: \.0) { category, indicators in
                    Section(category) {
                        ForEach(indicators) { ind in
                            Button {
                                Task {
                                    if vm.watchedNames.contains(ind.name) {
                                        await vm.unwatch(ind.name)
                                    } else {
                                        await vm.watch(ind.name, category: ind.category)
                                    }
                                }
                            } label: {
                                HStack {
                                    Image(systemName: vm.watchedNames.contains(ind.name) ? "checkmark.circle.fill" : "circle")
                                        .foregroundColor(vm.watchedNames.contains(ind.name) ? .appPrimary : .secondary)
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
            .navigationTitle("选择关注指标")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
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
                    IndicatorTrendCard(trend: trend)
                }
            }
        }
        .sheet(isPresented: $showSelector) {
            IndicatorSelectorSheet(vm: vm)
        }
    }
}
