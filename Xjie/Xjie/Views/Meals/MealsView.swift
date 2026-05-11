import SwiftUI
import PhotosUI

/// 膳食记录页面 — 对应小程序 pages/meals/meals
struct MealsView: View {
    @StateObject private var vm = MealsViewModel()
    @State private var showSourceDialog = false
    @State private var showCamera = false

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                // 操作按钮
                HStack(spacing: 12) {
                    Button { showSourceDialog = true } label: {
                        HStack {
                            Image(systemName: "camera")
                            Text("拍照记录")
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(
                            LinearGradient(colors: [Color.appGradientStart, Color.appGradientEnd], startPoint: .topLeading, endPoint: .bottomTrailing)
                        )
                        .foregroundColor(.white)
                        .cornerRadius(8)
                    }
                    .disabled(vm.uploading)

                    Button { vm.showManualInput = true } label: {
                        HStack {
                            Image(systemName: "pencil")
                            Text("手动记录")
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 14)
                        .background(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.appPrimary, lineWidth: 1)
                        )
                        .foregroundColor(.appPrimary)
                    }
                }

                if vm.loading {
                    ProgressView("加载中...")
                } else {
                    // 照片处理结果
                    if !vm.photos.isEmpty {
                        photosSection
                    }

                    // 膳食记录列表
                    if !vm.meals.isEmpty {
                        mealsSection

                        // PERF-03: 加载更多
                        if vm.hasMore {
                            Button {
                                Task { await vm.loadMore() }
                            } label: {
                                Text("加载更多")
                                    .font(.subheadline)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 8)
                            }
                        }
                    }

                    if vm.meals.isEmpty && vm.photos.isEmpty {
                        EmptyStateView(
                            icon: "fork.knife",
                            title: "暂无膳食记录",
                            subtitle: "点击上方按钮开始记录"
                        )
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
        }
        .background(Color.appBackground)
        .navigationTitle("膳食记录")
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.fetchData() }
        .refreshable { await vm.fetchData() }
        .photosPicker(isPresented: $vm.showPhotoPicker, selection: $vm.selectedPhoto, matching: .images)
        .onChange(of: vm.selectedPhoto) { _, newItem in
            if let item = newItem {
                Task { await vm.uploadPhoto(item: item) }
            }
        }
        .confirmationDialog("添加膳食照片", isPresented: $showSourceDialog, titleVisibility: .visible) {
            Button("拍照") { showCamera = true }
            Button("从相册选择") { vm.showPhotoPicker = true }
            Button("取消", role: .cancel) {}
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraImagePicker(
                onPick: { data, name in
                    showCamera = false
                    Task { await vm.uploadPhotoData(data, fileName: name) }
                },
                onCancel: { showCamera = false }
            )
            .ignoresSafeArea()
        }
        .alert("错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("好", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
        .alert("记录膳食", isPresented: $vm.showManualInput) {
            TextField("输入估算热量 (kcal)", text: $vm.manualKcal)
                .keyboardType(.numberPad)
            Button("取消", role: .cancel) { vm.manualKcal = "" }
            Button("添加") { Task { await vm.addMealManual() } }
        } message: {
            Text("请输入估算热量")
        }
    }

    // MARK: - 照片分析

    private var photosSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("照片分析", systemImage: "photo.on.rectangle").font(.headline)
            ForEach(vm.photos) { photo in
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(photo.status == "done" ? "已完成" : "处理中")
                            .font(.caption)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(photo.status == "done" ? Color.appSuccess.opacity(0.1) : Color.appWarning.opacity(0.1))
                            .foregroundColor(photo.status == "done" ? .appSuccess : .appWarning)
                            .cornerRadius(4)
                        if let kcal = photo.calorie_estimate_kcal {
                            Text("\(Utils.toFixed(kcal, n: 0)) kcal")
                                .font(.subheadline).bold()
                        }
                    }
                    Spacer()
                    VStack(alignment: .trailing) {
                        Text("置信度: \(photo.confidence != nil ? Utils.toFixed(photo.confidence! * 100, n: 0) + "%" : "--")")
                            .font(.caption).foregroundColor(.appMuted)
                        Text(Utils.formatDate(photo.uploaded_at))
                            .font(.caption2).foregroundColor(.appMuted)
                    }
                }
                .padding(.vertical, 4)
                Divider()
            }
        }
        .cardStyle()
    }

    // MARK: - 膳食记录

    private var mealsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("膳食记录", systemImage: "fork.knife").font(.headline)
            ForEach(vm.meals) { meal in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text("\(meal.kcal != nil ? Utils.toFixed(meal.kcal, n: 0) : "--") kcal")
                            .font(.subheadline).bold()
                        if let tags = meal.tags {
                            ForEach(tags, id: \.self) { tag in
                                Text(tag)
                                    .font(.caption2)
                                    .padding(.horizontal, 6).padding(.vertical, 2)
                                    .background(Color.appPrimary.opacity(0.1))
                                    .foregroundColor(.appPrimary)
                                    .cornerRadius(4)
                            }
                        }
                    }
                    HStack {
                        Text(Utils.formatDate(meal.meal_ts))
                            .font(.caption).foregroundColor(.appMuted)
                        if let notes = meal.notes, !notes.isEmpty {
                            Text(notes)
                                .font(.caption).foregroundColor(.appMuted)
                        }
                    }
                }
                .padding(.vertical, 4)
                Divider()
            }
        }
        .cardStyle()
    }
}


