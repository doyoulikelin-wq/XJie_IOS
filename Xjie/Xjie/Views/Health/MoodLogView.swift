import Charts
import SwiftUI

/// C4 — 情绪 emoji 5 时段打卡 + 与血糖叠加视图
struct MoodLogView: View {
    @StateObject private var vm = MoodViewModel()

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                todayCard
                trendCard
                if let corr = vm.correlation {
                    correlationCard(corr)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .background(Color.appBackground)
        .navigationTitle("情绪日记")
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.refresh() }
        .refreshable { await vm.refresh() }
        .overlay {
            if vm.loading && vm.days.isEmpty {
                ProgressView("加载中...")
            }
        }
        .alert("出错了", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("好", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    // MARK: - Today's check-in

    private var todayCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("今日打卡", systemImage: "face.smiling")
                    .font(.headline)
                Spacer()
                if vm.saving {
                    ProgressView().controlSize(.small)
                }
            }
            Text("点击对应时段的 emoji 完成打卡，可重复点击修改")
                .font(.caption)
                .foregroundColor(.appMuted)

            ForEach(MoodSegment.allCases) { segment in
                segmentRow(segment)
            }
        }
        .cardStyle()
    }

    private func segmentRow(_ segment: MoodSegment) -> some View {
        let current = vm.today?.level(for: segment)
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(segment.label).font(.subheadline.bold())
                Text(segment.window).font(.caption2).foregroundColor(.appMuted)
                Spacer()
                if let v = current, let lvl = MoodLevel(rawValue: v) {
                    Text(lvl.emoji)
                        .font(.title3)
                }
            }
            HStack(spacing: 10) {
                ForEach(MoodLevel.allCases) { lvl in
                    Button {
                        Task { await vm.checkIn(segment: segment, level: lvl) }
                    } label: {
                        Text(lvl.emoji)
                            .font(.system(size: 24))
                            .frame(maxWidth: .infinity, minHeight: 36)
                            .background(
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(current == lvl.rawValue
                                          ? Color.appPrimary.opacity(0.18)
                                          : Color.appBackground)
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: 8)
                                    .stroke(current == lvl.rawValue
                                            ? Color.appPrimary
                                            : Color.gray.opacity(0.2),
                                            lineWidth: current == lvl.rawValue ? 1.5 : 1)
                            )
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(segment.label) \(lvl.label)")
                }
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Trend chart

    private var trendCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("近 \(vm.lookbackDays) 天情绪曲线", systemImage: "chart.line.uptrend.xyaxis")
                    .font(.headline)
                Spacer()
                Picker("窗口", selection: $vm.lookbackDays) {
                    Text("7 天").tag(7)
                    Text("14 天").tag(14)
                    Text("30 天").tag(30)
                }
                .pickerStyle(.segmented)
                .frame(width: 200)
                .onChange(of: vm.lookbackDays) { _, _ in
                    Task { await vm.refresh() }
                }
            }

            if chartPoints.isEmpty {
                EmptyStateView(
                    icon: "face.dashed",
                    title: "暂无打卡数据",
                    subtitle: "打卡几天后即可看到情绪走势"
                )
                .frame(height: 160)
            } else {
                Chart {
                    ForEach(chartPoints, id: \.id) { p in
                        LineMark(
                            x: .value("日期", p.date),
                            y: .value("情绪", p.avg)
                        )
                        .foregroundStyle(Color.appPrimary)
                        .interpolationMethod(.monotone)
                        PointMark(
                            x: .value("日期", p.date),
                            y: .value("情绪", p.avg)
                        )
                        .foregroundStyle(Color.appPrimary)
                        .symbolSize(40)
                    }
                }
                .chartYScale(domain: 1...5)
                .chartYAxis {
                    AxisMarks(position: .leading, values: [1, 2, 3, 4, 5]) { v in
                        AxisGridLine()
                        AxisValueLabel {
                            if let raw = v.as(Int.self), let lvl = MoodLevel(rawValue: raw) {
                                Text(lvl.emoji).font(.caption)
                            }
                        }
                    }
                }
                .frame(height: 180)
            }

            // Heatmap-like 5×N grid showing each segment per day
            heatmapGrid
        }
        .cardStyle()
    }

    private struct ChartPoint: Identifiable {
        let id = UUID()
        let date: Date
        let avg: Double
    }

    private var chartPoints: [ChartPoint] {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = .current
        return vm.days.compactMap { day in
            guard let avg = day.avg, let d = f.date(from: day.date) else { return nil }
            return ChartPoint(date: d, avg: avg)
        }
    }

    private var heatmapGrid: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("时段细览").font(.caption).foregroundColor(.appMuted)
            ForEach(MoodSegment.allCases) { segment in
                HStack(spacing: 3) {
                    Text(segment.label)
                        .font(.caption2)
                        .frame(width: 32, alignment: .leading)
                        .foregroundColor(.appMuted)
                    ForEach(vm.days) { day in
                        let v = day.level(for: segment)
                        Text(v.flatMap { MoodLevel(rawValue: $0)?.emoji } ?? "·")
                            .font(.system(size: 13))
                            .frame(maxWidth: .infinity, minHeight: 18)
                            .background(
                                RoundedRectangle(cornerRadius: 3)
                                    .fill(v == nil ? Color.gray.opacity(0.06) : Color.appPrimary.opacity(0.08))
                            )
                    }
                }
            }
        }
        .padding(.top, 6)
    }

    // MARK: - Correlation card

    private func correlationCard(_ corr: MoodGlucoseCorrelation) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("情绪 × 血糖耦合度", systemImage: "waveform.path.ecg")
                .font(.headline)
            HStack(spacing: 16) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Pearson r")
                        .font(.caption2).foregroundColor(.appMuted)
                    Text(corr.pearson_r.map { String(format: "%.2f", $0) } ?? "—")
                        .font(.title3.bold())
                        .foregroundColor(.appPrimary)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text("配对样本")
                        .font(.caption2).foregroundColor(.appMuted)
                    Text("\(corr.paired_samples)")
                        .font(.title3.bold())
                }
                if let p = corr.p_value {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("p")
                            .font(.caption2).foregroundColor(.appMuted)
                        Text(String(format: "%.3f", p))
                            .font(.title3.bold())
                    }
                }
                Spacer()
            }
            Text(corr.interpretation)
                .font(.subheadline)
                .foregroundColor(.appText)
            Text("基于近 \(corr.days) 天的情绪打卡与同时段平均血糖计算，仅供参考。")
                .font(.caption2)
                .foregroundColor(.appMuted)
        }
        .cardStyle()
    }
}

#Preview {
    NavigationStack { MoodLogView() }
}
