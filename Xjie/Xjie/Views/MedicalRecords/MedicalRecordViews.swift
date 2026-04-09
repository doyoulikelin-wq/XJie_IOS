import SwiftUI

/// 病例列表 — 对应小程序 pages/medical-records/list
struct MedicalRecordListView: View {
    @StateObject private var vm = MedicalRecordListViewModel()

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                // 上传按钮
                Button { vm.showDocumentPicker = true } label: {
                    HStack {
                        Image(systemName: "camera")
                        Text("上传病例").foregroundColor(.appText)
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
                        NavigationLink(destination: MedicalRecordDetailView(docId: item.id)) {
                            documentRow(item)
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .background(Color.appBackground)
        .navigationTitle("历史病例")
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
            DocumentPickerView { data, fileName in
                Task { await vm.uploadRecord(data: data, fileName: fileName) }
            }
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

    private var emptyState: some View {
        EmptyStateView(
            icon: "doc.text",
            title: "暂无病例记录",
            subtitle: "点击上方按钮上传病例"
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
                        Text(doc.name ?? "病例详情").font(.title3).bold()
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
                            Label("AI 整理", systemImage: "sparkles")
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
                            Text("正在生成 AI 总结...").font(.caption).foregroundColor(.appMuted)
                        }
                        .cardStyle()
                    }

                    // 病例数据表格
                    if let csv = doc.csv_data, let columns = csv.columns, let rows = csv.rows {
                        CSVTableView(title: "病例数据", icon: "tablecells", columns: columns, rows: rows)
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
        .navigationTitle("病例详情")
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.fetchDetail(id: docId) }
        .overlay { if vm.loading { ProgressView() } }
    }
}
