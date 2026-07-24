import SwiftUI

/// 快捷功能“就医助手”首页。
///
/// 页面只展示服务端已保存的病人概况和时间证据；生成条件由服务端判断，
/// 客户端的时间比较仅用于提示，不能替代服务端写入约束。
@MainActor
struct MedicalAssistantDashboardView: View {
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var vm: MedicalAssistantViewModel

    /// 生产初始化器，连接真实仓库。
    init() {
        _vm = StateObject(wrappedValue: MedicalAssistantViewModel())
    }

    /// - Parameter viewModel: 测试或预览可注入的确定性 ViewModel。
    init(viewModel: MedicalAssistantViewModel) {
        _vm = StateObject(wrappedValue: viewModel)
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 16) {
                    header
                    overviewCard
                    timingCard
                    recentDocumentsCard
                    safetyNote
                }
                .padding(.horizontal, 16)
                .padding(.top, 12)
                .padding(.bottom, 24)
            }
            .accessibilityIdentifier("xage.medicalAssistant.scroll")
            .refreshable {
                await vm.load(accountScope: authManager.accountScope)
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            generationBar
        }
        .task(id: authManager.accountScope) {
            await vm.load(accountScope: authManager.accountScope)
        }
        .alert("就医助手", isPresented: Binding(
            get: { vm.noticeMessage != nil },
            set: { if !$0 { vm.noticeMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.noticeMessage ?? "")
        }
        .alert("无法完成", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("重试") {
                Task { await vm.load(accountScope: authManager.accountScope) }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    private var header: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [Color(hex: "1675DB"), Color(hex: "50D4C1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                Image(systemName: "cross.case.fill")
                    .font(.system(size: 27, weight: .semibold))
                    .foregroundStyle(.white)
            }
            .frame(width: 62, height: 62)
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4) {
                Text("就医助手")
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Text("整理资料，生成给医生看的病人概况")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("xage.medicalAssistant.header")
    }

    @ViewBuilder
    private var overviewCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("病人概况", systemImage: "person.text.rectangle.fill")
                    .font(.system(size: 19, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                Spacer()
                statusBadge
            }

            if vm.loading && vm.overview == nil {
                HStack(spacing: 10) {
                    ProgressView()
                    Text("正在读取最新概况…")
                        .foregroundStyle(Color(hex: "607B91"))
                }
                .frame(maxWidth: .infinity, minHeight: 150)
                .accessibilityIdentifier("xage.medicalAssistant.loading")
            } else if let overview = vm.overview, overview.hasSummary {
                Text(overview.summary)
                    .font(.system(size: 16))
                    .foregroundStyle(Color(hex: "173B59"))
                    .lineSpacing(6)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("xage.medicalAssistant.summary")
            } else {
                VStack(spacing: 12) {
                    Image(systemName: "doc.text.magnifyingglass")
                        .font(.system(size: 34, weight: .medium))
                        .foregroundStyle(Color(hex: "3D91DD"))
                    Text("还没有生成过概况，请点击下方按钮生成。")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Color(hex: "456982"))
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, minHeight: 150)
                .accessibilityIdentifier("xage.medicalAssistant.empty")
            }
        }
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
    }

    @ViewBuilder
    private var statusBadge: some View {
        if let overview = vm.overview {
            let title = overview.hasNewerUpload ? "有新资料" : (overview.hasSummary ? "已生成" : "未生成")
            let color = overview.hasNewerUpload ? Color(hex: "E27A22") : Color(hex: "1AAE96")
            Text(title)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(color)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(color.opacity(0.12), in: Capsule())
                .accessibilityIdentifier("xage.medicalAssistant.status")
        }
    }

    private var timingCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("更新时间")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 10) {
                    timeCell(
                        icon: "sparkles",
                        title: "概况生成时间",
                        value: formattedTime(vm.overview?.generated_at)
                    )
                    timeCell(
                        icon: "arrow.up.doc.fill",
                        title: "最近上传报告",
                        value: formattedTime(vm.overview?.latest_report_uploaded_at)
                    )
                }

                VStack(spacing: 10) {
                    timeCell(
                        icon: "sparkles",
                        title: "概况生成时间",
                        value: formattedTime(vm.overview?.generated_at)
                    )
                    timeCell(
                        icon: "arrow.up.doc.fill",
                        title: "最近上传报告",
                        value: formattedTime(vm.overview?.latest_report_uploaded_at)
                    )
                }
            }
        }
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
        .accessibilityIdentifier("xage.medicalAssistant.times")
    }

    /// 构建一格时间证据。
    /// - Parameters:
    ///   - icon: SF Symbol 名称。
    ///   - title: 时间类型标题。
    ///   - value: 已本地化的时间文本。
    private func timeCell(icon: String, title: String, value: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Color(hex: "1675DB"))
                .frame(width: 34, height: 34)
                .background(Color(hex: "1675DB").opacity(0.1), in: Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color(hex: "71879A"))
                Text(value)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173B59"))
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, minHeight: 62, alignment: .leading)
        .padding(.horizontal, 11)
        .background(.white.opacity(0.48), in: RoundedRectangle(cornerRadius: 18))
    }

    private var recentDocumentsCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("最近就医资料")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .accessibilityIdentifier("xage.medicalAssistant.documents.title")
                Spacer()
                Text("近一年 \(vm.overview?.report_count_last_year ?? 0) 份已入库")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color(hex: "6B8195"))
            }

            if let documents = vm.overview?.recent_documents, !documents.isEmpty {
                ForEach(Array(documents.enumerated()), id: \.element.id) { index, document in
                    NavigationLink {
                        MedicalRecordDetailView(docId: document.document_id)
                    } label: {
                        recentDocumentRow(document)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.medicalAssistant.document.\(document.document_id)")
                    if index < documents.count - 1 {
                        Divider().opacity(0.45)
                    }
                }
            } else {
                Text("暂无已上传的病历、就诊单或检查报告")
                    .font(.system(size: 14))
                    .foregroundStyle(Color(hex: "71879A"))
                    .frame(maxWidth: .infinity, minHeight: 72)
                    .accessibilityIdentifier("xage.medicalAssistant.documents.empty")
            }
        }
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    /// 构建一条最近资料入口。
    /// - Parameter document: 服务端返回的资料元数据。
    private func recentDocumentRow(_ document: MedicalAssistantRecentDocument) -> some View {
        HStack(spacing: 12) {
            Image(systemName: document.status == "admitted" ? "doc.text.fill" : "clock.fill")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(document.status == "admitted" ? Color(hex: "1675DB") : Color(hex: "E28A35"))
                .frame(width: 38, height: 38)
                .background(.white.opacity(0.62), in: RoundedRectangle(cornerRadius: 13))
            VStack(alignment: .leading, spacing: 3) {
                Text(document.title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Color(hex: "173B59"))
                    .lineLimit(2)
                Text(documentMetadata(document))
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "71879A"))
                    .lineLimit(2)
            }
            Spacer(minLength: 6)
            Text(documentStatus(document.status))
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(document.status == "admitted" ? Color(hex: "1AAE96") : Color(hex: "D57826"))
            Image(systemName: "chevron.right")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "91A7BA"))
        }
        .contentShape(Rectangle())
        .frame(minHeight: 58)
    }

    private var safetyNote: some View {
        Label(
            "概况仅整理本人已确认并入库的资料，供就诊沟通参考；请同时向医生出示原件。",
            systemImage: "checkmark.shield.fill"
        )
        .font(.system(size: 12))
        .foregroundStyle(Color(hex: "607B91"))
        .fixedSize(horizontal: false, vertical: true)
        .padding(.horizontal, 4)
    }

    private var generationBar: some View {
        VStack(spacing: 0) {
            Divider().opacity(0.25)
            Button {
                Task { await vm.generate(accountScope: authManager.accountScope) }
            } label: {
                HStack(spacing: 9) {
                    if vm.generating {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Image(systemName: "sparkles")
                    }
                    Text(vm.generating ? "正在生成病人概况…" : "生成病人概况")
                        .font(.system(size: 18, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, minHeight: 56)
                .background(
                    LinearGradient(
                        colors: [Color(hex: "176FE0"), Color(hex: "43D1B8")],
                        startPoint: .leading,
                        endPoint: .trailing
                    ),
                    in: Capsule()
                )
                .shadow(color: Color(hex: "176FE0").opacity(0.2), radius: 14, y: 6)
            }
            .buttonStyle(.plain)
            .disabled(vm.generating || vm.loading)
            .accessibilityIdentifier("xage.medicalAssistant.generate")
            .accessibilityHint("服务端会先判断最近上传报告是否晚于上次概况生成时间")
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
        }
        .background(.ultraThinMaterial)
    }

    /// 格式化服务端时间；入参为空时显示“暂无记录”。
    private func formattedTime(_ raw: String?) -> String {
        guard let date = MedicalAssistantOverview.date(from: raw) else { return "暂无记录" }
        return date.formatted(
            .dateTime
                .year()
                .month(.twoDigits)
                .day(.twoDigits)
                .hour(.twoDigits(amPM: .omitted))
                .minute(.twoDigits)
                .locale(Locale(identifier: "zh_CN"))
        )
    }

    private func documentMetadata(_ document: MedicalAssistantRecentDocument) -> String {
        let date = formattedTime(document.document_date ?? document.uploaded_at)
        return [date, document.hospital]
            .compactMap { $0 }
            .filter { !$0.isEmpty }
            .joined(separator: " · ")
    }

    private func documentStatus(_ status: String) -> String {
        switch status {
        case "admitted": return "已入库"
        case "failed": return "处理失败"
        default: return "处理中"
        }
    }
}
