import SwiftUI
import UniformTypeIdentifiers

/// 多组学数据页面（演示模式 + 上传入口）
/// 五幕结构：1) 指纹 2) 三联（代谢×CGM×心率）3) 时间轴 4) 故事化面板 5) 行动按钮
struct OmicsView: View {
    @State private var activeTab = 0
    @StateObject private var vm = OmicsViewModel()
    @ObservedObject private var demo = DemoSettings.shared

    @State private var activeStory: ActiveStory?

    private struct ActiveStory: Identifiable {
        let id = UUID()
        let title: String
        let value: String
        let unit: String
        let reference: String
        let status: String
        let story: String
        let keyword: String
    }

    private let tabs = ["蛋白组学", "代谢组学", "基因组学"]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 16) {
                    tabBar
                    ZStack {
                        switch activeTab {
                        case 0: proteomicsScene
                        case 1: metabolomicsScene
                        default: genomicsScene
                        }
                    }
                    .transition(
                        .asymmetric(
                            insertion: .scale(scale: 0.96).combined(with: .opacity),
                            removal: .opacity
                        )
                    )
                    .animation(.spring(response: 0.45, dampingFraction: 0.85), value: activeTab)
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
            }
            .background(Color.appBackground)
            .navigationTitle("多组学")
            .navigationBarTitleDisplayMode(.inline)
        }
        .task { if demo.omicsDemoEnabled { await vm.loadDemoIfNeeded() } }
        .sheet(isPresented: $vm.showFilePicker) {
            MetabolomicsFilePicker(vm: vm)
        }
        .sheet(item: $activeStory) { story in
            MetaboliteStorySheet(
                title: story.title,
                value: story.value,
                unit: story.unit,
                reference: story.reference,
                status: story.status,
                story: story.story,
                footer: { StoryCitations(keyword: story.keyword, vm: vm) }
            )
            .presentationDetents([.medium, .large])
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

    private var tabBar: some View {
        HStack(spacing: 0) {
            ForEach(Array(tabs.enumerated()), id: \.offset) { i, label in
                Button { activeTab = i } label: {
                    Text(label)
                        .font(.subheadline.bold())
                        .foregroundColor(activeTab == i ? .white : .appPrimary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(activeTab == i ? Color.appPrimary : Color.clear)
                        .cornerRadius(8)
                }
            }
        }
        .padding(4)
        .background(Color.appPrimary.opacity(0.1))
        .cornerRadius(10)
    }

    // MARK: - 代谢组学场景

    private var metabolomicsScene: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("代谢健康", systemImage: "chart.pie.fill")
                    .font(.headline).foregroundColor(.appPrimary)
                Spacer()
                if demo.omicsDemoEnabled { DemoBadge() }
            }

            if let m = vm.demoMetabolomics, demo.omicsDemoEnabled {
                VStack(alignment: .leading, spacing: 10) {
                    MetabolicFingerprintView(items: m.items, metabolicAgeDelta: m.metabolic_age_delta_years)
                    Divider()
                    Text(m.summary)
                        .font(.subheadline)
                        .foregroundColor(.appText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .cardStyle()

                if let t = vm.demoTriad {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("代谢 × 血糖 × 心率", systemImage: "circle.hexagongrid.fill")
                            .font(.headline).foregroundColor(.appPrimary)
                        OmicsTriadView(insight: t)
                    }
                    .cardStyle()
                }

                metaboliteListCard(items: m.items, legend: "关键代谢物（点击了解）")
                uploadCard
                if vm.analyzing { analyzingRow }
                if let result = vm.analysisResult { analysisResultView(result) }
            } else {
                placeholderCard(title: "代谢组学", desc: "打开演示模式查看示例代谢指纹，或上传真实代谢数据。")
                uploadCard
            }
        }
    }

    // MARK: - 蛋白组学场景

    private var proteomicsScene: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("慢性炎症肖像", systemImage: "heart.text.square.fill")
                    .font(.headline).foregroundColor(.appPrimary)
                Spacer()
                if demo.omicsDemoEnabled { DemoBadge() }
            }
            if let p = vm.demoProteomics, demo.omicsDemoEnabled {
                VStack(spacing: 10) {
                    InflammationRing(score: p.inflammation_score)
                        .frame(width: 180, height: 180)
                    Text(p.summary)
                        .font(.subheadline)
                        .multilineTextAlignment(.center)
                        .foregroundColor(.appText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity)
                .cardStyle()

                metaboliteListCard(items: p.items, legend: "关键蛋白（点击了解）")
            } else {
                placeholderCard(title: "蛋白组学", desc: "打开演示模式查看示例炎症肖像，或等待真实蛋白组数据。")
            }
        }
    }

    // MARK: - 基因组学场景

    private var genomicsScene: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("遗传倾向地图", systemImage: "dna")
                    .font(.headline).foregroundColor(.appPrimary)
                Spacer()
                if demo.omicsDemoEnabled { DemoBadge() }
            }

            if let g = vm.demoGenomics, demo.omicsDemoEnabled {
                VStack(alignment: .leading, spacing: 10) {
                    PRSBarRow(label: "2 型糖尿病 (T2D)", score: g.prs.t2d)
                    PRSBarRow(label: "心血管 (CVD)", score: g.prs.cvd)
                    PRSBarRow(label: "脂肪肝 (MASLD)", score: g.prs.masld)
                    Text(g.summary)
                        .font(.subheadline)
                        .foregroundColor(.appText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .cardStyle()

                VStack(alignment: .leading, spacing: 8) {
                    Text("关键基因变异").font(.subheadline.bold())
                    GeneTimelineStrip(variants: g.variants) { v in
                        activeStory = ActiveStory(
                            title: v.name,
                            value: v.genotype,
                            unit: "",
                            reference: "风险等级：\(v.risk_level)",
                            status: v.risk_level == "较高" ? "high" : (v.risk_level == "中" ? "borderline" : "normal"),
                            story: v.story_zh,
                            keyword: v.name
                        )
                    }
                }
                .cardStyle()

                if let mi = vm.demoMicrobiome {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Label("肠道菌群分布", systemImage: "leaf.fill")
                                .font(.subheadline.bold())
                                .foregroundColor(.appPrimary)
                            Spacer()
                            Text("多样性 \(String(format: "%.2f", mi.shannon))")
                                .font(.caption).foregroundColor(.appMuted)
                        }
                        MicrobiomeBubbleChart(taxa: mi.taxa) { t in
                            let zh = zhNameForTaxon(t.name)
                            activeStory = ActiveStory(
                                title: zh == t.name ? t.name : "\(zh)（\(t.name)）",
                                value: "\(Int(t.relative_abundance * 100))%",
                                unit: "相对丰度",
                                reference: t.reference,
                                status: t.status,
                                story: t.story_zh,
                                keyword: t.name
                            )
                        }
                        .frame(height: 260)
                    }
                    .cardStyle()
                }
            } else {
                placeholderCard(title: "基因组学", desc: "打开演示模式查看示例遗传倾向地图。")
            }
        }
    }

    // MARK: - 组件复用

    private func metaboliteListCard(items: [OmicsDemoItem], legend: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(legend).font(.subheadline.bold())
            ForEach(items.prefix(8)) { item in
                Button {
                    activeStory = ActiveStory(
                        title: item.name,
                        value: String(item.value),
                        unit: item.unit,
                        reference: item.reference,
                        status: item.status,
                        story: item.story_zh,
                        keyword: item.name
                    )
                } label: {
                    HStack {
                        Circle().fill(color(for: item.status)).frame(width: 10, height: 10)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.name).font(.subheadline).foregroundColor(.appText)
                            Text(item.reference).font(.caption).foregroundColor(.appMuted)
                        }
                        Spacer()
                        Text("\(String(item.value)) \(item.unit)")
                            .font(.subheadline.bold())
                            .foregroundColor(color(for: item.status))
                        Image(systemName: "chevron.right")
                            .font(.caption).foregroundColor(.appMuted)
                    }
                    .padding(10)
                    .background(Color.gray.opacity(0.04))
                    .cornerRadius(8)
                }
                .buttonStyle(.plain)
            }
        }
        .cardStyle()
    }

    private var uploadCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("上传真实代谢组数据", systemImage: "arrow.up.doc.fill")
                .font(.subheadline.bold())
                .foregroundColor(.appPrimary)
            Text("支持 CSV、Excel、PDF 格式。上传后 AI 将自动分析并输出结论。")
                .font(.caption).foregroundColor(.appMuted)
            if let fileName = vm.uploadedFileName {
                HStack {
                    Image(systemName: "doc.fill").foregroundColor(.appPrimary)
                    Text(fileName).font(.subheadline).lineLimit(1)
                    Spacer()
                    Button { vm.clearUpload() } label: {
                        Image(systemName: "xmark.circle.fill").foregroundColor(.appMuted)
                    }
                }
                .padding(10)
                .background(Color.appPrimary.opacity(0.06))
                .cornerRadius(8)
            }
            Button { vm.showFilePicker = true } label: {
                HStack {
                    Image(systemName: "plus.circle.fill")
                    Text("选择文件上传").font(.subheadline.bold())
                    Spacer()
                    Image(systemName: "chevron.right").font(.caption)
                }
                .padding(12)
                .background(Color.appPrimary.opacity(0.08))
                .foregroundColor(.appPrimary)
                .cornerRadius(10)
            }
        }
        .cardStyle()
    }

    private var analyzingRow: some View {
        HStack(spacing: 8) {
            ProgressView()
            Text("AI 正在分析代谢组数据...")
                .font(.subheadline).foregroundColor(.appMuted)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 12)
        .background(Color.appPrimary.opacity(0.04))
        .cornerRadius(10)
    }

    private func analysisResultView(_ result: MetabolomicsAnalysis) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image("Logo").resizable().scaledToFit().frame(width: 20, height: 20)
                Text("AI 分析结果").font(.subheadline.bold())
                Spacer()
                Text(result.riskLevel)
                    .font(.caption.bold())
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(riskColor(result.riskLevel).opacity(0.15))
                    .foregroundColor(riskColor(result.riskLevel))
                    .cornerRadius(6)
            }
            Text(result.summary).font(.subheadline)
            Text(result.analysis).font(.caption).foregroundColor(.appMuted)
        }
        .cardStyle()
    }

    private func placeholderCard(title: String, desc: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: "sparkles")
                .font(.system(size: 32))
                .foregroundColor(.appPrimary.opacity(0.7))
            Text(title).font(.headline)
            Text(desc).font(.subheadline)
                .foregroundColor(.appMuted)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 20)
        .cardStyle()
    }

    private func color(for status: String) -> Color {
        switch status {
        case "normal": return .green
        case "borderline": return .orange
        case "high": return .red
        case "low": return .blue
        default: return .gray
        }
    }

    private func riskColor(_ level: String) -> Color {
        switch level {
        case "低风险": return .green
        case "中风险": return .orange
        case "高风险": return .red
        default: return .appMuted
        }
    }
}

// MARK: - 辅助子视图

private struct InflammationRing: View {
    let score: Double
    var body: some View {
        ZStack {
            Circle().stroke(Color.appPrimary.opacity(0.08), lineWidth: 14)
            Circle()
                .trim(from: 0, to: CGFloat(min(max(score, 0), 100)) / 100.0)
                .stroke(
                    AngularGradient(colors: [.green, .orange, .red], center: .center),
                    style: StrokeStyle(lineWidth: 14, lineCap: .round)
                )
                .rotationEffect(.degrees(-90))
            VStack(spacing: 2) {
                Text("\(Int(score))")
                    .font(.system(size: 40, weight: .bold, design: .rounded))
                Text("炎症评分").font(.caption).foregroundColor(.appMuted)
            }
        }
    }
}

private struct PRSBarRow: View {
    let label: String
    let score: Double
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(label).font(.caption).foregroundColor(.appText)
                Spacer()
                Text("\(score >= 0 ? "+" : "")\(String(format: "%.2f", score))")
                    .font(.caption.bold())
                    .foregroundColor(color(for: score))
            }
            GeometryReader { geo in
                let w = geo.size.width
                let center = w / 2
                let fill = CGFloat(min(abs(score) / 1.5, 1.0)) * (w / 2)
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(Color.gray.opacity(0.15))
                        .frame(height: 8)
                    Rectangle()
                        .fill(Color.appMuted.opacity(0.3))
                        .frame(width: 1, height: 12)
                        .offset(x: center - 0.5)
                    RoundedRectangle(cornerRadius: 4)
                        .fill(color(for: score).opacity(0.8))
                        .frame(width: fill, height: 8)
                        .offset(x: score >= 0 ? center : center - fill)
                }
            }
            .frame(height: 12)
        }
    }
    private func color(for s: Double) -> Color {
        if s > 0.7 { return .red }
        if s > 0.2 { return .orange }
        if s < -0.3 { return .green }
        return .appMuted
    }
}

private struct StoryCitations: View {
    let keyword: String
    @ObservedObject var vm: OmicsViewModel
    @State private var citations: [Citation] = []
    @State private var loading = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("文献证据", systemImage: "book.closed.fill")
                .font(.subheadline.bold())
                .foregroundColor(.appPrimary)
            if loading {
                HStack { ProgressView(); Text("查询文献中...").font(.caption).foregroundColor(.appMuted) }
            } else if citations.isEmpty {
                Text("暂无匹配文献（该指标的知识库仍在完善中）")
                    .font(.caption)
                    .foregroundColor(.appMuted)
            } else {
                CitationFootnoteView(citations: citations)
            }
        }
        .task {
            loading = true
            citations = await vm.citations(for: keyword)
            loading = false
        }
    }
}

// MARK: - 文件选择器

struct MetabolomicsFilePicker: UIViewControllerRepresentable {
    @ObservedObject var vm: OmicsViewModel

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let types: [UTType] = [.commaSeparatedText, .pdf, .spreadsheet, .data]
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: true)
        picker.delegate = context.coordinator
        picker.allowsMultipleSelection = false
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(vm: vm) }

    class Coordinator: NSObject, UIDocumentPickerDelegate {
        let vm: OmicsViewModel
        init(vm: OmicsViewModel) { self.vm = vm }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else { return }
            vm.handlePickedFile(url)
        }
    }
}
