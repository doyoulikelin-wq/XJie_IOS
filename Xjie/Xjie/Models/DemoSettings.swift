import Foundation
import SwiftUI

/// 全局演示模式开关 (UserDefaults 持久化)。
/// 在没有真实组学/微生物/基因数据前默认开启，让用户看到完整产品视觉。
@MainActor
final class DemoSettings: ObservableObject {
    static let shared = DemoSettings()

    private let key = "xjie.omicsDemo"

    @Published var omicsDemoEnabled: Bool {
        didSet { UserDefaults.standard.set(omicsDemoEnabled, forKey: key) }
    }

    private init() {
        if UserDefaults.standard.object(forKey: key) == nil {
            self.omicsDemoEnabled = true      // 默认开启演示模式
            UserDefaults.standard.set(true, forKey: key)
        } else {
            self.omicsDemoEnabled = UserDefaults.standard.bool(forKey: key)
        }
    }
}
