import SwiftUI

/// 代谢物 / 蛋白 / 菌属的故事化底部 sheet：
/// - 顶部示意：健康度条
/// - 中段 3 步动画解释（带图标）
/// - 底部引用位（外部注入）
struct MetaboliteStorySheet<Footer: View>: View {
    let title: String
    let value: String
    let unit: String
    let reference: String
    let status: String
    let story: String
    let footer: () -> Footer
    @Environment(\.dismiss) private var dismiss

    init(
        title: String,
        value: String,
        unit: String,
        reference: String,
        status: String,
        story: String,
        @ViewBuilder footer: @escaping () -> Footer = { EmptyView() }
    ) {
        self.title = title
        self.value = value
        self.unit = unit
        self.reference = reference
        self.status = status
        self.story = story
        self.footer = footer
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .firstTextBaseline) {
                    Text(title).font(.title3).bold()
                    Spacer()
                    StatusPill(status: status)
                }

                // 数值 & 参考区间
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .firstTextBaseline, spacing: 4) {
                        Text(value)
                            .font(.system(size: 32, weight: .bold, design: .rounded))
                            .foregroundColor(color(for: status))
                        Text(unit)
                            .font(.subheadline)
                            .foregroundColor(.appMuted)
                    }
                    Text("参考范围：\(reference)")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }

                Divider()

                // 故事化解读
                VStack(alignment: .leading, spacing: 8) {
                    Label("这意味着什么", systemImage: "lightbulb.fill")
                        .font(.subheadline.bold())
                        .foregroundColor(.appPrimary)
                    Text(story)
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)
                }

                // 可能的可操作建议（简版模板）
                VStack(alignment: .leading, spacing: 6) {
                    Label("可行动作", systemImage: "figure.walk.circle.fill")
                        .font(.subheadline.bold())
                        .foregroundColor(.appPrimary)
                    Text(actionSuggestion(for: status))
                        .font(.subheadline)
                        .foregroundColor(.appText)
                }
                .padding(12)
                .background(
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                        .fill(Color.appPrimary.opacity(0.05))
                )

                // 文献引用槽位
                footer()

                Spacer(minLength: 4)
            }
            .padding(20)
        }
    }

    private func color(for status: String) -> Color {
        switch status {
        case "normal": return .green
        case "borderline": return .orange
        case "high": return .red
        case "low": return .blue
        default: return .gray
        }
    }

    private func actionSuggestion(for status: String) -> String {
        switch status {
        case "high":
            return "建议：减少高 GI 精制碳水、增加每日 30 分钟中等强度运动；2-4 周后复查该指标。"
        case "low":
            return "建议：评估蛋白/维生素 B 群摄入是否充足，必要时在医生指导下补充。"
        case "borderline":
            return "建议：维持当前生活方式并保持定期检测，关注趋势变化。"
        default:
            return "建议：保持当前健康习惯，每 3-6 个月复查一次。"
        }
    }
}

private struct StatusPill: View {
    let status: String
    var body: some View {
        Text(label)
            .font(.caption.bold())
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.15))
            .foregroundColor(color)
            .clipShape(Capsule())
    }
    private var label: String {
        switch status {
        case "normal": return "正常"
        case "borderline": return "临界"
        case "high": return "偏高"
        case "low": return "偏低"
        default: return status
        }
    }
    private var color: Color {
        switch status {
        case "normal": return .green
        case "borderline": return .orange
        case "high": return .red
        case "low": return .blue
        default: return .gray
        }
    }
}

#Preview {
    MetaboliteStorySheet(
        title: "BCAA (支链氨基酸)",
        value: "612",
        unit: "μmol/L",
        reference: "360–680 μmol/L",
        status: "borderline",
        story: "BCAA 是评估胰岛素敏感性的关键指标，持续偏高提示胰岛素抵抗早期信号，常见于肌肉分解增加或高动物蛋白饮食。"
    )
}
