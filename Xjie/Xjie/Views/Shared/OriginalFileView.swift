import PDFKit
import SwiftUI

/// 查看原件 — 从后端加载并展示用户上传的原始图片/文件
struct OriginalFileView: View {
    let fileUrl: String
    @State private var image: UIImage?
    @State private var pdfDocument: PDFDocument?
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
                .accessibilityIdentifier("xage.report.original.loading")
            } else if let image {
                OriginalZoomableImageView(image: image)
                    .frame(minHeight: 460)
                    .cornerRadius(8)
                    .shadow(color: .black.opacity(0.1), radius: 4)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("原始报告图片已加载，可双指缩放")
                    .accessibilityIdentifier("xage.report.original.image")
            } else if let pdfDocument {
                OriginalPDFDocumentView(document: pdfDocument)
                    .frame(minHeight: 460)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .accessibilityElement(children: .contain)
                    .accessibilityLabel("原始 PDF 已加载，可缩放和翻页")
                    .accessibilityIdentifier("xage.report.original.pdf")
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

    private func loadFile() async {
        loading = true
        image = nil
        pdfDocument = nil
        error = nil
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
            switch OriginalFilePayload.decode(data) {
            case .image(let loadedImage):
                image = loadedImage
            case .pdf(let loadedDocument):
                pdfDocument = loadedDocument
            case .unsupported:
                error = "不支持的文件格式"
            }
        } catch {
            self.error = "网络错误"
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
