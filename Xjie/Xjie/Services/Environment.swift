import Foundation

/// 环境配置 — SEC-03: 根据编译条件切换 API 地址
enum AppEnvironment {
    /// API 基础地址
    /// - Debug: 从 Info.plist 的 API_BASE_URL 读取，默认 http://localhost:8000
    /// - Release: 必须在 Info.plist 中配置正确的生产地址
    static let apiBaseURL: String = {
        #if DEBUG
        let environment = ProcessInfo.processInfo.environment
        if let debugURL = environment["XJIE_DEBUG_API_BASE_URL"] ?? Self.launchArgumentValue(for: "XJIE_DEBUG_API_BASE_URL"),
           !debugURL.isEmpty {
            return debugURL
        }
        #endif

        if let urlFromPlist = Bundle.main.object(forInfoDictionaryKey: "API_BASE_URL") as? String,
           !urlFromPlist.isEmpty {
            return urlFromPlist
        }
        #if DEBUG
        return "http://localhost:8000"
        #else
        fatalError("API_BASE_URL must be set in Info.plist for release builds")
        #endif
    }()

    #if DEBUG
    private static func launchArgumentValue(for key: String) -> String? {
        let arguments = ProcessInfo.processInfo.arguments
        for (index, argument) in arguments.enumerated() {
            if argument == key, arguments.indices.contains(index + 1) {
                return arguments[index + 1]
            }
            if argument.hasPrefix("\(key)=") {
                return String(argument.dropFirst(key.count + 1))
            }
        }
        return nil
    }
    #endif
}
