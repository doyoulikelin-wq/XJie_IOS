import SwiftUI
import UIKit

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
