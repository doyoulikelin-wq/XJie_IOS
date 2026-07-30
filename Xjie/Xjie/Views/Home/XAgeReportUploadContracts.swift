import Foundation
import UIKit

/// 健康报告上传入口与系统选择器之间共享的纯状态类型。
///
/// 文件只保存选择动作、文件载荷和账号归属快照，不持有 SwiftUI 页面状态或发起网络请求。
enum XAgeReportUploadAction {
    case camera
    case document
    case photoLibrary
}

struct XAgeReportUploadFile: Identifiable, Equatable {
    let id = UUID()
    let data: Data
    let fileName: String

    var previewImage: UIImage? {
        UIImage(data: data)
    }
}

/// 一次报告选择所属的登录主体。账号 scope 与数字用户 ID 必须同时有效，避免只靠其中一个字段误判身份。
struct XAgeReportUploadOwner: Equatable {
    let accountScope: String
    let subjectUserID: Int

    init?(accountScope: String?, subjectUserID: Int?) {
        guard let accountScope,
              !accountScope.isEmpty,
              let subjectUserID,
              subjectUserID > 0
        else { return nil }
        self.accountScope = accountScope
        self.subjectUserID = subjectUserID
    }
}

/// 报告选择会话的不可变身份快照；generation 额外阻断 A→B→A 后旧异步回调复活。
struct XAgeReportUploadContext: Equatable {
    let owner: XAgeReportUploadOwner
    let generation: UUID
}

struct XAgePendingReportUpload: Identifiable, Equatable {
    let id = UUID()
    let title: String
    let source: String
    let files: [XAgeReportUploadFile]
    let accountScope: String
    let subjectUserID: Int
    let accountGeneration: UUID

    init(
        title: String,
        source: String,
        files: [XAgeReportUploadFile],
        context: XAgeReportUploadContext
    ) {
        self.title = title
        self.source = source
        self.files = files
        accountScope = context.owner.accountScope
        subjectUserID = context.owner.subjectUserID
        accountGeneration = context.generation
    }

    /// 确认和上传前统一验证选择时账号、主体及会话代际仍完全一致。
    func belongs(to context: XAgeReportUploadContext?) -> Bool {
        guard let context else { return false }
        return accountScope == context.owner.accountScope
            && subjectUserID == context.owner.subjectUserID
            && accountGeneration == context.generation
    }

    var totalSizeText: String {
        let totalBytes = files.reduce(0) { $0 + $1.data.count }
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = totalBytes >= 1_000_000 ? [.useMB] : [.useKB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: Int64(totalBytes))
    }
}

/// 补页/替换页也绑定触发时主体，不能在账号切换后沿用旧工作流索引。
struct XAgePendingReportRecovery: Equatable {
    let assetIndex: Int
    let context: XAgeReportUploadContext
}

/// 报告历史请求的主体快照，阻断切号后的旧追踪响应回写。
struct XAgeReportHistoryContext: Equatable {
    let accountScope: String
    let subjectUserID: Int
}
