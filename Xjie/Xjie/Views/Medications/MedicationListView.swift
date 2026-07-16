import SwiftUI

/// All medication entry points share the same trusted page. The historical CRUD
/// list is intentionally unreachable so legacy rows cannot masquerade as current
/// confirmed plans.
struct MedicationListView: View {
    var body: some View {
        XAgeMedicationManagementView()
    }
}
