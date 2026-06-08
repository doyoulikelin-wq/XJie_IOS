import Foundation

@MainActor
final class FamilyViewModel: ObservableObject {
    @Published var groups: [FamilyGroup] = []
    @Published var members: [FamilyMember] = []
    @Published var subjects: [FamilySubject] = []
    @Published var selectedSubject: FamilySubject?
    @Published var selectedSummary: FamilySubjectSummary?
    @Published var permissionsByViewer: [Int: FamilyPermission] = [:]
    @Published var latestInvite: FamilyInvite?
    @Published var loading = false
    @Published var errorMessage: String?
    @Published var message: String?
    @Published var currentUserId: Int?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func load() async {
        loading = true
        defer { loading = false }
        do {
            async let user: UserInfo = api.get("/api/users/me")
            async let fetchedGroups: [FamilyGroup] = api.get("/api/family/groups")
            async let fetchedMembers: [FamilyMember] = api.get("/api/family/members")
            async let fetchedSubjects: [FamilySubject] = api.get("/api/family/subjects")
            let fetchedUser = try await user
            currentUserId = Int(fetchedUser.id ?? "")
            groups = try await fetchedGroups
            members = try await fetchedMembers
            subjects = try await fetchedSubjects
            if selectedSubject == nil {
                selectedSubject = subjects.first
            }
            await loadPermissionsForMembers()
            if let subject = selectedSubject {
                await loadSummary(subject)
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func createGroupIfNeeded() async -> Int? {
        if let id = groups.first?.id { return id }
        do {
            let group: FamilyGroup = try await api.post("/api/family/groups", body: FamilyGroupCreateBody(name: "我的家庭"))
            groups = [group]
            return group.id
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func createInvite(targetPhone: String?, relation: String?) async {
        let groupId = await createGroupIfNeeded()
        do {
            let invite: FamilyInvite = try await api.post(
                "/api/family/invites",
                body: FamilyInviteCreateBody(
                    group_id: groupId,
                    target_phone: targetPhone?.nilIfBlank,
                    relation: relation?.nilIfBlank,
                    role: "member"
                )
            )
            latestInvite = invite
            message = "邀请码已生成"
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func acceptInvite(code: String, displayName: String?) async {
        do {
            let _: FamilyMember = try await api.post(
                "/api/family/invites/accept",
                body: FamilyInviteAcceptBody(invite_code: code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased(), display_name: displayName?.nilIfBlank)
            )
            message = "已加入家庭"
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadSummary(_ subject: FamilySubject) async {
        selectedSubject = subject
        do {
            selectedSummary = try await api.get("/api/family/subjects/\(subject.user_id)/summary")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func sendCareEvent(type: String, message: String?, subject: FamilySubject? = nil) async {
        guard let target = subject ?? selectedSubject else { return }
        do {
            let _: FamilyCareEvent = try await api.post(
                "/api/family/care-events",
                body: FamilyCareEventCreateBody(subject_user_id: target.user_id, event_type: type, message: message)
            )
            self.message = "已记录关心提醒"
            await loadSummary(target)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func permission(for viewerUserId: Int) -> FamilyPermission {
        FamilyPermission.empty(subject: currentUserId ?? 0, viewer: viewerUserId)
            .merging(permissionsByViewer[viewerUserId])
    }

    func value(for viewerUserId: Int, field: FamilyPermissionField) -> Bool {
        let p = permission(for: viewerUserId)
        switch field {
        case .glucoseDetail: return p.can_view_glucose_detail
        case .medication: return p.can_view_medication
        case .healthData: return p.can_view_health_data
        case .documents: return p.can_view_documents
        case .omics: return p.can_view_omics
        case .aiSummary: return p.can_view_ai_summary
        }
    }

    func togglePermission(viewerUserId: Int, field: FamilyPermissionField, value: Bool) async {
        do {
            let updated: FamilyPermission = try await api.patch(
                "/api/family/permissions/\(viewerUserId)",
                body: FamilyPermissionPatchBody.one(field: field, value: value)
            )
            permissionsByViewer[viewerUserId] = updated
            message = "授权已更新"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func loadPermissionsForMembers() async {
        guard let currentUserId else { return }
        let viewers = members
            .filter { $0.user_id != currentUserId && $0.status == "active" }
            .map(\.user_id)
        var result = permissionsByViewer
        for viewer in viewers {
            do {
                let permission: FamilyPermission = try await api.get("/api/family/permissions/\(viewer)")
                result[viewer] = permission
            } catch {
                continue
            }
        }
        permissionsByViewer = result
    }
}

private extension FamilyPermission {
    func merging(_ other: FamilyPermission?) -> FamilyPermission {
        other ?? self
    }
}

private extension String {
    var nilIfBlank: String? {
        let value = trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }
}
