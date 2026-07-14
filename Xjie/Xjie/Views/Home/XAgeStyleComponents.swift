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

// MARK: - Canvas 样式陈列

private enum XAgeStylePreviewField: Hashable {
    case singleLine
}

/// 只使用本地状态的 XAGE 样式陈列页，Canvas 加载时不会创建业务 ViewModel 或发起网络请求。
struct XAgeStyleComponentsPreview: View {
    @State private var singleLineText = "示例输入"
    @State private var feedbackText = "请描述你遇到的问题或改进建议"
    @FocusState private var focusedField: XAgeStylePreviewField?

    /// 提供给 Canvas 和编译契约测试使用的无依赖初始化入口。
    init() {}

    /// 在完整液态背景上按区域组合各类共享样式，较大的表达式被拆到独立属性中。
    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                LazyVStack(alignment: .leading, spacing: 22) {
                    glassCardSection
                    capsuleSection
                    actionSection
                    singleLineInputSection
                    feedbackEditorSection
                    quickOptionsSection
                    medicationComparisonSection
                }
                .padding(20)
            }
        }
    }

    /// 展示常用的 20 与 28 两种玻璃卡片圆角。
    private var glassCardSection: some View {
        XAgeStylePreviewSection(title: "玻璃卡片") {
            HStack(spacing: 12) {
                XAgeStylePreviewCard(title: "圆角 20", cornerRadius: 20)
                XAgeStylePreviewCard(title: "圆角 28", cornerRadius: 28)
            }
        }
    }

    /// 并列展示生产浅蓝阴影和临时黑色阴影实验，便于 Canvas 中直接比较。
    private var capsuleSection: some View {
        XAgeStylePreviewSection(title: "胶囊与阴影") {
            HStack(spacing: 12) {
                XAgeStylePreviewCapsule(title: "生产阴影", usesBlackShadow: false)
                XAgeStylePreviewCapsule(title: "黑色阴影实验", usesBlackShadow: true)
            }
        }
    }

    /// 展示通用 XAGE 渐变主操作按钮。
    private var actionSection: some View {
        XAgeStylePreviewSection(title: "通用主操作按钮") {
            XAgeGradientActionLabel(title: "提交反馈", icon: "paperplane.fill")
        }
    }

    /// 使用预览自己的焦点枚举，验证泛型玻璃输入框无需依赖家庭页面状态。
    private var singleLineInputSection: some View {
        XAgeStylePreviewSection(title: "单行玻璃输入") {
            XAgeGlassTextField(
                placeholder: "请输入内容",
                text: $singleLineText,
                field: .singleLine,
                focusedField: $focusedField
            )
        }
    }

    /// 复现问题反馈页的 TextEditor 尺寸、内边距和共享胶囊背景。
    private var feedbackEditorSection: some View {
        XAgeStylePreviewSection(title: "问题反馈多行输入") {
            TextEditor(text: $feedbackText)
                .frame(minHeight: 180)
                .padding(10)
                .scrollContentBackground(.hidden)
                .background(XAgeCapsuleFill())
        }
    }

    /// 集中展示剂量、频次和使用说明三组生产快捷选项。
    private var quickOptionsSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            XAgeStylePreviewQuickOptions(
                title: "剂量快捷添加",
                options: MedicationQuickInput.dosageOptions
            )
            XAgeStylePreviewQuickOptions(
                title: "频次快捷添加",
                options: MedicationQuickInput.frequencyOptions
            )
            XAgeStylePreviewQuickOptions(
                title: "使用说明快捷添加",
                options: MedicationQuickInput.instructionOptions
            )
        }
    }

    /// 同时展示通用卡片和用药专用背景、卡片、胶囊及主操作按钮。
    private var medicationComparisonSection: some View {
        XAgeStylePreviewSection(title: "通用 / 用药样式对照") {
            HStack(spacing: 12) {
                XAgeStylePreviewComparisonCard(title: "通用") {
                    XAgeGlassCardBackground(cornerRadius: 22)
                }
                XAgeStylePreviewComparisonCard(title: "用药") {
                    ZStack {
                        XAgeMedicationLiquidBackground()
                        XAgeMedicationGlassCard(cornerRadius: 22)
                            .padding(6)
                    }
                }
            }

            Text("用药胶囊")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "1268BD"))
                .frame(maxWidth: .infinity)
                .frame(height: 36)
                .background(XAgeMedicationCapsuleFill())

            XAgeMedicationPrimaryActionLabel(title: "保存用药", icon: "checkmark")
        }
    }
}

/// 统一预览区块的标题、间距和内容布局。
private struct XAgeStylePreviewSection<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    /// 将区块标题和调用方提供的样式示例纵向排列。
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            content
        }
    }
}

/// 展示指定圆角值的通用玻璃卡片。
private struct XAgeStylePreviewCard: View {
    let title: String
    let cornerRadius: CGFloat

    /// 用固定高度保证两个圆角样例可以稳定并排比较。
    var body: some View {
        Text(title)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Color(hex: "365F80"))
            .frame(maxWidth: .infinity)
            .frame(height: 84)
            .background(XAgeGlassCardBackground(cornerRadius: cornerRadius))
    }
}

/// 胶囊阴影对照样例；黑色阴影实现仅服务于 Canvas，不会传回生产组件。
private struct XAgeStylePreviewCapsule: View {
    let title: String
    let usesBlackShadow: Bool

    /// 根据对照开关选择生产胶囊或复现临时实验参数的黑色阴影胶囊。
    var body: some View {
        Text(title)
            .font(.system(size: 12, weight: .bold))
            .foregroundStyle(Color(hex: "365F80"))
            .frame(maxWidth: .infinity)
            .frame(height: 42)
            .background {
                if usesBlackShadow {
                    blackShadowCapsule
                } else {
                    XAgeCapsuleFill()
                }
            }
    }

    /// 复现已删除临时文件中的黑色阴影，其他填充和描边参数与生产胶囊一致。
    private var blackShadowCapsule: some View {
        Capsule()
            .fill(.white.opacity(0.58))
            .background(.ultraThinMaterial, in: Capsule())
            .overlay(Capsule().stroke(.white.opacity(0.88), lineWidth: 1))
            .shadow(color: .black.opacity(0.12), radius: 14, x: 0, y: 7)
    }
}

/// 使用简单自适应网格展示用药快捷气泡，不复制生产页面的流式布局算法。
private struct XAgeStylePreviewQuickOptions: View {
    let title: String
    let options: [String]

    /// 根据可用宽度自动调整列数，并沿用用药专用胶囊背景。
    var body: some View {
        XAgeStylePreviewSection(title: title) {
            LazyVGrid(
                columns: [GridItem(.adaptive(minimum: 88), spacing: 8)],
                spacing: 8
            ) {
                ForEach(options, id: \.self) { option in
                    Button(option) {}
                        .buttonStyle(.plain)
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "1268BD"))
                        .frame(maxWidth: .infinity)
                        .frame(height: 36)
                        .background(XAgeMedicationCapsuleFill())
                }
            }
        }
    }
}

/// 将任意背景样式包装为统一尺寸的并排对照卡。
private struct XAgeStylePreviewComparisonCard<Background: View>: View {
    let title: String
    @ViewBuilder let background: Background

    /// 在固定尺寸内绘制标题及调用方提供的背景实现。
    var body: some View {
        Text(title)
            .font(.system(size: 13, weight: .bold))
            .foregroundStyle(Color(hex: "365F80"))
            .frame(maxWidth: .infinity)
            .frame(height: 86)
            .background(background)
    }
}

#Preview("XAGE 样式组件") {
    XAgeStyleComponentsPreview()
}
