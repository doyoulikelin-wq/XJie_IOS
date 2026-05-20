import SwiftUI

/// 老年人关怀模式：主动询问签到弹窗（大字体大按钮）
struct ElderlyCheckinSheet: View {
    @ObservedObject var vm: ElderlyViewModel
    let source: String  // "auto_prompt" 或 "manual"
    var onDone: () -> Void = {}

    @Environment(\.dismiss) private var dismiss
    @State private var activity: String = ""
    @State private var bodyFeeling: BodyFeeling? = nil
    @State private var mood: MoodChoice? = nil
    @State private var note: String = ""

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {

                    // 头部说明
                    VStack(alignment: .leading, spacing: 6) {
                        Text("您现在好吗？")
                            .font(.system(size: 28, weight: .bold))
                        Text("请简单告诉我们您当前的状态，方便家人和医生及时关心您。")
                            .font(.system(size: 17))
                            .foregroundColor(.appMuted)
                    }

                    // 您在干什么？
                    sectionTitle("您在干什么？")
                    quickActivityGrid

                    TextField("其他...", text: $activity)
                        .font(.system(size: 20))
                        .padding(14)
                        .background(Color.appBackground)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    // 身体感觉
                    sectionTitle("身体感觉怎么样？")
                    bodyFeelingGrid

                    // 心情
                    sectionTitle("心情如何？")
                    moodGrid

                    // 备注
                    sectionTitle("还想告诉家人什么？(可选)")
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
            .background(Color(uiColor: .systemGroupedBackground))
            .navigationTitle("关怀签到")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("稍后") { dismiss() }
                        .font(.system(size: 18))
                }
            }
        }
    }

    private func sectionTitle(_ s: String) -> some View {
        Text(s).font(.system(size: 22, weight: .semibold))
    }

    private var quickActivityGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 12)], spacing: 12) {
            ForEach(CommonActivity.allCases) { a in
                Button { activity = a.rawValue } label: {
                    Text(a.rawValue)
                        .font(.system(size: 19, weight: .medium))
                        .frame(maxWidth: .infinity, minHeight: 56)
                        .background(activity == a.rawValue ? Color.appPrimary : Color.white)
                        .foregroundColor(activity == a.rawValue ? .white : .appText)
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
