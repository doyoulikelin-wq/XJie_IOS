import SwiftUI

/// 关怀签到的快捷类型：决定弹窗的标题、活动选项与是否显示心情/身体感觉。
enum ElderlyCheckinKind {
    case combined        // 综合签到（默认）
    case medication      // 用药签到
    case sleep           // 睡眠复查
    case water           // 饮水复查
    case activity        // 活动复查

    var title: String {
        switch self {
        case .combined:   return "您现在好吗？"
        case .medication: return "用药签到"
        case .sleep:      return "睡眠复查"
        case .water:      return "饮水复查"
        case .activity:   return "活动复查"
        }
    }
    var subtitle: String {
        switch self {
        case .combined:   return "请简单告诉我们您当前的状态，方便家人和医生及时关心您。"
        case .medication: return "今日的药物是否已按时服用？如有不适请记录下来。"
        case .sleep:      return "昨晚睡得怎么样？是否容易入睡、是否中途醒来？"
        case .water:      return "今天大概喝了多少水？身体是否口渴？"
        case .activity:   return "今天有没有出门活动？散步或简单运动了多久？"
        }
    }
    var activitySection: String {
        switch self {
        case .combined:   return "您在干什么？"
        case .medication: return "今日服药情况"
        case .sleep:      return "昨夜睡眠情况"
        case .water:      return "今日饮水情况"
        case .activity:   return "今日活动情况"
        }
    }
    var showBodyFeeling: Bool {
        switch self {
        case .combined, .medication: return true
        default: return false
        }
    }
    var showMood: Bool {
        switch self {
        case .combined, .sleep: return true
        default: return false
        }
    }
    var bodySectionTitle: String {
        switch self {
        case .medication: return "服药后身体感觉"
        default: return "身体感觉怎么样？"
        }
    }
    var moodSectionTitle: String {
        switch self {
        case .sleep: return "醒来后心情如何？"
        default: return "心情如何？"
        }
    }
    var notePlaceholder: String { "还想告诉家人什么？(可选)" }
    var quickOptions: [String] {
        switch self {
        case .combined:   return CommonActivity.allCases.map { $0.rawValue }
        case .medication: return ["已按时服药", "忘记服药", "推迟服药", "出现副作用", "暂未到服药时间"]
        case .sleep:      return ["睡得很好", "入睡困难", "夜间多次醒", "睡眠较短", "睡眠充足"]
        case .water:      return ["饮水充足", "饮水偏少", "口渴明显", "几乎没喝水", "正常补水"]
        case .activity:   return ["今日散步", "做家务", "外出办事", "在家休息", "锻炼/拉伸"]
        }
    }
}

/// 老年人关怀模式：主动询问签到弹窗（大字体大按钮）
struct ElderlyCheckinSheet: View {
    @ObservedObject var vm: ElderlyViewModel
    let source: String  // "auto_prompt" 或 "manual"
    let kind: ElderlyCheckinKind
    var onDone: () -> Void = {}

    @Environment(\.dismiss) private var dismiss
    @State private var activity: String
    @State private var bodyFeeling: BodyFeeling? = nil
    @State private var mood: MoodChoice? = nil
    @State private var note: String = ""

    init(
        vm: ElderlyViewModel,
        source: String,
        presetActivity: String? = nil,
        kind: ElderlyCheckinKind = .combined,
        onDone: @escaping () -> Void = {}
    ) {
        self.vm = vm
        self.source = source
        self.kind = kind
        self.onDone = onDone
        _activity = State(initialValue: presetActivity ?? "")
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {

                    // 头部说明
                    VStack(alignment: .leading, spacing: 6) {
                        Text(kind.title)
                            .font(.system(size: 28, weight: .bold))
                        Text(kind.subtitle)
                            .font(.system(size: 17))
                            .foregroundColor(.appMuted)
                    }

                    sectionTitle(kind.activitySection)
                    quickActivityGrid

                    TextField("其他...", text: $activity)
                        .font(.system(size: 20))
                        .padding(14)
                        .background(Color.appBackground)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    if kind.showBodyFeeling {
                        sectionTitle(kind.bodySectionTitle)
                        bodyFeelingGrid
                    }

                    if kind.showMood {
                        sectionTitle(kind.moodSectionTitle)
                        moodGrid
                    }

                    sectionTitle(kind.notePlaceholder)
                    TextEditor(text: $note)
                        .font(.system(size: 18))
                        .frame(minHeight: 90)
                        .padding(8)
                        .background(Color.appBackground)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    if let err = vm.errorMessage {
                        Text(err).font(.subheadline).foregroundColor(.red)
                    }

                    Button {
                        Task {
                            let ok = await vm.submit(
                                activity: activity,
                                bodyFeeling: bodyFeeling,
                                mood: mood,
                                note: note,
                                source: source
                            )
                            if ok {
                                onDone()
                                dismiss()
                            }
                        }
                    } label: {
                        HStack {
                            if vm.submitting { ProgressView().tint(.white) }
                            Text(vm.submitting ? "提交中..." : "提交")
                                .font(.system(size: 22, weight: .semibold))
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 18)
                        .background(Color.appPrimary)
                        .foregroundColor(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                    }
                    .disabled(vm.submitting)
                }
                .padding(20)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle(kind.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("稍后") { dismiss() }
                        .font(.system(size: 18))
                }
                ToolbarItemGroup(placement: .keyboard) {
                    Spacer()
                    Button("完成") { Self.hideKeyboard() }
                }
            }
        }
    }

    private static func hideKeyboard() {
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil
        )
    }

    private func sectionTitle(_ s: String) -> some View {
        Text(s).font(.system(size: 22, weight: .semibold))
    }

    private var quickActivityGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 12)], spacing: 12) {
            ForEach(kind.quickOptions, id: \.self) { a in
                Button { activity = a } label: {
                    Text(a)
                        .font(.system(size: 19, weight: .medium))
                        .frame(maxWidth: .infinity, minHeight: 56)
                        .background(activity == a ? Color.appPrimary : Color.white)
                        .foregroundColor(activity == a ? .white : .appText)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .overlay(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(Color.appPrimary.opacity(0.3), lineWidth: 1)
                        )
                }
            }
        }
    }

    private var bodyFeelingGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), spacing: 12)], spacing: 12) {
            ForEach(BodyFeeling.allCases) { f in
                Button { bodyFeeling = (bodyFeeling == f ? nil : f) } label: {
                    VStack(spacing: 4) {
                        Text(f.emoji).font(.system(size: 32))
                        Text(f.label).font(.system(size: 16))
                    }
                    .frame(maxWidth: .infinity, minHeight: 78)
                    .background(bodyFeeling == f ? Color.appPrimary.opacity(0.15) : Color.white)
                    .foregroundColor(.appText)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(bodyFeeling == f ? Color.appPrimary : Color.appMuted.opacity(0.3),
                                    lineWidth: bodyFeeling == f ? 2 : 1)
                    )
                }
            }
        }
    }

    private var moodGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), spacing: 12)], spacing: 12) {
            ForEach(MoodChoice.allCases) { m in
                Button { mood = (mood == m ? nil : m) } label: {
                    VStack(spacing: 4) {
                        Text(m.emoji).font(.system(size: 32))
                        Text(m.label).font(.system(size: 16))
                    }
                    .frame(maxWidth: .infinity, minHeight: 78)
                    .background(mood == m ? Color.appPrimary.opacity(0.15) : Color.white)
                    .foregroundColor(.appText)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(mood == m ? Color.appPrimary : Color.appMuted.opacity(0.3),
                                    lineWidth: mood == m ? 2 : 1)
                    )
                }
            }
        }
    }
}
