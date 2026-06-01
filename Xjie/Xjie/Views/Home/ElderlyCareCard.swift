import SwiftUI

/// 首页"关怀复查"卡片：取代普通模式下的主动交互模块。
/// 由父视图根据 vm.elderlyMode 控制是否渲染。
struct ElderlyCareCard: View {
    @StateObject private var vm = ElderlyViewModel()
    @State private var showCheckin = false
    @State private var autoPromptShown = false
    @State private var presetActivity: String? = nil
    @State private var presetKind: ElderlyCheckinKind = .combined

    /// 关怀复查的快捷项
    private struct QuickReview: Identifiable {
        let id = UUID()
        let title: String
        let activity: String
        let kind: ElderlyCheckinKind
    }

    private let quickReviews: [QuickReview] = [
        .init(title: "用药签到", activity: "已按时服药", kind: .medication),
        .init(title: "睡眠复查", activity: "睡得很好", kind: .sleep),
        .init(title: "饮水复查", activity: "饮水充足", kind: .water),
        .init(title: "活动复查", activity: "今日散步", kind: .activity),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("关怀复查")
                    .font(.system(size: 19, weight: .semibold))
                    .foregroundColor(.appPrimary)
                Spacer()
                NavigationLink {
                    ElderlyHistoryView()
                } label: {
                    Text("历史").font(.system(size: 16)).foregroundColor(.appMuted)
                }
            }

            Text(promptText)
                .font(.system(size: 17))
                .foregroundColor(.appText)
                .fixedSize(horizontal: false, vertical: true)

            // 快捷复查按钮（2x2）
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                ForEach(quickReviews) { q in
                    Button {
                        presetActivity = q.activity
                        presetKind = q.kind
                        showCheckin = true
                    } label: {
                        Text(q.title)
                            .font(.system(size: 16, weight: .medium))
                            .frame(maxWidth: .infinity, minHeight: 52)
                            .background(Color.appPrimary.opacity(0.08))
                            .foregroundColor(.appPrimary)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                }
            }

            // 综合签到 / 历史
            HStack(spacing: 10) {
                Button {
                    presetActivity = nil
                    presetKind = .combined
                    showCheckin = true
                } label: {
                    Text("综合签到")
                        .font(.system(size: 17, weight: .semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(Color.appPrimary)
                        .foregroundColor(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                }

                NavigationLink {
                    ElderlyHistoryView()
                } label: {
                    Text("查看历史")
                        .font(.system(size: 17, weight: .medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .overlay(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(Color.appPrimary.opacity(0.6), lineWidth: 1)
                        )
                        .foregroundColor(.appPrimary)
                }
            }
        }
        .cardStyle()
        .task { await vm.fetchStatus() }
        .onAppear {
            Task {
                await vm.fetchStatus()
                if vm.shouldPrompt && !autoPromptShown {
                    autoPromptShown = true
                    presetActivity = nil
                    presetKind = .combined
                    showCheckin = true
                }
            }
        }
        .sheet(isPresented: $showCheckin, onDismiss: { presetActivity = nil; presetKind = .combined }) {
            ElderlyCheckinSheet(
                vm: vm,
                source: (vm.shouldPrompt && autoPromptShown) ? "auto_prompt" : "manual",
                presetActivity: presetActivity,
                kind: presetKind
            )
        }
    }

    private var promptText: String {
        guard let s = vm.status else { return "正在加载今日关怀状态…" }
        if s.should_prompt {
            return "该和您聊一聊啦。点击下方任一选项快速复查。"
        }
        if s.today_count > 0 {
            return "今日已记录 \(s.today_count) 次。每 \(s.interval_min) 分钟会主动询问一次。"
        }
        return "每 \(s.interval_min) 分钟会主动询问一次。可点击下方按钮立即复查。"
    }
}
