import SwiftUI

/// 助手「小捷」的轻量化矢量头像。
/// - 设计：squircle 柔和渐变 + 白色 SF Symbol，呼应 iOS 原生质感
/// - 与 Color.appPrimary 主题色一致；可选白色描边用于聊天大头像
struct AssistantAvatar: View {
    var size: CGFloat = 36
    var bordered: Bool = false

    var body: some View {
        let corner = size * 0.30
        ZStack {
            RoundedRectangle(cornerRadius: corner, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color.appPrimary,
                            Color.appPrimary.opacity(0.82)
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .overlay(
                    // 顶部高光，做轻微体积感
                    RoundedRectangle(cornerRadius: corner, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [Color.white.opacity(0.18), .clear],
                                startPoint: .top,
                                endPoint: .center
                            )
                        )
                )

            Image(systemName: "sparkles")
                .font(.system(size: size * 0.55, weight: .semibold))
                .foregroundStyle(Color.white)
                .shadow(color: Color.black.opacity(0.12), radius: 0.6, x: 0, y: 0.5)
        }
        .frame(width: size, height: size)
        .overlay(
            RoundedRectangle(cornerRadius: corner, style: .continuous)
                .strokeBorder(Color.white.opacity(bordered ? 0.9 : 0), lineWidth: bordered ? 1.5 : 0)
        )
        .accessibilityHidden(true)
    }
}

#Preview("AssistantAvatar") {
    VStack(spacing: 24) {
        HStack(spacing: 16) {
            AssistantAvatar(size: 28)
            AssistantAvatar(size: 36)
            AssistantAvatar(size: 48)
            AssistantAvatar(size: 64)
            AssistantAvatar(size: 80, bordered: true)
        }
        HStack(spacing: 12) {
            AssistantAvatar(size: 36)
            VStack(alignment: .leading, spacing: 2) {
                Text("小捷")
                    .font(.subheadline.bold())
                Text("你的健康助手")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 12).fill(Color(.systemBackground)))
        .shadow(color: .black.opacity(0.05), radius: 6, y: 2)
        .padding(.horizontal)
    }
    .padding()
    .background(Color(.systemGroupedBackground))
}
