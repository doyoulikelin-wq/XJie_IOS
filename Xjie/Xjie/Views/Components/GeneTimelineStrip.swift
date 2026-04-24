import SwiftUI

/// 基因风险色带 + 每个 SNP 的 pill 卡片
struct GeneTimelineStrip: View {
    let variants: [GeneVariant]
    var onTap: (GeneVariant) -> Void = { _ in }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(variants) { v in
                        Button { onTap(v) } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                HStack(spacing: 4) {
                                    Circle()
                                        .fill(colorFor(v.risk_level))
                                        .frame(width: 8, height: 8)
                                    Text(v.risk_level)
                                        .font(.system(size: 10, weight: .semibold))
                                        .foregroundColor(colorFor(v.risk_level))
                                }
                                Text(v.name)
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundColor(.appText)
                                    .lineLimit(1)
                                Text(v.genotype)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(.appMuted)
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 10)
                            .frame(minWidth: 132, alignment: .leading)
                            .background(
                                RoundedRectangle(cornerRadius: 10, style: .continuous)
                                    .fill(colorFor(v.risk_level).opacity(0.08))
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: 10, style: .continuous)
                                    .strokeBorder(colorFor(v.risk_level).opacity(0.25), lineWidth: 0.8)
                            )
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 2)
            }
        }
    }

    private func colorFor(_ level: String) -> Color {
        switch level {
        case "低": return .green
        case "中": return .orange
        case "较高": return .red
        default: return .gray
        }
    }
}

#Preview {
    GeneTimelineStrip(variants: [
        .init(name: "TCF7L2", key: "t", genotype: "CT", risk_level: "中", relevance: ["t2d"], story_zh: ""),
        .init(name: "FTO", key: "f", genotype: "AA", risk_level: "较高", relevance: ["obesity"], story_zh: ""),
        .init(name: "APOE", key: "a", genotype: "ε3/ε3", risk_level: "低", relevance: ["heart"], story_zh: ""),
        .init(name: "MTHFR", key: "m", genotype: "CC", risk_level: "低", relevance: ["heart"], story_zh: ""),
    ])
    .padding()
    .background(Color.appBackground)
}
