import SwiftUI

/// 首页上的老年人关怀卡片：仅在 elderly_mode 开启时显示。
/// 显示当前主动询问状态，提供"立即签到"按钮和"历史记录"入口。
struct ElderlyCareCard: View {
    @StateObject private var vm = ElderlyViewModel()
    @State private var showCheckin = false
    @State private var autoPromptShown = false

    var body: some View {
        Group {
            if vm.isEnabled {
                content
            } else {
                EmptyView()
            }
        }
        .task {
            await vm.fetchStatus()
            // 自动弹出：满足条件且本次会话尚未弹过
            if vm.shouldPrompt && !autoPromptShown {
                autoPromptShown = true
                showCheckin = true
            }
        }
        .sheet(isPresented: $showCheckin) {
            ElderlyCheckinSheet(vm: vm, source: showCheckinSource)
        }
    }

    private var showCheckinSource: String {
        vm.shouldPrompt && autoPromptShown ? "auto_prompt" : "manual"
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label("老年人关怀", systemImage: "heart.text.square.fill")
                    .font(.headline)
                    .foregroundColor(.appPrimary)
                Spacer()
                NavigationLink {
                    ElderlyHistoryView()
                } label: {
                    Text("记录").font(.subheadline).foregroundColor(.appMuted)
                }
            }

            if let s = vm.status {
                Text(promptText(for: s))
                    .font(.subheadline)
                    .foregroundColor(.appText)
            }

            HStack(spacing: 10) {
                Button {
                    showCheckin = true
                } label: {
                    HStack {
                        Image(systemName: "checkmark.circle.fill")
                        Text("现在签到").font(.system(size: 17, weight: .semibold))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .background(Color.appPrimary)
                    .foregroundColor(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                NavigationLink {
                    ElderlyHistoryView()
                } label: {
                    HStack {
                        Image(systemName: "clock.arrow.circlepath")
                        Text("查看历史").font(.system(size: 17, weight: .medium))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(Color.appPrimary.opacity(0.6), lineWidth: 1)
                    )
                    .foregroundColor(.appPrimary)
                }
            }
        }
        .cardStyle()
    }

    private func promptText(for s: ElderlyTodayStatus) -> String {
        if s.should_prompt {
            return "是时候记录一下您的状态啦 ❤️"
        }
        if s.today_count > 0 {
            return "今日已记录 \(s.today_count) 次，每 \(s.interval_min) 分钟会提醒一次"
        }
        return "每 \(s.interval_min) 分钟会主动询问一次身体感觉与心情"
    }
}
