import Foundation

/// MIME 类型推断 — 消除各 ViewModel 中的重复逻辑
enum MIMETypeHelper {
    static func mimeType(forExtension ext: String) -> String {
        switch ext.lowercased() {
        case "jpg", "jpeg": return "image/jpeg"
        case "png": return "image/png"
        case "heic": return "image/heic"
        case "heif": return "image/heif"
        case "webp": return "image/webp"
        case "gif": return "image/gif"
        case "tif", "tiff": return "image/tiff"
        case "csv": return "text/csv"
        case "pdf": return "application/pdf"
        default: return "application/octet-stream"
        }
    }

    static func mimeType(forFileName fileName: String) -> String {
        let ext = (fileName as NSString).pathExtension
        return mimeType(forExtension: ext)
    }
}
