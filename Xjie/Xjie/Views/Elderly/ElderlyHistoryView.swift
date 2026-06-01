import SwiftUI

/// 关怀模式：历史签到记录（按类型分组）
struct ElderlyHistoryView: View {
    @StateObject private var vm = ElderlyViewModel()
    @State private var showAdd = false

    /// 分组后的数据：保持稳定顺序
    private var grouped: [(kind: ElderlyCheckinKind, items: [ElderlyCheckin])] {
        let order: [ElderlyCheckinKind] = [.medication, .sleep, .water, .activity, .combined]
        var bucket: [ElderlyCheckinKind: [ElderlyCheckin]] = [:]
        for r in vm.history {
            let k = ElderlyCheckinKind.from(apiValue: r.prompt_type)
            bucket[k, default: []].append(r)
        }
        return order.compactMap { k in
            guard let items = bucket[k], !items.isEmpty else { return nil }
            return (k, items)
        }
    }

    var body: some View {
        Group {
            if vm.history.isEmpty && !vm.loading {
                VStack(spacing: 8) {
                    Text("暂无关怀记录")
                        .font(.headline)
                    Text("打开关怀模式后，App 会定期主动询问您的状态")
                        .font(.subheadline)
                        .foregroundColor(.appMuted)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                List {
                    ForEach(grouped, id: \.kind) { group in
                        Section {
                            ForEach(group.items) { row in
                                ElderlyHistoryRow(item: row, kind: group.kind)
                                    .listRowSeparator(.hidden)
                                    .listRowInsets(EdgeInsets(top: 6, leading: 12, bottom: 6, trailing: 12))
                                    .listRowBackground(Color.clear)
                                    .swipeActions {
                                        Button(role: .destructive) {
                                            Task { await vm.delete(row.id) }
                                        } label: { Text("删除") }
                                    }
                            }
                        } header: {
                            HStack(spacing: 6) {
                                Text(group.kind.displayName)
                                    .font(.subheadline).bold()
                                    .foregroundColor(.appText)
                                Text("(\(group.items.count))")
                                    .font(.caption)
                                    .foregroundColor(.appMuted)
                            }
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
                Button { showAdd = true } label: { Text("新增") }
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
    let kind: ElderlyCheckinKind

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
                    Text(a).font(.subheadline)
                }
                if let f = item.body_feeling, let fe = BodyFeeling(rawValue: f) {
                    Text(fe.label).font(.subheadline)
                }
                if let m = item.mood, let mc = MoodChoice(rawValue: m) {
                    Text(mc.label).font(.subheadline)
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
