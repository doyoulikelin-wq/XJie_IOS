import SwiftUI

enum MedicalAssistantDestination: Equatable {
    case review(HealthReportWorkflowRoute)
    case legacyDetail(documentID: String)
}

enum MedicalAssistantRoutingContract {
    static let title = "就医助手"

    static func destination(for document: HealthDocument) -> MedicalAssistantDestination {
        if let route = document.reportWorkflowRoute {
            return .review(route)
        }
        return .legacyDetail(documentID: document.id)
    }
}

/// 病例列表 — 对应小程序 pages/medical-records/list
struct MedicalRecordListView: View {
    @StateObject private var vm = MedicalRecordListViewModel()
    @EnvironmentObject private var authManager: AuthManager

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 7) {
                    Label("就医助手", systemImage: "cross.case.fill")
                        .font(.headline)
                        .foregroundColor(.appPrimary)
                    Text("上传门诊记录、出院小结等就医资料后，可在列表和详情中查看原件与资料整理结果。")
                        .font(.subheadline)
                        .foregroundColor(.appText)
                    Text("仅整理你上传的资料，不替代医生诊断、审方或安排随访。")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .cardStyle()

                Button { vm.showDocumentPicker = true } label: {
                    HStack {
                        Image(systemName: "doc.badge.plus")
                        Text("添加就医资料").foregroundColor(.appText)
                    }
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.appPrimary.opacity(0.1))
                    .cornerRadius(10)
                }
                .disabled(vm.uploading)

                if vm.items.isEmpty && !vm.loading {
                    emptyState
                } else {
                    ForEach(vm.items) { item in
                        NavigationLink(destination: destination(for: item)) {
                            documentRow(item)
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .background(Color.appBackground)
        .navigationTitle(MedicalAssistantRoutingContract.title)
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.fetchList() }
        .refreshable { await vm.fetchList() }
        .overlay { if vm.loading && !vm.uploading { ProgressView() } }
        .overlay {
            if vm.uploading {
                ZStack {
                    Color.black.opacity(0.3).ignoresSafeArea()
                    VStack(spacing: 16) {
                        ProgressView()
                            .scaleEffect(1.3)
                            .tint(.white)
                        Text(vm.uploadStage)
                            .font(.subheadline).bold()
                            .foregroundColor(.white)
                    }
                    .padding(32)
                    .background(.ultraThinMaterial)
                    .cornerRadius(16)
                }
            }
        }
        .overlay {
            if let msg = vm.successMessage {
                VStack {
                    Spacer()
                    Text(msg)
                        .font(.subheadline).bold()
                        .foregroundColor(.white)
                        .padding(.horizontal, 24).padding(.vertical, 12)
                        .background(Color.appPrimary)
                        .cornerRadius(20)
                        .padding(.bottom, 40)
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
                .onAppear {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                        withAnimation { vm.successMessage = nil }
                    }
                }
            }
        }
        .animation(.easeInOut, value: vm.successMessage)
        .sheet(isPresented: $vm.showDocumentPicker) {
            DocumentPickerView(
                onPick: { data, fileName in
                    Task { await vm.uploadRecord(data: data, fileName: fileName) }
                },
                onError: { message in
                    vm.errorMessage = message
                }
            )
        }
        .alert("确认删除", isPresented: $vm.showDeleteAlert) {
            Button("删除", role: .destructive) { Task { await vm.confirmDelete() } }
            Button("取消", role: .cancel) {}
        } message: {
            Text("删除后无法恢复，确定吗？")
        }
        .alert("错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    /// CODE-01: 使用共享标签组件
    private func documentRow(_ item: HealthDocument) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                if let date = item.doc_date, !date.isEmpty {
                    Text(String(date.prefix(10)))
                        .font(.subheadline).bold()
                        .foregroundColor(.appText)
                } else {
                    Text(item.name ?? "未命名")
                        .font(.subheadline).bold()
                        .foregroundColor(.appText)
                }
                if let brief = item.ai_brief, !brief.isEmpty {
                    Text(brief)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                        .lineLimit(1)
                }
                HStack(spacing: 5) {
                    Text(item.xAgeStatusLabel)
                        .font(.caption2.bold())
                        .foregroundColor(item.xAgeStatusColor)
                    Text("·")
                        .font(.caption2)
                        .foregroundColor(.appMuted)
                    Text(item.xAgeReviewActionTitle)
                        .font(.caption2)
                        .foregroundColor(.appMuted)
                        .lineLimit(1)
                }
            }
            Spacer()
            Button {
                vm.deleteItem(id: item.id)
            } label: {
                Image(systemName: "trash")
                    .font(.caption)
                    .foregroundColor(.appDanger.opacity(0.7))
            }
            .buttonStyle(.plain)
            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundColor(.appMuted)
        }
        .cardStyle()
        .contextMenu {
            Button(role: .destructive) {
                vm.deleteItem(id: item.id)
            } label: {
                Label("删除", systemImage: "trash")
            }
        }
    }

    @ViewBuilder
    private func destination(for item: HealthDocument) -> some View {
        switch MedicalAssistantRoutingContract.destination(for: item) {
        case .review(let route):
            HealthReportReviewView(
                route: route,
                accountScope: authManager.accountScope,
                documentTitle: item.xAgeDisplayTitle
            )
        case .legacyDetail(let documentID):
            MedicalRecordDetailView(docId: documentID)
        }
    }

    private var emptyState: some View {
        EmptyStateView(
            icon: "doc.text",
            title: "暂无就医资料",
            subtitle: "可通过上方按钮添加真实资料"
        )
    }
}

/// 病例详情 — 对应小程序 pages/medical-records/detail
struct MedicalRecordDetailView: View {
    let docId: String
    @StateObject private var vm = DocumentDetailViewModel()
    @State private var showOriginal = false

    var body: some View {
        ScrollView {
            if let doc = vm.doc {
                VStack(alignment: .leading, spacing: 12) {
                    // 标题
                    VStack(alignment: .leading, spacing: 4) {
                        Text(doc.name ?? "就医资料详情").font(.title3).bold()
                        if let date = doc.doc_date, !date.isEmpty {
                            Text(String(date.prefix(10)))
                                .font(.caption)
                                .foregroundColor(.appMuted)
                        }
                    }
                    .cardStyle()

                    // AI 总结内容
                    if let summary = doc.ai_summary, !summary.isEmpty {
                        VStack(alignment: .leading, spacing: 8) {
                            Label("资料整理（非诊断）", systemImage: "sparkles")
                                .font(.headline)
                                .foregroundColor(.appPrimary)
                            Text(summary)
                                .font(.body)
                                .foregroundColor(.appText)
                                .lineSpacing(4)
                        }
                        .cardStyle()
                    } else if vm.loading {
                        HStack {
                            ProgressView().controlSize(.small)
                            Text("正在整理上传资料...").font(.caption).foregroundColor(.appMuted)
                        }
                        .cardStyle()
                    }

                    // 病例数据表格
                    if let csv = doc.csv_data, let columns = csv.columns, let rows = csv.rows {
                        CSVTableView(title: "结构化资料", icon: "tablecells", columns: columns, rows: rows)
                    }

                    // 查看原件（原始上传图片）
                    if doc.file_url != nil {
                        Button {
                            withAnimation { showOriginal.toggle() }
                        } label: {
                            HStack {
                                Image(systemName: showOriginal ? "eye.slash" : "eye")
                                Text(showOriginal ? "收起原件" : "查看原件")
                            }
                            .font(.subheadline)
                            .foregroundColor(.appPrimary)
                            .frame(maxWidth: .infinity)
                            .padding(10)
                            .background(Color.appPrimary.opacity(0.08))
                            .cornerRadius(8)
                        }

                        if showOriginal, let fileUrl = doc.file_url {
                            OriginalFileView(fileUrl: fileUrl)
                        }
                    }
                }
                .padding(.horizontal, 16)
            }
        }
        .background(Color.appBackground)
        .navigationTitle("就医资料详情")
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.fetchDetail(id: docId) }
        .overlay { if vm.loading { ProgressView() } }
    }
}
