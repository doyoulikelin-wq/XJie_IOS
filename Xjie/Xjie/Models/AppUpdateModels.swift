import Foundation

struct AppUpdateCheck: Decodable, Identifiable {
    var id: String { "\(platform)-\(latest_build)" }

    let platform: String
    let current_version: String?
    let current_build: Int?
    let latest_version: String
    let latest_build: Int
    let min_supported_build: Int
    let update_available: Bool
    let required: Bool
    let force_update: Bool
    let title: String
    let message: String
    let changelog: String
    let download_url: String?
    let store_url: String?
    let sha256: String?

    var shouldForce: Bool { required || force_update }
    var updateURLString: String? { store_url?.isEmpty == false ? store_url : download_url }
}
