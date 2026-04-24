import SwiftUI

/// 代谢健康卡 — 替代之前难以理解的"代谢指纹"。
/// 设计原则：
/// - 顶部大数字（健康分 0-100）+ 代谢年龄差，告诉用户"我整体怎么样"
/// - 中段按相关系统分组（心血管 / 糖代谢 / 慢性炎症 / 神经情绪），每组用横向进度条
///   显示"正常项数 / 该组总数"，一眼看出哪个系统出了问题
/// - 底部"重点关注"pill 列出偏离最严重的 3 项
struct MetabolicFingerprintView: View {
    let items: [OmicsDemoItem]
    var metabolicAgeDelta: Double = 0

    @State private var appeared = false

    var body: some View {
        let groups = MetabolicFingerprintView.group(items: items)
        let healthScore = MetabolicFingerprintView.healthScore(items: items)
        let topConcerns = items
            .filter { $0.status == "high" || $0.status == "low" }
            .prefix(3)

        VStack(alignment: .leading, spacing: 16) {
            // ── 顶部健康分
            HStack(alignment: .center, spacing: 16) {
                ZStack {
                    Circle()
                        .stroke(Color.appPrimary.opacity(0.08), lineWidth: 10)
                        .frame(width: 88, height: 88)
                    Circle()
                        .trim(from: 0, to: appeared ? CGFloat(healthScore) / 100.0 : 0)
                        .stroke(
                            colorForScore(healthScore),
                            style: StrokeStyle(lineWidth: 10, lineCap: .round)
                        )
                        .rotationEffect(.degrees(-90))
                        .frame(width: 88, height: 88)
                        .animation(.easeOut(duration: 0.8), value: appeared)
                    VStack(spacing: 0) {
                        Text("\(Int(healthScore))")
                            .font(.system(size: 26, weight: .bold, design: .rounded))
                            .foregroundColor(colorForScore(healthScore))
                        Text("健康分")
                            .font(.system(size: 9))
                            .foregroundColor(.appMuted)
                    }
                }
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 6) {
                        Text("代谢年龄")
                            .font(.caption)
                            .foregroundColor(.appMuted)
                        Text("\(metabolicAgeDelta >= 0 ? "+" : "")\(String(format: "%.1f", metabolicAgeDelta)) 岁")
                            .font(.subheadline.bold())
                            .foregroundColor(metabolicAgeDelta <= 0 ? .green : (metabolicAgeDelta > 3 ? .red : .orange))
                    }
                    HStack(spacing: 6) {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption)
                            .foregroundColor(.green)
                        Text("\(items.filter { $0.status == "normal" }.count)/\(items.count) 项处于参考范围")
                            .font(.caption)
                            .foregroundColor(.appText)
                    }
                    Text(riskHintForScore(healthScore))
                        .font(.caption2)
                        .foregroundColor(.appMuted)
                }
                Spacer()
            }

            Divider()

            // ── 分系统占比条
            VStack(alignment: .leading, spacing: 10) {
                Text("分系统体检")
                    .font(.subheadline.bold())
                ForEach(groups) { g in
                    CategoryRow(group: g, appeared: appeared)
                }
            }

            // ── 重点关注
            if !topConcerns.isEmpty {
                Divider()
                VStack(alignment: .leading, spacing: 6) {
                    Text("重点关注")
                        .font(.subheadline.bold())
                    FlexibleHStack(spacing: 6) {
                        ForEach(Array(topConcerns), id: \.id) { item in
                            HStack(spacing: 4) {
                                Image(systemName: item.status == "high" ? "arrow.up" : "arrow.down")
                                    .font(.system(size: 9, weight: .bold))
                                Text(shortName(item.name))
                                    .font(.caption.bold())
                                Text(String(format: "%g", item.value))
                                    .font(.caption)
                            }
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(colorFor(item.status).opacity(0.12))
                            .foregroundColor(colorFor(item.status))
                            .clipShape(Capsule())
                        }
                    }
                }
            }
        }
        .onAppear { appeared = true }
    }

    // MARK: - Helpers

    private func colorForScore(_ s: Double) -> Color {
        if s >= 75 { return .green }
        if s >= 55 { return .orange }
        return .red
    }
    private func riskHintForScore(_ s: Double) -> String {
        if s >= 75 { return "整体处于健康区间" }
        if s >= 55 { return "部分指标偏离，建议关注" }
        return "多项指标偏离，建议尽快干预"
    }
    private func colorFor(_ status: String) -> Color {
        switch status {
        case "normal": return .green
        case "borderline": return .orange
        case "high": return .red
        case "low": return .blue
        default: return .gray
        }
    }
    private func shortName(_ n: String) -> String {
        // 取空格前的英文部分
        if let head = n.split(separator: " ").first { return String(head) }
        return n
    }

    // MARK: - 分组

    static func group(items: [OmicsDemoItem]) -> [CategoryGroup] {
        // 优先级：心血管 > 糖代谢 > 炎症 > 神经/情绪 > 其他
        var heart: [OmicsDemoItem] = []
        var sugar: [OmicsDemoItem] = []
        var inflam: [OmicsDemoItem] = []
        var mind: [OmicsDemoItem] = []
        var other: [OmicsDemoItem] = []
        for it in items {
            if it.relevance.contains("heart") { heart.append(it) }
            else if it.relevance.contains("cgm") || it.relevance.contains("t2d") { sugar.append(it) }
            else if it.relevance.contains("inflammation") { inflam.append(it) }
            else if it.relevance.contains("mood") { mind.append(it) }
            else { other.append(it) }
        }
        var out: [CategoryGroup] = []
        if !heart.isEmpty { out.append(.init(name: "心血管代谢", icon: "heart.fill", color: .red, items: heart)) }
        if !sugar.isEmpty { out.append(.init(name: "糖代谢", icon: "drop.fill", color: .appPrimary, items: sugar)) }
        if !inflam.isEmpty { out.append(.init(name: "慢性炎症", icon: "flame.fill", color: .orange, items: inflam)) }
        if !mind.isEmpty { out.append(.init(name: "神经/情绪", icon: "brain.head.profile", color: .purple, items: mind)) }
        if !other.isEmpty { out.append(.init(name: "其他", icon: "circle.dashed", color: .gray, items: other)) }
        return out
    }

    static func healthScore(items: [OmicsDemoItem]) -> Double {
        guard !items.isEmpty else { return 100 }
        let weights: [String: Double] = ["normal": 1.0, "borderline": 0.6, "high": 0.2, "low": 0.2]
        let s = items.map { weights[$0.status, default: 0.5] }.reduce(0, +) / Double(items.count)
        return (s * 100).rounded()
    }
}

struct CategoryGroup: Identifiable {
    let id = UUID()
    let name: String
    let icon: String
    let color: Color
    let items: [OmicsDemoItem]

    var normalCount: Int { items.filter { $0.status == "normal" }.count }
    var totalCount: Int { items.count }
    var ratio: Double { totalCount == 0 ? 1 : Double(normalCount) / Double(totalCount) }
    var summaryColor: Color {
        if ratio >= 0.85 { return .green }
        if ratio >= 0.55 { return .orange }
        return .red
    }
}

private struct CategoryRow: View {
    let group: CategoryGroup
    let appeared: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Image(systemName: group.icon)
                    .font(.system(size: 11))
                    .foregroundColor(group.color)
                Text(group.name)
                    .font(.caption)
                    .foregroundColor(.appText)
                Spacer()
                Text("\(group.normalCount)/\(group.totalCount) 正常")
                    .font(.caption2)
                    .foregroundColor(group.summaryColor)
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(Color.gray.opacity(0.1))
                    RoundedRectangle(cornerRadius: 4)
                        .fill(group.summaryColor.opacity(0.85))
                        .frame(width: appeared ? geo.size.width * CGFloat(group.ratio) : 0)
                        .animation(.easeOut(duration: 0.7), value: appeared)
                }
            }
            .frame(height: 8)
        }
    }
}

/// 简易自适应换行 HStack（用于"重点关注"pills）
struct FlexibleHStack<Content: View>: View {
    let spacing: CGFloat
    @ViewBuilder let content: () -> Content
    init(spacing: CGFloat = 6, @ViewBuilder content: @escaping () -> Content) {
        self.spacing = spacing
        self.content = content
    }
    var body: some View {
        // 用 VStack + HStack(alignment: .top) 容纳是最简单的方式；
        // 这里用 SwiftUI 原生 Layout 做真正的 flow。
        FlowLayout(spacing: spacing) { content() }
    }
}

private struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxW = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineH: CGFloat = 0
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x + s.width > maxW {
                x = 0; y += lineH + spacing; lineH = 0
            }
            x += s.width + spacing
            lineH = max(lineH, s.height)
        }
        return CGSize(width: maxW.isFinite ? maxW : x, height: y + lineH)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x: CGFloat = bounds.minX, y: CGFloat = bounds.minY, lineH: CGFloat = 0
        let maxX = bounds.maxX
        for v in subviews {
            let s = v.sizeThatFits(.unspecified)
            if x + s.width > maxX {
                x = bounds.minX; y += lineH + spacing; lineH = 0
            }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(s))
            x += s.width + spacing
            lineH = max(lineH, s.height)
        }
    }
}

#Preview {
    let items: [OmicsDemoItem] = [
        .init(name: "BCAA", key: "bcaa", value: 612, unit: "μmol/L", status: "borderline", reference: "360-680", story_zh: "", relevance: ["cgm", "t2d"]),
        .init(name: "TMAO", key: "tmao", value: 8.2, unit: "μmol/L", status: "high", reference: "1.5-6.0", story_zh: "", relevance: ["heart"]),
        .init(name: "Ceramides", key: "cer", value: 320, unit: "nmol/L", status: "high", reference: "120-280", story_zh: "", relevance: ["heart"]),
        .init(name: "GlycA", key: "glyca", value: 380, unit: "μmol/L", status: "normal", reference: "320-400", story_zh: "", relevance: ["inflammation"]),
        .init(name: "Kyn/Trp", key: "kt", value: 0.04, unit: "", status: "normal", reference: "", story_zh: "", relevance: ["mood"]),
        .init(name: "Lactate", key: "lac", value: 1.2, unit: "mmol/L", status: "normal", reference: "0.5-2.2", story_zh: "", relevance: ["cgm"]),
        .init(name: "ApoB/A1", key: "apo", value: 0.6, unit: "", status: "normal", reference: "", story_zh: "", relevance: ["heart"]),
        .init(name: "Histidine", key: "his", value: 60, unit: "μmol/L", status: "low", reference: "70-110", story_zh: "", relevance: ["inflammation"]),
    ]
    return MetabolicFingerprintView(items: items, metabolicAgeDelta: +2.4)
        .padding()
        .background(Color.white)
        .cornerRadius(12)
        .padding()
        .background(Color.appBackground)
}
