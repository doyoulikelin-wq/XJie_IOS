import SwiftUI
import UIKit
import PhotosUI
import UniformTypeIdentifiers

/// 系统图片选择器（包装 UIImagePickerController）。
/// 支持相机与相册；如指定 source 不可用会自动回退到可用图片来源。
struct CameraImagePicker: UIViewControllerRepresentable {
    /// 拍摄完成回调。返回 JPEG Data + 建议文件名。
    let onPick: (Data, String) -> Void
    /// 取消或失败回调（可选）。
    var onCancel: (() -> Void)? = nil
    /// JPEG 压缩质量。
    var jpegQuality: CGFloat = 0.85
    /// 图片来源。
    var sourceType: UIImagePickerController.SourceType = .camera
    /// 文件名前缀。
    var fileNamePrefix: String = "photo"

    @Environment(\.dismiss) private var dismiss

    init(
        onPick: @escaping (Data, String) -> Void,
        onCancel: (() -> Void)? = nil,
        jpegQuality: CGFloat = 0.85,
        sourceType: UIImagePickerController.SourceType = .camera,
        fileNamePrefix: String = "photo"
    ) {
        self.onPick = onPick
        self.onCancel = onCancel
        self.jpegQuality = jpegQuality
        self.sourceType = sourceType
        self.fileNamePrefix = fileNamePrefix
    }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.delegate = context.coordinator
        picker.allowsEditing = false
        if UIImagePickerController.isSourceTypeAvailable(sourceType) {
            picker.sourceType = sourceType
        } else if UIImagePickerController.isSourceTypeAvailable(.photoLibrary) {
            picker.sourceType = .photoLibrary
        } else if UIImagePickerController.isSourceTypeAvailable(.camera) {
            picker.sourceType = .camera
        }
        if picker.sourceType == .camera {
            picker.cameraCaptureMode = .photo
        }
        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let parent: CameraImagePicker

        init(parent: CameraImagePicker) {
            self.parent = parent
        }

        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            defer { picker.dismiss(animated: true) }
            let image = (info[.originalImage] as? UIImage)
            guard let image, let data = image.jpegData(compressionQuality: parent.jpegQuality) else {
                parent.onCancel?()
                return
            }
            let name = "\(parent.fileNamePrefix)_\(Int(Date().timeIntervalSince1970)).jpg"
            parent.onPick(data, name)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            picker.dismiss(animated: true)
            parent.onCancel?()
        }
    }
}

/// 系统相册多选器。用于报告图片上传前的确认流程，最多可选择 9 张。
struct MultiPhotoPicker: UIViewControllerRepresentable {
    struct PickedPhoto: Identifiable, Equatable {
        let id = UUID()
        let data: Data
        let fileName: String
    }

    let selectionLimit: Int
    let fileNamePrefix: String
    let onPick: ([PickedPhoto]) -> Void
    var onCancel: (() -> Void)? = nil
    var onError: ((String) -> Void)? = nil

    init(
        selectionLimit: Int = 9,
        fileNamePrefix: String = "photo",
        onPick: @escaping ([PickedPhoto]) -> Void,
        onCancel: (() -> Void)? = nil,
        onError: ((String) -> Void)? = nil
    ) {
        self.selectionLimit = selectionLimit
        self.fileNamePrefix = fileNamePrefix
        self.onPick = onPick
        self.onCancel = onCancel
        self.onError = onError
    }

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var configuration = PHPickerConfiguration(photoLibrary: .shared())
        configuration.filter = .images
        configuration.selectionLimit = max(1, selectionLimit)
        configuration.preferredAssetRepresentationMode = .current
        let picker = PHPickerViewController(configuration: configuration)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        private let parent: MultiPhotoPicker

        init(parent: MultiPhotoPicker) {
            self.parent = parent
        }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            guard !results.isEmpty else {
                parent.onCancel?()
                return
            }

            Task { @MainActor in
                do {
                    var photos: [PickedPhoto] = []
                    for (index, result) in results.prefix(parent.selectionLimit).enumerated() {
                        let provider = result.itemProvider
                        let typeIdentifier = Self.preferredTypeIdentifier(from: provider)
                        let data = try await Self.loadData(from: provider, typeIdentifier: typeIdentifier)
                        let ext = Self.fileExtension(for: typeIdentifier, fallbackData: data)
                        let timestamp = Int(Date().timeIntervalSince1970)
                        photos.append(
                            PickedPhoto(
                                data: data,
                                fileName: "\(parent.fileNamePrefix)_\(timestamp)_\(index + 1).\(ext)"
                            )
                        )
                    }
                    if photos.isEmpty {
                        parent.onCancel?()
                    } else {
                        parent.onPick(photos)
                    }
                } catch {
                    parent.onError?("无法读取所选照片：\(error.localizedDescription)")
                }
            }
        }

        private static func preferredTypeIdentifier(from provider: NSItemProvider) -> String {
            let preferred = [
                UTType.heic.identifier,
                "public.heif",
                UTType.jpeg.identifier,
                UTType.png.identifier,
                UTType.tiff.identifier,
                UTType.image.identifier
            ]
            return preferred.first { provider.hasItemConformingToTypeIdentifier($0) }
                ?? provider.registeredTypeIdentifiers.first
                ?? UTType.image.identifier
        }

        private static func loadData(from provider: NSItemProvider, typeIdentifier: String) async throws -> Data {
            try await withCheckedThrowingContinuation { continuation in
                provider.loadDataRepresentation(forTypeIdentifier: typeIdentifier) { data, error in
                    if let data {
                        continuation.resume(returning: data)
                    } else {
                        continuation.resume(throwing: error ?? URLError(.cannotDecodeContentData))
                    }
                }
            }
        }

        private static func fileExtension(for typeIdentifier: String, fallbackData: Data) -> String {
            if typeIdentifier == UTType.heic.identifier { return "heic" }
            if typeIdentifier == "public.heif" { return "heif" }
            if typeIdentifier == UTType.png.identifier { return "png" }
            if typeIdentifier == UTType.tiff.identifier { return "tiff" }
            if typeIdentifier == UTType.jpeg.identifier { return "jpg" }
            if let type = UTType(typeIdentifier), let ext = type.preferredFilenameExtension {
                return ext
            }
            if UIImage(data: fallbackData) != nil {
                return "jpg"
            }
            return "img"
        }
    }
}
