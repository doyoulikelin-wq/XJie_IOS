import SwiftUI

@MainActor
private struct XAgeKeyboardDoneAccessoryModifier: ViewModifier {
    let isPresented: Bool
    let accessibilityIdentifier: String
    let onDone: () -> Void

    func body(content: Content) -> some View {
        content.safeAreaInset(edge: .bottom, spacing: 0) {
            if isPresented {
                HStack {
                    Spacer()
                    Button {
                        onDone()
                        XAgeKeyboard.dismiss()
                    } label: {
                        Text("完成")
                            .frame(minWidth: 44, minHeight: 44)
                            .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier(accessibilityIdentifier)
                }
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Color(hex: "1268BD"))
                .padding(.horizontal, 18)
                .frame(height: 52)
                .frame(maxWidth: .infinity)
                .background(.ultraThinMaterial)
                .overlay(alignment: .top) {
                    Divider().opacity(0.35)
                }
            }
        }
    }
}

extension View {
    @MainActor
    func xAgeKeyboardDoneAccessory(
        isPresented: Bool,
        accessibilityIdentifier: String,
        onDone: @escaping () -> Void
    ) -> some View {
        modifier(
            XAgeKeyboardDoneAccessoryModifier(
                isPresented: isPresented,
                accessibilityIdentifier: accessibilityIdentifier,
                onDone: onDone
            )
        )
    }
}
