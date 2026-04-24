import SwiftUI

/// 通用"示例数据"徽章 — 放在每张 demo 面板顶部，传达此数据为演示。
struct DemoBadge: View {
    var label: String = "示例数据"
    var detail: String? = "仅用于功能演示，非真实检测结果"

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "sparkles")
                .font(.system(size: 11, weight: .semibold))
            Text(label)
                .font(.system(size: 11, weight: .semibold))
            if let detail {
                Text("·")
                    .font(.system(size: 11))
                    .foregroundColor(.appPrimary.opacity(0.5))
                Text(detail)
                    .font(.system(size: 10))
                    .foregroundColor(.appPrimary.opacity(0.8))
                    .lineLimit(1)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(
            Capsule()
                .fill(Color.appPrimary.opacity(0.12))
        )
        .foregroundColor(.appPrimary)
        .accessibilityLabel("示例数据，仅用于功能演示")
    }
}

#Preview {
    VStack(spacing: 12) {
        DemoBadge()
        DemoBadge(label: "示例数据", detail: nil)
    }
    .padding()
    .background(Color.appBackground)
}
