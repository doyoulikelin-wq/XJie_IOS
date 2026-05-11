import SwiftUI
import PhotosUI

@MainActor
final class MealsViewModel: ObservableObject {
    @Published var loading = false
    @Published var meals: [MealItem] = []
    @Published var photos: [MealPhoto] = []
    @Published var uploading = false
    @Published var showPhotoPicker = false
    @Published var selectedPhoto: PhotosPickerItem?
    @Published var showManualInput = false
    @Published var manualKcal = ""
    @Published var errorMessage: String?
    /// PERF-03: 分页
    @Published var hasMore = true
    private let pageSize = APIConstants.pageSize

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchData() async {
        loading = true
        defer { loading = false }
        // 后端 /api/meals 列表使用 from/to 时间范围（最近 30 天）
        let now = Date()
        let from = Calendar.current.date(byAdding: .day, value: -30, to: now) ?? now.addingTimeInterval(-30 * 86400)
        let iso = ISO8601DateFormatter()
        let mealsPath = URLBuilder.path("/api/meals", queryItems: [
            URLQueryItem(name: "from", value: iso.string(from: from)),
            URLQueryItem(name: "to", value: iso.string(from: now))
        ])
        async let m: [MealItem] = (try? await api.get(mealsPath)) ?? []
        async let p: [MealPhoto] = (try? await api.get("/api/dashboard/meals")) ?? []
        let fetchedMeals = await m
        let fetchedPhotos = await p
        guard !Task.isCancelled else { return }
        meals = fetchedMeals
        photos = fetchedPhotos
        hasMore = meals.count >= pageSize
    }

    /// PERF-03: 加载更多（后端暂不支持 offset 分页，这里简单关闭）
    func loadMore() async {
        hasMore = false
    }

    func uploadPhoto(item: PhotosPickerItem) async {
        guard let data = try? await item.loadTransferable(type: Data.self) else {
            selectedPhoto = nil
            return
        }
        defer { selectedPhoto = nil }
        await uploadPhotoData(data, fileName: "meal.jpg")
    }

    /// 直接上传二进制图片数据（用于相机拍照）
    func uploadPhotoData(_ data: Data, fileName: String = "meal.jpg") async {
        uploading = true
        defer { uploading = false }

        do {
            // Step 1: 获取上传凭证
            let ticket: MealUploadTicket = try await api.post(
                "/api/meals/photo/upload-url",
                body: PhotoUploadBody(filename: fileName, content_type: "image/jpeg")
            )

            // Step 2: 上传文件
            if let uploadUrl = ticket.upload_url, !uploadUrl.isEmpty {
                // 后端 mock-upload: PUT + multipart/form-data, 字段名 file
                try await putMultipartUpload(path: uploadUrl, fileData: data, fileName: fileName, mimeType: "image/jpeg")
            } else {
                _ = try await api.uploadFile(
                    "/api/meals/photo/upload", fileData: data, fileName: fileName, mimeType: "image/jpeg", formData: [:]
                )
            }

            // Step 3: 通知完成
            if let objectKey = ticket.object_key {
                try await api.postVoid(
                    "/api/meals/photo/complete",
                    body: PhotoCompleteBody(object_key: objectKey)
                )
            }

            await fetchData()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// PUT + multipart/form-data 上传（适配后端 mock-upload UploadFile 接口）
    private func putMultipartUpload(path: String, fileData: Data, fileName: String, mimeType: String) async throws {
        let auth = await AuthManager.shared
        let token = await auth.token
        let baseURL = AppEnvironment.apiBaseURL
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL(path)
        }
        let boundary = UUID().uuidString
        var req = URLRequest(url: url)
        req.httpMethod = "PUT"
        req.timeoutInterval = APIConstants.uploadTimeout
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        if !token.isEmpty {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        var body = Data()
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n".utf8))
        body.append(Data("Content-Type: \(mimeType)\r\n\r\n".utf8))
        body.append(fileData)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        req.httpBody = body
        let (data, response) = try await APIService.shared.trustedSession.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "上传失败"
            throw APIError.httpError(http.statusCode, msg)
        }
    }

    func addMealManual() async {
        guard let kcal = Int(manualKcal), kcal > 0 else {
            errorMessage = "请输入有效的热量数值"
            return
        }
        manualKcal = ""
        do {
            try await api.postVoid(
                "/api/meals",
                body: MealCreateBody(
                    meal_ts: ISO8601DateFormatter().string(from: Date()),
                    meal_ts_source: "user_confirmed",
                    kcal: kcal,
                    tags: [],
                    notes: ""
                )
            )
            await fetchData()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
