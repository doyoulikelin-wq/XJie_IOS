import PDFKit
import SwiftUI

/// 一页报告原件的本地定位信息；账号、数字主体和工作流必须同时匹配才允许读取。
private struct HealthReportLocalOriginalReference: Sendable {
    let workflowID: Int
    let assetIndex: Int
    let accountScope: String
    let subjectUserID: Int
}

/// 查看原件。健康报告优先读取本机逐字节副本，本地缺失时才使用账号绑定的服务器兼容地址。
struct OriginalFileView: View {
    private let fileUrl: String?
    private let localReference: HealthReportLocalOriginalReference?
    @State private var image: UIImage?
    @State private var pdfDocument: PDFDocument?
    @State private var loading = true
    @State private var error: String?
    @State private var sourceLabel: String?

    /// 兼容旧文档详情：没有本地工作流映射时，使用当前账号绑定的服务器读取。
    /// - Parameter fileUrl: 服务端返回的相对文件地址。
    init(fileUrl: String) {
        self.fileUrl = fileUrl
        self.localReference = nil
    }

    /// 健康报告详情入口：先按账号与主体读取本机原件，缺失时再访问同账号服务器副本。
    /// - Parameters:
    ///   - workflowID: 服务端报告工作流 ID。
    ///   - assetIndex: 报告内从 1 开始的原件页序。
    ///   - fileUrl: 当前页的服务器兼容地址。
    ///   - accountScope: 打开页面时捕获的账号作用域。
    ///   - subjectUserID: 报告所属的数字用户 ID。
    init(
        workflowID: Int,
        assetIndex: Int,
        fileUrl: String?,
        accountScope: String,
        subjectUserID: Int
    ) {
        self.fileUrl = fileUrl
        self.localReference = HealthReportLocalOriginalReference(
            workflowID: workflowID,
            assetIndex: assetIndex,
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
    }

    var body: some View {
        VStack(spacing: 8) {
            if loading {
                HStack {
                    ProgressView().controlSize(.small)
                    Text("加载原件...").font(.caption).foregroundColor(.appMuted)
                }
                .frame(maxWidth: .infinity)
                .padding(20)
                .accessibilityIdentifier("xage.report.original.loading")
            } else if let image {
                VStack(spacing: 8) {
                    sourceBadge
                    OriginalZoomableImageView(image: image)
                        .frame(minHeight: 460)
                        .cornerRadius(8)
                        .shadow(color: .black.opacity(0.1), radius: 4)
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("原始报告图片已加载，可双指缩放")
                        .accessibilityIdentifier("xage.report.original.image")
                }
            } else if let pdfDocument {
                VStack(spacing: 8) {
                    sourceBadge
                    OriginalPDFDocumentView(document: pdfDocument)
                        .frame(minHeight: 460)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .accessibilityElement(children: .contain)
                        .accessibilityLabel("原始 PDF 已加载，可缩放和翻页")
                        .accessibilityIdentifier("xage.report.original.pdf")
                }
            } else if let error {
                VStack(spacing: 10) {
                    Image(systemName: "exclamationmark.triangle")
                        .foregroundColor(.appMuted)
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.appMuted)
                    Button("重新加载") {
                        Task { await loadFile() }
                    }
                    .font(.caption.weight(.bold))
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("xage.report.original.retry")
                }
                .frame(maxWidth: .infinity)
                .padding(20)
                .accessibilityIdentifier("xage.report.original.error")
            }
        }
        .cardStyle()
        .task { await loadFile() }
    }

    @ViewBuilder
    private var sourceBadge: some View {
        if let sourceLabel {
            Label(sourceLabel, systemImage: sourceLabel == "本机原件" ? "iphone" : "icloud.and.arrow.down")
                .font(.caption.weight(.semibold))
                .foregroundStyle(Color.appMuted)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("xage.report.original.source")
        }
    }

    @MainActor
    private func loadFile() async {
        loading = true
        image = nil
        pdfDocument = nil
        error = nil
        sourceLabel = nil
        defer { loading = false }

        let capturedScope = localReference?.accountScope ?? AuthManager.shared.accountScope
        guard let capturedScope,
              !capturedScope.isEmpty,
              AuthManager.shared.accountScope == capturedScope else {
            error = "登录账号已变化，请重新打开报告"
            return
        }

        var localFailure: Error?
        if let localReference {
            do {
                let asset = try await HealthReportLocalOriginalStore.shared.loadAsset(
                    workflowID: localReference.workflowID,
                    assetIndex: localReference.assetIndex,
                    accountScope: localReference.accountScope,
                    subjectUserID: localReference.subjectUserID
                )
                guard AuthManager.shared.accountScope == capturedScope else {
                    throw APIError.accountScopeChanged
                }
                if applyPayload(asset.data) {
                    sourceLabel = "本机原件"
                    return
                }
                localFailure = HealthReportLocalOriginalStoreError.reportNotFound
            } catch {
                localFailure = error
            }
        }

        guard let fileUrl,
              !fileUrl.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            error = localFailure?.localizedDescription ?? "没有可读取的报告原件"
            return
        }

        do {
            let data: Data = try await APIService.shared.getAccountBound(
                fileUrl,
                expectedAccountScope: capturedScope,
                timeout: 60
            )
            guard AuthManager.shared.accountScope == capturedScope else {
                throw APIError.accountScopeChanged
            }
            guard applyPayload(data) else {
                error = "原件格式暂不支持"
                return
            }
            sourceLabel = "服务器备份"
        } catch {
            self.error = localFailure == nil
                ? "暂时无法读取服务器原件，请稍后重试"
                : "本机原件不可用，服务器备份也暂时无法读取"
        }
    }

    /// 将通过完整性或账号校验的字节转换为可展示载荷。
    /// - Parameter data: 本机原始字节或账号绑定的服务器响应。
    /// - Returns: 是否成功识别为图片或 PDF。
    @MainActor
    private func applyPayload(_ data: Data) -> Bool {
        switch OriginalFilePayload.decode(data) {
        case .image(let loadedImage):
            image = loadedImage
            return true
        case .pdf(let loadedDocument):
            pdfDocument = loadedDocument
            return true
        case .unsupported:
            return false
        }
    }
}

enum OriginalFilePayload {
    case image(UIImage)
    case pdf(PDFDocument)
    case unsupported

    static func decode(_ data: Data) -> OriginalFilePayload {
        guard !data.isEmpty else { return .unsupported }
        if let image = UIImage(data: data) {
            return .image(image)
        }
        if let document = PDFDocument(data: data), document.pageCount > 0 {
            return .pdf(document)
        }
        return .unsupported
    }
}

private struct OriginalZoomableImageView: UIViewRepresentable {
    let image: UIImage

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: Context) -> UIScrollView {
        let scrollView = UIScrollView()
        scrollView.backgroundColor = .secondarySystemBackground
        scrollView.delegate = context.coordinator
        scrollView.minimumZoomScale = 1
        scrollView.maximumZoomScale = 6
        scrollView.bouncesZoom = true
        scrollView.showsHorizontalScrollIndicator = true
        scrollView.showsVerticalScrollIndicator = true

        let imageView = UIImageView(image: image)
        imageView.contentMode = .scaleAspectFit
        imageView.translatesAutoresizingMaskIntoConstraints = false
        imageView.isAccessibilityElement = false
        scrollView.addSubview(imageView)
        context.coordinator.imageView = imageView
        context.coordinator.aspectConstraint = imageView.heightAnchor.constraint(
            equalTo: imageView.widthAnchor,
            multiplier: max(image.size.height / max(image.size.width, 1), 0.1)
        )
        context.coordinator.aspectConstraint?.isActive = true
        NSLayoutConstraint.activate([
            imageView.leadingAnchor.constraint(equalTo: scrollView.contentLayoutGuide.leadingAnchor),
            imageView.trailingAnchor.constraint(equalTo: scrollView.contentLayoutGuide.trailingAnchor),
            imageView.topAnchor.constraint(equalTo: scrollView.contentLayoutGuide.topAnchor),
            imageView.bottomAnchor.constraint(equalTo: scrollView.contentLayoutGuide.bottomAnchor),
            imageView.widthAnchor.constraint(equalTo: scrollView.frameLayoutGuide.widthAnchor)
        ])
        return scrollView
    }

    func updateUIView(_ scrollView: UIScrollView, context: Context) {
        guard let imageView = context.coordinator.imageView,
              imageView.image !== image else { return }
        imageView.image = image
        context.coordinator.aspectConstraint?.isActive = false
        context.coordinator.aspectConstraint = imageView.heightAnchor.constraint(
            equalTo: imageView.widthAnchor,
            multiplier: max(image.size.height / max(image.size.width, 1), 0.1)
        )
        context.coordinator.aspectConstraint?.isActive = true
        scrollView.setZoomScale(1, animated: false)
    }

    final class Coordinator: NSObject, UIScrollViewDelegate {
        weak var imageView: UIImageView?
        var aspectConstraint: NSLayoutConstraint?

        func viewForZooming(in scrollView: UIScrollView) -> UIView? {
            imageView
        }
    }
}

private struct OriginalPDFDocumentView: UIViewRepresentable {
    let document: PDFDocument

    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.displaysPageBreaks = true
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        if view.document !== document {
            view.document = document
        }
    }
}
