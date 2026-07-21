import SwiftUI

/// XAGE root shell.
/// NET-01: 集成离线横幅
struct MainTabView: View {
    @EnvironmentObject var networkMonitor: NetworkMonitor

    var body: some View {
        VStack(spacing: 0) {
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
