import SwiftUI

/// 查看原件 — 从后端加载并展示用户上传的原始图片/文件
struct OriginalFileView: View {
    let fileUrl: String
    @State private var image: UIImage?
    @State private var loading = true
    @State private var error: String?

    var body: some View {
        VStack(spacing: 8) {
            if loading {
                HStack {
                    ProgressView().controlSize(.small)
                    Text("加载原件...").font(.caption).foregroundColor(.appMuted)
                }
                .frame(maxWidth: .infinity)
                .padding(20)
            } else if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .cornerRadius(8)
                    .shadow(color: .black.opacity(0.1), radius: 4)
            } else if let error {
                VStack(spacing: 4) {
                    Image(systemName: "exclamationmark.triangle")
                        .foregroundColor(.appMuted)
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                }
                .frame(maxWidth: .infinity)
                .padding(20)
            }
        }
        .cardStyle()
        .task { await loadFile() }
    }

    private func loadFile() async {
        loading = true
        defer { loading = false }

        let base = AppEnvironment.apiBaseURL

        guard let url = URL(string: base + fileUrl) else {
            error = "无效地址"
            return
        }

        var request = URLRequest(url: url)
        let token = await AuthManager.shared.token
        if !token.isEmpty {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        do {
            let (data, response) = try await APIService.shared.trustedSession.data(for: request)
            guard let httpResp = response as? HTTPURLResponse, httpResp.statusCode == 200 else {
                error = "加载失败"
                return
            }
            if let img = UIImage(data: data) {
                image = img
            } else {
                error = "不支持的文件格式"
            }
        } catch {
            self.error = "网络错误"
        }
    }
}
