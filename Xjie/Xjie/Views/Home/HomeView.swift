import SwiftUI

/// 首页 — 对应小程序 pages/index/index
struct HomeView: View {
    @EnvironmentObject var authManager: AuthManager
    @StateObject private var vm = HomeViewModel()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 12) {
                    // 顶部欢迎栏
                    welcomeBar

                    // 主动消息卡片
                    if let proactive = vm.proactive, let msg = proactive.message, !msg.isEmpty {
                        proactiveCard(proactive)
                    }

                    // 主动交互级别滑块
                    interventionSlider

                    // 血糖概览
                    if let glucose = vm.dashboard?.glucose?.last_24h {
                        glucoseCard(glucose)
                    }

                    // 今日膳食
                    mealsCard

                    // 快捷入口
                    quickGrid
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
            }
            .background(Color.appBackground)
            .refreshable { await vm.fetchData() }
            .task { await vm.fetchData() }
            .overlay {
                if vm.loading {
                    ProgressView("加载中...")
                }
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
    }

    // MARK: - 子视图

    private var welcomeBar: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Label("你好", systemImage: "hand.wave")
                    .font(.title2).bold()
                if !authManager.subjectId.isEmpty {
                    Text(authManager.subjectId)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
            }
            Spacer()
            NavigationLink(destination: SettingsView()) {
                Image(systemName: "gearshape.fill")
                    .font(.title3)
                    .foregroundColor(.appMuted)
            }
        }
        .padding(.vertical, 8)
    }

    private func proactiveCard(_ p: ProactiveMessage) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                AssistantAvatar(size: 36)
                Text(p.message ?? "")
                    .font(.subheadline)
            }
            if p.has_rescue == true {
                NavigationLink(destination: ChatView(isEmbedded: true)) {
                    Label("有待处理的救援建议", systemImage: "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundColor(.appDanger)
                }
            }
        }
        .cardStyle()
    }

    private var interventionSlider: some View {
        let levelLabels = ["温和", "标准", "积极"]
        let levelDescs = [
            "仅高风险时提醒",
            "中等风险时提醒",
            "主动积极提醒",
        ]
        let idx = Int(vm.interventionLevel.rounded())

        return VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("主动交互", systemImage: "bell.badge")
                    .font(.headline)
                Spacer()
                Text(levelLabels[idx])
                    .font(.subheadline).bold()
                    .foregroundColor(.appPrimary)
            }

            Slider(value: $vm.interventionLevel, in: 0...2, step: 1) {
                Text("干预级别")
            } onEditingChanged: { editing in
                if !editing {
                    Task { await vm.updateInterventionLevel(vm.interventionLevel) }
                }
            }
            .tint(.appPrimary)

            HStack {
                Image(systemName: "speaker.slash").font(.caption2).foregroundColor(.appMuted)
                Spacer()
                Image(systemName: "equal").font(.caption2).foregroundColor(.appMuted)
                Spacer()
                Image(systemName: "bell.fill").font(.caption2).foregroundColor(.appMuted)
            }
            .padding(.horizontal, 4)

            Text(levelDescs[idx])
                .font(.caption)
                .foregroundColor(.appMuted)
        }
        .cardStyle()
    }

    private func glucoseCard(_ g: GlucoseSummary) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("今日血糖", systemImage: "chart.bar")
                .font(.headline)
            HStack {
                MetricItemView(value: Utils.formatGlucose(g.avg, withUnit: false), label: "平均 \(Utils.glucoseUnitLabel)")
                Spacer()
                MetricItemView(
                    value: g.tir_70_180_pct != nil ? Utils.toFixed(g.tir_70_180_pct) + "%" : "--",
                    label: "TIR",
                    color: .appSuccess
                )
                Spacer()
                MetricItemView(
                    value: "\(Utils.glucoseThreshold(g.min ?? 0)) - \(Utils.glucoseThreshold(g.max ?? 0))",
                    label: "范围"
                )
            }
        }
        .cardStyle()
    }

    private var mealsCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("今日膳食", systemImage: "fork.knife")
                .font(.headline)
            HStack {
                Text("\(Int(vm.dashboard?.kcal_today ?? 0)) kcal")
                    .font(.title2).bold()
                Spacer()
                Text("\(vm.dashboard?.meals_today?.count ?? 0) 餐")
                    .foregroundColor(.appMuted)
                    .font(.caption)
            }
        }
        .cardStyle()
    }

    private var quickGrid: some View {
        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
            NavigationLink(destination: GlucoseView()) {
                quickItem(icon: "chart.xyaxis.line", label: "血糖曲线")
            }
            NavigationLink(destination: MealsView()) {
                quickItem(icon: "camera", label: "记录膳食")
            }
            NavigationLink(destination: ChatView(isEmbedded: true)) {
                quickItem(icon: "bubble.left.and.text.bubble.right", label: "助手小捷")
            }
            NavigationLink(destination: HealthView()) {
                quickItem(icon: "list.clipboard", label: "健康数据")
            }
        }
    }

    private func quickItem(icon: String, label: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: icon)
                .font(.title)
                .foregroundColor(.appPrimary)
            Text(label).font(.caption).foregroundColor(.appText)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
        .background(Color.appCardBg)
        .cornerRadius(10)
        .shadow(color: .black.opacity(0.04), radius: 8, x: 0, y: 2)
    }
}
