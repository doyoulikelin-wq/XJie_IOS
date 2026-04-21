import SwiftUI

/// 肠道菌群"气泡"分布 — 圆面积 ∝ 相对丰度，点击弹出详情。
struct MicrobiomeBubbleChart: View {
    let taxa: [MicrobiomeTaxon]
    var onTap: (MicrobiomeTaxon) -> Void = { _ in }

    @State private var appeared = false

    var body: some View {
        GeometryReader { geo in
            let layout = _placeBubbles(taxa: taxa, size: geo.size)
            ZStack {
                ForEach(Array(layout.enumerated()), id: \.offset) { idx, placed in
                    let t = placed.taxon
                    Button { onTap(t) } label: {
                        ZStack {
                            Circle()
                                .fill(colorFor(t).opacity(0.18))
                            Circle()
                                .strokeBorder(colorFor(t), lineWidth: 1.2)
                            VStack(spacing: 2) {
                                Text(t.name.split(separator: " ").first.map(String.init) ?? t.name)
                                    .font(.system(size: max(9, placed.radius * 0.22), weight: .semibold))
                                    .foregroundColor(.appText)
                                    .lineLimit(1)
                                if placed.radius >= 28 {
                                    Text("\(Int(t.relative_abundance * 100))%")
                                        .font(.system(size: max(8, placed.radius * 0.18), weight: .medium))
                                        .foregroundColor(colorFor(t))
                                }
                            }
                            .padding(4)
                        }
                        .frame(width: placed.radius * 2, height: placed.radius * 2)
                    }
                    .buttonStyle(.plain)
                    .position(placed.center)
                    .scaleEffect(appeared ? 1 : 0.4)
                    .opacity(appeared ? 1 : 0)
                    .animation(
                        .spring(response: 0.55, dampingFraction: 0.7)
                            .delay(Double(idx) * 0.04),
                        value: appeared
                    )
                }
            }
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .aspectRatio(1.2, contentMode: .fit)
        .onAppear { appeared = true }
    }

    private func colorFor(_ t: MicrobiomeTaxon) -> Color {
        if t.relevance.contains("inflammation") && t.status == "high" { return .red }
        if t.relevance.contains("cgm") { return .appPrimary }
        if t.relevance.contains("mood") { return .purple }
        if t.relevance.contains("weight") { return .orange }
        return .green
    }
}

private struct _PlacedBubble {
    let taxon: MicrobiomeTaxon
    let center: CGPoint
    let radius: CGFloat
}

/// 极简贪心布局：按丰度降序，每个气泡尝试在一组候选位置中放下不重叠。
private func _placeBubbles(taxa: [MicrobiomeTaxon], size: CGSize) -> [_PlacedBubble] {
    let sorted = taxa.sorted { $0.relative_abundance > $1.relative_abundance }
    let area = Double(size.width) * Double(size.height) * 0.55
    let totalAbundance = sorted.map { $0.relative_abundance }.reduce(0, +)
    let scale = totalAbundance > 0 ? area / totalAbundance : 1.0
    var placed: [_PlacedBubble] = []
    let padding: CGFloat = 4
    for t in sorted {
        let r = CGFloat(sqrt(max(0.001, t.relative_abundance) * scale / .pi))
        let radius = max(16, min(r, min(size.width, size.height) * 0.34))
        var center = CGPoint(x: size.width / 2, y: size.height / 2)
        var placedOK = false
        // Candidate grid
        var candidates: [CGPoint] = []
        let stepX = max(20, radius * 0.9)
        let stepY = max(20, radius * 0.9)
        var y = radius + padding
        while y < size.height - radius - padding {
            var x = radius + padding
            while x < size.width - radius - padding {
                candidates.append(CGPoint(x: x, y: y))
                x += stepX
            }
            y += stepY
        }
        // Prefer candidates nearer to the center
        let cc = CGPoint(x: size.width / 2, y: size.height / 2)
        candidates.sort {
            hypot($0.x - cc.x, $0.y - cc.y) < hypot($1.x - cc.x, $1.y - cc.y)
        }
        for cand in candidates {
            var ok = true
            for p in placed {
                let d = hypot(cand.x - p.center.x, cand.y - p.center.y)
                if d < radius + p.radius + padding {
                    ok = false
                    break
                }
            }
            if ok {
                center = cand
                placedOK = true
                break
            }
        }
        if !placedOK {
            // Fallback: push outside
            center = CGPoint(x: CGFloat.random(in: radius...(size.width - radius)),
                             y: CGFloat.random(in: radius...(size.height - radius)))
        }
        placed.append(_PlacedBubble(taxon: t, center: center, radius: radius))
    }
    return placed
}

#Preview {
    let demo: [MicrobiomeTaxon] = [
        .init(name: "Akkermansia", key: "akk", relative_abundance: 0.08, reference: "0.01-0.04", status: "high", relevance: ["cgm"], story_zh: ""),
        .init(name: "Faecalibacterium", key: "fp", relative_abundance: 0.20, reference: "0.05-0.15", status: "high", relevance: ["inflammation"], story_zh: ""),
        .init(name: "Bacteroides", key: "bc", relative_abundance: 0.25, reference: "0.10-0.30", status: "normal", relevance: ["diet"], story_zh: ""),
        .init(name: "Prevotella", key: "pr", relative_abundance: 0.10, reference: "0.02-0.20", status: "normal", relevance: ["diet"], story_zh: ""),
        .init(name: "Bifido", key: "bf", relative_abundance: 0.06, reference: "0.02-0.10", status: "normal", relevance: ["cgm"], story_zh: ""),
        .init(name: "Roseburia", key: "rb", relative_abundance: 0.05, reference: "0.02-0.08", status: "normal", relevance: ["cgm"], story_zh: ""),
    ]
    return MicrobiomeBubbleChart(taxa: demo)
        .frame(width: 340, height: 260)
        .padding()
        .background(Color.appBackground)
}
