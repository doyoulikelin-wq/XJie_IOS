import SwiftUI
import UniformTypeIdentifiers

/// 首页“快捷功能”横向功能区。
///
/// 本组件拥有快捷项展示顺序和拖拽状态，并在每次换位后立即持久化；业务页面导航仍通过
/// `onOpen` 交给页面所有者处理，因此新增按钮无需修改数据卡片、评分或同步代码。
struct XAgeQuickActionStrip: View {
    /// 点击快捷功能时回传完整、带稳定 ID 的功能定义。
    let onOpen: (XAgeQuickActionSpec) -> Void

    @State private var actions: [XAgeQuickActionSpec]
    @State private var draggedActionID: String?

    /// 创建快捷功能区。
    /// - Parameter onOpen: 用户轻点按钮后的业务路由回调。
    init(onOpen: @escaping (XAgeQuickActionSpec) -> Void) {
        self.onOpen = onOpen
        self._actions = State(initialValue: XAgeQuickActionPreferences.load())
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("快捷功能")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 9) {
                    ForEach(actions, id: \.id) { action in
                        XAgeQuickActionButton(action: action) {
                            onOpen(action)
                        }
                        .onDrag {
                            draggedActionID = action.id
                            return NSItemProvider(object: action.id as NSString)
                        }
                        .onDrop(
                            of: [UTType.text],
                            delegate: XAgeQuickActionDropDelegate(
                                targetID: action.id,
                                actions: $actions,
                                draggedID: $draggedActionID,
                                onReorder: persistOrder
                            )
                        )
                    }
                }
            }
            .accessibilityIdentifier("xage.quickActions")
        }
    }

    /// 保存用户排序，同时更新当前渲染数组。
    /// - Parameter reordered: 按稳定功能 ID 排好序的新数组。
    private func persistOrder(_ reordered: [XAgeQuickActionSpec]) {
        actions = reordered
        XAgeQuickActionPreferences.save(reordered)
    }
}

/// 单个快捷功能按钮，统一图标、文字、触控范围及辅助功能语义。
private struct XAgeQuickActionButton: View {
    let action: XAgeQuickActionSpec
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: 6) {
                Image(systemName: action.systemImage)
                    .font(.system(size: 20, weight: .bold))
                    .foregroundStyle(Color(hex: "277EBB"))
                Text(action.title)
                    .font(.system(size: action.title.count > 3 ? 11 : 12, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .frame(width: 72, height: 72)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
            .contentShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(action.title)
        .accessibilityHint("轻点打开\(action.title)功能，长按拖动可调整位置")
        .accessibilityIdentifier("xage.quickAction.\(action.id)")
    }
}

/// 每个按钮既是拖拽目标也是换位锚点；经过目标时按稳定 ID 即时重排。
private struct XAgeQuickActionDropDelegate: DropDelegate {
    let targetID: String
    @Binding var actions: [XAgeQuickActionSpec]
    @Binding var draggedID: String?
    let onReorder: ([XAgeQuickActionSpec]) -> Void

    func validateDrop(info: DropInfo) -> Bool {
        draggedID != nil && info.hasItemsConforming(to: [UTType.text])
    }

    func dropEntered(info: DropInfo) {
        guard let draggedID else { return }
        let reordered = XAgeQuickActionPreferences.reordered(
            actions,
            draggedID: draggedID,
            targetID: targetID
        )
        guard reordered.map(\.id) != actions.map(\.id) else { return }
        withAnimation(.spring(response: 0.22, dampingFraction: 0.86)) {
            onReorder(reordered)
        }
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        DropProposal(operation: .move)
    }

    func performDrop(info: DropInfo) -> Bool {
        draggedID = nil
        return true
    }
}
