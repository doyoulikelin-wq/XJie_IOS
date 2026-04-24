import Foundation
import SwiftUI

/// 血糖显示单位偏好。后端始终以 mg/dL 存储，iOS 仅在展示层换算。
enum GlucoseUnit: String, Codable, CaseIterable, Identifiable {
    case mgdl = "mg_dl"
    case mmol = "mmol_l"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .mgdl: "mg/dL"
        case .mmol: "mmol/L"
        }
    }

    var shortLabel: String { label }

    /// 1 mmol/L = 18.018 mg/dL
    static let mgdlPerMmol: Double = 18.018
}

/// 全局单位偏好（UserDefaults 持久化），由 SettingsViewModel 与后端同步。
@MainActor
final class UnitsSettings: ObservableObject {
    static let shared = UnitsSettings()

    private let key = "xjie.glucoseUnit"

    @Published var glucoseUnit: GlucoseUnit {
        didSet { UserDefaults.standard.set(glucoseUnit.rawValue, forKey: key) }
    }

    private init() {
        let raw = UserDefaults.standard.string(forKey: key) ?? GlucoseUnit.mgdl.rawValue
        self.glucoseUnit = GlucoseUnit(rawValue: raw) ?? .mgdl
    }
}

extension Utils {
    /// mg/dL → mmol/L
    static func mgdlToMmol(_ mgdl: Double) -> Double {
        mgdl / GlucoseUnit.mgdlPerMmol
    }

    /// 把后端 mg/dL 数值按当前用户偏好渲染。`withUnit=false` 仅返回数值字符串。
    @MainActor
    static func formatGlucose(_ mgdl: Double?, withUnit: Bool = true) -> String {
        guard let mgdl, !mgdl.isNaN else { return "--" }
        let unit = UnitsSettings.shared.glucoseUnit
        switch unit {
        case .mmol:
            let s = String(format: "%.1f", mgdlToMmol(mgdl))
            return withUnit ? "\(s) mmol/L" : s
        case .mgdl:
            let s = String(format: "%.0f", mgdl)
            return withUnit ? "\(s) mg/dL" : s
        }
    }

    /// 当前单位的纯文字标签
    @MainActor
    static var glucoseUnitLabel: String {
        UnitsSettings.shared.glucoseUnit.label
    }

    /// 把 mg/dL 阈值（如 70 / 180）按用户单位渲染（不带单位后缀）
    @MainActor
    static func glucoseThreshold(_ mgdl: Double) -> String {
        let unit = UnitsSettings.shared.glucoseUnit
        switch unit {
        case .mmol: return String(format: "%.1f", mgdlToMmol(mgdl))
        case .mgdl: return String(format: "%.0f", mgdl)
        }
    }
}
