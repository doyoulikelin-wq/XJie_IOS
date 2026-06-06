import SwiftUI

/// 病史整理 — 与 Android `PatientHistoryScreen` 对齐
struct PatientHistoryView: View {
    @StateObject private var vm = PatientHistoryViewModel()
    @State private var isSummaryExpanded = false
    @State private var expandedSections: Set<String> = ["diagnoses", "medications", "recent_findings", "care_goals"]
    /// 高亮跳转 — 来自 Chat 或健康数据页的 focus 参数（diagnoses / medications / ...）
    var focusKey: String?
    /// 上层注入回调，用于跳转健康数据 focus
    var onJumpToHealthData: ((String) -> Void)?

    var body: some View {
        ScrollViewReader { proxy in
            List {
                listRow(passportHeader)
                listRow(summaryCard)
                listRow(evidenceCard)
                if !vm.profile.key_metrics.isEmpty {
                    listRow(metricsCard)
                }
                if !vm.profile.missing_sections.isEmpty {
                    listRow(missingCard)
                }
                listRow(quickSectionBar(proxy: proxy))
                ForEach(PatientHistorySectionCatalog.all) { meta in
                    listRow(sectionEditor(meta: meta))
                        .id("section-\(meta.key)")
                }
                listRow(saveButton)
                Color.clear
                    .frame(height: 20)
                    .listRowInsets(EdgeInsets())
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.appBackground)
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.appBackground)
            .navigationTitle("病史整理")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button {
                        Task { await vm.save() }
                    } label: {
                        Text(vm.saving ? "保存中" : "保存")
                    }
                    .disabled(vm.saving || vm.loading)
                }
            }
            .toolbar(.hidden, for: .tabBar)
            .task {
                await vm.load()
                if let key = focusKey {
                    try? await Task.sleep(for: .milliseconds(300))
                    withAnimation { proxy.scrollTo("section-\(key)", anchor: .top) }
                }
            }
            .refreshable { await vm.load() }
            .overlay {
                if vm.loading && vm.profile.sections.isEmpty {
                    ProgressView("加载中...")
                }
            }
            .alert("错误", isPresented: Binding(
                get: { vm.errorMessage != nil },
                set: { if !$0 { vm.errorMessage = nil } }
            )) {
                Button("确定", role: .cancel) {}
            } message: { Text(vm.errorMessage ?? "") }
            .alert("提示", isPresented: Binding(
                get: { vm.infoMessage != nil },
                set: { if !$0 { vm.infoMessage = nil } }
            )) {
                Button("好", role: .cancel) {}
            } message: { Text(vm.infoMessage ?? "") }
        }
    }

    private func listRow<Content: View>(_ content: Content) -> some View {
        content
            .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
            .listRowSeparator(.hidden)
            .listRowBackground(Color.appBackground)
    }

    // MARK: - 医生摘要

    private var passportHeader: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("就诊资料工作台")
                        .font(.headline)
                        .foregroundColor(.white)
                    Text("只保留已确认或有资料支持的事实，缺失项单独列出。")
                        .font(.caption)
                        .foregroundColor(.white.opacity(0.86))
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 2) {
                    Text("\(Int(vm.profile.completeness * 100))%")
                        .font(.title2.bold())
                        .foregroundColor(.white)
                    Text("完整度")
                        .font(.caption2)
                        .foregroundColor(.white.opacity(0.78))
                }
            }

            ProgressView(value: vm.profile.completeness)
                .tint(.white)

            HStack(spacing: 8) {
                statusTile(title: "病例", value: "\(vm.profile.evidence_overview.record_count)")
                statusTile(title: "体检", value: "\(vm.profile.evidence_overview.exam_count)")
                statusTile(title: "待补", value: "\(vm.profile.missing_sections.count)")
            }
        }
        .padding(16)
        .background(
            LinearGradient(
                colors: [Color.appGradientEnd, Color.appGradientStart],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .shadow(color: Color.appPrimary.opacity(0.18), radius: 18, x: 0, y: 8)
    }

    private func statusTile(title: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .font(.headline.bold())
                .foregroundColor(.white)
            Text(title)
                .font(.caption2)
                .foregroundColor(.white.opacity(0.8))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Color.white.opacity(0.15))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var summaryCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                withAnimation(.easeInOut(duration: 0.18)) {
                    isSummaryExpanded.toggle()
                }
            } label: {
                HStack {
                    Image(systemName: isSummaryExpanded ? "chevron.down.circle.fill" : "chevron.right.circle")
                        .foregroundColor(.appPrimary)
                    Image(systemName: "stethoscope")
                    Text("医生可读摘要").font(.headline)
                    Spacer()
                    Text("完整度 \(Int(vm.profile.completeness * 100))%")
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
            }
            .buttonStyle(.plain)

            if isSummaryExpanded {
                Text("用一两段话向医生说明你的核心健康问题、当前关注点和已知诊断。")
                    .font(.caption)
                    .foregroundColor(.appMuted)
                TextEditor(text: Binding(
                    get: { vm.profile.doctor_summary },
                    set: { vm.updateDoctorSummary($0) }
                ))
                .frame(minHeight: 140)
                .padding(8)
                .background(Color.appBackground)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.appStroke, lineWidth: 1))
                .clipShape(RoundedRectangle(cornerRadius: 10))
            } else {
                Text(vm.profile.doctor_summary.isEmpty ? "暂无摘要" : vm.profile.doctor_summary)
                    .font(.subheadline)
                    .foregroundColor(.appText)
                    .lineLimit(4)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.appSoftFill)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
        }
        .cardStyle()
    }

    // MARK: - 资料证据概览

    private var evidenceCard: some View {
        let ev = vm.profile.evidence_overview
        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: "doc.text.magnifyingglass")
                Text("资料证据").font(.headline)
                Spacer()
            }
            HStack(spacing: 12) {
                evidenceTile(title: "历史病例", value: "\(ev.record_count)", subtitle: ev.latest_record_date ?? "无记录")
                evidenceTile(title: "历史体检", value: "\(ev.exam_count)", subtitle: ev.latest_exam_date ?? "无记录")
            }
        }
        .cardStyle()
    }

    private func evidenceTile(title: String, value: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.caption).foregroundColor(.appMuted)
            Text(value).font(.title2).bold().foregroundColor(.appPrimary)
            Text(subtitle).font(.caption2).foregroundColor(.appMuted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(Color.appBackground)
        .cornerRadius(8)
    }

    // MARK: - 关键异常值

    private var metricsCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: "exclamationmark.triangle")
                    .foregroundColor(.appWarning)
                Text("关键异常值").font(.headline)
                Spacer()
            }
            Text("以下数据来自你最近的体检/病例，建议向医生说明：")
                .font(.caption).foregroundColor(.appMuted)
            ForEach(vm.profile.key_metrics) { metric in
                HStack(alignment: .top, spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(metric.name).font(.subheadline).bold()
                        Text("\(metric.value)\(metric.unit ?? "")")
                            .font(.subheadline)
                            .foregroundColor(.appWarning)
                        if let d = metric.date_label {
                            Text(d).font(.caption2).foregroundColor(.appMuted)
                        }
                    }
                    Spacer()
                    Button("去核对") {
                        onJumpToHealthData?(metric.focus)
                    }
                    .font(.caption)
                    .buttonStyle(.bordered)
                }
                .padding(8)
                .background(Color.appBackground)
                .cornerRadius(8)
            }
        }
        .cardStyle()
    }

    // MARK: - 缺失任务

    private var missingCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: "list.bullet.clipboard")
                Text("还需要补充").font(.headline)
                Spacer()
            }
            ForEach(vm.profile.missing_sections) { item in
                HStack {
                    Image(systemName: "circle")
                        .foregroundColor(.appMuted)
                    Text(item.label).font(.subheadline)
                    Spacer()
                }
                .padding(.vertical, 4)
            }
        }
        .cardStyle()
    }

    // MARK: - 结构化字段

    private var sectionsList: some View {
        VStack(spacing: 12) {
            ForEach(PatientHistorySectionCatalog.all) { meta in
                sectionEditor(meta: meta)
                    .id("section-\(meta.key)")
            }
        }
    }

    private func quickSectionBar(proxy: ScrollViewProxy) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("结构化字段")
                .font(.caption.bold())
                .foregroundColor(.appMuted)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(PatientHistorySectionCatalog.all) { meta in
                        Button {
                            withAnimation {
                                expandedSections.insert(meta.key)
                                proxy.scrollTo("section-\(meta.key)", anchor: .top)
                            }
                        } label: {
                            Text(meta.label)
                                .font(.caption.bold())
                                .padding(.horizontal, 10)
                                .padding(.vertical, 7)
                                .background(Color.appPrimary.opacity(expandedSections.contains(meta.key) ? 0.14 : 0.07))
                                .foregroundColor(.appPrimary)
                                .clipShape(Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.horizontal, 1)
            }
        }
    }

    private func sectionEditor(meta: PatientHistorySectionMeta) -> some View {
        let field = vm.profile.sections[meta.key] ?? PatientHistoryField()
        let isExpanded = expandedSections.contains(meta.key)
        return VStack(alignment: .leading, spacing: 8) {
            Button {
                withAnimation(.easeInOut(duration: 0.18)) {
                    if isExpanded { expandedSections.remove(meta.key) }
                    else { expandedSections.insert(meta.key) }
                }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: isExpanded ? "chevron.down.circle.fill" : "chevron.right.circle")
                        .foregroundColor(.appPrimary)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(meta.label)
                            .font(.headline)
                            .foregroundColor(.appText)
                        if !isExpanded {
                            Text(field.value.isEmpty ? meta.placeholder : field.value)
                                .font(.caption)
                                .foregroundColor(.appMuted)
                                .lineLimit(2)
                                .multilineTextAlignment(.leading)
                        }
                    }
                    Spacer()
                    statusBadge(field.status)
                }
            }
            .buttonStyle(.plain)

            if isExpanded {
                Text(meta.placeholder)
                    .font(.caption)
                    .foregroundColor(.appMuted)
                    .fixedSize(horizontal: false, vertical: true)
                TextEditor(text: Binding(
                    get: { field.value },
                    set: { vm.updateField(key: meta.key, value: $0) }
                ))
                .frame(minHeight: 92)
                .padding(8)
                .background(Color.appBackground)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.appStroke, lineWidth: 1))
                .clipShape(RoundedRectangle(cornerRadius: 10))
                HStack(spacing: 8) {
                    Text(PatientHistoryStatusDisplay.sourceText(field.source_type))
                        .font(.caption2)
                        .foregroundColor(.appMuted)
                    if let d = field.date_label {
                        Text("· \(d)").font(.caption2).foregroundColor(.appMuted)
                    }
                    Spacer()
                    Toggle(isOn: Binding(
                        get: { field.verified_by_user },
                        set: { vm.setVerified(key: meta.key, verified: $0) }
                    )) {
                        Text("已核对").font(.caption)
                    }
                    .toggleStyle(.switch)
                    .labelsHidden()
                    Text("已核对").font(.caption).foregroundColor(.appMuted)
                }
                HStack(spacing: 8) {
                    Button("明确无") { vm.setFieldStatus(key: meta.key, status: "none") }
                        .font(.caption)
                        .buttonStyle(.bordered)
                    Button("待核对") { vm.setFieldStatus(key: meta.key, status: "pending_review") }
                        .font(.caption)
                        .buttonStyle(.bordered)
                    Spacer()
                }
            }
        }
        .cardStyle()
    }

    private func statusBadge(_ status: String) -> some View {
        let color: Color = {
            switch status {
            case "confirmed", "documented": return .appSuccess
            case "pending_review": return .appWarning
            case "none": return .appMuted
            default: return .appMuted.opacity(0.6)
            }
        }()
        return Text(PatientHistoryStatusDisplay.text(status))
            .font(.caption2)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.15))
            .foregroundColor(color)
            .clipShape(Capsule())
    }

    // MARK: - 保存

    private var saveButton: some View {
        Button {
            Task { await vm.save() }
        } label: {
            HStack {
                if vm.saving { ProgressView().tint(.white) }
                Text(vm.saving ? "保存中..." : "保存病史整理")
                    .bold()
            }
            .frame(maxWidth: .infinity)
            .padding()
            .background(Color.appPrimary)
            .foregroundColor(.white)
            .cornerRadius(10)
        }
        .disabled(vm.saving || vm.loading)
    }
}

#Preview {
    NavigationStack { PatientHistoryView() }
}
