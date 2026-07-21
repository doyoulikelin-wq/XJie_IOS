import SwiftUI

/// 登录后的 XAGE 根容器。
/// 它只负责展示全局离线提示并承载 `XAgeMainView`；真正的数据、问答和 X年龄分页由主页面内部管理。
struct MainTabView: View {
    @EnvironmentObject var networkMonitor: NetworkMonitor

    /// 构建当前类型的 SwiftUI 主视图层级与交互入口。
    var body: some View {
        VStack(spacing: 0) {
            // 离线时保留主页面和已有内容，只在顶部提示网络状态；网络恢复后横幅会随监控状态自动消失。
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

            XAgeMainView()
        }
    }
}
