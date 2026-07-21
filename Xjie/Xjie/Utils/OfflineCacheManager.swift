import Foundation

/// NET-03: 离线缓存 — 将 API 响应缓存到本地文件供离线时展示
final class OfflineCacheManager {
    static let shared = OfflineCacheManager()

    private let cacheDir: URL
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init() {
        cacheDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("offline_cache", isDirectory: true)
        try? FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
    }

    /// 缓存 Encodable 数据
    func save<T: Encodable>(_ data: T, for key: String) {
        let file = cacheDir.appendingPathComponent(key.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? key)
        if let encoded = try? encoder.encode(data) {
            try? encoded.write(to: file, options: .atomic)
        }
    }

    /// 读取缓存
    func load<T: Decodable>(for key: String) -> T? {
        let file = cacheDir.appendingPathComponent(key.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? key)
        guard let data = try? LocalFileDataLoader.read(file) else { return nil }
        return try? decoder.decode(T.self, from: data)
    }

    /// 清除全部缓存
    func clearAll() {
        try? FileManager.default.removeItem(at: cacheDir)
        try? FileManager.default.createDirectory(at: cacheDir, withIntermediateDirectories: true)
    }
}
