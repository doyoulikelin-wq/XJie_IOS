import SwiftUI

/// 代谢指纹 — 极坐标多指标圆形矩阵，spring 动画从中心逐点展开。
///
/// - 每个指标按角度均匀分布
/// - 指标颜色：normal 绿 / borderline 橙 / high 红 / low 蓝
/// - 中心区域显示代谢年龄差
struct MetabolicFingerprintView: View {
    let items: [OmicsDemoItem]
    var metabolicAgeDelta: Double = 0
    @State private var progress: CGFloat = 0

    var body: some View {
        GeometryReader { geo in
            let side = min(geo.size.width, geo.size.height)
            let center = CGPoint(x: side / 2, y: side / 2)
            let radiusOuter = side * 0.44
            let radiusInner = side * 0.18

            ZStack {
                // 背景同心圆
                ForEach([0.45, 0.6, 0.75, 0.9], id: \.self) { r in
                    Circle()
                        .stroke(Color.appPrimary.opacity(0.06), lineWidth: 1)
                        .frame(width: side * r, height: side * r)
                        .position(center)
                }

                // 连接线（中心 → 每个指标点）
                ForEach(Array(items.enumerated()), id: \.offset) { idx, item in
                    let angle = Angle(degrees: Double(idx) / Double(max(items.count, 1)) * 360.0 - 90.0)
                    let pt = polarPoint(center: center, angle: angle, radius: radiusOuter)
                    Path { p in
                        p.move(to: center)
                        p.addLine(to: pt)
                    }
                    .trim(from: 0, to: progress)
                    .stroke(colorFor(item.status).opacity(0.35), lineWidth: 1)
                }

                // 指标圆点
                ForEach(Array(items.enumerated()), id: \.offset) { idx, item in
                    let angle = Angle(degrees: Double(idx) / Double(max(items.count, 1)) * 360.0 - 90.0)
                    let pt = polarPoint(center: center, angle: angle, radius: radiusOuter)
                    Circle()
                        .fill(colorFor(item.status))
                        .frame(width: dotSize(item.status), height: dotSize(item.status))
                        .overlay(Circle().stroke(Color.white, lineWidth: 1.2))
                        .shadow(color: colorFor(item.status).opacity(0.5), radius: 3)
                        .position(pt)
                        .scaleEffect(progress)
                        .opacity(progress)
                        .animation(
                            .spring(response: 0.6, dampingFraction: 0.65)
                                .delay(Double(idx) * 0.04),
                            value: progress
                        )
                }

                // 中心气泡
                VStack(spacing: 2) {
                    Text("代谢年龄")
                        .font(.system(size: 10))
                        .foregroundColor(.appMuted)
                    Text("\(metabolicAgeDelta >= 0 ? "+" : "")\(String(format: "%.1f", metabolicAgeDelta))")
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .foregroundColor(metabolicAgeDelta <= 0 ? .green : (metabolicAgeDelta > 3 ? .red : .orange))
                    Text("岁")
                        .font(.system(size: 10))
                        .foregroundColor(.appMuted)
                }
                .frame(width: radiusInner * 2, height: radiusInner * 2)
                .background(
                    Circle().fill(Color.appBackground)
                        .shadow(color: Color.black.opacity(0.05), radius: 4)
                )
                .position(center)
                .opacity(progress)
            }
            .frame(width: side, height: side)
        }
        .aspectRatio(1, contentMode: .fit)
        .onAppear {
            progress = 0
            withAnimation(.easeOut(duration: 0.4)) {
                progress = 1
            }
        }
    }

    private func polarPoint(center: CGPoint, angle: Angle, radius: CGFloat) -> CGPoint {
        CGPoint(
            x: center.x + radius * CGFloat(cos(angle.radians)),
            y: center.y + radius * CGFloat(sin(angle.radians))
        )
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

    private func dotSize(_ status: String) -> CGFloat {
        switch status {
        case "high", "low": return 14
        case "borderline": return 12
        default: return 9
        }
    }
}

#Preview {
    let items = (0..<20).map { i in
        OmicsDemoItem(
            name: "item\(i)",
            key: "k\(i)",
            value: 1.0,
            unit: "x",
            status: ["normal", "borderline", "high", "low", "normal"][i % 5],
            reference: "",
            story_zh: "",
            relevance: []
        )
    }
    return MetabolicFingerprintView(items: items, metabolicAgeDelta: +2.4)
        .frame(width: 320, height: 320)
        .padding()
        .background(Color.appBackground)
}
