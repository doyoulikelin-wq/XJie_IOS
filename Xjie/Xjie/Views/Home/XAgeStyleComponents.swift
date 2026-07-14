//
//  XAgeStyleComponents.swift
//  Xjie
//
//  XAGE 生产页面与 Xcode Canvas 共用的基础视觉组件。
//

import SwiftUI

/// 通用玻璃输入框。焦点字段使用泛型，家庭页面和独立预览可以复用同一套样式。
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

    /// 组合输入行为、焦点切换与共享胶囊背景。
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

/// XAGE 通用渐变主操作按钮标签。
struct XAgeGradientActionLabel: View {
    let title: String
    let icon: String

    /// 组合图标、标题和蓝绿渐变胶囊背景。
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
                .fill(
                    LinearGradient(
                        colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
        )
    }
}

/// XAGE 通用玻璃卡片背景，可由调用方指定圆角。
struct XAgeGlassCardBackground: View {
    var cornerRadius: CGFloat

    /// 绘制半透明材质、白色描边和浅蓝投影。
    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white.opacity(0.56))
            .background(
                .ultraThinMaterial,
                in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.84), lineWidth: 1)
            )
            .shadow(color: Color(hex: "73C8F0").opacity(0.18), radius: 28, x: 0, y: 14)
    }
}

/// XAGE 通用胶囊填充，供输入框、小按钮和提示区域复用。
struct XAgeCapsuleFill: View {
    /// 绘制半透明材质、白色描边和生产环境默认的浅蓝投影。
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.58))
            .background(.ultraThinMaterial, in: Capsule())
            .overlay(Capsule().stroke(.white.opacity(0.88), lineWidth: 1))
            .shadow(color: Color(hex: "7ACAF5").opacity(0.12), radius: 14, x: 0, y: 7)
    }
}

/// XAGE 页面共用的液态渐变底图。
struct XAgeLiquidBackground: View {
    /// 叠加基础渐变、彩色模糊光斑和中部高光，形成液态层次。
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

/// 用药页面专用的高强调主操作按钮标签。
struct XAgeMedicationPrimaryActionLabel: View {
    let title: String
    let icon: String

    /// 绘制更高的蓝绿渐变按钮，并保留用药页面原有投影参数。
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .bold))
            Text(title)
                .font(.system(size: 17, weight: .bold))
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .frame(height: 56)
        .background(
            LinearGradient(
                colors: [Color(hex: "22D4BF"), Color(hex: "1F8EEA")],
                startPoint: .leading,
                endPoint: .trailing
            )
        )
        .clipShape(Capsule())
        .shadow(color: Color(hex: "20CDB1").opacity(0.24), radius: 16, x: 0, y: 10)
    }
}

/// 用药页面专用玻璃卡片背景。
struct XAgeMedicationGlassCard: View {
    var cornerRadius: CGFloat

    /// 绘制用药卡片的白色半透明底、描边和浅蓝投影。
    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white.opacity(0.58))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.76), lineWidth: 1)
            )
            .shadow(color: Color(hex: "78BCE8").opacity(0.12), radius: 22, x: 0, y: 10)
    }
}

/// 用药页面专用胶囊填充，用于快捷气泡和编辑输入区。
struct XAgeMedicationCapsuleFill: View {
    /// 绘制用药模块原有的白色填充、描边和轻投影。
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.62))
            .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
            .shadow(color: Color(hex: "78BCE8").opacity(0.10), radius: 10, x: 0, y: 5)
    }
}

/// 用药管理页面专用的轻量渐变底图。
struct XAgeMedicationLiquidBackground: View {
    /// 绘制用药页面原有的浅蓝至白色渐变。
    var body: some View {
        LinearGradient(
            colors: [
                Color(hex: "D9F5FF"),
                Color(hex: "EAF9FF"),
                Color(hex: "F8FCFF")
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }
}
