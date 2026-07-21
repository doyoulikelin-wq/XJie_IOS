import SwiftUI

struct MedicationAddSourceView: View {
    let prescriptionCandidates: [MedicationPrefillCandidate]
    let legacyRecords: [Medication]
    let onPrescription: (MedicationPrefillCandidate) -> Void
    let onOCRText: () -> Void
    let onHistory: (Medication) -> Void
    let onManual: () -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(hex: "D9F5FF"), Color(hex: "EAF9FF"), Color(hex: "F8FCFF")],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    prescriptionSection
                    ocrSection
                    historySection
                    sourceButton(
                        title: "手动填写",
                        subtitle: "逐项填写并由你确认药名、剂量、频次和疗程",
                        icon: "square.and.pencil",
                        action: onManual
                    )
                    Label(
                        "任何来源都只是预填或草稿；只有你检查并确认后才创建可信计划。",
                        systemImage: "checkmark.shield.fill"
                    )
                    .font(.caption)
                    .foregroundStyle(Color(hex: "5D7890"))
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(Color.white.opacity(0.52), in: RoundedRectangle(cornerRadius: 20))
                }
                .padding(20)
            }
            .accessibilityIdentifier("xage.medication.addSource.root")
        }
        .presentationDragIndicator(.visible)
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 3) {
                Text("新增用药")
                    .font(.title.bold())
                    .foregroundStyle(Color(hex: "123E67"))
                Text("选择一种真实可用的录入方式")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
            }
            Spacer()
            Button { dismiss() } label: {
                Image(systemName: "xmark")
                    .frame(width: 44, height: 44)
                    .background(Color.white.opacity(0.62), in: Capsule())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("关闭新增用药")
            .accessibilityIdentifier("xage.medication.addSource.close")
        }
    }

    @ViewBuilder
    private var prescriptionSection: some View {
        if prescriptionCandidates.isEmpty {
            unavailableCard(
                title: "从已确认处方导入",
                detail: "当前账号没有服务端返回的待复核处方候选；客户端不会自行读取或伪造处方列表。",
                icon: "doc.text.magnifyingglass"
            )
        } else {
            VStack(alignment: .leading, spacing: 10) {
                Label("从已确认处方导入", systemImage: "doc.text.magnifyingglass")
                    .font(.headline)
                    .foregroundStyle(Color(hex: "123E67"))
                Text("处方内容仍需逐字段检查，确认前不会进入当前用药或 AI。")
                    .font(.caption)
                    .foregroundStyle(Color(hex: "5D7890"))
                ForEach(prescriptionCandidates) { candidate in
                    Button {
                        onPrescription(candidate)
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(candidate.extracted_data["name"]?.text ?? "未识别药名")
                                    .font(.subheadline.bold())
                                Text(candidate.low_confidence_fields.isEmpty ? "等待检查" : "含低置信字段，需重点核对")
                                    .font(.caption2)
                                    .foregroundStyle(candidate.low_confidence_fields.isEmpty ? Color(hex: "5D7890") : Color.orange)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                        }
                        .frame(minHeight: 44)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(16)
            .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 22))
        }
    }

    private var ocrSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("拍摄处方或药盒", systemImage: "camera.viewfinder")
                .font(.headline)
                .foregroundStyle(Color(hex: "123E67"))
            Text("当前可信接口只接收 OCR 原始文字，尚未提供原始图片上传。可先用系统相机或相册识别文字，再粘贴到小捷；本页不会把这个入口写成已完成拍照识别。")
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
            Button(action: onOCRText) {
                Label("粘贴已识别文字", systemImage: "text.viewfinder")
                    .font(.subheadline.bold())
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("xage.medication.addSource.ocrText")
        }
        .padding(16)
        .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 22))
    }

    @ViewBuilder
    private var historySection: some View {
        if legacyRecords.isEmpty {
            unavailableCard(
                title: "从历史用药重新启用",
                detail: "当前账号没有可供重新核对的旧用药记录；服务端也尚未提供独立可信历史选择接口。",
                icon: "clock.arrow.circlepath"
            )
        } else {
            VStack(alignment: .leading, spacing: 10) {
                Label("从历史用药重新启用", systemImage: "clock.arrow.circlepath")
                    .font(.headline)
                    .foregroundStyle(Color(hex: "123E67"))
                Text("旧记录只作为预填；重新确认后才会建立带新版本的可信计划。")
                    .font(.caption)
                    .foregroundStyle(Color.orange)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(legacyRecords.prefix(8)) { medication in
                    Button { onHistory(medication) } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(medication.name)
                                    .font(.subheadline.bold())
                                Text([medication.dosage, medication.frequency].compactMap { $0 }.joined(separator: " · "))
                                    .font(.caption2)
                                    .foregroundStyle(Color(hex: "5D7890"))
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                        }
                        .frame(minHeight: 44)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(16)
            .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 22))
        }
    }

    private func sourceButton(
        title: String,
        subtitle: String,
        icon: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.title3.bold())
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 44, height: 44)
                    .background(Color.white.opacity(0.62), in: Circle())
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(Color(hex: "123E67"))
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(Color(hex: "5D7890"))
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .foregroundStyle(Color(hex: "6D8498"))
            }
            .padding(16)
            .background(Color.white.opacity(0.55), in: RoundedRectangle(cornerRadius: 22))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("xage.medication.addSource.manual")
    }

    private func unavailableCard(title: String, detail: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: icon)
                .font(.headline)
                .foregroundStyle(Color(hex: "123E67"))
            Text(detail)
                .font(.caption)
                .foregroundStyle(Color(hex: "5D7890"))
                .fixedSize(horizontal: false, vertical: true)
            Text("当前不可用")
                .font(.caption2.bold())
                .foregroundStyle(Color.orange)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(Color.white.opacity(0.45), in: RoundedRectangle(cornerRadius: 22))
        .accessibilityElement(children: .combine)
    }
}
