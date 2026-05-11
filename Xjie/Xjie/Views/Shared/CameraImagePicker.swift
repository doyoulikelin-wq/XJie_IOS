import SwiftUI
import UIKit

/// 系统相机拍照选择器（包装 UIImagePickerController）。
/// 仅支持 sourceType = .camera；如设备无相机会自动回退到相册。
struct CameraImagePicker: UIViewControllerRepresentable {
    /// 拍摄完成回调。返回 JPEG Data + 建议文件名。
    let onPick: (Data, String) -> Void
    /// 取消或失败回调（可选）。
    var onCancel: (() -> Void)? = nil
    /// JPEG 压缩质量。
    var jpegQuality: CGFloat = 0.85

    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.delegate = context.coordinator
        picker.allowsEditing = false
        if UIImagePickerController.isSourceTypeAvailable(.camera) {
            picker.sourceType = .camera
            picker.cameraCaptureMode = .photo
        } else {
            picker.sourceType = .photoLibrary
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
            let name = "meal_\(Int(Date().timeIntervalSince1970)).jpg"
            parent.onPick(data, name)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            picker.dismiss(animated: true)
            parent.onCancel?()
        }
    }
}
