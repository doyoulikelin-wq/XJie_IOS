import SwiftUI

/// 老年人模式：历史签到记录
struct ElderlyHistoryView: View {
    @StateObject private var vm = ElderlyViewModel()
    @State private var showAdd = false

    var body: some View {
        Group {
            if vm.history.isEmpty && !vm.loading {
                ContentUnavailableView(
                    "暂无关怀记录",
                    systemImage: "heart.text.square",
                    description: Text("打开老年人关怀模式后，App 会定期主动询问您的状态")
                )
            } else {
                List {
                    ForEach(vm.history) { row in
                        ElderlyHistoryRow(item: row)
                            .listRowSeparator(.hidden)
                            .listRowInsets(EdgeInsets(top: 6, leading: 12, bottom: 6, trailing: 12))
                            .listRowBackground(Color.clear)
                            .swipeActions {
                                Button(role: .destructive) {
                                    Task { await vm.delete(row.id) }
                                } label: { Label("删除", systemImage: "trash") }
                            }
                    }
                }
                .listStyle(.plain)
            }
        }
        .background(Color.appBackground)
        .navigationTitle("关怀记录")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { showAdd = true } label: { Image(systemName: "plus") }
            }
        }
        .task { await vm.fetchHistory() }
        .refreshable { await vm.fetchHistory() }
        .overlay { if vm.loading && vm.history.isEmpty { ProgressView() } }
        .sheet(isPresented: $showAdd) {
            ElderlyCheckinSheet(vm: vm, source: "manual")
        }
    }
}

private struct ElderlyHistoryRow: View {
    let item: ElderlyCheckin

    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM-dd HH:mm"
        return f
    }()

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(Self.formatter.string(from: item.created_at))
                    .font(.subheadline).foregroundColor(.appMuted)
                Spacer()
                if item.source == "manual" {
                    Text("主动记录").font(.caption2)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Color.appPrimary.opacity(0.15))
                        .clipShape(Capsule())
                }
            }
            HStack(spacing: 14) {
                if let a = item.activity, !a.isEmpty {
                    Label(a, systemImage: "figure.walk").font(.subheadline)
                }
                if let f = item.body_feeling, let fe = BodyFeeling(rawValue: f) {
                    Label("\(fe.emoji) \(fe.label)", systemImage: "heart").font(.subheadline)
                        .labelStyle(.titleOnly)
                }
                if let m = item.mood, let mc = MoodChoice(rawValue: m) {
                    Text("\(mc.emoji) \(mc.label)").font(.subheadline)
                }
            }
            .foregroundColor(.appText)
            if let n = item.note, !n.isEmpty {
                Text(n).font(.subheadline).foregroundColor(.appMuted)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}
