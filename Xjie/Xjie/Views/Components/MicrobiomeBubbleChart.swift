import SwiftUI

/// 将常见肠道菌属拉丁名映射为中文名（未命中则回退原名）。
func zhNameForTaxon(_ name: String) -> String {
    let key = (name.split(separator: " ").first.map(String.init) ?? name).lowercased()
    let map: [String: String] = [
        "akkermansia": "阿克曼氏菌",
        "faecalibacterium": "粪杆菌",
        "bacteroides": "拟杆菌",
        "prevotella": "普雷沃氏菌",
        "bifidobacterium": "双歧杆菌",
        "bifido": "双歧杆菌",
        "roseburia": "罗斯氏菌",
        "blautia": "布劳特氏菌",
        "eubacterium": "真杆菌",
        "ruminococcus": "瘤胃球菌",
        "clostridium": "梭菌",
        "enterococcus": "肠球菌",
        "escherichia": "大肠杆菌",
        "lactobacillus": "乳杆菌",
        "streptococcus": "链球菌",
        "veillonella": "韦荣氏菌",
        "fusobacterium": "梭杆菌",
        "dialister": "小杆菌",
        "coprococcus": "粪球菌",
        "parabacteroides": "副拟杆菌",
        "collinsella": "柯林斯氏菌",
        "dorea": "多里氏菌",
        "megamonas": "巨单胞菌"
    ]
    return map[key] ?? name
}

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
                                Text(zhNameForTaxon(t.name))
                                    .font(.system(size: max(9, placed.radius * 0.20), weight: .semibold))
                                    .foregroundColor(.appText)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.6)
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

/// 按丰度降序贪心布局，并保证气泡之间不重叠。
/// 策略：1) 细粒度网格找最靠近中心的空位；2) 若找不到则逐步缩小半径重试；3) 最后用松弛一次驱散残余重叠。
private func _placeBubbles(taxa: [MicrobiomeTaxon], size: CGSize) -> [_PlacedBubble] {
    guard size.width > 0, size.height > 0, !taxa.isEmpty else { return [] }
    let sorted = taxa.sorted { $0.relative_abundance > $1.relative_abundance }
    // 初始面积预算（留 35% 空白以容纳间隙）
    let totalAbundance = sorted.map { $0.relative_abundance }.reduce(0, +)
    let availableArea = Double(size.width) * Double(size.height) * 0.55
    var scale = totalAbundance > 0 ? availableArea / totalAbundance : 1.0
    let maxRadius = min(size.width, size.height) * 0.30
    let minRadius: CGFloat = 16
    let padding: CGFloat = 5
    let cc = CGPoint(x: size.width / 2, y: size.height / 2)

    func radiusFor(_ t: MicrobiomeTaxon, scale: Double) -> CGFloat {
        let r = CGFloat(sqrt(max(0.001, t.relative_abundance) * scale / .pi))
        return max(minRadius, min(r, maxRadius))
    }

    // 自适应：若第一次放置失败率过高，会缩小 scale 重试最多 3 次
    for attempt in 0..<3 {
        var placed: [_PlacedBubble] = []
        var allOK = true
        for t in sorted {
            let radius = radiusFor(t, scale: scale)
            var bestCenter: CGPoint? = nil
            // 细网格：步长 = min(radius, 12)，保证候选足够密
            let step: CGFloat = max(8, min(radius * 0.35, 14))
            var bestDist = CGFloat.infinity
            var y = radius + padding
            while y <= size.height - radius - padding {
                var x = radius + padding
                while x <= size.width - radius - padding {
                    let cand = CGPoint(x: x, y: y)
                    var ok = true
                    for p in placed {
                        let d = hypot(cand.x - p.center.x, cand.y - p.center.y)
                        if d < radius + p.radius + padding { ok = false; break }
                    }
                    if ok {
                        let dc = hypot(cand.x - cc.x, cand.y - cc.y)
                        if dc < bestDist { bestDist = dc; bestCenter = cand }
                    }
                    x += step
                }
                y += step
            }
            if let c = bestCenter {
                placed.append(_PlacedBubble(taxon: t, center: c, radius: radius))
            } else {
                allOK = false
                break
            }
        }
        if allOK {
            return _relax(placed: placed, size: size, padding: padding)
        }
        // 缩小尺寸后重试
        scale *= 0.75
        if attempt == 2 {
            // 最后一次无论如何都输出，再用松弛驱散重叠
            var placed: [_PlacedBubble] = []
            for t in sorted {
                let radius = radiusFor(t, scale: scale)
                let c = CGPoint(
                    x: CGFloat.random(in: radius...(max(radius, size.width - radius))),
                    y: CGFloat.random(in: radius...(max(radius, size.height - radius)))
                )
                placed.append(_PlacedBubble(taxon: t, center: c, radius: radius))
            }
            return _relax(placed: placed, size: size, padding: padding)
        }
    }
    return []
}

/// 弹性松弛：多次扫描，两两重叠时沿连线方向推开。
private func _relax(placed: [_PlacedBubble], size: CGSize, padding: CGFloat) -> [_PlacedBubble] {
    var arr = placed
    for _ in 0..<60 {
        var moved = false
        for i in 0..<arr.count {
            for j in (i + 1)..<arr.count {
                let a = arr[i], b = arr[j]
                let dx = b.center.x - a.center.x
                let dy = b.center.y - a.center.y
                let dist = max(0.001, hypot(dx, dy))
                let want = a.radius + b.radius + padding
                if dist < want {
                    let overlap = (want - dist) / 2
                    let ux = dx / dist, uy = dy / dist
                    var ac = CGPoint(x: a.center.x - ux * overlap, y: a.center.y - uy * overlap)
                    var bc = CGPoint(x: b.center.x + ux * overlap, y: b.center.y + uy * overlap)
                    // clamp to bounds
                    ac.x = min(max(ac.x, a.radius + padding), size.width - a.radius - padding)
                    ac.y = min(max(ac.y, a.radius + padding), size.height - a.radius - padding)
                    bc.x = min(max(bc.x, b.radius + padding), size.width - b.radius - padding)
                    bc.y = min(max(bc.y, b.radius + padding), size.height - b.radius - padding)
                    arr[i] = _PlacedBubble(taxon: a.taxon, center: ac, radius: a.radius)
                    arr[j] = _PlacedBubble(taxon: b.taxon, center: bc, radius: b.radius)
                    moved = true
                }
            }
        }
        if !moved { break }
    }
    return arr
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
