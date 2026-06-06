import SwiftUI

/// 血糖曲线页面 — 对应小程序 pages/glucose/glucose
struct GlucoseView: View {
    @StateObject private var vm = GlucoseViewModel()

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                // 时间窗口切换
                windowTabs

                if let quality = vm.cgmQuality {
                    cgmQualityCard(quality)
                }

                // 统计卡片
                if let summary = vm.summary {
                    summaryCard(summary)
                    glucoseInsightCard(summary)
                }

                // Canvas 图表
                chartCard
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .background(Color.appBackground)
        .navigationTitle("血糖曲线")
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.fetchRange() }
        .refreshable { await vm.fetchPoints() }
        .alert("错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    // MARK: - 时间窗口

    private var windowTabs: some View {
        HStack(spacing: 0) {
            ForEach(["24h", "7d", "all"], id: \.self) { w in
                Button {
                    Task {
                        vm.window = w
                        await vm.fetchPoints()
                    }
                } label: {
                    Text(w == "all" ? "全部" : w == "7d" ? "7 天" : "24h")
                        .font(.subheadline.bold())
                        .foregroundColor(vm.window == w ? .white : .appPrimary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                        .background(vm.window == w ? Color.appPrimary : Color.clear)
                        .cornerRadius(8)
                }
            }
        }
        .padding(4)
        .background(Color.appPrimary.opacity(0.1))
        .cornerRadius(10)
    }

    // MARK: - 统计卡片

    private func summaryCard(_ s: GlucoseSummary) -> some View {
        HStack {
            MetricItemView(value: Utils.formatGlucose(s.avg, withUnit: false), label: "平均 \(Utils.glucoseUnitLabel)")
            Spacer()
            MetricItemView(value: s.tir_70_180_pct != nil ? Utils.toFixed(s.tir_70_180_pct) + "%" : "--", label: "TIR", color: .appSuccess)
            Spacer()
            MetricItemView(value: s.variability ?? "--", label: "变异性")
            Spacer()
            MetricItemView(value: "\(vm.points.count)", label: "数据点")
        }
        .cardStyle()
    }

    private func cgmQualityCard(_ q: CGMQuality) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("CGM 14 天连续数据", systemImage: "sensor.tag.radiowaves.forward")
                    .font(.headline)
                Spacer()
                Text(q.status == "good" ? "良好" : q.status == "watch" ? "有缺口" : "待连接")
                    .font(.caption.bold())
                    .foregroundColor(cgmStatusColor(q.status))
            }
            HStack {
                MetricItemView(value: "\(q.active_days)/\(q.window_days)", label: "有效天数", color: .appPrimary)
                Spacer()
                MetricItemView(value: "\(q.completeness_pct)%", label: "完整率", color: cgmStatusColor(q.status))
                Spacer()
                MetricItemView(value: Utils.toFixed(q.gap_hours), label: "缺口小时")
                Spacer()
                MetricItemView(value: "\(q.reading_count)", label: "读数")
            }
            ProgressView(value: Double(q.completeness_pct), total: 100)
                .tint(cgmStatusColor(q.status))
            Text(q.message)
                .font(.caption)
                .foregroundColor(.appMuted)
        }
        .cardStyle()
    }

    private func cgmStatusColor(_ status: String) -> Color {
        switch status {
        case "good": return .appSuccess
        case "watch": return .orange
        default: return .appMuted
        }
    }

    private func glucoseInsightCard(_ s: GlucoseSummary) -> some View {
        let tir = s.tir_70_180_pct ?? 0
        let tone: Color = tir >= 70 ? .appSuccess : (tir >= 50 ? .appWarning : .appDanger)
        let title = tir >= 70 ? "今天整体较稳" : (tir >= 50 ? "今天需要留意波动" : "今天建议重点复盘")
        let action = tir >= 70
        ? "保持当前饮食和运动节奏，继续记录下一餐。"
        : "优先查看餐后 2 小时和夜间时段，必要时问小捷做一次复盘。"

        return VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 14)
                        .fill(tone.opacity(0.14))
                        .frame(width: 46, height: 46)
                    Image(systemName: tir >= 70 ? "checkmark.seal.fill" : "waveform.path.ecg")
                        .foregroundColor(tone)
                        .font(.title3.bold())
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.headline)
                        .foregroundColor(.appText)
                    Text(action)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
            }
            HStack(spacing: 8) {
                insightChip(label: "平均", value: Utils.formatGlucose(s.avg, withUnit: true), color: .appPrimary)
                insightChip(label: "TIR", value: s.tir_70_180_pct != nil ? Utils.toFixed(tir) + "%" : "--", color: tone)
                insightChip(label: "数据点", value: "\(vm.points.count)", color: .appAccent)
            }
        }
        .cardStyle()
    }

    private func insightChip(label: String, value: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .font(.subheadline.bold())
                .foregroundColor(color)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
            Text(label)
                .font(.caption2)
                .foregroundColor(.appMuted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(color.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    // MARK: - Canvas 图表

    private var chartCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("血糖曲线").font(.headline)

            if vm.loading {
                ProgressView("加载中...")
                    .frame(maxWidth: .infinity, minHeight: 220)
            } else if vm.points.isEmpty {
                Text("暂无血糖数据")
                    .foregroundColor(.appMuted)
                    .frame(maxWidth: .infinity, minHeight: 220)
            } else {
                GlucoseChartCanvas(chartData: vm.chartData, window: vm.window)
                    .frame(height: 240)

                // 图例
                if vm.window == "24h" {
                    HStack(spacing: 10) {
                        legendItem(color: Color.green.opacity(0.15), label: "目标 \(Utils.glucoseThreshold(70))-\(Utils.glucoseThreshold(180))")
                        legendItem(color: .gray, label: "过去")
                        legendItem(color: .appPrimary, label: "当前")
                        legendItem(color: .orange, label: "基线均值")
                    }
                    .font(.caption2)
                } else {
                    HStack(spacing: 16) {
                        legendItem(color: Color.green.opacity(0.15), label: "目标范围 \(Utils.glucoseThreshold(70))-\(Utils.glucoseThreshold(180)) \(Utils.glucoseUnitLabel)")
                        legendItem(color: .appPrimary, label: "血糖值")
                    }
                    .font(.caption2)
                }
            }
        }
        .cardStyle()
    }

    private func legendItem(color: Color, label: String) -> some View {
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(label).foregroundColor(.appMuted)
        }
    }
}

// MARK: - 血糖图表 Canvas (对应 glucose.js 的 drawChart)

struct GlucoseChartCanvas: View {
    let chartData: [(date: Date, value: Double)]
    var window: String = "24h"

    var body: some View {
        GeometryReader { geo in
            Canvas { ctx, size in
                let w = size.width
                let h = size.height
                let padLeft = ChartConstants.padLeft
                let padRight = ChartConstants.padRight
                let padTop = ChartConstants.padTop
                let padBottom = ChartConstants.padBottom
                let chartW = w - padLeft - padRight
                let chartH = h - padTop - padBottom

                let values = chartData.map { $0.value }
                let minVal = min(values.min() ?? 50, 50)
                let maxVal = max(values.max() ?? 200, 200)
                let valRange = maxVal - minVal == 0 ? 1 : maxVal - minVal

                // 目标范围背景
                let y180 = padTop + chartH * (1 - (ChartConstants.targetHigh - minVal) / valRange)
                let y70 = padTop + chartH * (1 - (ChartConstants.targetLow - minVal) / valRange)
                let targetRect = CGRect(
                    x: padLeft,
                    y: max(y180, padTop),
                    width: chartW,
                    height: min(y70 - y180, chartH)
                )
                ctx.fill(Path(targetRect), with: .color(.green.opacity(0.08)))

                // Y 轴参考线（标签按用户血糖单位渲染）
                for refVal in ChartConstants.refLines {
                    let y = padTop + chartH * (1 - (refVal - minVal) / valRange)
                    var linePath = Path()
                    linePath.move(to: CGPoint(x: padLeft, y: y))
                    linePath.addLine(to: CGPoint(x: w - padRight, y: y))
                    ctx.stroke(linePath, with: .color(.gray.opacity(0.3)), style: StrokeStyle(lineWidth: 0.5, dash: [4, 4]))
                    ctx.draw(Text(Utils.glucoseThreshold(refVal)).font(.system(size: ChartConstants.labelFontSize)).foregroundColor(.gray), at: CGPoint(x: 18, y: y))
                }

                guard chartData.count > 1 else { return }
                let timestamps = chartData.map { $0.date.timeIntervalSince1970 }
                let minT = timestamps.min() ?? 0
                let maxT = timestamps.max() ?? 1
                let tRange = maxT - minT == 0 ? 1 : maxT - minT

                // X 轴时间标签
                let tickCount = window == "24h" ? 6 : (window == "7d" ? 7 : 5)
                let timeFmt = DateFormatter()
                timeFmt.dateFormat = window == "24h" ? "HH:mm" : "M/d"
                for i in 0...tickCount {
                    let frac = Double(i) / Double(tickCount)
                    let x = padLeft + chartW * CGFloat(frac)
                    let tickDate = Date(timeIntervalSince1970: minT + tRange * frac)
                    ctx.draw(
                        Text(timeFmt.string(from: tickDate))
                            .font(.system(size: ChartConstants.labelFontSize))
                            .foregroundColor(.gray),
                        at: CGPoint(x: x, y: h - 6)
                    )
                }

                // 数据点 → 画布坐标
                func pointAt(_ i: Int) -> CGPoint {
                    let x = padLeft + chartW * CGFloat((timestamps[i] - minT) / tRange)
                    let y = padTop + chartH * CGFloat(1 - (chartData[i].value - minVal) / valRange)
                    return CGPoint(x: x, y: y)
                }

                if window == "24h" {
                    // 基线均值 — 橘色虚线
                    let avgVal = values.reduce(0, +) / Double(values.count)
                    let yAvg = padTop + chartH * CGFloat(1 - (avgVal - minVal) / valRange)
                    var baselinePath = Path()
                    baselinePath.move(to: CGPoint(x: padLeft, y: yAvg))
                    baselinePath.addLine(to: CGPoint(x: w - padRight, y: yAvg))
                    ctx.stroke(baselinePath, with: .color(.orange), style: StrokeStyle(lineWidth: 1, dash: [6, 4]))
                    ctx.draw(
                        Text("\(Int(avgVal))").font(.system(size: ChartConstants.labelFontSize)).foregroundColor(.orange),
                        at: CGPoint(x: 18, y: yAvg)
                    )

                    // 按 12 小时分割: 过去 / 当前
                    let boundary = Date().addingTimeInterval(-12 * 3600).timeIntervalSince1970
                    let splitIdx = timestamps.firstIndex { $0 >= boundary } ?? chartData.count

                    // 过去段 — 灰色
                    if splitIdx > 0 {
                        var pastPath = Path()
                        pastPath.move(to: pointAt(0))
                        for i in 1..<min(splitIdx + 1, chartData.count) {
                            pastPath.addLine(to: pointAt(i))
                        }
                        ctx.stroke(pastPath, with: .color(.gray), lineWidth: ChartConstants.lineWidth)
                    }

                    // 当前段 — 蓝色加粗
                    let startIdx = splitIdx > 0 ? splitIdx - 1 : 0
                    if startIdx < chartData.count - 1 {
                        var curPath = Path()
                        curPath.move(to: pointAt(startIdx))
                        for i in (startIdx + 1)..<chartData.count {
                            curPath.addLine(to: pointAt(i))
                        }
                        ctx.stroke(curPath, with: .color(.appPrimary), lineWidth: ChartConstants.lineWidth + 0.5)
                    }
                } else {
                    // 7d / 全部 — 单色曲线
                    var curvePath = Path()
                    for i in chartData.indices {
                        let pt = pointAt(i)
                        if i == 0 { curvePath.move(to: pt) }
                        else { curvePath.addLine(to: pt) }
                    }
                    ctx.stroke(curvePath, with: .color(.appPrimary), lineWidth: ChartConstants.lineWidth)
                }
            }
        }
    }
}
