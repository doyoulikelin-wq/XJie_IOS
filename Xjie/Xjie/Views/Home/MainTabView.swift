import SwiftUI

/// 主 TabBar — iPhone 用 TabView，iPad 用侧边栏
/// NET-01: 集成离线横幅
struct MainTabView: View {
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var networkMonitor: NetworkMonitor
    @Environment(\.horizontalSizeClass) private var sizeClass
    @State private var selectedCompactTab: iPadTab = .home
    @State private var pendingChatPrompt: String?

    var body: some View {
        VStack(spacing: 0) {
            // NET-01: 离线横幅
            if !networkMonitor.isConnected {
                HStack(spacing: 6) {
                    Image(systemName: "wifi.slash")
                    Text(String(localized: "network.offline"))
                }
                .font(.caption)
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
                .background(Color.appWarning)
            }

            if sizeClass == .regular {
                iPadLayout
            } else {
                iPhoneLayout
            }
        }
    }

    // MARK: - iPhone (compact)

    private var iPhoneLayout: some View {
        TabView(selection: $selectedCompactTab) {
            HomeView()
                .tabItem {
                    Image(systemName: "house.fill")
                    Text("首页")
                }
                .tag(iPadTab.home)

            HealthDataView()
                .tabItem {
                    Image(systemName: "heart.text.square.fill")
                    Text("健康数据")
                }
                .tag(iPadTab.healthData)

            HealthPlanView(onGeneratePlan: openPlanGenerationChat)
                .tabItem {
                    Image(systemName: "list.clipboard.fill")
                    Text("计划")
                }
                .tag(iPadTab.healthPlan)

            OmicsView()
                .tabItem {
                    Image(systemName: "atom")
                    Text("多组学")
                }
                .tag(iPadTab.omics)

            ChatView(
                initialPrompt: pendingChatPrompt,
                onInitialPromptConsumed: { pendingChatPrompt = nil }
            )
                .tabItem {
                    Image(systemName: "bubble.left.and.bubble.right.fill")
                    Text("助手小捷")
                }
                .tag(iPadTab.chat)
        }
        .tint(Color.appPrimary)
    }

    // MARK: - iPad (regular)

    @State private var selectedTab: iPadTab? = .home

    private var planGenerationPrompt: String {
        "我想生成健康计划。请先问我想生成哪一类计划（运动、饮食、用药或组合）、目标周期、禁忌/限制和是否有用药需求；用药相关内容仅在我明确确认需要时再纳入计划。"
    }

    private func openPlanGenerationChat() {
        pendingChatPrompt = planGenerationPrompt
        selectedCompactTab = .chat
        selectedTab = .chat
    }

    private enum iPadTab: String, CaseIterable, Identifiable {
        case home = "首页"
        case healthData = "健康数据"
        case healthPlan = "计划"
        case omics = "多组学"
        case chat = "助手小捷"

        var id: String { rawValue }

        var icon: String {
            switch self {
            case .home: return "house.fill"
            case .healthData: return "heart.text.square.fill"
            case .healthPlan: return "list.clipboard.fill"
            case .omics: return "atom"
            case .chat: return "bubble.left.and.bubble.right.fill"
            }
        }
    }

    private var iPadLayout: some View {
        NavigationSplitView {
            List(iPadTab.allCases, selection: $selectedTab) { tab in
                Label {
                    Text(tab.rawValue)
                } icon: {
                    Image(systemName: tab.icon)
                }
            }
            .navigationTitle("Xjie")
            .listStyle(.sidebar)
        } detail: {
            switch selectedTab {
            case .home: HomeView()
            case .healthData: HealthDataView()
            case .healthPlan: HealthPlanView(onGeneratePlan: openPlanGenerationChat)
            case .omics: OmicsView()
            case .chat: ChatView(
                initialPrompt: pendingChatPrompt,
                onInitialPromptConsumed: { pendingChatPrompt = nil }
            )
            case nil: HomeView()
            }
        }
        .tint(Color.appPrimary)
    }
}
