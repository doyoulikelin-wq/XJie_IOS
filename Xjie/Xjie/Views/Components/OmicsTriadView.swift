import SwiftUI

/// 代谢组 × CGM × 心率 三圆交叠 + 粒子从相邻圆流向中心交叠区。
struct OmicsTriadView: View {
    let insight: OmicsTriadInsight
    @State private var phase: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let h = geo.size.height
            let r: CGFloat = min(w, h) * 0.28
            let cx = w / 2
            let cy = h / 2 + 6
            let cA = CGPoint(x: cx, y: cy - r * 0.55)
            let cB = CGPoint(x: cx - r * 0.7, y: cy + r * 0.45)
            let cC = CGPoint(x: cx + r * 0.7, y: cy + r * 0.45)

            TimelineView(.animation(minimumInterval: 1.0 / 45.0)) { ctx in
                let t = ctx.date.timeIntervalSinceReferenceDate
                Canvas { canvasCtx, _ in
                    // 三圆
                    _drawCircle(&canvasCtx, center: cA, radius: r, color: Color.appPrimary, name: "代谢组")
                    _drawCircle(&canvasCtx, center: cB, radius: r, color: .orange, name: "CGM")
                    _drawCircle(&canvasCtx, center: cC, radius: r, color: .pink, name: "心率")

                    // 粒子：A→center, B→center, C→center 流动
                    for (src, col, scoreKey) in [
                        (cA, Color.appPrimary, insight.metabolomics_score),
                        (cB, Color.orange, insight.cgm_score),
                        (cC, Color.pink, insight.heart_score),
                    ] {
                        let count = Int(6 + scoreKey * 10)
                        for i in 0..<count {
                            let p = (t * 0.4 + Double(i) / Double(count)).truncatingRemainder(dividingBy: 1.0)
                            let x = src.x + (CGPoint(x: cx, y: cy).x - src.x) * p
                            let y = src.y + (CGPoint(x: cx, y: cy).y - src.y) * p
                            let size: CGFloat = 3
                            let rect = CGRect(x: x - size/2, y: y - size/2, width: size, height: size)
                            canvasCtx.opacity = 0.55 * (1.0 - abs(p - 0.5) * 1.3)
                            canvasCtx.fill(Circle().path(in: rect), with: .color(col))
                        }
                        canvasCtx.opacity = 1
                    }

                    // 中心 overlap 标识
                    let overlapRect = CGRect(
                        x: cx - 24, y: cy - 24, width: 48, height: 48
                    )
                    canvasCtx.fill(
                        Circle().path(in: overlapRect),
                        with: .color(.white.opacity(0.85))
                    )
                    canvasCtx.stroke(
                        Circle().path(in: overlapRect),
                        with: .color(.appPrimary),
                        lineWidth: 1.2
                    )
                    let scoreText = "\(Int(insight.overlap_score * 100))"
                    canvasCtx.draw(
                        Text(scoreText).font(.system(size: 16, weight: .bold, design: .rounded))
                            .foregroundColor(.appPrimary),
                        at: CGPoint(x: cx, y: cy - 4)
                    )
                    canvasCtx.draw(
                        Text("耦合").font(.system(size: 9)).foregroundColor(.appMuted),
                        at: CGPoint(x: cx, y: cy + 12)
                    )
                }
            }
        }
        .aspectRatio(1.2, contentMode: .fit)
    }

    private func _drawCircle(_ ctx: inout GraphicsContext, center: CGPoint, radius: CGFloat, color: Color, name: String) {
        let rect = CGRect(x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2)
        ctx.fill(Circle().path(in: rect), with: .color(color.opacity(0.18)))
        ctx.stroke(Circle().path(in: rect), with: .color(color.opacity(0.7)), lineWidth: 1.5)
        ctx.draw(
            Text(name).font(.system(size: 11, weight: .semibold)).foregroundColor(color),
            at: CGPoint(x: center.x, y: center.y - radius - 10)
        )
    }
}

#Preview {
    OmicsTriadView(insight: OmicsTriadInsight(
        is_demo: true,
        metabolomics_score: 0.65,
        cgm_score: 0.55,
        heart_score: 0.45,
        overlap_score: 0.42,
        insights: ["BCAA 升高与餐后血糖同步"]
    ))
    .frame(width: 340, height: 280)
    .padding()
    .background(Color.appBackground)
}
