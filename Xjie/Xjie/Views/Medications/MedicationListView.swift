import SwiftUI

struct MedicationListView: View {
    @StateObject private var vm = MedicationViewModel()
    @State private var editing: Medication? = nil
    @State private var creating = false

    var body: some View {
        Group {
            if vm.loading && vm.medications.isEmpty {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if vm.medications.isEmpty {
                emptyState
            } else {
                listContent
            }
        }
        .navigationTitle("我的用药")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                Menu {
                    Button { creating = true } label: { Label("新增用药", systemImage: "plus") }
                    Button { Task { await NotificationScheduler.shared.fireTestNotification() } } label: {
                        Label("测试通知", systemImage: "bell.badge")
                    }
                    Button { Task { await NotificationScheduler.shared.scheduleTestAlarm(seconds: 10) } } label: {
                        Label("10 秒后测试闹钟", systemImage: "alarm")
                    }
                    Button { Task { await NotificationScheduler.shared.dumpPending() } } label: {
                        Label("打印已注册通知（控制台）", systemImage: "list.bullet.rectangle")
                    }
                } label: {
                    Image(systemName: "plus.circle.fill").font(.system(size: 20))
                }
            }
        }
        .sheet(isPresented: $creating) {
            MedicationEditView(editing: nil) { body in
                let ok = await vm.save(body, editing: nil)
                if ok { creating = false }
            }
        }
        .sheet(item: $editing) { med in
            MedicationEditView(editing: med) { body in
                let ok = await vm.save(body, editing: med)
                if ok { editing = nil }
            }
        }
        .task { await vm.load() }
        .alert("提示", isPresented: Binding(get: { vm.error != nil }, set: { if !$0 { vm.error = nil } })) {
            Button("好") { vm.error = nil }
        } message: { Text(vm.error ?? "") }
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            Image(systemName: "pills.fill").font(.system(size: 56)).foregroundColor(.appPrimary.opacity(0.4))
            Text("还没有添加用药").font(.system(size: 18)).foregroundColor(.appMuted)
            Button { creating = true } label: {
                Text("拍照添加用药")
                    .font(.system(size: 17, weight: .semibold))
                    .padding(.horizontal, 22)
                    .padding(.vertical, 12)
                    .background(Color.appPrimary)
                    .foregroundColor(.white)
                    .clipShape(Capsule())
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var listContent: some View {
        ScrollView {
            VStack(spacing: 12) {
                ForEach(vm.medications) { m in
                    medicationCard(m)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .background(Color.appBackground)
    }

    @ViewBuilder
    private func medicationCard(_ m: Medication) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(m.name).font(.system(size: 19, weight: .semibold))
                if let d = m.dosage, !d.isEmpty {
                    Text(d).font(.system(size: 15)).foregroundColor(.appMuted)
                }
                Spacer()
                if !m.enabled {
                    Text("已暂停").font(.system(size: 12)).padding(.horizontal, 8).padding(.vertical, 3)
                        .background(Color.gray.opacity(0.15)).clipShape(Capsule())
                }
            }
            if let f = m.frequency, !f.isEmpty {
                Text(f).font(.system(size: 14)).foregroundColor(.appMuted)
            }
            if !m.schedule_times.isEmpty {
                HStack(spacing: 6) {
                    Image(systemName: "bell.fill").font(.system(size: 12)).foregroundColor(.appPrimary)
                    Text(m.schedule_times.joined(separator: " · "))
                        .font(.system(size: 14, weight: .medium))
                        .foregroundColor(.appPrimary)
                }
            }
            if let ins = m.instructions, !ins.isEmpty {
                Text(ins).font(.system(size: 13)).foregroundColor(.appText).lineLimit(2)
            }
            HStack {
                if let s = m.course_start, let e = m.course_end {
                    Text("\(s) ~ \(e)").font(.system(size: 12)).foregroundColor(.appMuted)
                }
                Spacer()
                Button("编辑") { editing = m }.font(.system(size: 14))
                Button(role: .destructive) {
                    Task { await vm.delete(m) }
                } label: { Text("删除").font(.system(size: 14)) }
            }
        }
        .padding(14)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .shadow(color: .black.opacity(0.04), radius: 2, y: 1)
    }
}
