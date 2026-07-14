import SwiftUI

#if DEBUG
#Preview("XAGE 主页面") {
    let authManager: AuthManager = .makeTestingInstance()
    let externalReportImport: XAgeExternalReportImportRouter = .init()

    XAgeMainView()
        .environmentObject(authManager)
        .environmentObject(externalReportImport)
}
#endif
