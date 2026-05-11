import Foundation

@MainActor
final class PatientHistoryViewModel: ObservableObject {
    @Published var profile: PatientHistoryProfile = .empty
    @Published var loading = false
    @Published var saving = false
    @Published var errorMessage: String?
    @Published var infoMessage: String?

    private let repository: PatientHistoryRepositoryProtocol

    init(repository: PatientHistoryRepositoryProtocol = PatientHistoryRepository()) {
        self.repository = repository
    }

    func load() async {
        loading = true
        defer { loading = false }
        do {
            profile = try await repository.fetch()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func updateDoctorSummary(_ text: String) {
        profile.doctor_summary = text
    }

    func updateField(key: String, value: String) {
        var field = profile.sections[key] ?? PatientHistoryField()
        field.value = value
        if value.isEmpty {
            if field.status == "confirmed" || field.status == "pending_review" {
                field.status = "missing"
            }
        } else if field.status == "missing" || field.status == "none" {
            field.status = "pending_review"
        }
        field.source_type = field.source_type.isEmpty ? "user" : field.source_type
        profile.sections[key] = field
    }

    func setFieldStatus(key: String, status: String) {
        var field = profile.sections[key] ?? PatientHistoryField()
        field.status = status
        if status == "none" {
            field.value = ""
        }
        profile.sections[key] = field
    }

    func setVerified(key: String, verified: Bool) {
        var field = profile.sections[key] ?? PatientHistoryField()
        field.verified_by_user = verified
        if verified && field.status == "pending_review" {
            field.status = "confirmed"
        }
        profile.sections[key] = field
    }

    func save() async {
        guard !saving else { return }
        saving = true
        defer { saving = false }
        let payload = PatientHistoryProfileIn(
            doctor_summary: profile.doctor_summary,
            sections: profile.sections,
            verified_at: ISO8601DateFormatter().string(from: Date())
        )
        do {
            profile = try await repository.save(payload)
            infoMessage = "已保存"
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
