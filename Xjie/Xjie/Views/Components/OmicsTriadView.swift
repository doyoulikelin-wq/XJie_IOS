import SwiftUI

/// 三系统联动视图 — 替代之前难以理解的"三圆交叠 + 粒子"。
/// 设计原则：
/// - 三个并排的健康度卡片（代谢 / 血糖 / 心率），数值越大越健康
/// - 中间用箭头表达"代谢 → 血糖 → 心率"的影响传递
/// - 顶部一个清晰的"耦合度"百分比条，告诉用户三系统是否同时偏离
/// - 不再用花哨粒子或交叠圆，所有数字都直接可读
struct OmicsTriadView: View {
    let insight: OmicsTriadInsight
    @State private var appeared = false

    /// 后端 score: 0-1，越高越异常 → 转换为"健康度"（百分制，越高越健康）
    private func healthFor(_ score: Double) -> Int {
        Int((1.0 - score).clamped(to: 0...1) * 100)
    }
    private var couplingPct: Int {
        // overlap_score 是三者最小值，最小说明三者同时偏离
        Int(insight.overlap_score * 100)
    }
    private var couplingColor: Color {
        if couplingPct < 25 { return .green }
        if couplingPct < 50 { return .orange }
        return .red
    }
    private var couplingHint: String {
        if couplingPct < 25 { return "三系统协调良好，无明显共同偏离" }
        if couplingPct < 50 { return "三系统出现部分共同偏离，建议关注" }
        return "三系统同时偏离明显，建议尽快干预"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            // ── 耦合度概览
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("三系统耦合度")
                        .font(.subheadline.bold())
                    Spacer()
                    Text("\(couplingPct)%")
                        .font(.headline)
                        .foregroundColor(couplingColor)
                }
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 4)
                            .fill(Color.gray.opacity(0.12))
                        RoundedRectangle(cornerRadius: 4)
                            .fill(couplingColor.opacity(0.85))
                            .frame(width: appeared ? geo.size.width * CGFloat(couplingPct) / 100.0 : 0)
                            .animation(.easeOut(duration: 0.7), value: appeared)
                    }
                }
                .frame(height: 8)
                Text(couplingHint)
                    .font(.caption2)
                    .foregroundColor(.appMuted)
            }

            // ── 三系统并排
            HStack(spacing: 0) {
                SystemTile(
                    title: "代谢",
                    icon: "flask.fill",
                    color: .appPrimary,
                    health: healthFor(insight.metabolomics_score)
                )
                ConnectorArrow()
                SystemTile(
                    title: "血糖",
                    icon: "drop.fill",
                    color: .orange,
                    health: healthFor(insight.cgm_score)
                )
                ConnectorArrow()
                SystemTile(
                    title: "心率",
                    icon: "heart.fill",
                    color: .pink,
                    health: healthFor(insight.heart_score)
                )
            }

            // ── 联动洞察
            if !insight.insights.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("联动洞察")
                        .font(.subheadline.bold())
                    ForEach(Array(insight.insights.enumerated()), id: \.offset) { _, text in
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "lightbulb.fill")
                                .foregroundColor(.appPrimary)
                                .font(.caption)
                                .padding(.top, 2)
                            Text(text)
                                .font(.subheadline)
                                .foregroundColor(.appText)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.appPrimary.opacity(0.06))
                        .cornerRadius(8)
                    }
                }
            }
        }
        .onAppear { appeared = true }
    }
}

private struct SystemTile: View {
    let title: String
    let icon: String
    let color: Color
    let health: Int  // 0-100，越大越健康

    private var bandColor: Color {
        if health >= 70 { return .green }
        if health >= 50 { return .orange }
        return .red
    }
    private var statusLabel: String {
        if health >= 70 { return "正常" }
        if health >= 50 { return "偏高" }
        return "偏离明显"
    }

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 11))
                    .foregroundColor(color)
                Text(title)
                    .font(.caption.bold())
                    .foregroundColor(color)
            }
            Text("\(health)")
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundColor(bandColor)
                .contentTransition(.numericText())
            Text(statusLabel)
                .font(.system(size: 10))
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(bandColor.opacity(0.15))
                .foregroundColor(bandColor)
                .clipShape(Capsule())
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 14)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(color.opacity(0.06))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(color.opacity(0.15), lineWidth: 0.8)
        )
    }
}

private struct ConnectorArrow: View {
    var body: some View {
        Image(systemName: "arrow.right")
            .font(.system(size: 14, weight: .semibold))
            .foregroundColor(.appMuted.opacity(0.6))
            .padding(.horizontal, 4)
    }
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}

#Preview {
    OmicsTriadView(insight: OmicsTriadInsight(
        is_demo: true,
        metabolomics_score: 0.55,
        cgm_score: 0.62,
        heart_score: 0.30,
        overlap_score: 0.30,
        insights: [
            "BCAA 升高与餐后血糖偏高同步出现，提示胰岛素敏感性下降的早期信号。",
            "血糖波动峰值时段静息心率偏高，自主神经受血糖波动影响明显。"
        ]
    ))
    .padding()
    .background(Color.white)
    .cornerRadius(12)
    .padding()
    .background(Color.appBackground)
}
