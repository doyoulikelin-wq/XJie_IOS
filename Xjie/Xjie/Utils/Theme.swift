import SwiftUI

/// 全局颜色定义 — 品牌色 XJ+ (Teal → Blue 渐变)
extension Color {
    static let appPrimary = Color(hex: "1565C0")       // 深蓝（Logo 主色）
    static let appAccent = Color(hex: "00C9A7")        // 青绿（Logo 辅色）
    static let appGradientStart = Color(hex: "00C9A7") // 渐变起点：青绿
    static let appGradientEnd = Color(hex: "1565C0")   // 渐变终点：深蓝
    static let appMuted = Color(.secondaryLabel)
    static let appDanger = Color(hex: "ef4444")
    static let appSuccess = Color(hex: "22c55e")
    static let appWarning = Color(hex: "f59e0b")
    static let appText = Color(.label)
    static let appBackground = Color(.systemBackground)
    static let appCardBg = Color(.secondarySystemBackground)
    static let appStroke = Color(.separator).opacity(0.28)
    static let appSoftFill = Color(hex: "F3F8FC")

    init(hex: String) {
        let scanner = Scanner(string: hex.trimmingCharacters(in: .alphanumerics.inverted))
        var int: UInt64 = 0
        scanner.scanHexInt64(&int)
        let r = Double((int >> 16) & 0xFF) / 255
        let g = Double((int >> 8) & 0xFF) / 255
        let b = Double(int & 0xFF) / 255
        self.init(red: r, green: g, blue: b)
    }
}

/// 全局样式修饰器
struct CardStyle: ViewModifier {
    @Environment(\.colorScheme) private var colorScheme

    func body(content: Content) -> some View {
        content
            .padding(16)
            .background(Color.appCardBg)
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(Color.appStroke, lineWidth: 0.5)
            )
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .shadow(
                color: colorScheme == .dark ? .clear : .black.opacity(0.055),
                radius: 12, x: 0, y: 5
            )
    }
}

struct PrimaryGradientButtonStyle: ButtonStyle {
    var isEnabled = true

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.bold())
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(
                LinearGradient(
                    colors: isEnabled
                    ? [Color.appGradientStart, Color.appGradientEnd]
                    : [Color.gray.opacity(0.35), Color.gray.opacity(0.5)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
            .foregroundColor(.white)
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .opacity(configuration.isPressed ? 0.86 : 1)
    }
}

extension View {
    func cardStyle() -> some View {
        modifier(CardStyle())
    }

    func primaryGradientButtonStyle(isEnabled: Bool = true) -> some View {
        buttonStyle(PrimaryGradientButtonStyle(isEnabled: isEnabled))
    }
}
