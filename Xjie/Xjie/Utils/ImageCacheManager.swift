import UIKit

/// PERF-05: 图片缓存管理器 — 内存 + 磁盘双层缓存，3 天 TTL
final class ImageCacheManager {
    static let shared = ImageCacheManager()

    private let memoryCache = NSCache<NSString, UIImage>()
    private let diskCacheDir: URL
    private let maxAge: TimeInterval = 3 * 24 * 3600 // 3 天

    private init() {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        diskCacheDir = caches.appendingPathComponent("ImageCache", isDirectory: true)
        try? FileManager.default.createDirectory(at: diskCacheDir, withIntermediateDirectories: true)
        memoryCache.countLimit = 100
        memoryCache.totalCostLimit = 50 * 1024 * 1024 // 50 MB
        cleanExpired()
    }

    /// 获取缓存图片（内存优先 → 磁盘）
    func image(for url: URL) -> UIImage? {
        let key = cacheKey(for: url)

        // 1) 内存
        if let img = memoryCache.object(forKey: key as NSString) {
            return img
        }

        // 2) 磁盘
        let filePath = diskCacheDir.appendingPathComponent(key)
        guard FileManager.default.fileExists(atPath: filePath.path) else { return nil }

        // 检查过期
        if let attrs = try? FileManager.default.attributesOfItem(atPath: filePath.path),
           let modified = attrs[.modificationDate] as? Date,
           Date().timeIntervalSince(modified) > maxAge {
            try? FileManager.default.removeItem(at: filePath)
            return nil
        }

        guard let data = try? LocalFileDataLoader.read(filePath),
              let img = UIImage(data: data) else { return nil }
        memoryCache.setObject(img, forKey: key as NSString, cost: data.count)
        return img
    }

    /// 存储图片到缓存
    func store(_ image: UIImage, for url: URL) {
        let key = cacheKey(for: url)
        memoryCache.setObject(image, forKey: key as NSString)

        if let data = image.jpegData(compressionQuality: 0.8) {
            let filePath = diskCacheDir.appendingPathComponent(key)
            try? data.write(to: filePath, options: .atomic)
        }
    }

    /// 清理所有超过 3 天的缓存
    func cleanExpired() {
        DispatchQueue.global(qos: .utility).async { [diskCacheDir, maxAge] in
            guard let files = try? FileManager.default.contentsOfDirectory(
                at: diskCacheDir, includingPropertiesForKeys: [.contentModificationDateKey]
            ) else { return }

            let now = Date()
            for file in files {
                guard let attrs = try? file.resourceValues(forKeys: [.contentModificationDateKey]),
                      let modified = attrs.contentModificationDate,
                      now.timeIntervalSince(modified) > maxAge else { continue }
                try? FileManager.default.removeItem(at: file)
            }
        }
    }

    /// 清除全部缓存
    func clearAll() {
        memoryCache.removeAllObjects()
        try? FileManager.default.removeItem(at: diskCacheDir)
        try? FileManager.default.createDirectory(at: diskCacheDir, withIntermediateDirectories: true)
    }

    private func cacheKey(for url: URL) -> String {
        // SHA256-like deterministic key via simple hash
        let str = url.absoluteString
        var hash: UInt64 = 5381
        for byte in str.utf8 {
            hash = ((hash &<< 5) &+ hash) &+ UInt64(byte)
        }
        let ext = url.pathExtension.isEmpty ? "img" : url.pathExtension
        return "\(hash).\(ext)"
    }
}
