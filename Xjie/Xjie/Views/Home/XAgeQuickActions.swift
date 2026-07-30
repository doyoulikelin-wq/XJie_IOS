import SwiftUI
import UniformTypeIdentifiers

/// 首页“快捷功能”横向功能区。
///
/// 本组件拥有快捷项展示顺序和拖拽状态，并只在用户真正释放到目标按钮后持久化；业务页面导航
/// 仍通过 `onOpen` 交给页面所有者处理，因此新增按钮无需修改数据卡片、评分或同步代码。
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
                                onCommit: persistOrder
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

/// 每个按钮都是释放锚点；排序只在真正释放时提交，经过或取消拖动都不会改写用户顺序。
private struct XAgeQuickActionDropDelegate: DropDelegate {
    let targetID: String
    @Binding var actions: [XAgeQuickActionSpec]
    @Binding var draggedID: String?
    let onCommit: ([XAgeQuickActionSpec]) -> Void

    func validateDrop(info: DropInfo) -> Bool {
        guard let draggedID,
              actions.contains(where: { $0.id == draggedID }) else { return false }
        return info.hasItemsConforming(to: [UTType.text])
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        DropProposal(operation: .move)
    }

    func performDrop(info: DropInfo) -> Bool {
        guard let draggedID else { return false }
        defer { self.draggedID = nil }
        let reordered = XAgeQuickActionPreferences.reordered(
            actions,
            draggedID: draggedID,
            targetID: targetID
        )
        guard reordered.map(\.id) != actions.map(\.id) else { return false }
        withAnimation(.spring(response: 0.22, dampingFraction: 0.86)) {
            onCommit(reordered)
        }
        return true
    }
}
