import Foundation
import Combine

@MainActor
final class MedicationViewModel: ObservableObject {
    @Published var medications: [Medication] = []
    @Published var loading = false
    @Published var error: String?

    private let repo: MedicationRepositoryProtocol
    init(repo: MedicationRepositoryProtocol = MedicationRepository()) { self.repo = repo }

    func load() async {
        loading = true; defer { loading = false }
        do {
            medications = try await repo.list()
            // 加载后立即重新调度本地提醒
            await NotificationScheduler.shared.rescheduleAll(medications: medications)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func save(_ body: MedicationBody, editing: Medication?) async -> Bool {
        do {
            if let m = editing {
                let updated = try await repo.update(id: m.id, body: body)
                if let i = medications.firstIndex(where: { $0.id == m.id }) {
                    medications[i] = updated
                } else {
                    medications.insert(updated, at: 0)
                }
            } else {
                let created = try await repo.create(body)
                medications.insert(created, at: 0)
            }
            await NotificationScheduler.shared.rescheduleAll(medications: medications)
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func delete(_ m: Medication) async {
        do {
            try await repo.delete(id: m.id)
            medications.removeAll { $0.id == m.id }
            await NotificationScheduler.shared.rescheduleAll(medications: medications)
        } catch {
            self.error = error.localizedDescription
        }
    }

    func recognize(rawText: String) async -> MedicationRecognizeResult? {
        do {
            return try await repo.recognize(rawText: rawText)
        } catch {
            self.error = error.localizedDescription
            return nil
        }
    }
}
