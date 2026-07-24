import Foundation

/// 就医助手最近资料的服务端只读信息。
struct MedicalAssistantRecentDocument: Decodable, Identifiable, Equatable, Sendable {
    /// 服务端文档 ID，用于进入原件/详情页。
    let document_id: String
    /// 服务端整理后的资料标题。
    let title: String
    /// 报告或病历中的医院名称；未识别时为空。
    let hospital: String?
    /// 资料正文中的医疗日期，而不是上传时间。
    let document_date: String?
    /// 文件实际上传到服务端的时间。
    let uploaded_at: String
    /// admitted / processing / failed。
    let status: String

    var id: String { document_id }
}

/// 概况生成动作的服务端结果，未知值必须保留为失败闭合状态。
enum MedicalAssistantGenerationResult: Equatable, Sendable {
    case loaded
    case generated
    case noInformationUpdate
    case noReports
    case reportProcessing
    case unknown(String)

    init(rawValue: String) {
        switch rawValue {
        case "loaded": self = .loaded
        case "generated": self = .generated
        case "no_information_update": self = .noInformationUpdate
        case "no_reports": self = .noReports
        case "report_processing": self = .reportProcessing
        default: self = .unknown(rawValue)
        }
    }
}

/// 页面一次加载所需的完整服务端快照。
struct MedicalAssistantOverview: Decodable, Equatable, Sendable {
    /// 服务端确认的本人主体 ID。
    let subject_user_id: Int
    /// 给医生查看的概况正文；空字符串表示从未生成。
    let summary: String
    /// 最近一次正式概况生成时间。
    let generated_at: String?
    /// 最近一次上传病历或报告的服务端时间。
    let latest_report_uploaded_at: String?
    /// 当前近一年内已确认并入库的资料数。
    let report_count_last_year: Int
    /// 首页展示的最近资料，服务端按上传时间倒序返回。
    let recent_documents: [MedicalAssistantRecentDocument]
    /// GET 为 loaded，POST 返回本次生成判断结果。
    let generation_result: String

    var generationResult: MedicalAssistantGenerationResult {
        MedicalAssistantGenerationResult(rawValue: generation_result)
    }

    var hasSummary: Bool {
        !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// 只用于展示“有新资料”；是否允许生成仍由服务端原子判断。
    var hasNewerUpload: Bool {
        guard let uploaded = Self.date(from: latest_report_uploaded_at),
              let generated = Self.date(from: generated_at) else {
            return latest_report_uploaded_at != nil && generated_at == nil
        }
        return uploaded > generated
    }

    /// 将服务端 ISO-8601 字符串转换为 Date；入参为空或格式非法时返回 nil。
    static func date(from value: String?) -> Date? {
        guard let value else { return nil }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: value) { return date }
        return ISO8601DateFormatter().date(from: value)
    }
}
