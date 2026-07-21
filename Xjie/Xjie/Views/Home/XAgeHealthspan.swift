import SwiftUI

private struct XAgeInfoSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("X年龄原理")
                            .font(.title2.bold())
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("尚未启用 · 等待版本化验证")
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                    Spacer()
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "2A79BB"))
                            .frame(width: 36, height: 36)
                            .background(XAgeCapsuleFill())
                    }
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.info.close")
                    .accessibilityLabel("关闭 X年龄原理")
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(spacing: 10) {
                            infoMetric(title: "X年龄", value: "--")
                            infoMetric(title: "差值", value: "--")
                            infoMetric(title: "进度", value: "--")
                        }

                        Text("X年龄只会在服务端版本化算法、输入范围、账户归属和结果复现校验通过后启用。当前不会使用本地估算，也不会展示年龄、差值、衰老进度或周趋势。")
                            .font(.body)
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)

                        VStack(alignment: .leading, spacing: 8) {
                            Text("当前状态")
                                .font(.headline)
                                .foregroundStyle(Color(hex: "173F64"))
                            Text("等待版本化验证")
                                .font(.body.weight(.semibold))
                                .foregroundStyle(Color(hex: "128F92"))
                            Text("你仍可继续同步健康数据或上传报告；数据同步完成不代表 X年龄已经生成。")
                                .font(.subheadline)
                                .foregroundStyle(Color(hex: "5D7890"))
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(16)
                        .background(XAgeCapsuleFill())
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))
                }
                .scrollIndicators(.hidden)
            }
            .padding(24)
        }
    }

    private func infoMetric(title: String, value: String) -> some View {
        VStack(spacing: 5) {
            Text(value)
                .font(.title3.bold())
                .foregroundStyle(Color(hex: "173F64"))
            Text(title)
                .font(.caption.weight(.medium))
                .foregroundStyle(Color(hex: "6F879B"))
        }
        .frame(maxWidth: .infinity)
        .frame(minHeight: 58)
        .background(XAgeCapsuleFill())
    }
}

struct XAgeHealthspanView: View {
    @Binding var selectedSection: XAgeTopSection
    let infoRequest: Int
    @State private var showInfo = false

    private var score: XAgeAgeScore {
        XAgeTrustedScorePresentationPolicy.currentPresentation().xAge
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                VStack(spacing: 5) {
                    Text("X年龄")
                        .font(.title2.bold())
                        .foregroundStyle(Color(hex: "123E67"))
                    Text("尚未启用")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Color(hex: "128F92"))
                }
                .padding(.top, 12)
                .accessibilityIdentifier("xage.xage.disabled")

                ZStack {
                    Circle()
                        .fill(
                            RadialGradient(
                                colors: [Color(hex: "8EF7E6").opacity(0.24), Color(hex: "21B5FF").opacity(0.12), .clear],
                                center: .center,
                                startRadius: 20,
                                endRadius: 170
                            )
                        )
                        .frame(width: 272, height: 272)
                        .blur(radius: 7)
                    Image("x_age_particle_ring_blue_green")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 254, height: 254)
                    Circle()
                        .fill(.white.opacity(0.54))
                        .background(.ultraThinMaterial, in: Circle())
                        .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                        .frame(width: 154, height: 154)
                    VStack(spacing: 4) {
                        Text(score.displayAge)
                            .font(.system(.largeTitle, design: .rounded, weight: .bold))
                            .foregroundStyle(Color(hex: "12324F"))
                            .accessibilityIdentifier("xage.xage.age")
                        HStack(spacing: 5) {
                            Text("X年龄")
                                .font(.headline)
                                .foregroundStyle(Color(hex: "45677F"))
                            Button {
                                showInfo = true
                            } label: {
                                Image(systemName: "info.circle.fill")
                                    .foregroundStyle(Color(hex: "18AFA7"))
                                    .frame(width: 44, height: 44)
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("xage.xage.info.inline")
                            .accessibilityLabel("X年龄原理")
                        }
                        Text(score.displayDelta)
                            .font(.subheadline.bold())
                            .foregroundStyle(Color(hex: "10A88E"))
                    }
                }
                .frame(minHeight: 262)

                XAgePaceCard()

                VStack(alignment: .leading, spacing: 8) {
                    Text("等待版本化验证")
                        .font(.headline)
                        .foregroundStyle(Color(hex: "173F64"))
                    Text("当前不展示本地计算的年龄、差值、衰老进度或周趋势。服务端评分契约冻结并通过验证后再启用。")
                        .font(.subheadline)
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(XAgeGlassCardBackground(cornerRadius: 26))
                .accessibilityIdentifier("xage.xage.validation")
                .padding(.bottom, 20)
            }
            .padding(.horizontal, 24)
        }
        .scrollIndicators(.hidden)
        .onChange(of: infoRequest) { _, _ in
            guard selectedSection == .xAge else { return }
            showInfo = true
        }
        .sheet(isPresented: $showInfo) {
            XAgeInfoSheet()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
    }
}

private struct XAgePaceCard: View {
    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text("衰老进度")
                    .font(.headline)
                    .foregroundStyle(Color(hex: "173F64"))
                Text("版本化验证完成后展示")
                    .font(.subheadline)
                    .foregroundStyle(Color(hex: "6A8197"))
            }
            Spacer()
            Text("--")
                .font(.title.bold())
                .foregroundStyle(Color(hex: "17324E"))
        }
        .padding(16)
        .frame(maxWidth: .infinity)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("xage.xage.pace.unavailable")
    }
}
