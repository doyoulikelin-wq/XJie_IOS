import Foundation

struct FamilyGroup: Decodable, Identifiable {
    let id: Int
    let name: String
    let owner_user_id: Int
    let created_at: String
}

struct FamilyMember: Decodable, Identifiable {
    let id: Int
    let group_id: Int
    let user_id: Int
    let role: String
    let relation: String?
    let display_name: String?
    let status: String
    let phone: String?
    let username: String?
    let profile_name: String?
    let created_at: String

    var bestName: String {
        profile_name ?? display_name ?? username ?? phone ?? "家庭成员"
    }
}

struct FamilyPermission: Decodable {
    let id: Int?
    let subject_user_id: Int
    let viewer_user_id: Int
    var can_view_glucose_detail: Bool
    var can_view_medication: Bool
    var can_view_health_data: Bool
    var can_view_documents: Bool
    var can_view_omics: Bool
    var can_view_ai_summary: Bool

    static func empty(subject: Int, viewer: Int) -> FamilyPermission {
        FamilyPermission(
            id: nil,
            subject_user_id: subject,
            viewer_user_id: viewer,
            can_view_glucose_detail: false,
            can_view_medication: false,
            can_view_health_data: false,
            can_view_documents: false,
            can_view_omics: false,
            can_view_ai_summary: false
        )
    }
}

struct FamilyInvite: Decodable, Identifiable {
    let id: Int
    let group_id: Int
    let invite_code: String
    let target_phone: String?
    let relation: String?
    let role: String
    let status: String
    let expires_at: String
    let created_at: String
}

struct FamilySubject: Decodable, Identifiable {
    let user_id: Int
    let display_name: String
    let relation: String?
    let group_id: Int?
    let member_id: Int?
    let permissions: FamilyPermission

    var id: Int { user_id }
}

struct FamilyHealthStatus: Decodable {
    let level: String
    let reading_count: Int
    let avg: Double?
    let tir_70_180_pct: Double?
    let min: Int?
    let max: Int?

    var levelLabel: String {
        switch level {
        case "stable": return "稳定"
        case "watch": return "需留意"
        case "risk": return "需关注"
        default: return "待补数据"
        }
    }
}

struct FamilyPlanSummary: Decodable {
    let date: String
    let tasks_total: Int
    let tasks_completed: Int
    let completion_pct: Int
}

struct FamilyCareSummary: Decodable {
    let today_checkins: Int
    let last_checkin_at: String?
    let pending_care_events: Int
}

struct FamilySubjectSummary: Decodable {
    let subject: FamilySubject
    let health_status: FamilyHealthStatus
    let plan: FamilyPlanSummary
    let care: FamilyCareSummary
    let permissions: FamilyPermission
    let alerts: [String]
    let generated_at: String
}

struct FamilyCareEvent: Decodable, Identifiable {
    let id: Int
    let subject_user_id: Int
    let actor_user_id: Int
    let event_type: String
    let message: String?
    let status: String
    let created_at: String
    let handled_at: String?
}

struct FamilyGroupCreateBody: Encodable {
    let name: String
}

struct FamilyInviteCreateBody: Encodable {
    let group_id: Int?
    let target_phone: String?
    let relation: String?
    let role: String
}

struct FamilyInviteAcceptBody: Encodable {
    let invite_code: String
    let display_name: String?
}

struct FamilyPermissionPatchBody: Encodable {
    let can_view_glucose_detail: Bool?
    let can_view_medication: Bool?
    let can_view_health_data: Bool?
    let can_view_documents: Bool?
    let can_view_omics: Bool?
    let can_view_ai_summary: Bool?

    static func one(field: FamilyPermissionField, value: Bool) -> FamilyPermissionPatchBody {
        FamilyPermissionPatchBody(
            can_view_glucose_detail: field == .glucoseDetail ? value : nil,
            can_view_medication: field == .medication ? value : nil,
            can_view_health_data: field == .healthData ? value : nil,
            can_view_documents: field == .documents ? value : nil,
            can_view_omics: field == .omics ? value : nil,
            can_view_ai_summary: field == .aiSummary ? value : nil
        )
    }
}

enum FamilyPermissionField: String, CaseIterable, Identifiable {
    case glucoseDetail
    case medication
    case healthData
    case documents
    case omics
    case aiSummary

    var id: String { rawValue }

    var title: String {
        switch self {
        case .glucoseDetail: return "血糖明细"
        case .medication: return "用药信息"
        case .healthData: return "健康数据"
        case .documents: return "病例/体检原始资料"
        case .omics: return "多组学数据"
        case .aiSummary: return "AI 健康总结"
        }
    }

    var subtitle: String {
        switch self {
        case .glucoseDetail: return "允许查看平均值、TIR、最高/最低值"
        case .medication: return "允许查看用药提醒和用药信息"
        case .healthData: return "允许查看健康指标统计"
        case .documents: return "敏感资料，需单独授权"
        case .omics: return "默认关闭，真实数据上传后才建议授权"
        case .aiSummary: return "允许查看 AI 整理出的总结"
        }
    }
}

struct FamilyCareEventCreateBody: Encodable {
    let subject_user_id: Int
    let event_type: String
    let message: String?
}
