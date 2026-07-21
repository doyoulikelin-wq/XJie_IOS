import AVFoundation
import Speech
import SwiftUI
import UIKit

struct XAgeSectionHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(subtitle)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
        }
    }
}

struct XAgeGlassTextField<Field: Hashable>: View {
    let placeholder: String
    @Binding var text: String
    var keyboardType: UIKeyboardType = .default
    let field: Field
    var focusedField: FocusState<Field?>.Binding
    var contentType: UITextContentType? = nil
    var capitalization: TextInputAutocapitalization = .sentences
    var submitLabel: SubmitLabel = .done
    var nextField: Field? = nil

    var body: some View {
        TextField(placeholder, text: $text)
            .font(.system(size: 14, weight: .semibold))
            .keyboardType(keyboardType)
            .textContentType(contentType)
            .textInputAutocapitalization(capitalization)
            .disableAutocorrection(true)
            .focused(focusedField, equals: field)
            .submitLabel(submitLabel)
            .onSubmit {
                focusedField.wrappedValue = nextField
            }
            .padding(.horizontal, 12)
            .frame(height: 44)
            .background(XAgeCapsuleFill())
    }
}

struct XAgeGradientActionLabel: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .bold))
            Text(title)
                .font(.system(size: 14, weight: .bold))
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .frame(height: 44)
        .background(
            Capsule()
                .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
        )
    }
}

struct CapsuleButton: View {
    let title: String
    var isEnabled = true
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "365F80"))
                .frame(width: 56, height: 44)
                .background {
                    XAgeCapsuleFill()
                        .frame(height: 30)
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.42)
    }
}

struct XAgeGlassCardBackground: View {
    var cornerRadius: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white.opacity(0.56))
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.84), lineWidth: 1)
            )
            .shadow(color: Color(hex: "73C8F0").opacity(0.18), radius: 28, x: 0, y: 14)
    }
}

struct XAgeCapsuleFill: View {
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.58))
            .background(.ultraThinMaterial, in: Capsule())
            .overlay(Capsule().stroke(.white.opacity(0.88), lineWidth: 1))
            .shadow(color: Color(hex: "7ACAF5").opacity(0.12), radius: 14, x: 0, y: 7)
    }
}

struct XAgeRoundedFieldBackground: View {
    var cornerRadius: CGFloat = 18

    var body: some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)

        shape
            .fill(.white.opacity(0.58))
            .background(.ultraThinMaterial, in: shape)
            .overlay(shape.stroke(.white.opacity(0.88), lineWidth: 1))
            .shadow(color: Color(hex: "7ACAF5").opacity(0.12), radius: 14, x: 0, y: 7)
    }
}

struct XAgeLiquidBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(hex: "E8F7FF"), Color(hex: "D5ECFF"), Color(hex: "F7FCFF")],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            Circle()
                .fill(Color(hex: "61E7E1").opacity(0.28))
                .frame(width: 235, height: 235)
                .blur(radius: 26)
                .offset(x: -150, y: -260)
            Circle()
                .fill(Color(hex: "8CC8FF").opacity(0.32))
                .frame(width: 260, height: 300)
                .blur(radius: 30)
                .offset(x: 160, y: -320)
            Circle()
                .fill(Color(hex: "C9C2FF").opacity(0.22))
                .frame(width: 230, height: 260)
                .blur(radius: 34)
                .offset(x: 135, y: 150)
            Rectangle()
                .fill(.white.opacity(0.2))
                .frame(width: 88)
                .blur(radius: 22)
                .rotationEffect(.degrees(5))
                .offset(x: -6)
        }
    }
}

#if DEBUG
private enum XAgeStylePreviewField: Hashable {
    case input
}

struct XAgeStyleComponentsPreview: View {
    @State private var text = ""
    @FocusState private var focusedField: XAgeStylePreviewField?

    var body: some View {
        VStack(spacing: 18) {
            XAgeGlassTextField(
                placeholder: "输入内容",
                text: $text,
                field: .input,
                focusedField: $focusedField
            )
            XAgeGradientActionLabel(title: "主要操作", icon: "checkmark")
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(.clear)
                .frame(height: 96)
                .background(XAgeGlassCardBackground(cornerRadius: 24))
        }
        .padding(24)
        .background(XAgeLiquidBackground().ignoresSafeArea())
    }
}

#Preview("XAGE 样式组件") {
    XAgeStyleComponentsPreview()
}
#endif
