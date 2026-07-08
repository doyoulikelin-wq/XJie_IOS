import AVFoundation
import Speech
import SwiftUI
import UIKit

enum XAgeTopSection: String, CaseIterable, Identifiable {
    case data = "数据"
    case chat = "问答"
    case xAge = "X年龄"

    var id: String { rawValue }
}

private extension View {
    @ViewBuilder
    func xAgeAccessibilitySelected(_ isSelected: Bool) -> some View {
        if isSelected {
            accessibilityAddTraits(.isSelected)
        } else {
            self
        }
    }
}

struct XAgeMainView: View {
    @Environment(\.scenePhase) private var scenePhase
    @EnvironmentObject private var externalReportImport: XAgeExternalReportImportRouter
    @StateObject private var appleHealthSync = AppleHealthSyncViewModel()
    @StateObject private var serverSync = XAgeServerSyncViewModel()
    @StateObject private var externalReportUploadVM = HealthDataViewModel()
    @State private var selectedSection: XAgeTopSection = Self.initialSection()
    @State private var selectedDataPanelCategory: XAgeDataPanelCategory = .reports
    @State private var showMoreMenu = false
    @State private var dataSortMode = false
    @State private var chatHistoryRequest = 0
    @State private var xAgeInfoRequest = 0
    @State private var pendingExternalUpload: XAgePendingReportUpload?
    @State private var externalImportError: String?

    var body: some View {
        NavigationStack {
            ZStack {
                XAgeLiquidBackground()
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    XAgeTopBar(
                        selected: $selectedSection,
                        showMoreMenu: $showMoreMenu,
                        dataSortMode: dataSortMode,
                        onToggleDataSort: {
                            withAnimation(.spring(response: 0.28, dampingFraction: 0.88)) {
                                dataSortMode.toggle()
                            }
                        },
                        onOpenChatHistory: {
                            chatHistoryRequest += 1
                        },
                        onOpenXAgeInfo: {
                            xAgeInfoRequest += 1
                        }
                    )
                    .padding(.top, 12)
                    .padding(.horizontal, 24)
                    .zIndex(2)

                    ZStack {
                        XAgeDataDashboardView(
                            sortMode: $dataSortMode,
                            appleHealthSync: appleHealthSync,
                            serverSync: serverSync,
                            scores: compositeScores,
                            onOpenMetricGuide: openMetricGuide
                        )
                            .opacity(selectedSection == .data ? 1 : 0)
                            .allowsHitTesting(selectedSection == .data)
                            .accessibilityHidden(selectedSection != .data)
                            .zIndex(selectedSection == .data ? 1 : 0)

                        XAgeConversationSurface(
                            selectedSection: $selectedSection,
                            historyRequest: chatHistoryRequest
                        )
                            .opacity(selectedSection == .chat ? 1 : 0)
                            .allowsHitTesting(selectedSection == .chat)
                            .accessibilityHidden(selectedSection != .chat)
                            .zIndex(selectedSection == .chat ? 1 : 0)

                        XAgeHealthspanView(
                            selectedSection: $selectedSection,
                            infoRequest: xAgeInfoRequest,
                            scores: compositeScores
                        )
                            .opacity(selectedSection == .xAge ? 1 : 0)
                            .allowsHitTesting(selectedSection == .xAge)
                            .accessibilityHidden(selectedSection != .xAge)
                            .zIndex(selectedSection == .xAge ? 1 : 0)
                    }
                    .animation(.easeInOut(duration: 0.18), value: selectedSection)
                }
            }
            .navigationBarHidden(true)
            .sheet(isPresented: $showMoreMenu) {
                XAgeMoreMenu(
                    selectedCategory: $selectedDataPanelCategory,
                    appleHealthSync: appleHealthSync,
                    snapshot: serverSync.snapshot,
                    onSelectCategory: selectPanelCategory,
                    onClose: { showMoreMenu = false }
                )
                    .presentationDetents([.large])
            }
            .sheet(item: $pendingExternalUpload) { upload in
                XAgeReportUploadConfirmSheet(
                    upload: upload,
                    isUploading: externalReportUploadVM.uploading,
                    onCancel: { pendingExternalUpload = nil },
                    onConfirm: {
                        pendingExternalUpload = nil
                        uploadExternalReports(upload.files)
                    }
                )
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
            }
            .alert("导入失败", isPresented: Binding(
                get: { externalImportError != nil },
                set: { if !$0 { externalImportError = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(externalImportError ?? "")
            }
            .alert("上传提示", isPresented: Binding(
                get: { externalReportUploadVM.infoMessage != nil },
                set: { if !$0 { externalReportUploadVM.infoMessage = nil } }
            )) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text(externalReportUploadVM.infoMessage ?? "")
            }
            .alert("上传失败", isPresented: Binding(
                get: { externalReportUploadVM.errorMessage != nil },
                set: { if !$0 { externalReportUploadVM.errorMessage = nil } }
            )) {
                Button("确定", role: .cancel) {}
            } message: {
                Text(externalReportUploadVM.errorMessage ?? "")
            }
            .onAppear {
                handlePendingExternalImportIfNeeded()
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
            .onChange(of: scenePhase) { _, phase in
                guard phase == .active else { return }
                Task { await refreshXAgeDataFromAppLifecycle() }
            }
            .onChange(of: externalReportImport.pendingImport) { _, _ in
                handlePendingExternalImportIfNeeded()
            }
        }
    }

    private var compositeScores: XAgeCompositeScores {
        XAgeCompositeScores.compute(
            context: XAgeAlgorithmContext(
                snapshot: serverSync.snapshot,
                samples: appleHealthSync.samples
            )
        )
    }

    private func selectPanelCategory(_ category: XAgeDataPanelCategory) {
        selectedDataPanelCategory = category
        dataSortMode = false
        withAnimation(.spring(response: 0.3, dampingFraction: 0.86)) {
            selectedSection = .data
        }
    }

    private func openMetricGuide(_ kind: XAgeDataKind) {
        dataSortMode = false
        selectedDataPanelCategory = kind == .inflammation ? .reports : .daily
        showMoreMenu = true
    }

    private func refreshXAgeDataFromAppLifecycle() async {
        guard AuthManager.shared.isLoggedIn else { return }
        await appleHealthSync.refreshIfPreviouslySynced()
        await serverSync.refresh()
    }

    private func handlePendingExternalImportIfNeeded() {
        guard let item = externalReportImport.pendingImport else { return }
        externalReportImport.markHandled(item.id)
        Task { await prepareExternalReportImport(item.url) }
    }

    private func prepareExternalReportImport(_ url: URL) async {
        let access = url.startAccessingSecurityScopedResource()
        defer {
            if access {
                url.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let data = try Data(contentsOf: url)
            guard !data.isEmpty else {
                externalImportError = "文件为空，无法上传。"
                return
            }
            let fileName = url.lastPathComponent.isEmpty ? "外部导入报告" : url.lastPathComponent
            let file = XAgeReportUploadFile(data: data, fileName: fileName)
            pendingExternalUpload = XAgePendingReportUpload(
                title: "确认导入报告",
                source: "打开方式",
                files: [file]
            )
            selectedSection = .data
            selectedDataPanelCategory = .reports
        } catch {
            externalImportError = "无法读取该文件：\(error.localizedDescription)"
        }
    }

    private func uploadExternalReports(_ files: [XAgeReportUploadFile]) {
        guard !files.isEmpty else { return }
        externalReportUploadVM.uploadDocType = "exam"
        Task {
            for file in files {
                _ = await externalReportUploadVM.uploadFile(data: file.data, fileName: file.fileName)
            }
            await serverSync.refresh()
        }
    }

    private static func initialSection() -> XAgeTopSection {
        #if DEBUG
        if let rawValue = ProcessInfo.processInfo.environment["XAGE_INITIAL_SECTION"] ?? launchArgumentValue(for: "XAGE_INITIAL_SECTION"),
           let section = XAgeTopSection.section(matching: rawValue) {
            return section
        }
        #endif
        return .data
    }

    #if DEBUG
    private static func launchArgumentValue(for key: String) -> String? {
        let arguments = ProcessInfo.processInfo.arguments
        for (index, argument) in arguments.enumerated() {
            if argument == key, arguments.indices.contains(index + 1) {
                return arguments[index + 1]
            }
            if argument.hasPrefix("\(key)=") {
                return String(argument.dropFirst(key.count + 1))
            }
        }
        return nil
    }
    #endif
}

#if DEBUG
private extension XAgeTopSection {
    static func section(matching value: String) -> XAgeTopSection? {
        switch value {
        case "data", "数据":
            return .data
        case "chat", "qa", "问答":
            return .chat
        case "xAge", "xage", "X年龄":
            return .xAge
        default:
            return nil
        }
    }
}
#endif

private struct XAgeTopBar: View {
    @Binding var selected: XAgeTopSection
    @Binding var showMoreMenu: Bool
    let dataSortMode: Bool
    let onToggleDataSort: () -> Void
    let onOpenChatHistory: () -> Void
    let onOpenXAgeInfo: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            Button {
                showMoreMenu = true
            } label: {
                Image(systemName: "line.3.horizontal")
                    .font(.system(size: 18, weight: .semibold))
                    .frame(width: 34, height: 34)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "173F64"))
            .accessibilityLabel("资料菜单")
            .accessibilityIdentifier("xage.more")

            HStack(spacing: 0) {
                ForEach(XAgeTopSection.allCases) { section in
                    Button {
                        withAnimation(.spring(response: 0.32, dampingFraction: 0.86)) {
                            selected = section
                        }
                    } label: {
                        Text(section.rawValue)
                            .font(.system(size: 15, weight: selected == section ? .bold : .medium))
                            .foregroundStyle(selected == section ? Color(hex: "1268BD") : Color(hex: "4E718E"))
                            .frame(width: section == .xAge ? 80 : 70, height: 38)
                            .contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("xage.segment.\(section.id)")
                    .buttonStyle(.plain)
                    .background {
                        if selected == section {
                            RoundedRectangle(cornerRadius: 19, style: .continuous)
                                .fill(.white.opacity(0.72))
                                .overlay(
                                    RoundedRectangle(cornerRadius: 19, style: .continuous)
                                        .stroke(.white.opacity(0.92), lineWidth: 1)
                                )
                                .shadow(color: Color(hex: "2FB6E3").opacity(0.16), radius: 16, x: 0, y: 8)
                        }
                    }
                }
            }
            .frame(width: 238, height: 48)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(.white.opacity(0.48))
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(.white.opacity(0.86), lineWidth: 1)
                    )
                    .shadow(color: Color(hex: "7CCAF5").opacity(0.16), radius: 22, x: 0, y: 10)
            )

            if selected == .xAge {
                Color.clear
                    .frame(width: 52, height: 38)
                    .accessibilityHidden(true)
            } else {
                Button {
                    if selected == .data {
                        onToggleDataSort()
                    } else if selected == .chat {
                        onOpenChatHistory()
                    }
                } label: {
                    Group {
                        if selected == .data {
                            Text(dataSortMode ? "完成" : "排序")
                                .font(.system(size: 14, weight: .bold))
                                .frame(width: 52, height: 34)
                        } else {
                            Image(systemName: "clock.arrow.circlepath")
                                .font(.system(size: 18, weight: .bold))
                                .frame(width: 38, height: 38)
                        }
                    }
                    .background(
                        Capsule()
                            .fill(.white.opacity(0.48))
                            .overlay(Capsule().stroke(.white.opacity(0.86), lineWidth: 1))
                    )
                }
                .buttonStyle(.plain)
                .foregroundStyle(selected == .chat ? Color(hex: "173F64") : Color(hex: "2A79BB"))
                .accessibilityIdentifier(selected == .data ? (dataSortMode ? "xage.data.sort.done" : "xage.data.sort") : "xage.chat.history")
            }
        }
    }
}

private struct XAgeDataDashboardView: View {
    @Binding var sortMode: Bool
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @ObservedObject var serverSync: XAgeServerSyncViewModel
    let scores: XAgeCompositeScores
    let onOpenMetricGuide: (XAgeDataKind) -> Void
    @State private var activeSheet: XAgeDataSheet?
    @State private var metrics = XAgeMetric.defaultCards
    @State private var pendingMetricScrollID: String?
    @State private var isTodayStatusHidden = false

    var body: some View {
        VStack(spacing: 0) {
            stickyHeader
            metricsScroll
        }
        .safeAreaInset(edge: .bottom) { sortDoneInset }
        .onChange(of: appleHealthSync.samples) { _, samples in
            mergeAppleHealthSamples(samples)
        }
        .onReceive(serverSync.$metricCards) { cards in
            mergeServerMetrics(cards)
        }
        .task {
            await refreshAllData(includeAppleHealth: true)
        }
        .sheet(item: $activeSheet) { sheet in
            sheetContent(sheet)
        }
    }

    private var stickyHeader: some View {
        XAgeDataStickyHeader(
            collapseProgress: 0,
            caption: serverSync.snapshot.headerCaption,
            scores: scores,
            showsTodayStatus: !isTodayStatusHidden,
            onSelectDetail: { activeSheet = .detail($0) },
            onSelectInfo: { activeSheet = .scoreInfo($0) }
        )
        .padding(.horizontal, 24)
        .padding(.top, 16)
        .padding(.bottom, 10)
        .zIndex(2)
    }

    private var metricsScroll: some View {
        ScrollViewReader { proxy in
            ScrollView {
                XAgeDataScrollOffsetProbe()
                metricList
            }
            .coordinateSpace(name: XAgeDataScrollSpace.name)
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.data.scroll")
            .refreshable {
                await refreshAllData(includeAppleHealth: true)
            }
            .accessibilityScrollAction { edge in
                switch edge {
                case .bottom:
                    setTodayStatusHidden(true)
                case .top:
                    setTodayStatusHidden(false)
                default:
                    break
                }
            }
            .modifier(
                XAgeDataScrollOffsetTracker { offset in
                    updateTodayStatusVisibility(forOffset: offset)
                }
            )
            .onPreferenceChange(XAgeDataScrollOffsetPreferenceKey.self) { minY in
                updateTodayStatusVisibility(forOffset: max(0, -minY))
            }
            .onChange(of: metrics.count) { _, _ in
                scrollToPendingMetric(with: proxy)
            }
            .onChange(of: metricOrderIDs) { _, _ in
                scrollToPendingMetric(with: proxy)
            }
            .onChange(of: sortMode) { _, isSorting in
                scrollToFirstMetricIfNeeded(isSorting: isSorting, proxy: proxy)
            }
        }
    }

    private var metricList: some View {
        LazyVStack(spacing: 12) {
            if !sortMode {
                XAgeAppleHealthSyncCard(viewModel: appleHealthSync)
                    .accessibilityIdentifier("xage.appleHealth.sync")
            }

            ForEach(Array(metrics.enumerated()), id: \.element.id) { index, card in
                metricCard(card, index: index)
            }

            if !sortMode {
                metricLibraryEntries
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 10)
        .padding(.bottom, sortMode ? 112 : 32)
    }

    @ViewBuilder
    private var metricLibraryEntries: some View {
        XAgeMetricLibraryEntryCard(
            availableCount: availableCandidateCount,
            totalCount: allCatalogMetrics.count,
            onManage: { activeSheet = .metricManager },
            onShowAll: { activeSheet = .allMetrics }
        )
        .id("metric-library")
        .accessibilityIdentifier("xage.data.metric.library")

        XAgeAddMetricCard(availableCount: availableCandidateCount) {
            activeSheet = .metricManager
        }
        .id("add-metric")
        .accessibilityIdentifier("xage.data.metric.add")
    }

    private func metricCard(_ card: XAgeMetric, index: Int) -> some View {
        XAgeMetricCard(card: card, sortMode: sortMode) {
            activeSheet = .metricDetail(card)
        } onMoveUp: {
            moveMetric(index, -1)
        } onMoveDown: {
            moveMetric(index, 1)
        } onPin: {
            pinMetricToTop(index)
        } onDelete: {
            removeMetric(index)
        }
        .id(card.id)
        .accessibilityIdentifier("xage.data.metric.\(card.id)")
    }

    @ViewBuilder
    private var sortDoneInset: some View {
        if sortMode {
            XAgeSortDoneBar {
                withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                    sortMode = false
                }
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 10)
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    @ViewBuilder
    private func sheetContent(_ sheet: XAgeDataSheet) -> some View {
        switch sheet {
        case .detail(let kind):
            XAgeDataDetailView(
                kind: kind,
                metric: scores.score(for: kind),
                onSyncAppleHealth: {
                    Task { await syncAppleHealthFromDetail() }
                },
                onOpenGuide: {
                    activeSheet = nil
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.24) {
                        onOpenMetricGuide(kind)
                    }
                }
            )
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        case .scoreInfo(let kind):
            XAgeScoreInfoSheet(kind: kind, metric: scores.score(for: kind))
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        case .metricPicker:
            XAgeMetricCandidateSheet(metrics: availableCandidateMetrics) { metric in
                addMetric(metric)
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            .presentationContentInteraction(.scrolls)
            .interactiveDismissDisabled(true)
        case .metricManager:
            XAgeMetricManagerSheet(
                pinnedMetrics: $metrics,
                catalogSections: metricCatalogSections,
                onOpenMetric: { metric in
                    openMetricDetail(afterClosingCurrentSheet: metric)
                }
            )
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
            .presentationContentInteraction(.scrolls)
            .interactiveDismissDisabled(true)
        case .allMetrics:
            XAgeAllMetricsSheet(
                pinnedMetricIDs: Set(metrics.map(\.id)),
                catalogSections: allMetricSections,
                onTogglePinned: { metric in
                    togglePinnedMetric(metric)
                },
                onOpenMetric: { metric in
                    openMetricDetail(afterClosingCurrentSheet: metric)
                }
            )
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
            .presentationContentInteraction(.scrolls)
            .interactiveDismissDisabled(true)
        case .metricDetail(let metric):
            XAgeMetricDetailSheet(
                metric: metric,
                onManualRecord: {
                    activeSheet = .manualEntry(metric)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        case .manualEntry(let metric):
            XAgeManualMetricEntrySheet(
                metric: metric,
                onSaved: {
                    Task {
                        await refreshAllData(includeAppleHealth: false)
                        await MainActor.run {
                            activeSheet = nil
                        }
                    }
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
    }

    private func scrollToPendingMetric(with proxy: ScrollViewProxy) {
        guard let metricID = pendingMetricScrollID else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.16) {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.9)) {
                proxy.scrollTo(metricID, anchor: .top)
            }
            pendingMetricScrollID = nil
        }
    }

    private func scrollToFirstMetricIfNeeded(isSorting: Bool, proxy: ScrollViewProxy) {
        guard isSorting, let firstMetricID = metrics.first?.id else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.9)) {
                proxy.scrollTo(firstMetricID, anchor: .top)
            }
        }
    }

    private func openMetricDetail(afterClosingCurrentSheet metric: XAgeMetric) {
        activeSheet = nil
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.24) {
            activeSheet = .metricDetail(metric)
        }
    }

    private func refreshAllData(includeAppleHealth: Bool) async {
        if includeAppleHealth {
            await appleHealthSync.refreshIfPreviouslySynced()
        }
        await serverSync.refresh()
        mergeServerMetrics(serverSync.metricCards)
    }

    private func syncAppleHealthFromDetail() async {
        await appleHealthSync.requestAccessAndSync()
        await refreshAllData(includeAppleHealth: false)
    }

    private func updateTodayStatusVisibility(forOffset scrollOffset: CGFloat) {
        let offset = max(0, scrollOffset)
        let shouldHide = isTodayStatusHidden ? offset > 8 : offset > 28
        guard shouldHide != isTodayStatusHidden else { return }
        setTodayStatusHidden(shouldHide)
    }

    private func setTodayStatusHidden(_ hidden: Bool) {
        guard hidden != isTodayStatusHidden else { return }
        withAnimation(.easeInOut(duration: 0.18)) {
            isTodayStatusHidden = hidden
        }
    }

    private var availableCandidateMetrics: [XAgeMetric] {
        let currentIDs = Set(metrics.map(\.id))
        return allCatalogMetrics.filter { !currentIDs.contains($0.id) }
    }

    private var availableCandidateCount: Int {
        availableCandidateMetrics.count
    }

    private var metricOrderIDs: [String] {
        metrics.map(\.id)
    }

    private var metricCatalogSections: [XAgeMetricCatalogSection] {
        XAgeMetric.catalogSections(serverMetrics: serverSync.indicatorCatalogCards)
    }

    private var allMetricSections: [XAgeMetricCatalogSection] {
        var sections = [XAgeMetricCatalogSection(
            title: "置顶",
            icon: "pin.fill",
            accent: Color(hex: "238AD6"),
            metrics: metrics
        )]
        sections.append(contentsOf: metricCatalogSections)
        return sections.filter { !$0.metrics.isEmpty }
    }

    private var allCatalogMetrics: [XAgeMetric] {
        dedupedMetrics(metrics + metricCatalogSections.flatMap(\.metrics))
    }

    private func addMetric(_ metric: XAgeMetric) {
        guard !metrics.contains(where: { $0.id == metric.id }) else { return }
        pendingMetricScrollID = metric.id
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            metrics.append(metric)
        }
    }

    private func togglePinnedMetric(_ metric: XAgeMetric) {
        if let index = metrics.firstIndex(where: { $0.id == metric.id }) {
            withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                _ = metrics.remove(at: index)
            }
        } else {
            addMetric(metric)
        }
    }

    private func moveMetric(_ index: Int, _ direction: Int) {
        let target = index + direction
        guard metrics.indices.contains(index), metrics.indices.contains(target) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            metrics.swapAt(index, target)
        }
    }

    private func pinMetricToTop(_ index: Int) {
        guard metrics.indices.contains(index), index != metrics.startIndex else { return }
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            let metric = metrics.remove(at: index)
            pendingMetricScrollID = metric.id
            metrics.insert(metric, at: metrics.startIndex)
        }
    }

    private func removeMetric(_ index: Int) {
        guard metrics.indices.contains(index) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            _ = metrics.remove(at: index)
        }
    }

    private func mergeAppleHealthSamples(_ samples: [AppleHealthSyncSample]) {
        let synced = samples.compactMap { XAgeMetric.appleHealthMetric(from: $0) }
        guard !synced.isEmpty else { return }
        withAnimation(.spring(response: 0.26, dampingFraction: 0.88)) {
            for metric in synced {
                if let index = metrics.firstIndex(where: { $0.id == metric.id }) {
                    metrics[index] = metric
                } else {
                    metrics.append(metric)
                }
            }
        }
    }

    private func mergeServerMetrics(_ serverMetrics: [XAgeMetric]) {
        guard !serverMetrics.isEmpty else { return }
        let shouldAnimate = metrics.contains { metric in
            serverMetrics.contains(where: { $0.id == metric.id })
        }
        let apply = {
            var next = metrics
            for metric in serverMetrics {
                if let index = next.firstIndex(where: { $0.id == metric.id }) {
                    next[index] = metric
                } else {
                    next.insert(metric, at: 0)
                }
            }
            metrics = dedupedMetrics(next)
        }
        if shouldAnimate {
            withAnimation(.spring(response: 0.26, dampingFraction: 0.88), apply)
        } else {
            apply()
        }
    }

    private func dedupedMetrics(_ source: [XAgeMetric]) -> [XAgeMetric] {
        var seenIDs = Set<String>()
        var seenTitles = Set<String>()
        var result: [XAgeMetric] = []
        for metric in source {
            let titleKey = metric.title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard !seenIDs.contains(metric.id), !seenTitles.contains(titleKey) else { continue }
            seenIDs.insert(metric.id)
            seenTitles.insert(titleKey)
            result.append(metric)
        }
        return result
    }
}

@MainActor
private final class XAgeServerSyncViewModel: ObservableObject {
    @Published private(set) var snapshot = XAgeServerSyncSnapshot.placeholder
    @Published private(set) var metricCards: [XAgeMetric] = []
    @Published private(set) var indicatorCatalogCards: [XAgeMetric] = []
    @Published private(set) var isLoading = false

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func refresh() async {
        let auth = AuthManager.shared
        if auth.isUIValidationSession {
            snapshot = XAgeServerSyncSnapshot.placeholder
            metricCards = []
            indicatorCatalogCards = []
            return
        }

        guard auth.isLoggedIn else {
            snapshot = .loggedOut
            metricCards = []
            indicatorCatalogCards = []
            return
        }

        isLoading = true
        defer { isLoading = false }

        async let userReq: UserInfo? = getOptional("/api/users/me")
        async let dashboardReq: DashboardHealth? = getOptional("/api/dashboard/health")
        async let todayReq: TodayBriefing? = getOptional("/api/agent/today")
        async let summaryReq: HealthDataSummary? = getOptional("/api/health-data/summary")
        async let recordReq: DocumentListResponse? = getOptional("/api/health-data/documents?doc_type=record")
        async let examReq: DocumentListResponse? = getOptional("/api/health-data/documents?doc_type=exam")
        async let indicatorReq: IndicatorListResponse? = getOptional("/api/health-data/indicators")
        async let watchedReq: WatchedListResponse? = getOptional("/api/health-data/indicators/watched")
        async let conversationsReq: [ChatConversation]? = getOptional("/api/chat/conversations?limit=20&offset=0")
        async let plansReq: HealthPlanListResponse? = getOptional("/api/health-plans")
        async let elderlyReq: ElderlyCheckinList? = getOptional("/api/elderly?limit=20&days=30")

        let user = await userReq
        let dashboard = await dashboardReq
        let today = await todayReq
        let summary = await summaryReq
        let records = await recordReq
        let exams = await examReq
        let indicators = await indicatorReq
        let watched = await watchedReq
        let conversations = await conversationsReq
        let plans = await plansReq
        let elderly = await elderlyReq

        let watchedNames = watched?.items.map(\.indicator_name) ?? []
        let indicatorItems = indicators?.indicators ?? []
        let trendNames = Self.trendRequestNames(watchedNames: watchedNames)
        let trendResponse = await fetchTrends(for: trendNames)
        let trends = trendResponse?.indicators ?? []

        guard !Task.isCancelled else { return }

        snapshot = XAgeServerSyncSnapshot(
            isLoaded: true,
            isLoggedOut: false,
            summaryUpdatedAt: summary?.updated_at,
            hasSummary: !(summary?.summary_text?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ?? true),
            recordCount: records?.items?.count ?? records?.total ?? 0,
            examCount: exams?.items?.count ?? exams?.total ?? 0,
            indicatorCount: indicators?.indicators.count ?? 0,
            watchedIndicatorCount: watchedNames.count,
            trendPointCount: trends.reduce(0) { $0 + $1.points.count },
            conversationCount: conversations?.count ?? 0,
            planCount: plans?.items.count ?? 0,
            feedbackCount: elderly?.items.count ?? 0,
            profileCompletion: Self.profileCompletion(user?.profile),
            latestDocumentDate: Self.latestDocumentDate(records: records?.items ?? [], exams: exams?.items ?? []),
            dashboardScore: dashboard?.metabolic_state?.score,
            todayGoalCount: today?.today_goals?.count ?? today?.daily_plan?.payload.today_goals?.count ?? 0,
            primaryWatchedName: watchedNames.first,
            userAge: user?.profile?.age,
            profileHeightCm: user?.profile?.height_cm,
            profileWeightKg: user?.profile?.weight_kg,
            algorithmTrends: Self.algorithmTrends(
                from: trends,
                records: records?.items ?? [],
                exams: exams?.items ?? []
            )
        )
        metricCards = Self.metricCards(from: trends, dashboard: dashboard)
        indicatorCatalogCards = Self.indicatorCatalogCards(from: indicatorItems)
    }

    private func getOptional<T: Decodable>(_ path: String) async -> T? {
        try? await api.get(path)
    }

    private func fetchTrends(for names: [String]) async -> IndicatorTrendResponse? {
        guard !names.isEmpty else { return nil }
        var merged: [IndicatorTrend] = []
        var start = 0
        while start < names.count {
            let end = min(start + 10, names.count)
            let batch = Array(names[start..<end])
            if let response = await fetchTrendBatch(for: batch) {
                merged.append(contentsOf: response.indicators)
            }
            start = end
        }
        return merged.isEmpty ? nil : IndicatorTrendResponse(indicators: Self.dedupedTrends(merged))
    }

    private func fetchTrendBatch(for names: [String]) async -> IndicatorTrendResponse? {
        let joined = names.joined(separator: ",")
        var allowed = CharacterSet.urlQueryAllowed
        allowed.remove(charactersIn: "+&=?")
        let encoded = joined.addingPercentEncoding(withAllowedCharacters: allowed) ?? joined
        return try? await api.get("/api/health-data/indicators/trend?names=\(encoded)")
    }

    private static func trendRequestNames(watchedNames: [String]) -> [String] {
        let defaultNames = [
            "心率变异性",
            "睡眠",
            "步数",
            "收缩压",
            "舒张压",
            "静息心率",
            "血氧",
            "活动能量",
            "运动分钟",
            "步行+跑步距离",
            "呼吸频率",
            "爬楼层数",
            "体重",
            "体脂率"
        ]
        var seen = Set<String>()
        return (defaultNames + watchedNames).compactMap { name in
            let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return nil }
            let key = trimmed.lowercased()
            guard seen.insert(key).inserted else { return nil }
            return trimmed
        }
    }

    private static func dedupedTrends(_ source: [IndicatorTrend]) -> [IndicatorTrend] {
        var seen = Set<String>()
        return source.filter { trend in
            seen.insert(trend.name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()).inserted
        }
    }

    private static func metricCards(from trends: [IndicatorTrend], dashboard: DashboardHealth?) -> [XAgeMetric] {
        let accents = [
            Color(hex: "238AD6"),
            Color(hex: "20CDB1"),
            Color(hex: "EF9A3D"),
            Color(hex: "7B4DFF")
        ]
        let trendCards = trends
            .filter { !isLegacyCombinedBloodPressure($0.name) }
            .prefix(8)
            .enumerated()
            .compactMap { item -> XAgeMetric? in
                let (index, trend) = item
                guard let latest = latestPoint(from: trend.points) else { return nil }
                let source = latest.source ?? "document"
                let measuredRaw = latest.measured_at ?? latest.date
                let dateLabel = XAgeServerSyncFormat.cardTime(measuredRaw, source: source)
                let stale = staleness(for: trend.name, source: source, measuredAt: measuredRaw)
                let sourceDescription = sourceLabel(source)
                let subtitle: String
                if stale.isStale {
                    subtitle = "\(sourceDescription) \(dateLabel)；已超过 \(stale.limitDays) 天未更新，仅作历史参考。"
                } else if latest.abnormal {
                    subtitle = "\(sourceDescription) \(dateLabel)；最近一次结果异常，已纳入当前趋势。"
                } else {
                    subtitle = "\(sourceDescription) \(dateLabel)；已同步到当前版本。"
                }
                return XAgeMetric(
                    id: canonicalMetricID(for: trend.name),
                    title: trend.name,
                    value: Self.displayValue(latest.value),
                    unit: trend.unit ?? "",
                    time: stale.isStale ? "需更新" : dateLabel,
                    subtitle: subtitle,
                    accent: accents[index % accents.count],
                    source: source,
                    measuredAt: measuredRaw,
                    isStale: stale.isStale
                )
            }
        return dedupedMetrics([glucoseMetric(from: dashboard)].compactMap { $0 } + trendCards)
    }

    @MainActor
    private static func glucoseMetric(from dashboard: DashboardHealth?) -> XAgeMetric? {
        guard let summary = dashboard?.glucose?.last_24h,
              let avg = summary.avg else { return nil }
        let value = Utils.formatGlucose(avg, withUnit: false)
        let unit = Utils.glucoseUnitLabel
        let tir = summary.tir_70_180_pct.map { "TIR \(Int($0.rounded()))%" } ?? "TIR 待同步"
        let variability = summary.variability?.isEmpty == false ? summary.variability! : "波动待评估"
        let latest = dashboard?.cgm_quality?.latest_ts
        let time = XAgeServerSyncFormat.cardTime(latest, source: "cgm")
        let stale = staleness(for: "血糖波动", source: "cgm", measuredAt: latest)
        return XAgeMetric(
            id: "glucose",
            title: "血糖波动",
            value: value,
            unit: unit,
            time: stale.isStale ? "需更新" : time,
            subtitle: "CGM 最近 24 小时平均值；\(tir)，\(variability)。",
            accent: Color(hex: "11A7C8"),
            source: "cgm",
            measuredAt: latest,
            isStale: stale.isStale
        )
    }

    private static func indicatorCatalogCards(from indicators: [IndicatorInfo]) -> [XAgeMetric] {
        indicators
            .filter { !isLegacyCombinedBloodPressure($0.name) }
            .prefix(80)
            .enumerated()
            .map { index, indicator in
                let accents = [
                    Color(hex: "238AD6"),
                    Color(hex: "20CDB1"),
                    Color(hex: "EF9A3D"),
                    Color(hex: "7B4DFF"),
                    Color(hex: "F05B72")
                ]
                let countText = indicator.count > 0 ? "\(indicator.count)点" : "待上传"
                return XAgeMetric(
                    id: canonicalMetricID(for: indicator.name),
                    title: indicator.name,
                    value: countText,
                    unit: "",
                    time: indicator.category ?? "服务器",
                    subtitle: "来自服务器指标库；已有 \(indicator.count) 个历史点，可置顶后查看趋势或继续补录。",
                    accent: accents[index % accents.count],
                    source: indicator.count > 0 ? "server_indicator_catalog" : "server_catalog",
                    isPlaceholder: indicator.count == 0
                )
            }
    }

    private static func dedupedMetrics(_ source: [XAgeMetric]) -> [XAgeMetric] {
        var seenIDs = Set<String>()
        var seenTitles = Set<String>()
        var result: [XAgeMetric] = []
        for metric in source {
            let titleKey = metric.title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard !seenIDs.contains(metric.id), !seenTitles.contains(titleKey) else { continue }
            seenIDs.insert(metric.id)
            seenTitles.insert(titleKey)
            result.append(metric)
        }
        return result
    }

    private static func latestPoint(from points: [TrendPoint]) -> TrendPoint? {
        points.sorted {
            let lhs = XAgeServerSyncFormat.date(from: $0.measured_at ?? $0.date) ?? .distantPast
            let rhs = XAgeServerSyncFormat.date(from: $1.measured_at ?? $1.date) ?? .distantPast
            return lhs < rhs
        }.last
    }

    private static func staleness(for name: String, source: String, measuredAt raw: String?) -> (isStale: Bool, limitDays: Int) {
        let limit = freshnessLimitDays(for: name, source: source)
        guard let date = XAgeServerSyncFormat.date(from: raw) else { return (false, limit) }
        let days = Calendar.current.dateComponents(
            [.day],
            from: Calendar.current.startOfDay(for: date),
            to: Calendar.current.startOfDay(for: Date())
        ).day ?? 0
        return (max(0, days) > limit, limit)
    }

    private static func freshnessLimitDays(for name: String, source: String) -> Int {
        let normalized = name.lowercased()
        if ["体重", "体脂", "血压", "收缩压", "舒张压"].contains(where: { normalized.contains($0) }) {
            return 14
        }
        if source == "apple_health" || ["步数", "睡眠", "hrv", "心率", "呼吸", "血氧", "活动", "运动", "爬楼", "距离", "能量"].contains(where: { normalized.contains($0.lowercased()) }) {
            return 2
        }
        return 180
    }

    private static func sourceLabel(_ source: String?) -> String {
        switch (source ?? "").lowercased() {
        case "apple_health": return "Apple 健康"
        case "manual": return "手动记录"
        case "device": return "设备同步"
        case "cgm": return "CGM"
        default: return "报告趋势"
        }
    }

    private static func isLegacyCombinedBloodPressure(_ name: String) -> Bool {
        name.trimmingCharacters(in: .whitespacesAndNewlines) == "血压"
    }

    private static func canonicalMetricID(for name: String) -> String {
        let normalized = name.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if normalized.contains("hrv") || normalized.contains("心率变异") { return "hrv" }
        if normalized.contains("睡眠") { return "sleep" }
        if normalized.contains("血糖") || normalized.contains("葡萄糖") { return "glucose" }
        if normalized.contains("体温") { return "temp" }
        if normalized.contains("步数") { return "steps" }
        if normalized.contains("步行+跑步距离") || normalized.contains("步行跑步距离") { return "distance" }
        if normalized.contains("活动能量") { return "activeEnergy" }
        if normalized.contains("运动分钟") { return "exerciseMinutes" }
        if normalized.contains("爬楼") { return "flights" }
        if normalized.contains("静息心率") { return "restingHeartRate" }
        if normalized.contains("呼吸频率") { return "respiratoryRate" }
        if normalized.contains("血氧") { return "bloodOxygen" }
        if normalized.contains("收缩压") { return "systolicBloodPressure" }
        if normalized.contains("舒张压") { return "diastolicBloodPressure" }
        if normalized.contains("体重") { return "bodyWeight" }
        if normalized.contains("体脂") { return "bodyFat" }
        if normalized.contains("正念") { return "mindfulMinutes" }
        if normalized.contains("日照") { return "daylight" }
        return "server-\(name)"
    }

    private static func displayValue(_ value: Double) -> String {
        if value.rounded() == value {
            return String(Int(value))
        }
        if abs(value) >= 100 {
            return String(format: "%.1f", value)
        }
        return String(format: "%.2f", value).replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }

    private static func algorithmTrends(
        from trends: [IndicatorTrend],
        records: [HealthDocument],
        exams: [HealthDocument]
    ) -> [XAgeAlgorithmTrend] {
        var items = trends.compactMap { trend -> XAgeAlgorithmTrend? in
            guard let latest = latestPoint(from: trend.points) else { return nil }
            return XAgeAlgorithmTrend(
                name: trend.name,
                value: latest.value,
                unit: trend.unit,
                refLow: trend.ref_low,
                refHigh: trend.ref_high,
                abnormal: latest.abnormal,
                measuredAt: latest.measured_at ?? latest.date,
                source: latest.source ?? "server_trend",
                confidence: trend.points.count >= 2 ? 0.82 : 0.72
            )
        }

        for document in records + exams {
            let documentDate = document.doc_date
            items.append(contentsOf: labFeatures(from: document.abnormal_flags ?? [], date: documentDate))
            items.append(contentsOf: labFeatures(from: document.csv_data, date: documentDate))
        }

        var unique: [String: XAgeAlgorithmTrend] = [:]
        for item in items {
            let key = XAgeAlgorithmTrend.normalizedKey(item.name)
            if let existing = unique[key], existing.source == "server_trend" {
                continue
            }
            unique[key] = item
        }
        return Array(unique.values)
    }

    private static func labFeatures(from flags: [AbnormalFlag], date: String?) -> [XAgeAlgorithmTrend] {
        flags.compactMap { flag in
            let name = flag.name ?? flag.field ?? ""
            guard !name.isEmpty, let value = parseNumericValue(flag.value) else { return nil }
            return XAgeAlgorithmTrend(
                name: name,
                value: value,
                unit: flag.unit,
                refLow: nil,
                refHigh: nil,
                abnormal: true,
                measuredAt: date,
                source: "document_flag",
                confidence: 0.62
            )
        }
    }

    private static func labFeatures(from csv: CSVData?, date: String?) -> [XAgeAlgorithmTrend] {
        guard let columns = csv?.columns, let rows = csv?.rows, !columns.isEmpty else { return [] }
        let normalized = columns.map { $0.lowercased() }
        let nameIndex = firstIndex(in: normalized, matching: ["项目", "指标", "名称", "name", "indicator", "item"])
        let valueIndex = firstIndex(in: normalized, matching: ["结果", "数值", "value", "result"])
        let unitIndex = firstIndex(in: normalized, matching: ["单位", "unit"])
        guard let nameIndex, let valueIndex else { return [] }

        return rows.compactMap { row in
            guard row.indices.contains(nameIndex), row.indices.contains(valueIndex) else { return nil }
            let name = row[nameIndex].trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty, let value = parseNumericValue(row[valueIndex]) else { return nil }
            let unit = unitIndex.flatMap { row.indices.contains($0) ? row[$0] : nil }
            return XAgeAlgorithmTrend(
                name: name,
                value: value,
                unit: unit,
                refLow: nil,
                refHigh: nil,
                abnormal: false,
                measuredAt: date,
                source: "document_csv",
                confidence: 0.58
            )
        }
    }

    private static func firstIndex(in columns: [String], matching needles: [String]) -> Int? {
        columns.firstIndex { column in
            needles.contains { column.contains($0) }
        }
    }

    private static func parseNumericValue(_ raw: String?) -> Double? {
        guard let raw else { return nil }
        let normalized = raw
            .replacingOccurrences(of: ",", with: "")
            .replacingOccurrences(of: "＞", with: ">")
            .replacingOccurrences(of: "＜", with: "<")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let pattern = #"[-+]?\d+(?:\.\d+)?"#
        guard let range = normalized.range(of: pattern, options: .regularExpression) else { return nil }
        return Double(normalized[range])
    }

    private static func profileCompletion(_ profile: UserProfile?) -> Int {
        guard let profile else { return 0 }
        let fields: [Bool] = [
            !(profile.sex?.isEmpty ?? true),
            profile.age != nil,
            profile.height_cm != nil,
            profile.weight_kg != nil,
            !(profile.display_name?.isEmpty ?? true)
        ]
        let filled = fields.filter { $0 }.count
        return Int((Double(filled) / Double(fields.count) * 100).rounded())
    }

    private static func latestDocumentDate(records: [HealthDocument], exams: [HealthDocument]) -> String? {
        (records + exams)
            .compactMap(\.doc_date)
            .sorted()
            .last
    }

}

private enum XAgeServerSyncFormat {
    static func date(from raw: String?) -> Date? {
        guard let raw, !raw.isEmpty else { return nil }
        return Utils.parseISO(raw) ?? dateOnlyFormatter.date(from: raw)
    }

    static func shortDate(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "暂无" }
        if let date = date(from: raw) {
            return monthDayFormatter.string(from: date)
        }
        if raw.count >= 10 {
            let end = raw.index(raw.startIndex, offsetBy: 10)
            return String(raw[..<end])
        }
        return raw
    }

    static func cardTime(_ raw: String?, source: String?) -> String {
        guard let raw, !raw.isEmpty else { return "暂无" }
        guard let date = date(from: raw) else { return shortDate(raw) }
        let sourceKey = (source ?? "").lowercased()
        if sourceKey == "apple_health" || sourceKey == "device" || sourceKey == "cgm" {
            if Calendar.current.isDateInToday(date) {
                return timeFormatter.string(from: date)
            }
            return monthDayFormatter.string(from: date)
        }
        return monthDayFormatter.string(from: date)
    }

    private static let dateOnlyFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private static let monthDayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日"
        return formatter
    }()

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "H:mm"
        return formatter
    }()
}

private struct XAgeServerSyncSnapshot: Equatable {
    let isLoaded: Bool
    let isLoggedOut: Bool
    let summaryUpdatedAt: String?
    let hasSummary: Bool
    let recordCount: Int
    let examCount: Int
    let indicatorCount: Int
    let watchedIndicatorCount: Int
    let trendPointCount: Int
    let conversationCount: Int
    let planCount: Int
    let feedbackCount: Int
    let profileCompletion: Int
    let latestDocumentDate: String?
    let dashboardScore: Int?
    let todayGoalCount: Int
    let primaryWatchedName: String?
    let userAge: Int?
    let profileHeightCm: Double?
    let profileWeightKg: Double?
    let algorithmTrends: [XAgeAlgorithmTrend]

    static let placeholder = XAgeServerSyncSnapshot(
        isLoaded: false,
        isLoggedOut: false,
        summaryUpdatedAt: nil,
        hasSummary: false,
        recordCount: 0,
        examCount: 0,
        indicatorCount: 0,
        watchedIndicatorCount: 0,
        trendPointCount: 0,
        conversationCount: 0,
        planCount: 0,
        feedbackCount: 0,
        profileCompletion: 0,
        latestDocumentDate: nil,
        dashboardScore: nil,
        todayGoalCount: 0,
        primaryWatchedName: nil,
        userAge: nil,
        profileHeightCm: nil,
        profileWeightKg: nil,
        algorithmTrends: []
    )

    static let loggedOut = XAgeServerSyncSnapshot(
        isLoaded: true,
        isLoggedOut: true,
        summaryUpdatedAt: nil,
        hasSummary: false,
        recordCount: 0,
        examCount: 0,
        indicatorCount: 0,
        watchedIndicatorCount: 0,
        trendPointCount: 0,
        conversationCount: 0,
        planCount: 0,
        feedbackCount: 0,
        profileCompletion: 0,
        latestDocumentDate: nil,
        dashboardScore: nil,
        todayGoalCount: 0,
        primaryWatchedName: nil,
        userAge: nil,
        profileHeightCm: nil,
        profileWeightKg: nil,
        algorithmTrends: []
    )

    var headerCaption: String {
        if !isLoaded { return "正在同步历史数据" }
        if isLoggedOut { return "未登录 · 待登录同步" }
        if recordCount + examCount + indicatorCount == 0 { return "暂无历史同步数据 · 待上传" }
        let date = XAgeServerSyncFormat.shortDate(summaryUpdatedAt ?? latestDocumentDate)
        return "\(date) · 已同步"
    }

    var latestDocumentLabel: String {
        XAgeServerSyncFormat.shortDate(latestDocumentDate)
    }

    var primaryWatchedLabel: String {
        primaryWatchedName ?? "关注指标"
    }

    func stats(for category: XAgeDataPanelCategory) -> [XAgePanelStat] {
        switch category {
        case .reports:
            return [
                XAgePanelStat(title: "病历", value: "\(recordCount)", unit: "份"),
                XAgePanelStat(title: "体检", value: "\(examCount)", unit: "份"),
                XAgePanelStat(title: "指标", value: "\(indicatorCount)", unit: "项")
            ]
        case .daily:
            return [
                XAgePanelStat(title: "关注", value: "\(watchedIndicatorCount)", unit: "项"),
                XAgePanelStat(title: "趋势", value: "\(trendPointCount)", unit: "点"),
                XAgePanelStat(title: "目标", value: "\(todayGoalCount)", unit: "条")
            ]
        case .medical:
            return [
                XAgePanelStat(title: "计划", value: "\(planCount)", unit: "个"),
                XAgePanelStat(title: "问答", value: "\(conversationCount)", unit: "次"),
                XAgePanelStat(title: "反馈", value: "\(feedbackCount)", unit: "条")
            ]
        case .profile:
            return [
                XAgePanelStat(title: "基础", value: "\(profileCompletion)", unit: "%"),
                XAgePanelStat(title: "摘要", value: hasSummary ? "有" : "待", unit: ""),
                XAgePanelStat(title: "评分", value: dashboardScore.map(String.init) ?? "--", unit: "")
            ]
        }
    }
}

struct XAgeAlgorithmTrend: Equatable {
    let name: String
    let value: Double
    let unit: String?
    let refLow: Double?
    let refHigh: Double?
    let abnormal: Bool
    let measuredAt: String?
    let source: String
    let confidence: Double

    var displayValue: String {
        if value.rounded() == value {
            return "\(Int(value))\(unitLabel)"
        }
        return "\(String(format: "%.2f", value).replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression))\(unitLabel)"
    }

    private var unitLabel: String {
        guard let unit, !unit.isEmpty else { return "" }
        return " \(unit)"
    }

    static func normalizedKey(_ raw: String) -> String {
        raw.lowercased()
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "-", with: "")
            .replacingOccurrences(of: "_", with: "")
            .replacingOccurrences(of: "/", with: "")
            .replacingOccurrences(of: "（", with: "")
            .replacingOccurrences(of: "）", with: "")
            .replacingOccurrences(of: "(", with: "")
            .replacingOccurrences(of: ")", with: "")
    }
}

struct XAgeAlgorithmContext: Equatable {
    var userAge: Int?
    var profileHeightCm: Double?
    var profileWeightKg: Double?
    var dashboardScore: Int?
    var trendPointCount: Int
    var documentCount: Int
    var watchedIndicatorCount: Int
    var samples: [AppleHealthSyncSample]
    var serverTrends: [XAgeAlgorithmTrend]

    init(
        userAge: Int? = nil,
        profileHeightCm: Double? = nil,
        profileWeightKg: Double? = nil,
        dashboardScore: Int? = nil,
        trendPointCount: Int = 0,
        documentCount: Int = 0,
        watchedIndicatorCount: Int = 0,
        samples: [AppleHealthSyncSample] = [],
        serverTrends: [XAgeAlgorithmTrend] = []
    ) {
        self.userAge = userAge
        self.profileHeightCm = profileHeightCm
        self.profileWeightKg = profileWeightKg
        self.dashboardScore = dashboardScore
        self.trendPointCount = trendPointCount
        self.documentCount = documentCount
        self.watchedIndicatorCount = watchedIndicatorCount
        self.samples = samples
        self.serverTrends = serverTrends
    }
}

fileprivate extension XAgeAlgorithmContext {
    init(snapshot: XAgeServerSyncSnapshot, samples: [AppleHealthSyncSample]) {
        self.init(
            userAge: snapshot.userAge,
            profileHeightCm: snapshot.profileHeightCm,
            profileWeightKg: snapshot.profileWeightKg,
            dashboardScore: snapshot.dashboardScore,
            trendPointCount: snapshot.trendPointCount,
            documentCount: snapshot.recordCount + snapshot.examCount,
            watchedIndicatorCount: snapshot.watchedIndicatorCount,
            samples: samples,
            serverTrends: snapshot.algorithmTrends
        )
    }
}

struct XAgeScoreField: Identifiable, Equatable {
    let title: String
    let value: String

    var id: String { "\(title)-\(value)" }
}

struct XAgeScoreDriver: Identifiable, Equatable {
    let title: String
    let value: String
    let note: String

    var id: String { "\(title)-\(value)-\(note)" }
}

struct XAgeMetricScore: Equatable {
    let value: Int
    let confidence: Int
    let isReady: Bool
    let badgeLabel: String
    let stateLabel: String
    let summary: String
    let simpleExplanation: String
    let explanation: String
    let nextAction: String
    let fields: [XAgeScoreField]
    let drivers: [XAgeScoreDriver]
    let isProxy: Bool

    var displayValue: String {
        isReady ? "\(value)" : "--"
    }
}

struct XAgeAgeScore: Equatable {
    let chronologicalAge: Double
    let ageValue: Double
    let isReady: Bool
    let age: String
    let delta: String
    let pace: Double
    let confidence: Int
    let status: String
    let summary: String
    let explanation: String
    let nextAction: String
    let drivers: [XAgeScoreDriver]
    let ageRange: String
}

struct XAgeCompositeScores: Equatable {
    let pressure: XAgeMetricScore
    let recovery: XAgeMetricScore
    let inflammation: XAgeMetricScore
    let xAge: XAgeAgeScore

    var todaySummary: String {
        if !pressure.isReady || !recovery.isReady || !inflammation.isReady {
            return "数据还不够，先同步 Apple 健康或上传报告；达到评估门槛后再显示压力、恢复和炎症分。"
        }
        return "\(recovery.stateLabel)，\(pressure.stateLabel)；\(inflammation.stateLabel)。\(mostUsefulAction)"
    }

    static func compute(context: XAgeAlgorithmContext) -> XAgeCompositeScores {
        let pressure = makePressure(context)
        let recovery = makeRecovery(context)
        let inflammation = makeInflammation(context)
        let xAge = makeXAge(context, pressure: pressure, recovery: recovery, inflammation: inflammation)
        return XAgeCompositeScores(
            pressure: pressure,
            recovery: recovery,
            inflammation: inflammation,
            xAge: xAge
        )
    }

    private var mostUsefulAction: String {
        if pressure.value >= 70 {
            return "先做 2 分钟延长呼气，再复看身体有没有回应。"
        }
        if recovery.value < 45 {
            return "今天把强度降一档，优先补水和午间短恢复。"
        }
        if inflammation.value >= 60 {
            return "记录体温、症状和睡眠；连续偏高时上传报告并复查。"
        }
        return "今天优先保持睡眠、补水和低强度活动的节律。"
    }
}

private extension XAgeCompositeScores {
    struct Evidence {
        let title: String
        let value: Double
        let displayValue: String
        let confidence: Double
        let abnormal: Bool
        let rawName: String?
        let unit: String?
        let source: String?
    }

    struct WeightedFeature {
        let title: String
        let score: Double
        let confidence: Double
        let weight: Double
        let displayValue: String
        let note: String

        var field: XAgeScoreField {
            XAgeScoreField(title: title, value: displayValue)
        }

        var driver: XAgeScoreDriver {
            XAgeScoreDriver(title: title, value: displayValue, note: note)
        }

        var driverStrength: Double {
            abs(score - 50) * confidence * weight
        }
    }

    struct WeightedResult {
        let score: Double
        let confidence: Int
        let drivers: [XAgeScoreDriver]
        let fields: [XAgeScoreField]
    }

    func score(for kind: XAgeDataKind) -> XAgeMetricScore {
        switch kind {
        case .pressure:
            return pressure
        case .recovery:
            return recovery
        case .inflammation:
            return inflammation
        }
    }

    static func makePressure(_ context: XAgeAlgorithmContext) -> XAgeMetricScore {
        var features: [WeightedFeature] = []

        if let hrv = evidence(context, metricID: "hrv", aliases: ["心率变异性", "hrv", "sdnn", "rmssd"], title: "HRV/PRV") {
            features.append(WeightedFeature(
                title: "HRV/PRV",
                score: hrvSuppressionBad(hrv.value),
                confidence: hrv.confidence,
                weight: 18,
                displayValue: hrv.displayValue,
                note: "HRV/PRV 越低，算法把交感负荷子分打得越高。"
            ))
        }

        if let rhr = evidence(context, metricID: "restingHeartRate", aliases: ["静息心率", "rhr", "restingheartrate"], title: "静息心率") {
            features.append(WeightedFeature(
                title: "静息心率",
                score: rhrBad(rhr.value),
                confidence: rhr.confidence,
                weight: 18,
                displayValue: rhr.displayValue,
                note: "静息心率高于基线时，压力子分上调。"
            ))
        }

        if let respiration = evidence(context, metricID: "respiratoryRate", aliases: ["呼吸频率", "呼吸率", "respiratory", "respiration"], title: "呼吸") {
            features.append(WeightedFeature(
                title: "呼吸",
                score: respirationBad(respiration.value),
                confidence: respiration.confidence,
                weight: 10,
                displayValue: respiration.displayValue,
                note: "呼吸频率偏离个人常态时，压力子分按偏离幅度上调。"
            ))
        }

        if let temperature = evidence(context, metricID: nil, aliases: ["体温", "temperature", "temp"], title: "体温") {
            features.append(WeightedFeature(
                title: "体温",
                score: temperatureBad(temperature.value),
                confidence: temperature.confidence * 0.86,
                weight: 6,
                displayValue: temperature.displayValue,
                note: "体温偏离按低权重进入压力分。"
            ))
        }

        if let load = activityLoad(context) {
            features.append(WeightedFeature(
                title: "活动负荷",
                score: load.score,
                confidence: load.confidence,
                weight: 8,
                displayValue: load.displayValue,
                note: "活动负荷越高，短期压力子分越高。"
            ))
        }

        if let sleep = evidence(context, metricID: "sleep", aliases: ["睡眠", "sleep"], title: "睡眠") {
            features.append(WeightedFeature(
                title: "睡眠债",
                score: sleepDebtBad(sleep.value),
                confidence: sleep.confidence,
                weight: 8,
                displayValue: sleep.displayValue,
                note: "睡眠低于 7 小时时，睡眠债子分上调压力分。"
            ))
        }

        let result = weightedResult(features, context: context, requiredSignals: 6, requiredDomains: 3, cap: nil, fallback: 50)
        let value = Int(result.score.rounded())
        let hasAutonomic = features.contains { $0.title == "HRV/PRV" || $0.title == "静息心率" }
        let isReady = result.confidence >= 35 && features.count >= 3 && hasAutonomic
        return XAgeMetricScore(
            value: value,
            confidence: result.confidence,
            isReady: isReady,
            badgeLabel: isReady ? pressureBadge(value) : "待评估",
            stateLabel: isReady ? pressureState(value) : "压力待评估",
            summary: isReady ? pressureSummary(value) : "压力评估需要 HRV/静息心率，再配合睡眠、活动、呼吸或体温中的至少两类近期数据。",
            simpleExplanation: "压力分看的是身体是否处在“紧绷和占用恢复资源”的状态。HRV 降低、静息心率升高、睡眠不足或负荷过高时，分数会上升；数据不足时先不显示分数。",
            explanation: "压力分先把 HRV/PRV 抑制、静息心率、呼吸频率、睡眠债、活动负荷和体温偏移换算为 0-100 子分，再按权重加权平均。HRV 低、静息心率高、睡眠不足和高负荷会推高分数，因为这些输入代表交感负荷和恢复资源占用增加。",
            nextAction: isReady
                ? (value >= 70 ? "先降低刺激并做 2 分钟延长呼气，再复测心率和 HRV；这些输入会直接改变下一次压力分。" : "保持当前睡眠、补水和短时走动节律；这些输入会把 HRV、心率和睡眠债维持在低负荷区间。")
                : "先同步 Apple 健康中的 HRV、静息心率、睡眠和活动；如果没有可穿戴数据，可以在指标详情里手动记录。",
            fields: scoreFields(result.fields, confidence: result.confidence, isReady: isReady, missing: "HRV/静息心率 + 睡眠/活动/呼吸"),
            drivers: scoreDrivers(result.drivers, isReady: isReady, title: "补齐压力输入", note: "达到 3 类近期信号后才显示压力分，避免把单次 HRV 或心率误读成长期压力。"),
            isProxy: false
        )
    }

    static func makeRecovery(_ context: XAgeAlgorithmContext) -> XAgeMetricScore {
        var features: [WeightedFeature] = []
        let hrv = evidence(context, metricID: "hrv", aliases: ["心率变异性", "hrv", "sdnn", "rmssd"], title: "HRV/PRV")
        let sleep = evidence(context, metricID: "sleep", aliases: ["睡眠", "sleep"], title: "睡眠")

        if let hrv {
            features.append(WeightedFeature(
                title: "HRV/PRV",
                score: hrvGood(hrv.value),
                confidence: hrv.confidence,
                weight: 25,
                displayValue: hrv.displayValue,
                note: "HRV/PRV 越高且越接近个人稳定区间，恢复子分越高。"
            ))
        }

        if let rhr = evidence(context, metricID: "restingHeartRate", aliases: ["静息心率", "rhr", "restingheartrate"], title: "静息心率") {
            features.append(WeightedFeature(
                title: "静息心率",
                score: rhrGood(rhr.value),
                confidence: rhr.confidence,
                weight: 15,
                displayValue: rhr.displayValue,
                note: "静息心率越接近基线，恢复子分越高。"
            ))
        }

        if let sleep {
            features.append(WeightedFeature(
                title: "睡眠",
                score: sleepGood(sleep.value),
                confidence: sleep.confidence,
                weight: 20,
                displayValue: sleep.displayValue,
                note: "睡眠时长和连续性直接决定睡眠恢复子分。"
            ))
        }

        if let stability = stabilityGood(context) {
            features.append(WeightedFeature(
                title: "生理稳定性",
                score: stability.score,
                confidence: stability.confidence,
                weight: 12,
                displayValue: stability.displayValue,
                note: "呼吸、血氧和体温越接近稳定区间，恢复分越高。"
            ))
        }

        if let load = activityLoad(context) {
            features.append(WeightedFeature(
                title: "前日/今日负荷",
                score: 100 - load.score,
                confidence: load.confidence,
                weight: 10,
                displayValue: load.displayValue,
                note: "活动负荷越高，恢复分按负荷权重下调。"
            ))
        }

        var caps: [Double] = []
        if hrv == nil { caps.append(55) }
        if sleep == nil { caps.append(70) }
        let result = weightedResult(features, context: context, requiredSignals: 6, requiredDomains: 3, cap: caps.min(), fallback: 55)
        let value = Int(result.score.rounded())
        let isReady = result.confidence >= 35 && features.count >= 3 && hrv != nil && sleep != nil
        return XAgeMetricScore(
            value: value,
            confidence: result.confidence,
            isReady: isReady,
            badgeLabel: isReady ? recoveryBadge(value) : "待评估",
            stateLabel: isReady ? recoveryState(value) : "恢复待评估",
            summary: isReady ? recoverySummary(value) : "恢复评估需要 HRV 和最近一晚睡眠，再配合静息心率、呼吸/血氧/体温或活动负荷。",
            simpleExplanation: "恢复分看的是身体有没有回到稳定状态。HRV 越稳定、睡眠越充分、静息心率和呼吸越平稳，恢复越好；缺少 HRV 或睡眠时不显示分数。",
            explanation: "恢复分先把 HRV/PRV、静息心率、昨夜睡眠、呼吸/血氧/体温稳定性和前日/今日负荷换算为 0-100 子分，再按权重加权。HRV 高、静息心率接近基线、睡眠充足和生理稳定会提高分数，因为这些输入代表自主神经和能量系统回到稳定区间。",
            nextAction: isReady
                ? (value >= 67 ? "今天可以安排挑战任务；算法依据是 HRV、睡眠和稳定性子分都在较高区间。" : "今天把任务强度降一档，优先补水、低强度活动和提前睡眠；这些动作对应恢复分的主要输入。")
                : "先同步 Apple 健康中的 HRV、睡眠、静息心率和呼吸/血氧；连续几天后恢复分会更稳定。",
            fields: scoreFields(result.fields, confidence: result.confidence, isReady: isReady, missing: "HRV + 睡眠 + 至少 1 类稳定性信号"),
            drivers: scoreDrivers(result.drivers, isReady: isReady, title: "补齐恢复输入", note: "恢复分必须同时看到 HRV 和睡眠，否则容易把单项数据误判为整体恢复。"),
            isProxy: false
        )
    }

    static func makeInflammation(_ context: XAgeAlgorithmContext) -> XAgeMetricScore {
        let hscrp = evidence(context, metricID: nil, aliases: ["hscrp", "crp", "超敏c反应蛋白", "c反应蛋白"], title: "hsCRP")
        let wbc = evidence(context, metricID: nil, aliases: ["白细胞", "wbc"], title: "WBC")
            .flatMap { credibleBloodWhiteCell($0) ? $0 : nil }
        let nlr = evidence(context, metricID: nil, aliases: ["nlr", "中性粒细胞淋巴细胞比值"], title: "NLR")
        let cytokine = evidence(context, metricID: nil, aliases: ["il6", "白介素6", "tnf", "glyca"], title: "炎症因子")
        let hasLab = hscrp != nil || wbc != nil || nlr != nil || cytokine != nil

        var features: [WeightedFeature] = []
        if let hscrp {
            features.append(WeightedFeature(
                title: "hsCRP",
                score: hscrpBad(hscrp.value),
                confidence: hscrp.confidence,
                weight: 30,
                displayValue: hscrp.displayValue,
                note: hscrp.value > 10 ? "hsCRP 超过 10 时按急性异常上限处理，并降低本次慢性评分权重。" : "hsCRP 作为实验室锚点直接进入炎症主权重。"
            ))
        }
        if let nlr {
            features.append(WeightedFeature(
                title: "CBC/NLR",
                score: nlrBad(nlr.value),
                confidence: nlr.confidence,
                weight: 16,
                displayValue: nlr.displayValue,
                note: "NLR 越高，CBC/NLR 子分越高。"
            ))
        } else if let wbc {
            features.append(WeightedFeature(
                title: "CBC/WBC",
                score: wbcBad(wbc.value),
                confidence: wbc.confidence,
                weight: 16,
                displayValue: wbc.displayValue,
                note: "白细胞超出血常规区间时，CBC/WBC 子分上调炎症分。"
            ))
        }
        if let cytokine {
            features.append(WeightedFeature(
                title: "炎症因子",
                score: cytokineBad(cytokine.value),
                confidence: cytokine.confidence,
                weight: 14,
                displayValue: cytokine.displayValue,
                note: "IL-6/TNFα/GlycA 有值时按炎症因子主权重进入模型。"
            ))
        }

        if let temperature = evidence(context, metricID: nil, aliases: ["体温", "temperature", "temp"], title: "体温") {
            features.append(WeightedFeature(
                title: "体温",
                score: temperatureBad(temperature.value),
                confidence: temperature.confidence * 0.86,
                weight: hasLab ? 8 : 20,
                displayValue: temperature.displayValue,
                note: "体温偏离按体温子分进入模型；无实验室锚点时权重提高。"
            ))
        }
        if let rhr = evidence(context, metricID: "restingHeartRate", aliases: ["静息心率", "rhr", "restingheartrate"], title: "静息心率") {
            features.append(WeightedFeature(
                title: "静息心率",
                score: rhrBad(rhr.value),
                confidence: rhr.confidence,
                weight: hasLab ? 7 : 18,
                displayValue: rhr.displayValue,
                note: "静息心率越高，身体小火苗代理子分越高。"
            ))
        }
        if let hrv = evidence(context, metricID: "hrv", aliases: ["心率变异性", "hrv", "sdnn", "rmssd"], title: "HRV/PRV") {
            features.append(WeightedFeature(
                title: "HRV/PRV",
                score: hrvSuppressionBad(hrv.value),
                confidence: hrv.confidence,
                weight: hasLab ? 6 : 16,
                displayValue: hrv.displayValue,
                note: "HRV/PRV 越低，慢性负荷代理子分越高。"
            ))
        }
        if let respiration = evidence(context, metricID: "respiratoryRate", aliases: ["呼吸频率", "呼吸率", "respiratory", "respiration"], title: "呼吸") {
            features.append(WeightedFeature(
                title: "呼吸",
                score: respirationBad(respiration.value),
                confidence: respiration.confidence,
                weight: hasLab ? 4 : 12,
                displayValue: respiration.displayValue,
                note: "呼吸偏离按偏离幅度提高代理子分。"
            ))
        }
        if let oxygen = evidence(context, metricID: "bloodOxygen", aliases: ["血氧", "spo2", "氧饱和"], title: "血氧") {
            features.append(WeightedFeature(
                title: "血氧",
                score: oxygenBad(oxygen.value),
                confidence: oxygen.confidence,
                weight: hasLab ? 2 : 6,
                displayValue: oxygen.displayValue,
                note: "血氧低于稳定区间时，提高呼吸/睡眠复核子分。"
            ))
        }
        if !hasLab, let load = sleepOrOverloadBad(context) {
            features.append(WeightedFeature(
                title: "睡眠/负荷",
                score: load.score,
                confidence: load.confidence,
                weight: 8,
                displayValue: load.displayValue,
                note: "睡眠债和过度负荷直接提高身体小火苗代理分。"
            ))
        }

        let cap: Double? = hasLab ? ((hscrp?.value ?? 0) > 10 ? 70 : nil) : 55
        let result = weightedResult(features, context: context, requiredSignals: hasLab ? 6 : 5, requiredDomains: hasLab ? 3 : 2, cap: cap, fallback: hasLab ? 42 : 35)
        let value = Int(result.score.rounded())
        let isReady = hasLab && result.confidence >= 35
        return XAgeMetricScore(
            value: value,
            confidence: result.confidence,
            isReady: isReady,
            badgeLabel: isReady ? inflammationBadge(value) : "待评估",
            stateLabel: isReady ? inflammationState(value, proxy: !hasLab) : "炎症待评估",
            summary: isReady ? inflammationSummary(value, proxy: !hasLab) : "炎症评分需要近期 hsCRP、血常规/CBC、NLR 或炎症因子报告。可穿戴数据只作为辅助，不单独给炎症分。",
            simpleExplanation: hasLab
                ? "炎症分先看报告里的炎症锚点，再用体温、心率、HRV、呼吸和血氧补充判断。实验室指标直接反映炎症相关反应，所以权重最高。"
                : "当前没有报告里的炎症锚点，小捷只看到体温、心率、睡眠等辅助信号。这些信号能提示身体负荷，但不能单独说明炎症，所以首页先显示待评估。",
            explanation: hasLab
                ? "炎症分优先把 hsCRP、CBC/NLR、IL-6/TNFα/GlycA 换算为实验室子分，并给这些子分最高权重；再加入体温、静息心率、HRV、呼吸和血氧作为补充。实验室项权重最高，因为它们直接对应炎症相关生物标志物。"
                : "当前没有可信实验室锚点，算法启用“身体小火苗”代理信号：把体温偏移、静息心率、HRV 抑制、呼吸、血氧、睡眠债和活动负荷换算为代理子分并加权。该代理信号只表示算法风险负荷，不是炎症诊断。",
            nextAction: isReady
                ? (value >= 60 ? "先记录体温、症状、睡眠、饮酒和训练；连续偏高时上传最新报告，实验室锚点会替代代理项并重算炎症分。" : "继续同步 Apple 健康和上传报告；新增实验室锚点会替代代理项并提高置信度。")
                : "上传近期血常规、hsCRP 或体检化验报告后再评估炎症分；Apple 健康的体温、心率和睡眠会作为辅助输入。",
            fields: scoreFields((hasLab ? result.fields : [XAgeScoreField(title: "类型", value: "代理信号")] + result.fields), confidence: result.confidence, isReady: isReady, missing: "hsCRP / 血常规 / NLR / 炎症因子报告"),
            drivers: scoreDrivers(result.drivers, isReady: isReady, title: "上传炎症锚点", note: "炎症必须有实验室指标支撑；没有报告时只保留辅助信号，不展示炎症分。"),
            isProxy: !hasLab
        )
    }

    static func makeXAge(
        _ context: XAgeAlgorithmContext,
        pressure: XAgeMetricScore,
        recovery: XAgeMetricScore,
        inflammation: XAgeMetricScore
    ) -> XAgeAgeScore {
        var domains: [WeightedFeature] = []
        domains.append(WeightedFeature(
            title: "自主神经",
            score: recovery.valueAsDouble,
            confidence: Double(recovery.confidence) / 100,
            weight: 15,
            displayValue: "\(recovery.value)",
            note: "恢复分越高，X年龄域分越高，年龄差向年轻方向移动。"
        ))

        if let sleep = evidence(context, metricID: "sleep", aliases: ["睡眠", "sleep"], title: "睡眠") {
            domains.append(WeightedFeature(
                title: "睡眠健康",
                score: sleepGood(sleep.value),
                confidence: sleep.confidence,
                weight: 15,
                displayValue: sleep.displayValue,
                note: "睡眠处于 7-9 小时区间时，睡眠域分提高。"
            ))
        }

        if let activity = activityGood(context) {
            domains.append(WeightedFeature(
                title: "活动与心肺",
                score: activity.score,
                confidence: activity.confidence,
                weight: 25,
                displayValue: activity.displayValue,
                note: "步数和运动分钟越接近目标，活动域分越高。"
            ))
        }

        let inflammationWeight: Double = inflammation.isProxy ? 10 : 20
        domains.append(WeightedFeature(
            title: inflammation.isProxy ? "小火苗代理" : "炎症与代谢",
            score: 100 - inflammation.valueAsDouble,
            confidence: Double(inflammation.confidence) / 100,
            weight: inflammationWeight,
            displayValue: "\(inflammation.value)",
            note: inflammation.isProxy ? "无实验室数据时，小火苗代理以低权重进入 X年龄。" : "实验室炎症和代谢信号以主权重进入 X年龄。"
        ))

        if let dashboardScore = context.dashboardScore {
            domains.append(WeightedFeature(
                title: "代谢状态",
                score: clamp(Double(dashboardScore)),
                confidence: 0.72,
                weight: inflammation.isProxy ? 10 : 8,
                displayValue: "\(dashboardScore)",
                note: "服务端代谢评分直接补充代谢域。"
            ))
        }

        if let body = bodyCompositionGood(context) {
            domains.append(WeightedFeature(
                title: "身体组成",
                score: body.score,
                confidence: body.confidence,
                weight: 15,
                displayValue: body.displayValue,
                note: "体重、BMI 或体脂进入身体组成域。"
            ))
        }

        let result = weightedResult(domains, context: context, requiredSignals: 8, requiredDomains: 4, cap: nil, fallback: 50)
        let validDays = estimatedValidDays(context)
        let dataCap: Double
        if validDays < 30 {
            dataCap = 30
        } else if validDays < 90 {
            dataCap = 60
        } else if validDays < 180 {
            dataCap = 75
        } else {
            dataCap = 90
        }
        let confidence = min(result.confidence, Int(dataCap.rounded()))
        let chronAge = Double(context.userAge ?? 35)
        let readyDomains = domains.filter { $0.confidence > 0 }.count
        let isReady = validDays >= 7 && confidence >= 35 && readyDomains >= 4 && pressure.isReady && recovery.isReady
        let shrinkage = min(1, Double(validDays) / 180) * (Double(confidence) / 100)
        let domainAgeDelta = (50 - result.score) / 10 * 2.2
        let loadDelta = (Double(pressure.value) - 50) / 50 * 1.2
        let rawDelta = clamp(domainAgeDelta + loadDelta - 0.35, -6.5, 3.5)
        let ageValue = chronAge + rawDelta * max(0.18, shrinkage)
        let deltaYears = ageValue - chronAge
        let pace = clamp(1 + (Double(pressure.value) - 50) * 0.006 - (Double(recovery.value) - 50) * 0.005 + (Double(inflammation.value) - 50) * 0.004, -1, 3)
        let rangeWidth = 0.8 + 3.0 * (1 - Double(confidence) / 100)

        return XAgeAgeScore(
            chronologicalAge: chronAge,
            ageValue: ageValue,
            isReady: isReady,
            age: isReady ? String(format: "%.1f", ageValue) : "--",
            delta: isReady ? deltaLabel(deltaYears) : "待评估",
            pace: pace,
            confidence: confidence,
            status: isReady ? xAgeStatus(pace: pace, delta: deltaYears, confidence: confidence) : "待评估",
            summary: isReady
                ? xAgeSummary(result: result, pressure: pressure, recovery: recovery, inflammation: inflammation, validDays: validDays)
                : "上一个评估周期的数据还不够。先同步 HRV、睡眠、活动和报告指标，达到门槛后再显示 X年龄。",
            explanation: "X年龄先把恢复、自主神经、睡眠、活动、炎症/小火苗、代谢和身体组成归一化为 0-100 域分，再把域分折算成年龄差并加到实际年龄上。域分越低，年龄差越往上；域分越高，年龄差越往下。有效天数决定置信度和年龄区间宽度，当前结果是趋势年龄。",
            nextAction: "继续同步睡眠、HRV、活动和报告指标；新增数据会增加有效天数、收窄年龄区间并提高置信度。",
            drivers: result.drivers,
            ageRange: isReady ? "\(String(format: "%.1f", ageValue - rangeWidth)) - \(String(format: "%.1f", ageValue + rangeWidth))" : "数据不足"
        )
    }

    static func weightedResult(
        _ features: [WeightedFeature],
        context: XAgeAlgorithmContext,
        requiredSignals: Double,
        requiredDomains: Double,
        cap: Double?,
        fallback: Double
    ) -> WeightedResult {
        let usable = features.filter { $0.confidence > 0 && $0.score.isFinite && $0.weight > 0 }
        guard !usable.isEmpty else {
            let field = XAgeScoreField(title: "数据状态", value: "建立基线中")
            let driver = XAgeScoreDriver(title: "数据不足", value: "--", note: "同步 Apple 健康或上传报告后，算法用真实输入替代占位值。")
            return WeightedResult(score: fallback, confidence: 12, drivers: [driver], fields: [field])
        }

        let expectedWeight = max(features.map(\.weight).reduce(0, +), usable.map(\.weight).reduce(0, +))
        let denominator = usable.reduce(0) { $0 + $1.weight * $1.confidence }
        let numerator = usable.reduce(0) { $0 + $1.weight * $1.confidence * $1.score }
        let coverage = denominator / expectedWeight
        let signalCount = Double(max(1, context.samples.count + min(context.serverTrends.count, 8) + min(context.watchedIndicatorCount, 4)))
        let sampleFactor = min(1, sqrt(signalCount / requiredSignals))
        let domainBalance = min(1, Double(usable.count) / requiredDomains)
        var confidence = 100 * pow(coverage, 0.55) * pow(sampleFactor, 0.25) * pow(domainBalance, 0.20) * 0.94
        if let cap {
            confidence = min(confidence, cap)
        }
        let sorted = usable.sorted { $0.driverStrength > $1.driverStrength }
        return WeightedResult(
            score: clamp(numerator / denominator),
            confidence: Int(clamp(confidence, 0, 100).rounded()),
            drivers: sorted.prefix(4).map(\.driver),
            fields: Array(usable.prefix(8).map(\.field))
        )
    }

    static func evidence(
        _ context: XAgeAlgorithmContext,
        metricID: String?,
        aliases: [String],
        title: String
    ) -> Evidence? {
        if let metricID,
           let sample = context.samples
            .filter({ $0.metricID == metricID })
            .sorted(by: { $0.measuredAt > $1.measuredAt })
            .first {
            return Evidence(
                title: title,
                value: sample.value,
                displayValue: sample.displayUnit.isEmpty
                    ? "\(sample.displayValue)\(sample.unit.isEmpty ? "" : " \(sample.unit)")"
                    : "\(sample.displayValue) \(sample.displayUnit)",
                confidence: sampleConfidence(sample),
                abnormal: false,
                rawName: sample.indicatorName,
                unit: sample.displayUnit.isEmpty ? sample.unit : sample.displayUnit,
                source: "apple_health"
            )
        }

        let normalizedAliases = aliases.map(XAgeAlgorithmTrend.normalizedKey)
        guard let trend = context.serverTrends.first(where: { trend in
            let key = XAgeAlgorithmTrend.normalizedKey(trend.name)
            return normalizedAliases.contains { alias in
                key.contains(alias) || alias.contains(key)
            }
        }) else { return nil }

        return Evidence(
            title: title,
            value: normalizedPercentValue(trend.value, unit: trend.unit, title: title),
            displayValue: trend.displayValue,
            confidence: serverTrendConfidence(trend),
            abnormal: trend.abnormal,
            rawName: trend.name,
            unit: trend.unit,
            source: trend.source
        )
    }

    static func sampleConfidence(_ sample: AppleHealthSyncSample) -> Double {
        let days = max(0, Date().timeIntervalSince(sample.measuredAt) / 86_400)
        return clamp(0.9 * exp(-days / 21), 0.35, 0.9)
    }

    static func serverTrendConfidence(_ trend: XAgeAlgorithmTrend) -> Double {
        guard let measuredAt = trend.measuredAt, let date = parseDate(measuredAt) else {
            return clamp(trend.confidence, 0.35, 0.86)
        }
        let days = max(0, Date().timeIntervalSince(date) / 86_400)
        let freshness = exp(-days / 120)
        return clamp(trend.confidence * freshness, 0.25, 0.86)
    }

    static func parseDate(_ raw: String) -> Date? {
        if let date = isoFormatter.date(from: raw) { return date }
        return dateOnlyFormatter.date(from: raw)
    }

    static func activityLoad(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        let steps = evidence(context, metricID: "steps", aliases: ["步数", "steps"], title: "步数")
        let exercise = evidence(context, metricID: "exerciseMinutes", aliases: ["运动分钟", "exercise"], title: "运动分钟")
        let energy = evidence(context, metricID: "activeEnergy", aliases: ["活动能量", "activeenergy", "kcal"], title: "活动能量")
        let values = [steps, exercise, energy].compactMap { $0 }
        guard !values.isEmpty else { return nil }
        let stepLoad = steps.map { linear($0.value, low: 9_000, high: 16_000, minScore: 18, maxScore: 86) } ?? 0
        let exerciseLoad = exercise.map { linear($0.value, low: 45, high: 120, minScore: 18, maxScore: 88) } ?? 0
        let energyLoad = energy.map { linear($0.value, low: 450, high: 900, minScore: 18, maxScore: 86) } ?? 0
        let score = max(stepLoad, exerciseLoad, energyLoad)
        return (
            score,
            values.map(\.confidence).reduce(0, +) / Double(values.count),
            values.prefix(2).map(\.displayValue).joined(separator: " · ")
        )
    }

    static func activityGood(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        let steps = evidence(context, metricID: "steps", aliases: ["步数", "steps"], title: "步数")
        let exercise = evidence(context, metricID: "exerciseMinutes", aliases: ["运动分钟", "exercise"], title: "运动分钟")
        let values = [steps, exercise].compactMap { $0 }
        guard !values.isEmpty else { return nil }
        let stepGood = steps.map { linear($0.value, low: 2_000, high: 8_000, minScore: 35, maxScore: 95) } ?? 50
        let exerciseGood = exercise.map { linear($0.value, low: 0, high: 30, minScore: 45, maxScore: 95) } ?? 50
        let score = steps != nil && exercise != nil ? (stepGood * 0.65 + exerciseGood * 0.35) : (steps != nil ? stepGood : exerciseGood)
        return (
            score,
            values.map(\.confidence).reduce(0, +) / Double(values.count),
            values.map(\.displayValue).joined(separator: " · ")
        )
    }

    static func stabilityGood(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        var parts: [(Double, Evidence)] = []
        if let respiration = evidence(context, metricID: "respiratoryRate", aliases: ["呼吸频率", "呼吸率", "respiratory"], title: "呼吸") {
            parts.append((100 - respirationBad(respiration.value), respiration))
        }
        if let oxygen = evidence(context, metricID: "bloodOxygen", aliases: ["血氧", "spo2", "氧饱和"], title: "血氧") {
            parts.append((100 - oxygenBad(oxygen.value), oxygen))
        }
        if let temperature = evidence(context, metricID: nil, aliases: ["体温", "temperature", "temp"], title: "体温") {
            parts.append((100 - temperatureBad(temperature.value), temperature))
        }
        guard !parts.isEmpty else { return nil }
        return (
            parts.map(\.0).reduce(0, +) / Double(parts.count),
            parts.map { $0.1.confidence }.reduce(0, +) / Double(parts.count),
            parts.prefix(2).map { $0.1.displayValue }.joined(separator: " · ")
        )
    }

    static func sleepOrOverloadBad(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        var parts: [(Double, Evidence)] = []
        if let sleep = evidence(context, metricID: "sleep", aliases: ["睡眠", "sleep"], title: "睡眠") {
            parts.append((sleepDebtBad(sleep.value), sleep))
        }
        if let load = activityLoad(context) {
            let evidence = Evidence(
                title: "活动负荷",
                value: load.score,
                displayValue: load.displayValue,
                confidence: load.confidence,
                abnormal: false,
                rawName: nil,
                unit: nil,
                source: nil
            )
            parts.append((load.score, evidence))
        }
        guard !parts.isEmpty else { return nil }
        return (
            parts.map(\.0).max() ?? 0,
            parts.map { $0.1.confidence }.reduce(0, +) / Double(parts.count),
            parts.prefix(2).map { $0.1.displayValue }.joined(separator: " · ")
        )
    }

    static func bodyCompositionGood(_ context: XAgeAlgorithmContext) -> (score: Double, confidence: Double, displayValue: String)? {
        var scores: [(Double, String, Double)] = []
        if let weight = evidence(context, metricID: "bodyWeight", aliases: ["体重", "weight"], title: "体重"),
           let height = context.profileHeightCm, height > 0 {
            let bmi = weight.value / pow(height / 100, 2)
            scores.append((bmiGood(bmi), String(format: "BMI %.1f", bmi), min(weight.confidence, 0.78)))
        }
        if let bodyFat = evidence(context, metricID: "bodyFat", aliases: ["体脂", "bodyfat"], title: "体脂率") {
            scores.append((bodyFatGood(bodyFat.value), bodyFat.displayValue, bodyFat.confidence))
        }
        if scores.isEmpty, let weight = context.profileWeightKg, let height = context.profileHeightCm, height > 0 {
            let bmi = weight / pow(height / 100, 2)
            scores.append((bmiGood(bmi), String(format: "BMI %.1f", bmi), 0.62))
        }
        guard !scores.isEmpty else { return nil }
        return (
            scores.map(\.0).reduce(0, +) / Double(scores.count),
            scores.map(\.2).reduce(0, +) / Double(scores.count),
            scores.map(\.1).joined(separator: " · ")
        )
    }

    static func estimatedValidDays(_ context: XAgeAlgorithmContext) -> Int {
        let sampleDays = context.samples.isEmpty ? 0 : min(45, context.samples.count * 4)
        let documentDays = context.documentCount > 0 ? min(90, 25 + context.documentCount / 2) : 0
        return max(context.trendPointCount, sampleDays, documentDays)
    }

    static func addConfidenceField(_ fields: [XAgeScoreField], confidence: Int) -> [XAgeScoreField] {
        var merged = fields
        merged.append(XAgeScoreField(title: "置信度", value: "\(confidence)%"))
        return merged
    }

    static func scoreFields(_ fields: [XAgeScoreField], confidence: Int, isReady: Bool, missing: String) -> [XAgeScoreField] {
        if isReady {
            return addConfidenceField(fields, confidence: confidence)
        }
        var merged = [
            XAgeScoreField(title: "评估状态", value: "待评估"),
            XAgeScoreField(title: "还需要", value: missing),
            XAgeScoreField(title: "当前置信度", value: "\(confidence)%")
        ]
        if !fields.isEmpty {
            merged.append(contentsOf: fields.prefix(3))
        }
        return merged
    }

    static func scoreDrivers(_ drivers: [XAgeScoreDriver], isReady: Bool, title: String, note: String) -> [XAgeScoreDriver] {
        if isReady {
            return drivers
        }
        return [XAgeScoreDriver(title: title, value: "待补齐", note: note)] + drivers.prefix(2)
    }

    static func normalizedPercentValue(_ value: Double, unit: String?, title: String) -> Double {
        let lower = (unit ?? "").lowercased()
        if (title == "血氧" || title.contains("体脂")) && value <= 1.2 {
            return value * 100
        }
        if lower.contains("%"), value <= 1.2 {
            return value * 100
        }
        return value
    }

    static func credibleBloodWhiteCell(_ evidence: Evidence) -> Bool {
        let name = (evidence.rawName ?? evidence.title).lowercased()
        let normalizedName = XAgeAlgorithmTrend.normalizedKey(name)
        let unit = (evidence.unit ?? "").lowercased()
        let display = evidence.displayValue.lowercased()

        if urineSedimentLike(display) || urineSedimentLike(unit) || urineSedimentLike(name) {
            return false
        }
        if normalizedName.contains("尿")
            || normalizedName.contains("沉渣")
            || normalizedName.contains("镜检")
            || normalizedName.contains("上皮")
            || normalizedName.contains("粪") {
            return false
        }

        let compactUnit = unit
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "×", with: "x")
            .replacingOccurrences(of: "*", with: "x")
        let hasBloodUnit = compactUnit.contains("/l")
            && (compactUnit.contains("10") || compactUnit.contains("e9") || compactUnit.contains("^9"))
        let hasBloodName = normalizedName.contains("白细胞计数")
            || normalizedName.contains("血白细胞")
            || normalizedName.contains("血常规")
            || normalizedName.contains("全血")
            || normalizedName.contains("cbc")
            || normalizedName == "wbc"

        return hasBloodUnit || hasBloodName
    }

    static func urineSedimentLike(_ text: String) -> Bool {
        let lower = text.lowercased()
        return lower.contains("/hp") || lower.contains("/lp") || lower.contains("个/hp") || lower.contains("个/lp")
    }

    static func hrvGood(_ value: Double) -> Double {
        linear(value, low: 18, high: 65, minScore: 25, maxScore: 95)
    }

    static func hrvSuppressionBad(_ value: Double) -> Double {
        100 - hrvGood(value)
    }

    static func rhrGood(_ value: Double) -> Double {
        if value <= 58 { return 92 }
        return 100 - linear(value, low: 58, high: 88, minScore: 18, maxScore: 88)
    }

    static func rhrBad(_ value: Double) -> Double {
        100 - rhrGood(value)
    }

    static func respirationBad(_ value: Double) -> Double {
        let deviation = abs(value - 16)
        return linear(deviation, low: 2, high: 8, minScore: 12, maxScore: 88)
    }

    static func temperatureBad(_ value: Double) -> Double {
        let deviation: Double
        if value > 30 {
            deviation = abs(value - 36.7)
        } else {
            deviation = abs(value)
        }
        return linear(deviation, low: 0.2, high: 1.1, minScore: 12, maxScore: 86)
    }

    static func oxygenBad(_ value: Double) -> Double {
        if value >= 97 { return 10 }
        if value >= 95 { return linear(97 - value, low: 0, high: 2, minScore: 16, maxScore: 38) }
        return linear(95 - value, low: 0, high: 6, minScore: 48, maxScore: 90)
    }

    static func sleepGood(_ hours: Double) -> Double {
        if (7...9).contains(hours) { return 92 }
        if hours < 7 { return linear(hours, low: 4, high: 7, minScore: 28, maxScore: 88) }
        return clamp(92 - (hours - 9) * 16, 55, 92)
    }

    static func sleepDebtBad(_ hours: Double) -> Double {
        if hours >= 7 { return 14 }
        return linear(7 - hours, low: 0, high: 3, minScore: 18, maxScore: 88)
    }

    static func hscrpBad(_ value: Double) -> Double {
        if value < 1 { return 18 }
        if value < 3 { return linear(value, low: 1, high: 3, minScore: 35, maxScore: 58) }
        if value <= 10 { return linear(value, low: 3, high: 10, minScore: 62, maxScore: 92) }
        return 95
    }

    static func wbcBad(_ value: Double) -> Double {
        if (4...10).contains(value) { return 20 }
        if value < 4 { return linear(4 - value, low: 0, high: 2, minScore: 32, maxScore: 72) }
        return linear(value, low: 10, high: 16, minScore: 42, maxScore: 88)
    }

    static func nlrBad(_ value: Double) -> Double {
        if value < 2.5 { return 22 }
        return linear(value, low: 2.5, high: 5.5, minScore: 38, maxScore: 86)
    }

    static func cytokineBad(_ value: Double) -> Double {
        linear(value, low: 2, high: 10, minScore: 28, maxScore: 88)
    }

    static func bmiGood(_ value: Double) -> Double {
        if (18.5...24.9).contains(value) { return 88 }
        if value < 18.5 { return linear(value, low: 16, high: 18.5, minScore: 52, maxScore: 82) }
        return 100 - linear(value, low: 25, high: 33, minScore: 18, maxScore: 72)
    }

    static func bodyFatGood(_ value: Double) -> Double {
        if (16...28).contains(value) { return 84 }
        if value < 16 { return linear(value, low: 8, high: 16, minScore: 54, maxScore: 80) }
        return 100 - linear(value, low: 28, high: 42, minScore: 24, maxScore: 74)
    }

    static func pressureBadge(_ value: Int) -> String {
        if value >= 70 { return "压力偏高" }
        if value >= 40 { return "压力中等" }
        return "压力偏低"
    }

    static func pressureState(_ value: Int) -> String {
        value >= 70 ? "压力偏高" : (value >= 40 ? "压力中等" : "压力较低")
    }

    static func pressureSummary(_ value: Int) -> String {
        value >= 70 ? "压力输入处在高负荷区间；先降低刺激并复测。" : "压力负荷处在可管理区间。"
    }

    static func recoveryBadge(_ value: Int) -> String {
        if value >= 67 { return "恢复良好" }
        if value >= 34 { return "恢复一般" }
        return "恢复偏低"
    }

    static func recoveryState(_ value: Int) -> String {
        value >= 67 ? "恢复较好" : (value >= 34 ? "恢复一般" : "恢复偏低")
    }

    static func recoverySummary(_ value: Int) -> String {
        value >= 67 ? "恢复输入处在高分区间，可以承接适度挑战。" : "恢复输入处在保守区间，今天降低强度并补齐睡眠。"
    }

    static func inflammationBadge(_ value: Int) -> String {
        if value >= 70 { return "小火苗高" }
        if value >= 40 { return "炎症关注" }
        return "小火苗低"
    }

    static func inflammationState(_ value: Int, proxy: Bool) -> String {
        if value >= 70 { return proxy ? "小火苗偏高" : "炎症负荷偏高" }
        if value >= 40 { return proxy ? "小火苗中等" : "炎症负荷中等" }
        return proxy ? "小火苗较低" : "炎症负荷较低"
    }

    static func inflammationSummary(_ value: Int, proxy: Bool) -> String {
        if proxy {
            return value >= 60 ? "代理信号处在高位，体温和症状记录会参与下一次重算。" : "代理信号处在低位，实验室数据会替代当前代理项。"
        }
        return value >= 60 ? "实验室和生理信号处在复核区间。" : "炎症负荷处于较低区间。"
    }

    static func deltaLabel(_ value: Double) -> String {
        if value <= -0.15 { return "年轻 \(String(format: "%.1f", abs(value))) 岁" }
        if value >= 0.15 { return "偏大 \(String(format: "%.1f", value)) 岁" }
        return "接近实际年龄"
    }

    static func xAgeStatus(pace: Double, delta: Double, confidence: Int) -> String {
        if confidence < 35 { return "建立基线中" }
        if pace < 0.85 || delta < -0.5 { return "趋势变年轻" }
        if pace > 1.15 || delta > 0.5 { return "负荷略高" }
        return "稳定且健康"
    }

    static func xAgeSummary(result: WeightedResult, pressure: XAgeMetricScore, recovery: XAgeMetricScore, inflammation: XAgeMetricScore, validDays: Int) -> String {
        if validDays < 30 {
            return "有效天数不足 30 天，算法启用低影响系数和低置信度区间。"
        }
        if let driver = result.drivers.first {
            return "\(driver.title) 是本周年龄差的最大贡献项；算法每周用压力、恢复、炎症和日常节律重算 X年龄。"
        }
        return "当前 X年龄由压力、恢复、炎症和日常节律共同决定。"
    }

    static func linear(_ value: Double, low: Double, high: Double, minScore: Double, maxScore: Double) -> Double {
        guard high > low else { return minScore }
        let ratio = (value - low) / (high - low)
        return clamp(minScore + ratio * (maxScore - minScore))
    }

    static func clamp(_ value: Double, _ lower: Double = 0, _ upper: Double = 100) -> Double {
        min(max(value, lower), upper)
    }

    static let isoFormatter = ISO8601DateFormatter()

    static let dateOnlyFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()
}

private extension XAgeMetricScore {
    var valueAsDouble: Double { Double(value) }
}

private enum XAgeDataScrollSpace {
    static let name = "xageDataScroll"
}

private struct XAgeDataScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

private struct XAgeDataScrollOffsetProbe: View {
    var body: some View {
        GeometryReader { proxy in
            Color.clear
                .preference(
                    key: XAgeDataScrollOffsetPreferenceKey.self,
                    value: proxy.frame(in: .named(XAgeDataScrollSpace.name)).minY
                )
        }
        .frame(height: 1)
        .accessibilityHidden(true)
    }
}

private struct XAgeDataScrollOffsetTracker: ViewModifier {
    let onOffsetChange: (CGFloat) -> Void

    func body(content: Content) -> some View {
        if #available(iOS 18.0, *) {
            content
                .onScrollGeometryChange(for: CGFloat.self) { geometry in
                    geometry.contentOffset.y
                } action: { _, newValue in
                    onOffsetChange(newValue)
                }
        } else {
            content
        }
    }
}

private enum XAgeDataSheet: Identifiable {
    case detail(XAgeDataKind)
    case scoreInfo(XAgeDataKind)
    case metricPicker
    case metricManager
    case allMetrics
    case metricDetail(XAgeMetric)
    case manualEntry(XAgeMetric)

    var id: String {
        switch self {
        case .detail(let kind): return "detail-\(kind.id)"
        case .scoreInfo(let kind): return "score-info-\(kind.id)"
        case .metricPicker: return "metric-picker"
        case .metricManager: return "metric-manager"
        case .allMetrics: return "all-metrics"
        case .metricDetail(let metric): return "metric-detail-\(metric.id)"
        case .manualEntry(let metric): return "manual-entry-\(metric.id)"
        }
    }
}

private struct XAgeDataStickyHeader: View {
    let collapseProgress: CGFloat
    let caption: String
    let scores: XAgeCompositeScores
    let showsTodayStatus: Bool
    let onSelectDetail: (XAgeDataKind) -> Void
    let onSelectInfo: (XAgeDataKind) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12 - 4 * collapseProgress) {
            VStack(alignment: .leading, spacing: 4) {
                Text("今日健康数据")
                    .font(.system(size: 27 - 4 * collapseProgress, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .lineLimit(1)
                Text(caption)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "5D7B95"))
                    .opacity(Double(1 - collapseProgress))
                    .frame(height: 18 * (1 - collapseProgress), alignment: .top)
                    .clipped()
            }
            .frame(height: 52 - 18 * collapseProgress, alignment: .topLeading)

            XAgeScoreRingPanel(
                collapseProgress: collapseProgress,
                scores: scores,
                onSelectDetail: onSelectDetail,
                onSelectInfo: onSelectInfo
            )

            if showsTodayStatus {
                XAgeScoreSummaryCard(compactProgress: collapseProgress, scores: scores)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
    }
}

private enum XAgeDataKind: String, Identifiable {
    case pressure = "压力"
    case recovery = "恢复"
    case inflammation = "炎症"

    var id: String { rawValue }

    var tint: Color {
        switch self {
        case .pressure: return Color(hex: "2789D8")
        case .recovery: return Color(hex: "14B887")
        case .inflammation: return Color(hex: "EF9A3D")
        }
    }

    var accessibilityKey: String {
        switch self {
        case .pressure: return "pressure"
        case .recovery: return "recovery"
        case .inflammation: return "inflammation"
        }
    }
}

private struct XAgeScoreRing: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    var ringSize: CGFloat = 86
    var onInfo: (() -> Void)? = nil

    var body: some View {
        let lineWidth = max(7, ringSize * 0.1)
        VStack(spacing: 7) {
            ZStack {
                Circle()
                    .trim(from: 0.04, to: 0.9)
                    .stroke(Color.white.opacity(0.52), style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                    .rotationEffect(.degrees(112))
                Circle()
                    .trim(from: 0.04, to: 0.04 + 0.86 * CGFloat(metric.isReady ? metric.value : 0) / 100)
                    .stroke(
                        AngularGradient(
                            colors: [kind.tint.opacity(0.35), kind.tint, Color.appAccent, kind.tint],
                            center: .center
                        ),
                        style: StrokeStyle(lineWidth: lineWidth, lineCap: .round)
                    )
                    .rotationEffect(.degrees(112))
                    .opacity(metric.isReady ? 1 : 0.28)
                    .shadow(color: kind.tint.opacity(metric.isReady ? 0.22 : 0.08), radius: 8, x: 0, y: 3)
                Text(metric.displayValue)
                    .font(.system(size: metric.isReady ? (ringSize >= 80 ? 25 : 22) : 20, weight: .bold))
                    .foregroundStyle(Color(hex: "17324E"))
            }
            .frame(width: ringSize, height: ringSize)
            .contentShape(Circle())

            HStack(spacing: 3) {
                Text(kind.rawValue)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color(hex: "43657F"))
                    .lineLimit(1)
                if let onInfo {
                    Button(action: onInfo) {
                        Image(systemName: "info.circle.fill")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(kind.tint)
                            .frame(width: 18, height: 18)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.data.score.\(kind.accessibilityKey).info")
                    .accessibilityLabel("\(kind.rawValue)原理")
                }
            }
            .frame(height: 18)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct XAgeScoreRingPanel: View {
    let collapseProgress: CGFloat
    let scores: XAgeCompositeScores
    let onSelectDetail: (XAgeDataKind) -> Void
    let onSelectInfo: (XAgeDataKind) -> Void

    var body: some View {
        let ringSize = 86 - 14 * collapseProgress
        HStack(spacing: 8) {
            XAgeScoreRing(kind: .pressure, metric: scores.pressure, ringSize: ringSize) {
                onSelectInfo(.pressure)
            }
                .onTapGesture { onSelectDetail(.pressure) }
                .accessibilityIdentifier("xage.data.score.pressure")
            XAgeScoreRing(kind: .recovery, metric: scores.recovery, ringSize: ringSize) {
                onSelectInfo(.recovery)
            }
                .onTapGesture { onSelectDetail(.recovery) }
                .accessibilityIdentifier("xage.data.score.recovery")
            XAgeScoreRing(kind: .inflammation, metric: scores.inflammation, ringSize: ringSize) {
                onSelectInfo(.inflammation)
            }
                .onTapGesture { onSelectDetail(.inflammation) }
                .accessibilityIdentifier("xage.data.score.inflammation")
        }
        .frame(maxWidth: .infinity)
        .frame(height: 122)
        .background(XAgeGlassCardBackground(cornerRadius: 28))
    }
}

private struct XAgeScoreSummaryCard: View {
    let compactProgress: CGFloat
    let scores: XAgeCompositeScores

    private var badges: [(id: String, title: String, color: Color)] {
        [
            ("pressure", scores.pressure.badgeLabel, Color(hex: "2789D8")),
            ("recovery", scores.recovery.badgeLabel, Color(hex: "14B887")),
            ("inflammation", scores.inflammation.badgeLabel, Color(hex: "EF9A3D"))
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8 - 2 * compactProgress) {
            HStack(spacing: 8) {
                Text("今日状态")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Spacer(minLength: 4)
                HStack(spacing: 5) {
                    ForEach(badges, id: \.id) { item in
                        HStack(spacing: 3) {
                            Circle()
                                .fill(item.color)
                                .frame(width: 6, height: 6)
                            Text(item.title)
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(item.color)
                                .lineLimit(1)
                        }
                        .frame(width: 60, height: 22)
                        .background(
                            Capsule()
                                .fill(.white.opacity(0.48))
                                .overlay(Capsule().stroke(.white.opacity(0.76), lineWidth: 1))
                        )
                    }
                }
            }
            Text(scores.todaySummary)
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(2)
                .lineLimit(compactProgress > 0.7 ? 1 : 2)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12 - 2 * compactProgress)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeMetricCatalogSection: Identifiable {
    var id: String { title }
    let title: String
    let icon: String
    let accent: Color
    let metrics: [XAgeMetric]
}

private struct XAgeMetric: Identifiable {
    let id: String
    let title: String
    let value: String
    let unit: String
    let time: String
    let subtitle: String
    let accent: Color
    let source: String?
    let measuredAt: String?
    let isPlaceholder: Bool
    let isStale: Bool

    init(
        id: String,
        title: String,
        value: String,
        unit: String,
        time: String,
        subtitle: String,
        accent: Color,
        source: String? = nil,
        measuredAt: String? = nil,
        isPlaceholder: Bool = false,
        isStale: Bool = false
    ) {
        self.id = id
        self.title = title
        self.value = value
        self.unit = unit
        self.time = time
        self.subtitle = subtitle
        self.accent = accent
        self.source = source
        self.measuredAt = measuredAt
        self.isPlaceholder = isPlaceholder
        self.isStale = isStale
    }

    static let defaultCards = [
        XAgeMetric(id: "hrv", title: "心率变异性", value: "无", unit: "", time: "待同步", subtitle: "同步 Apple 健康后显示最近一次 HRV。", accent: Color(hex: "7B4DFF"), isPlaceholder: true),
        XAgeMetric(id: "sleep", title: "睡眠", value: "无", unit: "", time: "待同步", subtitle: "同步 Apple 健康后显示最近一晚睡眠。", accent: Color(hex: "14B887"), isPlaceholder: true),
        XAgeMetric(id: "glucose", title: "血糖波动", value: "待上传", unit: "", time: "待上传", subtitle: "上传血糖、CGM 或报告后显示波动趋势。", accent: Color(hex: "11A7C8"), isPlaceholder: true),
        XAgeMetric(id: "temp", title: "体温偏移", value: "无", unit: "", time: "待上传", subtitle: "上传或记录体温后显示最近体温偏移。", accent: Color(hex: "EF9A3D"), isPlaceholder: true)
    ]

    static let appleHealthCandidates = [
        XAgeMetric(id: "steps", title: "步数", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日 Apple 健康步数。", accent: Color(hex: "238AD6"), isPlaceholder: true),
        XAgeMetric(id: "distance", title: "步行+跑步距离", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日步行和跑步距离。", accent: Color(hex: "18B7D6"), isPlaceholder: true),
        XAgeMetric(id: "activeEnergy", title: "活动能量", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日活动能量消耗。", accent: Color(hex: "EF9A3D"), isPlaceholder: true),
        XAgeMetric(id: "exerciseMinutes", title: "运动分钟", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日运动分钟。", accent: Color(hex: "14B887"), isPlaceholder: true),
        XAgeMetric(id: "flights", title: "爬楼层数", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示今日爬楼层数。", accent: Color(hex: "4E8FE9"), isPlaceholder: true),
        XAgeMetric(id: "restingHeartRate", title: "静息心率", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次静息心率。", accent: Color(hex: "F05B72"), isPlaceholder: true),
        XAgeMetric(id: "respiratoryRate", title: "呼吸频率", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次呼吸频率。", accent: Color(hex: "2A79C7"), isPlaceholder: true),
        XAgeMetric(id: "bloodOxygen", title: "血氧", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次血氧。", accent: Color(hex: "7B4DFF"), isPlaceholder: true),
        XAgeMetric(id: "systolicBloodPressure", title: "收缩压", value: "待上传", unit: "", time: "待上传", subtitle: "同步 Apple 健康或手动记录后显示收缩压。", accent: Color(hex: "DB5B9B"), isPlaceholder: true),
        XAgeMetric(id: "diastolicBloodPressure", title: "舒张压", value: "待上传", unit: "", time: "待上传", subtitle: "同步 Apple 健康或手动记录后显示舒张压。", accent: Color(hex: "A47BEF"), isPlaceholder: true),
        XAgeMetric(id: "bodyWeight", title: "体重", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次体重。", accent: Color(hex: "11A7C8"), isPlaceholder: true),
        XAgeMetric(id: "bodyFat", title: "体脂率", value: "待同步", unit: "", time: "待同步", subtitle: "同步后显示最近一次体脂率。", accent: Color(hex: "A47BEF"), isPlaceholder: true),
        XAgeMetric(id: "mindfulMinutes", title: "正念分钟", value: "待上传", unit: "", time: "待上传", subtitle: "记录正念时间后用于压力管理分析。", accent: Color(hex: "20CDB1"), isPlaceholder: true),
        XAgeMetric(id: "daylight", title: "日照时间", value: "待上传", unit: "", time: "待上传", subtitle: "记录户外日照后用于节律和睡眠分析。", accent: Color(hex: "F3B349"), isPlaceholder: true)
    ]

    static func catalogSections(serverMetrics: [XAgeMetric]) -> [XAgeMetricCatalogSection] {
        let serverDynamic = deduped(serverMetrics.map {
            XAgeMetric(
                id: $0.id,
                title: $0.title,
                value: $0.value,
                unit: $0.unit,
                time: $0.time,
                subtitle: $0.subtitle,
                accent: $0.accent,
                source: $0.source ?? "document",
                measuredAt: $0.measuredAt,
                isPlaceholder: $0.isPlaceholder,
                isStale: $0.isStale
            )
        })
        let serverStatic = deduped(serverKnowledgeCandidates.filter { candidate in
            !serverDynamic.contains { $0.title == candidate.title }
        })

        var sections: [XAgeMetricCatalogSection] = [
            XAgeMetricCatalogSection(
                title: "小捷核心指标",
                icon: "sparkles",
                accent: Color(hex: "238AD6"),
                metrics: defaultCards
            )
        ]
        sections.append(contentsOf: appleHealthCatalogSections)
        if !serverDynamic.isEmpty {
            sections.append(
                XAgeMetricCatalogSection(
                    title: "服务器已入库指标",
                    icon: "externaldrive.connected.to.line.below",
                    accent: Color(hex: "20CDB1"),
                    metrics: serverDynamic
                )
            )
        }
        sections.append(
            XAgeMetricCatalogSection(
                title: "服务器常见检验指标",
                icon: "cross.case.fill",
                accent: Color(hex: "7B4DFF"),
                metrics: serverStatic
            )
        )
        return sections
    }

    static var appleHealthCatalogCount: Int {
        appleHealthCatalogSections.reduce(0) { $0 + $1.metrics.count }
    }

    private static let appleHealthCatalogSections: [XAgeMetricCatalogSection] = [
        XAgeMetricCatalogSection(
            title: "健身记录",
            icon: "figure.run",
            accent: Color(hex: "FF5A1F"),
            metrics: [
                catalogMetric("steps", "步数", "今日步数；同步 Apple 健康后自动更新。", "步", Color(hex: "FF5A1F")),
                catalogMetric("distance", "步行+跑步距离", "今日步行和跑步距离。", "km", Color(hex: "18B7D6")),
                catalogMetric("exerciseMinutes", "锻炼分钟数", "Apple 健康记录的锻炼分钟。", "min", Color(hex: "14B887")),
                catalogMetric("activeMinutes", "活动分钟数", "日常活动累计分钟。", "min", Color(hex: "20CDB1")),
                catalogMetric("activeEnergy", "活动能量", "活动消耗能量。", "kcal", Color(hex: "EF9A3D")),
                catalogMetric("basalEnergy", "静息能量", "基础代谢消耗能量。", "kcal", Color(hex: "F3B349")),
                catalogMetric("flights", "爬楼层数", "今日爬楼层数。", "层", Color(hex: "4E8FE9")),
                catalogMetric("cyclingDistance", "骑行距离", "骑行训练或通勤距离。", "km", Color(hex: "11A7C8")),
                catalogMetric("swimmingDistance", "游泳距离", "游泳训练距离。", "m", Color(hex: "238AD6")),
                catalogMetric("swimmingStrokes", "划水次数", "游泳划水次数。", "次", Color(hex: "2A79C7")),
                catalogMetric("wheelchairDistance", "推轮椅距离", "轮椅推动距离。", "km", Color(hex: "7B4DFF")),
                catalogMetric("vo2Max", "心肺适能", "最大摄氧量，用于评估心肺耐力。", "ml/kg/min", Color(hex: "F05B72"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "身体测量",
            icon: "figure.stand",
            accent: Color(hex: "11A7C8"),
            metrics: [
                catalogMetric("bodyHeight", "身高", "个人身高记录。", "cm", Color(hex: "238AD6")),
                catalogMetric("bodyWeight", "体重", "最近一次体重。", "kg", Color(hex: "11A7C8")),
                catalogMetric("bodyMassIndex", "BMI", "体重和身高计算出的体质指数。", "", Color(hex: "20CDB1")),
                catalogMetric("bodyFat", "体脂率", "身体脂肪比例。", "%", Color(hex: "A47BEF")),
                catalogMetric("leanBodyMass", "瘦体重", "除脂肪外的体重估算。", "kg", Color(hex: "7B4DFF")),
                catalogMetric("waistCircumference", "腰围", "腹部脂肪和代谢风险参考。", "cm", Color(hex: "EF9A3D")),
                catalogMetric("bodyTemperature", "体温", "最近一次体温。", "°C", Color(hex: "EF9A3D")),
                catalogMetric("basalBodyTemperature", "基础体温", "静息状态体温趋势。", "°C", Color(hex: "F3B349"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "心脏",
            icon: "heart.fill",
            accent: Color(hex: "F05B72"),
            metrics: [
                catalogMetric("heartRate", "心率", "最近一次心率。", "bpm", Color(hex: "F05B72")),
                catalogMetric("restingHeartRate", "静息心率", "最近一次静息心率。", "bpm", Color(hex: "F05B72")),
                catalogMetric("walkingHeartRateAverage", "步行心率平均值", "步行时平均心率。", "bpm", Color(hex: "DB5B9B")),
                catalogMetric("hrv", "心率变异性", "最近一次 HRV。", "ms", Color(hex: "7B4DFF")),
                catalogMetric("heartRateRecovery", "心率恢复", "运动后心率下降速度。", "bpm", Color(hex: "EF9A3D")),
                catalogMetric("systolicBloodPressure", "收缩压", "血压高压。", "mmHg", Color(hex: "DB5B9B")),
                catalogMetric("diastolicBloodPressure", "舒张压", "血压低压。", "mmHg", Color(hex: "A47BEF"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "睡眠与呼吸",
            icon: "bed.double.fill",
            accent: Color(hex: "14B887"),
            metrics: [
                catalogMetric("sleep", "睡眠", "最近一晚睡眠时长。", "h", Color(hex: "14B887")),
                catalogMetric("sleepScore", "睡眠评分", "Apple 健康的睡眠评分。", "", Color(hex: "20CDB1")),
                catalogMetric("timeInBed", "卧床时间", "上床到起床的总时长。", "h", Color(hex: "238AD6")),
                catalogMetric("respiratoryRate", "呼吸频率", "最近一次呼吸频率。", "次/分", Color(hex: "2A79C7")),
                catalogMetric("bloodOxygen", "血氧", "最近一次血氧饱和度。", "%", Color(hex: "7B4DFF")),
                catalogMetric("inhalerUsage", "吸入器使用次数", "呼吸相关用药使用次数。", "次", Color(hex: "11A7C8"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "营养与代谢",
            icon: "fork.knife",
            accent: Color(hex: "EF9A3D"),
            metrics: [
                catalogMetric("glucose", "血糖波动", "血糖或 CGM 趋势。", "mmol/L", Color(hex: "11A7C8")),
                catalogMetric("bloodGlucose", "血糖", "血糖测量值。", "mmol/L", Color(hex: "11A7C8")),
                catalogMetric("insulinDelivery", "胰岛素输注", "胰岛素记录。", "IU", Color(hex: "238AD6")),
                catalogMetric("dietaryEnergy", "膳食能量", "饮食摄入能量。", "kcal", Color(hex: "EF9A3D")),
                catalogMetric("dietaryWater", "水", "饮水量。", "ml", Color(hex: "2A79C7")),
                catalogMetric("dietaryCarbs", "碳水化合物", "饮食碳水摄入。", "g", Color(hex: "F3B349")),
                catalogMetric("dietaryProtein", "蛋白质", "饮食蛋白摄入。", "g", Color(hex: "20CDB1")),
                catalogMetric("dietaryFat", "总脂肪", "饮食脂肪摄入。", "g", Color(hex: "A47BEF")),
                catalogMetric("dietaryFiber", "膳食纤维", "饮食纤维摄入。", "g", Color(hex: "14B887")),
                catalogMetric("dietaryCaffeine", "咖啡因", "咖啡因摄入。", "mg", Color(hex: "7B4DFF"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "身心与环境",
            icon: "sun.max.fill",
            accent: Color(hex: "F3B349"),
            metrics: [
                catalogMetric("mindfulMinutes", "正念分钟", "冥想或正念训练时间。", "min", Color(hex: "20CDB1")),
                catalogMetric("daylight", "日照时间", "户外日照暴露时间。", "min", Color(hex: "F3B349")),
                catalogMetric("environmentalAudio", "环境噪声级别", "环境声音暴露。", "dB", Color(hex: "6C8194")),
                catalogMetric("headphoneAudio", "耳机音量", "耳机声音暴露。", "dB", Color(hex: "238AD6")),
                catalogMetric("uvExposure", "紫外线指数", "紫外线暴露水平。", "", Color(hex: "EF9A3D"))
            ]
        ),
        XAgeMetricCatalogSection(
            title: "生理记录",
            icon: "calendar.badge.clock",
            accent: Color(hex: "DB5B9B"),
            metrics: [
                catalogMetric("menstrualFlow", "经期", "经期流量记录。", "", Color(hex: "DB5B9B")),
                catalogMetric("intermenstrualBleeding", "点滴出血", "非经期出血记录。", "", Color(hex: "F05B72")),
                catalogMetric("cervicalMucus", "宫颈黏液质量", "生理周期相关记录。", "", Color(hex: "A47BEF")),
                catalogMetric("ovulationTest", "排卵测试结果", "排卵测试记录。", "", Color(hex: "7B4DFF")),
                catalogMetric("sexualActivity", "性活动", "生理健康相关记录。", "", Color(hex: "20CDB1")),
                catalogMetric("symptoms", "症状", "身体症状记录。", "", Color(hex: "EF9A3D"))
            ]
        )
    ]

    private static let serverKnowledgeCandidates: [XAgeMetric] = [
        serverMetric("server-wbc", "白细胞", "血常规", "免疫与感染状态参考。", "×10^9/L", Color(hex: "F05B72")),
        serverMetric("server-rbc", "红细胞", "血常规", "携氧能力和贫血风险参考。", "×10^12/L", Color(hex: "DB5B9B")),
        serverMetric("server-hgb", "血红蛋白", "血常规", "贫血与携氧能力核心指标。", "g/L", Color(hex: "A47BEF")),
        serverMetric("server-plt", "血小板", "血常规", "凝血和炎症风险参考。", "×10^9/L", Color(hex: "7B4DFF")),
        serverMetric("server-alt", "谷丙转氨酶", "肝功能", "肝细胞损伤敏感指标。", "U/L", Color(hex: "EF9A3D")),
        serverMetric("server-ast", "谷草转氨酶", "肝功能", "肝脏、心肌和肌肉损伤参考。", "U/L", Color(hex: "F3B349")),
        serverMetric("server-tbil", "总胆红素", "肝功能", "肝胆代谢和黄疸风险参考。", "μmol/L", Color(hex: "EF9A3D")),
        serverMetric("server-alb", "白蛋白", "肝功能", "营养、肝合成和慢性病状态参考。", "g/L", Color(hex: "20CDB1")),
        serverMetric("server-ggt", "γ-谷氨酰转肽酶", "肝功能", "胆道和酒精相关肝负荷参考。", "U/L", Color(hex: "F3B349")),
        serverMetric("server-creatinine", "肌酐", "肾功能", "肾小球滤过能力参考。", "μmol/L", Color(hex: "238AD6")),
        serverMetric("server-bun", "尿素氮", "肾功能", "蛋白代谢、脱水和肾功能参考。", "mmol/L", Color(hex: "2A79C7")),
        serverMetric("server-uric-acid", "尿酸", "肾功能", "痛风和代谢风险参考。", "μmol/L", Color(hex: "7B4DFF")),
        serverMetric("server-tc", "总胆固醇", "血脂", "总体血脂水平。", "mmol/L", Color(hex: "EF9A3D")),
        serverMetric("server-tg", "甘油三酯", "血脂", "脂肪肝和心血管代谢风险参考。", "mmol/L", Color(hex: "F3B349")),
        serverMetric("server-hdl", "高密度脂蛋白", "血脂", "心血管保护性脂蛋白。", "mmol/L", Color(hex: "20CDB1")),
        serverMetric("server-ldl", "低密度脂蛋白", "血脂", "动脉粥样硬化风险核心指标。", "mmol/L", Color(hex: "F05B72")),
        serverMetric("server-fbg", "空腹血糖", "血糖", "空腹状态糖代谢参考。", "mmol/L", Color(hex: "11A7C8")),
        serverMetric("server-hba1c", "糖化血红蛋白", "血糖", "近 3 个月平均血糖水平。", "%", Color(hex: "238AD6")),
        serverMetric("server-2hpg", "餐后2小时血糖", "血糖", "餐后糖耐量参考。", "mmol/L", Color(hex: "2A79C7")),
        serverMetric("server-tsh", "促甲状腺激素", "甲状腺", "甲状腺功能调节核心指标。", "mIU/L", Color(hex: "7B4DFF")),
        serverMetric("server-ft3", "游离T3", "甲状腺", "活性甲状腺激素。", "pmol/L", Color(hex: "A47BEF")),
        serverMetric("server-ft4", "游离T4", "甲状腺", "甲状腺激素前体。", "pmol/L", Color(hex: "DB5B9B")),
        serverMetric("server-waist", "腰围", "体格", "中心性肥胖和代谢风险参考。", "cm", Color(hex: "EF9A3D")),
        serverMetric("server-cortisol", "皮质醇", "内分泌", "压力轴负荷参考。", "nmol/L", Color(hex: "F3B349")),
        serverMetric("server-hscrp", "hsCRP", "炎症", "低度炎症负荷参考。", "mg/L", Color(hex: "F05B72")),
        serverMetric("server-il6", "IL-6", "炎症", "炎症因子负荷参考。", "pg/mL", Color(hex: "DB5B9B"))
    ]

    private static func catalogMetric(_ id: String, _ title: String, _ subtitle: String, _ unit: String, _ accent: Color) -> XAgeMetric {
        let needsUpload = title.contains("血糖") || title.contains("血压") || title == "体温"
        return XAgeMetric(
            id: id,
            title: title,
            value: needsUpload ? "待上传" : "待同步",
            unit: "",
            time: needsUpload ? "待上传" : "待同步",
            subtitle: subtitle,
            accent: accent,
            source: "apple_health_catalog",
            isPlaceholder: true
        )
    }

    private static func serverMetric(_ id: String, _ title: String, _ category: String, _ subtitle: String, _ unit: String, _ accent: Color) -> XAgeMetric {
        XAgeMetric(
            id: id,
            title: title,
            value: "待上传",
            unit: unit,
            time: category,
            subtitle: "服务器指标库：\(subtitle)",
            accent: accent,
            source: "server_catalog",
            isPlaceholder: true
        )
    }

    private static func deduped(_ source: [XAgeMetric]) -> [XAgeMetric] {
        var seenIDs = Set<String>()
        var seenTitles = Set<String>()
        var result: [XAgeMetric] = []
        for metric in source {
            let title = metric.title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard !seenIDs.contains(metric.id), !seenTitles.contains(title) else { continue }
            seenIDs.insert(metric.id)
            seenTitles.insert(title)
            result.append(metric)
        }
        return result
    }

    static func appleHealthMetric(from sample: AppleHealthSyncSample) -> XAgeMetric? {
        let fallback = appleHealthCandidates.first { $0.id == sample.metricID }
        let defaultMetric = defaultCards.first { $0.id == sample.metricID }
        let base = fallback ?? defaultMetric
        guard let base else { return nil }
        let measuredAt = appleHealthISOFormatter.string(from: sample.measuredAt)
        return XAgeMetric(
            id: sample.metricID,
            title: sample.indicatorName,
            value: sample.displayValue,
            unit: sample.displayUnit,
            time: appleHealthTimeLabel(sample.measuredAt),
            subtitle: "\(sample.subtitle)，已同步到服务器并更新用户端趋势。",
            accent: base.accent,
            source: "apple_health",
            measuredAt: measuredAt
        )
    }

    private static func appleHealthTimeLabel(_ date: Date) -> String {
        if Calendar.current.isDateInToday(date) {
            return appleHealthTimeFormatter.string(from: date)
        }
        return appleHealthShortFormatter.string(from: date)
    }

    private static let appleHealthISOFormatter = ISO8601DateFormatter()

    private static let appleHealthShortFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日"
        return formatter
    }()

    private static let appleHealthTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "H:mm"
        return formatter
    }()
}

private extension XAgeMetric {
    var libraryIconName: String {
        switch id {
        case "steps": return "figure.walk"
        case "distance", "cyclingDistance", "wheelchairDistance": return "map.fill"
        case "exerciseMinutes", "activeMinutes", "mindfulMinutes": return "timer"
        case "activeEnergy", "basalEnergy", "dietaryEnergy": return "flame.fill"
        case "flights": return "figure.stairs"
        case "swimmingDistance", "swimmingStrokes": return "water.waves"
        case "vo2Max": return "lungs.fill"
        case "bodyHeight", "leanBodyMass": return "figure.stand"
        case "bodyWeight": return "scalemass.fill"
        case "bodyMassIndex", "bodyFat": return "percent"
        case "waistCircumference": return "ruler.fill"
        case "bodyTemperature", "basalBodyTemperature", "temp": return "thermometer.medium"
        case "heartRate", "restingHeartRate", "walkingHeartRateAverage": return "heart.fill"
        case "hrv", "heartRateRecovery": return "waveform.path.ecg"
        case "systolicBloodPressure", "diastolicBloodPressure": return "gauge"
        case "sleep", "sleepScore", "timeInBed": return "bed.double.fill"
        case "respiratoryRate", "inhalerUsage": return "lungs.fill"
        case "bloodOxygen": return "drop.fill"
        case "glucose", "bloodGlucose", "insulinDelivery": return "drop.triangle.fill"
        case "dietaryWater": return "drop.fill"
        case "dietaryCarbs", "dietaryProtein", "dietaryFat", "dietaryFiber", "dietaryCaffeine": return "fork.knife"
        case "daylight", "uvExposure": return "sun.max.fill"
        case "environmentalAudio", "headphoneAudio": return "ear.fill"
        case "menstrualFlow", "intermenstrualBleeding", "cervicalMucus", "ovulationTest", "sexualActivity": return "calendar.badge.clock"
        case "symptoms": return "cross.case.fill"
        default:
            if id.hasPrefix("server-") || source == "server_catalog" || source == "document" {
                return "cross.case.fill"
            }
            return "chart.line.uptrend.xyaxis"
        }
    }
}

private struct XAgeAppleHealthSyncCard: View {
    @ObservedObject var viewModel: AppleHealthSyncViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .shadow(color: Color(hex: "20CDB1").opacity(0.22), radius: 12, x: 0, y: 7)
                    Image(systemName: "heart.text.square.fill")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Apple 健康同步")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(viewModel.statusSubtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(2)
                        .minimumScaleFactor(0.84)
                }

                Spacer(minLength: 8)

                Button {
                    Task { await viewModel.requestAccessAndSync() }
                } label: {
                    Group {
                        if viewModel.isWorking {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Text(viewModel.lastSyncedAt == nil ? "授权" : "同步")
                                .font(.system(size: 14, weight: .bold))
                        }
                    }
                    .foregroundStyle(.white)
                    .frame(width: 62, height: 34)
                    .background(
                        Capsule()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                }
                .buttonStyle(.plain)
                .disabled(viewModel.isWorking)
                .accessibilityIdentifier("xage.appleHealth.sync.button")
            }

            HStack(spacing: 7) {
                XAgeSyncBadge(title: viewModel.statusTitle)
                if let response = viewModel.syncResponse {
                    XAgeSyncBadge(title: "\(response.inserted + response.updated) 项已写入")
                } else {
                    XAgeSyncBadge(title: "只读授权")
                }
                XAgeSyncBadge(title: "\(viewModel.samples.count) 项本地数据")
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeSyncBadge: View {
    let title: String

    var body: some View {
        Text(title)
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .lineLimit(1)
            .minimumScaleFactor(0.78)
            .frame(maxWidth: .infinity)
            .frame(height: 28)
            .background(XAgeCapsuleFill())
    }
}

private struct XAgeMetricCard: View {
    let card: XAgeMetric
    let sortMode: Bool
    let onOpen: () -> Void
    let onMoveUp: () -> Void
    let onMoveDown: () -> Void
    let onPin: () -> Void
    let onDelete: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [card.accent, Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 14, height: 14)
                Text(card.title)
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(card.accent)
                    .lineLimit(1)
                Spacer(minLength: 8)
                Text(card.time)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(card.isStale ? Color(hex: "EF9A3D") : Color(hex: "6A8198"))
                    .lineLimit(1)
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "A0B1C0"))
                    .frame(width: 14)
            }

            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(card.value)
                    .font(.system(size: card.value.count > 4 ? 27 : 31, weight: .bold))
                    .foregroundStyle(card.isPlaceholder ? Color(hex: "6C8194") : (card.isStale ? Color(hex: "496A83") : Color(hex: "101C2F")))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                if !card.unit.isEmpty {
                    Text(card.unit)
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Color(hex: "70879D"))
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }

            Text(card.subtitle)
                .font(.system(size: 12))
                .foregroundStyle(card.isStale ? Color(hex: "9A6A28") : Color(hex: "5D7890"))
                .lineSpacing(2)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            if sortMode {
                HStack(spacing: 8) {
                    CapsuleButton(title: "上移", action: onMoveUp)
                    CapsuleButton(title: "下移", action: onMoveDown)
                    Spacer()
                    XAgeMetricSortActionButton(title: "置顶", icon: "pin.fill", action: onPin)
                    XAgeMetricSortActionButton(title: "删除", icon: "trash", destructive: true, action: onDelete)
                }
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .contentShape(RoundedRectangle(cornerRadius: 24, style: .continuous))
        .onTapGesture {
            guard !sortMode else { return }
            onOpen()
        }
    }
}

private struct XAgeMetricSortActionButton: View {
    let title: String
    let icon: String
    var destructive = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .bold))
                Text(title)
                    .font(.system(size: 12, weight: .bold))
            }
            .foregroundStyle(destructive ? Color(hex: "C84755") : Color(hex: "237FC4"))
            .frame(width: 58, height: 30)
            .background(
                Capsule()
                    .fill(.white.opacity(0.54))
                    .background(.ultraThinMaterial, in: Capsule())
                    .overlay(Capsule().stroke(.white.opacity(0.86), lineWidth: 1))
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }
}

private struct XAgeSortDoneBar: View {
    let onDone: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "arrow.up.arrow.down")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(Color(hex: "237FC4"))
                .frame(width: 32, height: 32)
                .background(Circle().fill(.white.opacity(0.52)))

            VStack(alignment: .leading, spacing: 2) {
                Text("正在排序")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text("置顶、删除或调整顺序后点这里完成")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }

            Spacer(minLength: 6)

            Button(action: onDone) {
                HStack(spacing: 5) {
                    Image(systemName: "checkmark")
                        .font(.system(size: 12, weight: .black))
                    Text("完成排序")
                        .font(.system(size: 13, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(width: 104, height: 36)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("xage.data.sort.bottomDone")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .shadow(color: Color(hex: "7CCAF5").opacity(0.18), radius: 18, x: 0, y: 10)
    }
}

private struct XAgeAddMetricCard: View {
    let availableCount: Int
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                ZStack {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .shadow(color: Color(hex: "20CDB1").opacity(0.24), radius: 12, x: 0, y: 7)
                    Circle()
                        .stroke(.white.opacity(0.56), lineWidth: 1)
                        .frame(width: 32, height: 32)
                    Image(systemName: "plus")
                        .font(.system(size: 20, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 48, height: 48)

                VStack(alignment: .leading, spacing: 4) {
                    Text(availableCount == 0 ? "全部指标已添加" : "添加指标")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(availableCount == 0 ? "候选列表暂无新项目" : "从 Apple 健康和报告指标库中选择")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }

                Spacer(minLength: 8)

                Text(availableCount == 0 ? "完成" : "\(availableCount)项")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 56, height: 30)
                    .background(XAgeCapsuleFill())
            }
            .padding(.horizontal, 18)
            .frame(height: 88)
            .background(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .fill(.white.opacity(0.42))
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 24, style: .continuous)
                            .stroke(style: StrokeStyle(lineWidth: 1, dash: [7, 5]))
                            .foregroundStyle(.white.opacity(0.88))
                    )
                    .shadow(color: Color(hex: "73C8F0").opacity(0.14), radius: 22, x: 0, y: 12)
            )
        }
        .buttonStyle(.plain)
        .disabled(availableCount == 0)
        .opacity(availableCount == 0 ? 0.72 : 1)
    }
}

private struct XAgeMetricLibraryEntryCard: View {
    let availableCount: Int
    let totalCount: Int
    let onManage: () -> Void
    let onShowAll: () -> Void

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .shadow(color: Color(hex: "20CDB1").opacity(0.24), radius: 12, x: 0, y: 7)
                Circle()
                    .stroke(.white.opacity(0.58), lineWidth: 1)
                    .frame(width: 34, height: 34)
                Image(systemName: "list.bullet.rectangle.portrait.fill")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(.white)
            }
            .frame(width: 50, height: 50)

            VStack(alignment: .leading, spacing: 5) {
                Text("卡片管理")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text("\(totalCount) 项指标 · \(availableCount) 项可添加")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }

            Spacer(minLength: 8)

            VStack(spacing: 7) {
                Button(action: onManage) {
                    Text("编辑")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(.white)
                        .frame(width: 56, height: 30)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        )
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.metric.library.manage")

                Button(action: onShowAll) {
                    Text("全部")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .frame(width: 56, height: 30)
                        .background(XAgeCapsuleFill())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.metric.library.all")
                .accessibilityLabel("显示所有健康数据")
            }
        }
        .padding(.horizontal, 18)
        .frame(height: 94)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeMetricManagerSheet: View {
    @Binding var pinnedMetrics: [XAgeMetric]
    let catalogSections: [XAgeMetricCatalogSection]
    let onOpenMetric: (XAgeMetric) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var searchText = ""

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(spacing: 0) {
                XAgeMetricSheetHeader(
                    title: "编辑列表",
                    subtitle: "参照 Apple 健康：置顶、排序、解释和添加指标",
                    countText: "\(pinnedMetrics.count) 置顶",
                    closeIcon: "checkmark",
                    onClose: { dismiss() }
                )
                .padding(.horizontal, 24)
                .padding(.top, 22)
                .padding(.bottom, 12)

                XAgeMetricSearchField(text: $searchText, placeholder: "搜索指标")
                    .padding(.horizontal, 24)
                    .padding(.bottom, 12)
                    .accessibilityIdentifier("xage.metric.manager.search")

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        XAgeMetricSectionHeader(
                            title: "置顶",
                            subtitle: pinnedMetrics.isEmpty ? "点击下方加号把指标固定到数据页" : "使用箭头调整顺序，点击勾选取消置顶",
                            icon: "pin.fill",
                            accent: Color(hex: "238AD6")
                        )

                        if filteredPinnedMetrics.isEmpty {
                            XAgeMetricEmptyRow(
                                title: pinnedMetrics.isEmpty ? "还没有置顶指标" : "置顶中没有匹配项",
                                subtitle: pinnedMetrics.isEmpty ? "从下面的候选列表选择需要长期关注的项目。" : "换一个关键词再试。"
                            )
                        } else {
                            ForEach(filteredPinnedMetrics) { metric in
                                let actualIndex = pinnedMetrics.firstIndex(where: { $0.id == metric.id }) ?? 0
                                XAgeMetricPinnedManagerRow(
                                    metric: metric,
                                    canMoveUp: actualIndex > 0,
                                    canMoveDown: actualIndex < pinnedMetrics.count - 1,
                                    onOpen: { onOpenMetric(metric) },
                                    onUnpin: { unpin(metric) },
                                    onMoveUp: { moveMetric(from: actualIndex, by: -1) },
                                    onMoveDown: { moveMetric(from: actualIndex, by: 1) }
                                )
                                .id("pinned-\(metric.id)")
                                .accessibilityIdentifier("xage.metric.manager.pinned.\(metric.id)")
                            }
                        }

                        ForEach(filteredCandidateSections) { section in
                            XAgeMetricSectionHeader(
                                title: section.title,
                                subtitle: "\(section.metrics.count) 项可添加",
                                icon: section.icon,
                                accent: section.accent
                            )

                            ForEach(section.metrics) { metric in
                                XAgeMetricLibraryCandidateRow(
                                    metric: metric,
                                    isPinned: false,
                                    onOpen: { onOpenMetric(metric) },
                                    onTogglePinned: { pin(metric) }
                                )
                                .id("manager-candidate-\(metric.id)")
                                .accessibilityIdentifier("xage.metric.manager.candidate.\(metric.id)")
                            }
                        }

                        if filteredCandidateSections.isEmpty && !searchText.isEmpty {
                            XAgeMetricEmptyRow(title: "没有匹配的候选指标", subtitle: "已置顶项目会显示在上方；也可以打开全部指标查看。")
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.bottom, 30)
                }
                .scrollIndicators(.hidden)
            }
        }
    }

    private var pinnedIDs: Set<String> {
        Set(pinnedMetrics.map(\.id))
    }

    private var normalizedSearchText: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private var filteredPinnedMetrics: [XAgeMetric] {
        filter(pinnedMetrics)
    }

    private var filteredCandidateSections: [XAgeMetricCatalogSection] {
        catalogSections.compactMap { section in
            let metrics = filter(section.metrics.filter { !pinnedIDs.contains($0.id) })
            guard !metrics.isEmpty else { return nil }
            return XAgeMetricCatalogSection(title: section.title, icon: section.icon, accent: section.accent, metrics: metrics)
        }
    }

    private func filter(_ metrics: [XAgeMetric]) -> [XAgeMetric] {
        guard !normalizedSearchText.isEmpty else { return metrics }
        return metrics.filter { metric in
            [
                metric.title,
                metric.subtitle,
                metric.time,
                metric.unit
            ]
            .joined(separator: " ")
            .lowercased()
            .contains(normalizedSearchText)
        }
    }

    private func pin(_ metric: XAgeMetric) {
        guard !pinnedMetrics.contains(where: { $0.id == metric.id }) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            pinnedMetrics.append(metric)
        }
    }

    private func unpin(_ metric: XAgeMetric) {
        guard let index = pinnedMetrics.firstIndex(where: { $0.id == metric.id }) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            _ = pinnedMetrics.remove(at: index)
        }
    }

    private func moveMetric(from index: Int, by delta: Int) {
        let target = index + delta
        guard pinnedMetrics.indices.contains(index), pinnedMetrics.indices.contains(target) else { return }
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            pinnedMetrics.swapAt(index, target)
        }
    }
}

private struct XAgeAllMetricsSheet: View {
    let pinnedMetricIDs: Set<String>
    let catalogSections: [XAgeMetricCatalogSection]
    let onTogglePinned: (XAgeMetric) -> Void
    let onOpenMetric: (XAgeMetric) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var searchText = ""

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(spacing: 0) {
                XAgeMetricSheetHeader(
                    title: "所有健康数据",
                    subtitle: "Apple 健康项目和小捷服务器指标库",
                    countText: "\(filteredSections.reduce(0) { $0 + $1.metrics.count }) 项",
                    closeIcon: "xmark",
                    onClose: { dismiss() }
                )
                .padding(.horizontal, 24)
                .padding(.top, 22)
                .padding(.bottom, 12)

                XAgeMetricSearchField(text: $searchText, placeholder: "搜索所有指标")
                    .padding(.horizontal, 24)
                    .padding(.bottom, 12)
                    .accessibilityIdentifier("xage.metric.all.search")

                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        ForEach(filteredSections) { section in
                            XAgeMetricSectionHeader(
                                title: section.title,
                                subtitle: "\(section.metrics.count) 项",
                                icon: section.icon,
                                accent: section.accent
                            )

                            ForEach(section.metrics) { metric in
                                XAgeMetricLibraryCandidateRow(
                                    metric: metric,
                                    isPinned: pinnedMetricIDs.contains(metric.id),
                                    onOpen: { onOpenMetric(metric) },
                                    onTogglePinned: { onTogglePinned(metric) }
                                )
                                .id("all-\(section.id)-\(metric.id)")
                                .accessibilityIdentifier("xage.metric.all.\(metric.id)")
                            }
                        }

                        if filteredSections.isEmpty {
                            XAgeMetricEmptyRow(title: "没有匹配的指标", subtitle: "换一个关键词或返回编辑列表继续选择。")
                        }
                    }
                    .padding(.horizontal, 24)
                    .padding(.bottom, 30)
                }
                .scrollIndicators(.hidden)
            }
        }
    }

    private var normalizedSearchText: String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private var filteredSections: [XAgeMetricCatalogSection] {
        var seenIDs = Set<String>()
        var seenTitles = Set<String>()
        var result: [XAgeMetricCatalogSection] = []

        for section in catalogSections {
            let uniqueMetrics = section.metrics.filter { metric in
                let title = metric.title.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                guard !seenIDs.contains(metric.id), !seenTitles.contains(title) else { return false }
                seenIDs.insert(metric.id)
                seenTitles.insert(title)
                return true
            }
            let metrics = normalizedSearchText.isEmpty ? uniqueMetrics : uniqueMetrics.filter { metric in
                [
                    metric.title,
                    metric.subtitle,
                    metric.time,
                    metric.unit
                ]
                .joined(separator: " ")
                .lowercased()
                .contains(normalizedSearchText)
            }
            if !metrics.isEmpty {
                result.append(XAgeMetricCatalogSection(title: section.title, icon: section.icon, accent: section.accent, metrics: metrics))
            }
        }
        return result
    }
}

private struct XAgeMetricSheetHeader: View {
    let title: String
    let subtitle: String
    let countText: String
    let closeIcon: String
    let onClose: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 27, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }

            Spacer(minLength: 8)

            Text(countText)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "347FB7"))
                .frame(minWidth: 58)
                .padding(.horizontal, 10)
                .frame(height: 32)
                .background(XAgeCapsuleFill())

            Button(action: onClose) {
                Image(systemName: closeIcon)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "1268BD"))
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(closeIcon == "checkmark" ? "完成" : "关闭")
        }
    }
}

private struct XAgeMetricSearchField: View {
    @Binding var text: String
    let placeholder: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "6C8194"))
            TextField(placeholder, text: $text)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Color(hex: "173F64"))
                .textFieldStyle(.plain)
                .submitLabel(.search)
            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Color(hex: "8AA1B5"))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("清除搜索")
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 44)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeMetricSectionHeader: View {
    let title: String
    let subtitle: String
    let icon: String
    let accent: Color

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 26, height: 26)
                .background(Circle().fill(accent))
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(subtitle)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 4)
    }
}

private struct XAgeMetricPinnedManagerRow: View {
    let metric: XAgeMetric
    let canMoveUp: Bool
    let canMoveDown: Bool
    let onOpen: () -> Void
    let onUnpin: () -> Void
    let onMoveUp: () -> Void
    let onMoveDown: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onUnpin) {
                Image(systemName: "minus")
                    .font(.system(size: 12, weight: .black))
                    .foregroundStyle(.white)
                    .frame(width: 28, height: 28)
                    .background(
                        Circle()
                            .fill(Color(hex: "A9B8C5").opacity(0.82))
                            .overlay(Circle().stroke(.white.opacity(0.72), lineWidth: 1))
                    )
            }
            .buttonStyle(.plain)
            .accessibilityLabel("取消置顶\(metric.title)")

            XAgeMetricRoundIcon(metric: metric)
                .contentShape(Circle())
                .onTapGesture(perform: onOpen)

            VStack(alignment: .leading, spacing: 4) {
                Text(metric.title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(metric.subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }
            .contentShape(Rectangle())
            .onTapGesture(perform: onOpen)

            Spacer(minLength: 6)

            Button(action: onOpen) {
                Image(systemName: "info.circle")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(metric.accent)
                    .frame(width: 30, height: 30)
                    .background(Circle().fill(.white.opacity(0.5)))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(metric.title)解释")

            VStack(spacing: 4) {
                Button(action: onMoveUp) {
                    Image(systemName: "chevron.up")
                        .font(.system(size: 11, weight: .black))
                        .foregroundStyle(canMoveUp ? Color(hex: "347FB7") : Color(hex: "A9B8C5"))
                        .frame(width: 28, height: 20)
                        .background(Capsule().fill(.white.opacity(0.46)))
                }
                .buttonStyle(.plain)
                .disabled(!canMoveUp)
                .accessibilityLabel("上移\(metric.title)")

                Button(action: onMoveDown) {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 11, weight: .black))
                        .foregroundStyle(canMoveDown ? Color(hex: "347FB7") : Color(hex: "A9B8C5"))
                        .frame(width: 28, height: 20)
                        .background(Capsule().fill(.white.opacity(0.46)))
                }
                .buttonStyle(.plain)
                .disabled(!canMoveDown)
                .accessibilityLabel("下移\(metric.title)")
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 74)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeMetricLibraryCandidateRow: View {
    let metric: XAgeMetric
    let isPinned: Bool
    let onOpen: () -> Void
    let onTogglePinned: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: onTogglePinned) {
                Image(systemName: isPinned ? "checkmark" : "pin.fill")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(isPinned ? .white : metric.accent)
                    .frame(width: 30, height: 30)
                    .background(
                        Circle()
                            .fill(isPinned ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing)) : AnyShapeStyle(.white.opacity(0.56)))
                            .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                    )
            }
            .buttonStyle(.plain)
            .accessibilityLabel(isPinned ? "取消置顶\(metric.title)" : "置顶\(metric.title)")

            XAgeMetricRoundIcon(metric: metric)
                .contentShape(Circle())
                .onTapGesture(perform: onOpen)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(metric.title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(metric.time)
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(metric.accent)
                        .lineLimit(1)
                }
                Text(metric.subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }
            .contentShape(Rectangle())
            .onTapGesture(perform: onOpen)

            Spacer(minLength: 6)

            Button(action: onOpen) {
                Image(systemName: "info.circle")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(metric.accent)
                    .frame(width: 30, height: 30)
                    .background(Circle().fill(.white.opacity(0.5)))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(metric.title)详情")
        }
        .padding(.horizontal, 14)
        .frame(height: 72)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeMetricRoundIcon: View {
    let metric: XAgeMetric

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    LinearGradient(
                        colors: [metric.accent, Color(hex: "20CDB1")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .shadow(color: metric.accent.opacity(0.18), radius: 10, x: 0, y: 5)
            Image(systemName: metric.libraryIconName)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white)
        }
        .frame(width: 42, height: 42)
    }
}

private struct XAgeMetricEmptyRow: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(subtitle)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeMetricCandidateSheet: View {
    let metrics: [XAgeMetric]
    let onSelect: (XAgeMetric) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("添加指标")
                            .font(.system(size: 27, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                            .lineLimit(1)
                        Text("参照 Apple 健康可记录项目")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .lineLimit(1)
                    }

                    Spacer()

                    Text("\(metrics.count) 项")
                        .font(.system(size: 12, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .frame(width: 58, height: 32)
                        .background(XAgeCapsuleFill())

                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .frame(width: 34, height: 34)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("关闭")
                }

                if metrics.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        Text("已添加全部候选指标")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("主界面下拉列表已经包含所有候选项。")
                            .font(.system(size: 13))
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))
                    Spacer()
                } else {
                    ScrollView {
                        LazyVStack(spacing: 10) {
                            ForEach(metrics) { metric in
                                Button {
                                    onSelect(metric)
                                    dismiss()
                                } label: {
                                    XAgeMetricCandidateRow(metric: metric)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.data.metric.candidate.\(metric.id)")
                            }
                        }
                        .padding(.bottom, 20)
                    }
                    .scrollIndicators(.hidden)
                }
            }
            .padding(24)
        }
    }
}

}

private struct XAgeMetricCandidateRow: View {
    let metric: XAgeMetric

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [metric.accent, Color(hex: "20CDB1")],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .shadow(color: metric.accent.opacity(0.18), radius: 10, x: 0, y: 5)
                Image(systemName: iconName)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(.white)
            }
            .frame(width: 42, height: 42)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(metric.title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(metric.time)
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(metric.accent)
                        .lineLimit(1)
                }

                Text(metric.subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }

            Spacer(minLength: 8)

            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text(metric.value)
                    .font(.system(size: metric.value.count > 4 ? 18 : 20, weight: .bold))
                    .foregroundStyle(Color(hex: "12324F"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                if !metric.unit.isEmpty {
                    Text(metric.unit)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }
            }
            .frame(width: 66, alignment: .trailing)

            Image(systemName: "checkmark")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 30, height: 30)
                .background(
                    Circle()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        .overlay(Circle().stroke(.white.opacity(0.72), lineWidth: 1))
                )
        }
        .padding(.horizontal, 14)
        .frame(height: 72)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }

    private var iconName: String {
        switch metric.id {
        case "steps": return "figure.walk"
        case "distance": return "map.fill"
        case "activeEnergy": return "flame.fill"
        case "exerciseMinutes": return "timer"
        case "flights": return "figure.stairs"
        case "restingHeartRate": return "heart.fill"
        case "respiratoryRate": return "lungs.fill"
        case "bloodOxygen": return "drop.fill"
        case "systolicBloodPressure", "diastolicBloodPressure": return "gauge"
        case "bodyWeight": return "scalemass.fill"
        case "bodyFat": return "percent"
        case "mindfulMinutes": return "brain.head.profile"
        case "daylight": return "sun.max.fill"
        default: return "plus"
        }
    }
}

private struct XAgeMetricDetailSheet: View {
    let metric: XAgeMetric
    let onManualRecord: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                            Image(systemName: iconName)
                                .font(.system(size: 18, weight: .bold))
                                .foregroundStyle(.white)
                        }
                        .frame(width: 48, height: 48)

                        VStack(alignment: .leading, spacing: 4) {
                            Text(metric.title)
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                                .lineLimit(1)
                            Text(statusTitle)
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(statusColor)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 4)
                                .background(XAgeCapsuleFill())
                        }

                        Spacer()

                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 36, height: 36)
                                .background(XAgeCapsuleFill())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭\(metric.title)详情")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        HStack(alignment: .firstTextBaseline, spacing: 5) {
                            Text(metric.value)
                                .font(.system(size: metric.value.count > 4 ? 32 : 40, weight: .bold))
                                .foregroundStyle(metric.isPlaceholder ? Color(hex: "6C8194") : Color(hex: "101C2F"))
                                .lineLimit(1)
                                .minimumScaleFactor(0.72)
                            if !metric.unit.isEmpty {
                                Text(metric.unit)
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(Color(hex: "70879D"))
                            }
                            Spacer()
                        }
                        Text(metric.subtitle)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 10) {
                        XAgeMetricDetailRow(title: "数据来源", value: sourceLabel)
                        XAgeMetricDetailRow(title: "更新时间", value: updateLabel)
                        XAgeMetricDetailRow(title: "当前状态", value: statusTitle)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    Button {
                        onManualRecord()
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "square.and.pencil")
                                .font(.system(size: 15, weight: .bold))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("手动记录")
                                    .font(.system(size: 15, weight: .bold))
                                Text("录入后进入趋势，并刷新主界面")
                                    .font(.system(size: 11, weight: .medium))
                                    .opacity(0.86)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.system(size: 12, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .padding(.horizontal, 16)
                        .frame(height: 54)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                                .overlay(Capsule().stroke(.white.opacity(0.68), lineWidth: 1))
                        )
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.metric.manualEntry")
                    .accessibilityLabel("手动记录\(metric.title)")

                    Text(detailExplanation)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(statusColor)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }

    private var statusTitle: String {
        if metric.isPlaceholder { return metric.time.contains("上传") ? "待上传" : "暂无数据" }
        if metric.source == "server_indicator_catalog" { return "已入库" }
        if metric.isStale { return "需更新" }
        return "已同步"
    }

    private var statusColor: Color {
        if metric.isPlaceholder { return Color(hex: "6C8194") }
        if metric.isStale { return Color(hex: "EF9A3D") }
        return metric.accent
    }

    private var sourceLabel: String {
        switch (metric.source ?? "").lowercased() {
        case "apple_health": return "Apple 健康"
        case "apple_health_catalog": return "Apple 健康候选"
        case "manual": return "手动记录"
        case "device": return "设备同步"
        case "cgm": return "CGM"
        case "document": return "报告趋势"
        case "server_catalog": return "服务器指标库"
        case "server_indicator_catalog": return "服务器已入库指标"
        default: return metric.isPlaceholder ? "暂无" : "服务端趋势"
        }
    }

    private var updateLabel: String {
        if let measuredAt = metric.measuredAt {
            return XAgeServerSyncFormat.shortDate(measuredAt)
        }
        return metric.time
    }

    private var detailExplanation: String {
        if metric.isPlaceholder {
            if metric.source == "apple_health_catalog" {
                return "这是 Apple 健康可记录项目。完成授权同步后，小捷会按测量时间读取最新值；没有 Apple 健康数据时，也可以手动记录。"
            }
            if metric.source == "server_catalog" {
                return "这是服务器指标库候选项。上传报告或手动记录后，小捷会把该指标写入趋势，并用最新有效值更新数据页。"
            }
            return "当前没有这个指标的有效数据；同步 Apple 健康、手动记录或上传报告后，主界面会用真实数值替换占位。"
        }
        if metric.source == "server_indicator_catalog" {
            return "这个指标已经存在服务器历史记录。置顶后先展示历史点数量；上传报告、Apple 健康同步或手动记录产生新值后，数据页会按最新测量时间更新。"
        }
        if metric.isStale {
            return "这条数据已超过当前指标的时效窗口，保留为历史参考，不作为最新状态展示。"
        }
        return "这条数据来自\(sourceLabel)，按测量时间进入趋势，并用于当前数据页展示。"
    }

    private var iconName: String {
        metric.libraryIconName
    }
}

private struct XAgeManualMetricEntrySheet: View {
    let metric: XAgeMetric
    let onSaved: () -> Void
    @StateObject private var vm = ManualIndicatorViewModel()
    @State private var indicatorName: String
    @State private var valueText = ""
    @State private var unitText: String
    @State private var measuredAt = Date()
    @State private var notes = ""
    @Environment(\.dismiss) private var dismiss

    init(metric: XAgeMetric, onSaved: @escaping () -> Void) {
        self.metric = metric
        self.onSaved = onSaved
        _indicatorName = State(initialValue: metric.title)
        _unitText = State(initialValue: metric.unit)
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                            Image(systemName: "square.and.pencil")
                                .font(.system(size: 18, weight: .bold))
                                .foregroundStyle(.white)
                        }
                        .frame(width: 48, height: 48)

                        VStack(alignment: .leading, spacing: 3) {
                            Text("手动记录")
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            Text("保存后进入用户端趋势")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }

                        Spacer()

                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 36, height: 36)
                                .background(XAgeCapsuleFill())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭手动记录")
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        XAgeManualMetricTextField(title: "指标", placeholder: "指标名称", text: $indicatorName)
                        XAgeManualMetricTextField(title: "数值", placeholder: "例如 120", text: $valueText, keyboardType: .decimalPad)
                        XAgeManualMetricTextField(title: "单位", placeholder: "可选", text: $unitText)
                        DatePicker("测量时间", selection: $measuredAt, in: ...Date(), displayedComponents: [.date, .hourAndMinute])
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                            .padding(.horizontal, 14)
                            .frame(height: 52)
                            .background(XAgeCapsuleFill())
                        XAgeManualMetricTextField(title: "备注", placeholder: "可选", text: $notes)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    Text("手动记录会标记为“手动记录”来源。Apple 健康同日同步到同一指标时，会按来源和测量时间合并，主界面始终显示当前最有效的数据。")
                        .font(.system(size: 13))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())

                    Button {
                        Task { await save() }
                    } label: {
                        HStack(spacing: 8) {
                            if vm.saving {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(vm.saving ? "保存中" : "保存记录")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(!canSave || vm.saving)
                    .opacity(!canSave || vm.saving ? 0.55 : 1)
                    .accessibilityIdentifier("xage.metric.manualEntry.save")
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
        .onChange(of: vm.savedOk) { _, saved in
            guard saved else { return }
            onSaved()
        }
        .alert("保存失败", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    private var canSave: Bool {
        !indicatorName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && parsedValue != nil
    }

    private var parsedValue: Double? {
        Double(valueText.replacingOccurrences(of: "，", with: ".").trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private func save() async {
        guard let value = parsedValue else { return }
        let trimmedUnit = unitText.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedNotes = notes.trimmingCharacters(in: .whitespacesAndNewlines)
        await vm.submit(
            indicatorName: indicatorName.trimmingCharacters(in: .whitespacesAndNewlines),
            value: value,
            unit: trimmedUnit.isEmpty ? nil : trimmedUnit,
            measuredAt: measuredAt,
            notes: trimmedNotes.isEmpty ? nil : trimmedNotes
        )
    }
}

private struct XAgeManualMetricTextField: View {
    let title: String
    let placeholder: String
    @Binding var text: String
    var keyboardType: UIKeyboardType = .default

    var body: some View {
        HStack(spacing: 12) {
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "5D7890"))
                .frame(width: 54, alignment: .leading)
            TextField(placeholder, text: $text)
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .keyboardType(keyboardType)
                .textFieldStyle(.plain)
                .multilineTextAlignment(.trailing)
        }
        .padding(.horizontal, 14)
        .frame(height: 52)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeMetricDetailRow: View {
    let title: String
    let value: String

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color(hex: "5D7890"))
            Spacer(minLength: 12)
            Text(value)
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "17324E"))
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .padding(11)
        .background(XAgeCapsuleFill())
    }
}

private enum XAgeDataPanelCategory: String, CaseIterable, Identifiable, Hashable {
    case reports = "报告"
    case daily = "日常"
    case medical = "就医"
    case profile = "画像"

    var id: String {
        switch self {
        case .reports: return "reports"
        case .daily: return "daily"
        case .medical: return "medical"
        case .profile: return "profile"
        }
    }

    var headline: String {
        switch self {
        case .reports: return "报告入库"
        case .daily: return "日常同步"
        case .medical: return "就医整理"
        case .profile: return "健康画像"
        }
    }

    var subtitle: String {
        switch self {
        case .reports: return "体检、化验、影像"
        case .daily: return "睡眠、步数、HRV"
        case .medical: return "诊断、处方、随访"
        case .profile: return "基础、慢病、过敏"
        }
    }

    var actionTitle: String {
        switch self {
        case .reports: return "上传"
        case .daily: return "查看"
        case .medical: return "整理"
        case .profile: return "完善"
        }
    }

    var iconName: String {
        switch self {
        case .reports: return "doc.text.fill"
        case .daily: return "waveform.path.ecg"
        case .medical: return "cross.case.fill"
        case .profile: return "person.text.rectangle.fill"
        }
    }

    var gradient: [Color] {
        switch self {
        case .reports: return [Color(hex: "238AD6"), Color(hex: "20CDB1")]
        case .daily: return [Color(hex: "18B7D6"), Color(hex: "34D6A6")]
        case .medical: return [Color(hex: "4E8FE9"), Color(hex: "7BD5F1")]
        case .profile: return [Color(hex: "2A79C7"), Color(hex: "6EE4C6")]
        }
    }

    var detailSummary: String {
        switch self {
        case .reports: return "把体检、化验和影像资料先入库，小捷会在后台识别结构化字段，并提示缺失项。"
        case .daily: return "聚合睡眠、步数、HRV 和训练负荷，用来解释当天压力、恢复和炎症评分变化。"
        case .medical: return "把诊断、处方和随访整理成连续时间线，方便下一次问诊前快速回顾。"
        case .profile: return "维护基础资料、慢病、过敏和长期用药，让问答和计划生成更贴近个人状态。"
        }
    }

    var rows: [XAgePanelRow] {
        switch self {
        case .reports:
            return [
                XAgePanelRow(icon: "arrow.up.doc.fill", title: "数据上传", subtitle: "体检报告、化验单、影像截图"),
                XAgePanelRow(icon: "doc.text.magnifyingglass", title: "AI 识别队列", subtitle: "抽取指标、异常值和参考范围"),
                XAgePanelRow(icon: "clock.arrow.circlepath", title: "历史报告", subtitle: "单份摘要、异常项和原始资料"),
                XAgePanelRow(icon: "checkmark.seal.fill", title: "需要确认", subtitle: "核对姓名、日期和关键指标")
            ]
        case .daily:
            return [
                XAgePanelRow(icon: "heart.text.square.fill", title: "Apple Health", subtitle: "同步睡眠、步数、静息心率"),
                XAgePanelRow(icon: "waveform.path.ecg", title: "恢复信号", subtitle: "HRV、呼吸率和训练负荷"),
                XAgePanelRow(icon: "chart.line.uptrend.xyaxis", title: "趋势解释", subtitle: "连接日常变化与三项评分")
            ]
        case .medical:
            return [
                XAgePanelRow(icon: "list.clipboard.fill", title: "诊断摘要", subtitle: "按科室和时间整理病程"),
                XAgePanelRow(icon: "pills.fill", title: "处方核对", subtitle: "剂量、频次和注意事项"),
                XAgePanelRow(icon: "calendar.badge.clock", title: "随访提醒", subtitle: "复诊、复查和报告回传")
            ]
        case .profile:
            return [
                XAgePanelRow(icon: "person.fill", title: "基础资料", subtitle: "年龄、身高、体重和目标"),
                XAgePanelRow(icon: "tag.fill", title: "长期标签", subtitle: "慢病、家族史和风险因素"),
                XAgePanelRow(icon: "exclamationmark.shield.fill", title: "安全信息", subtitle: "过敏、禁忌和长期用药")
            ]
        }
    }
}

private struct XAgePanelStat: Identifiable {
    var id: String { title }
    let title: String
    let value: String
    let unit: String
}

private struct XAgePanelRow: Identifiable {
    var id: String { title }
    let icon: String
    let title: String
    let subtitle: String

    var key: String {
        switch title {
        case "数据上传", "拍照上传": return "upload"
        case "AI 识别队列": return "recognition"
        case "历史报告": return "history"
        case "需要确认": return "confirm"
        case "Apple Health": return "apple-health"
        case "恢复信号": return "recovery"
        case "趋势解释": return "trend"
        case "诊断摘要": return "diagnosis"
        case "处方核对": return "prescription"
        case "随访提醒": return "follow-up"
        case "基础资料": return "basic"
        case "长期标签": return "tags"
        case "安全信息": return "safety"
        default: return title
        }
    }
}

private struct XAgePanelCategoryGlyph: View {
    let category: XAgeDataPanelCategory
    let selected: Bool

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    selected
                    ? AnyShapeStyle(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                    : AnyShapeStyle(Color(hex: "B8DFF5").opacity(0.3))
                )
                .overlay(Circle().stroke(.white.opacity(selected ? 0.84 : 0.58), lineWidth: 0.8))

            glyph
                .foregroundStyle(selected ? .white : Color(hex: "347FB7"))
        }
        .accessibilityHidden(true)
    }

    @ViewBuilder
    private var glyph: some View {
        switch category {
        case .reports:
            VStack(spacing: 1.6) {
                ForEach([8.0, 5.8, 7.2], id: \.self) { width in
                    RoundedRectangle(cornerRadius: 1.2, style: .continuous)
                        .frame(width: width, height: 1.8)
                }
            }
        case .daily:
            HStack(alignment: .bottom, spacing: 1.5) {
                ForEach([5.0, 9.0, 6.0, 11.0], id: \.self) { height in
                    RoundedRectangle(cornerRadius: 1.2, style: .continuous)
                        .frame(width: 2, height: height)
                }
            }
        case .medical:
            Image(systemName: "cross.fill")
                .font(.system(size: 8.5, weight: .bold))
        case .profile:
            Image(systemName: "checkmark")
                .font(.system(size: 8.5, weight: .bold))
        }
    }
}

private struct XAgePanelHeroAsset: View {
    let category: XAgeDataPanelCategory

    var body: some View {
        ZStack {
            Circle()
                .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                .shadow(color: category.gradient.last?.opacity(0.24) ?? Color(hex: "20CDB1").opacity(0.24), radius: 12, x: 0, y: 7)
            Circle()
                .stroke(.white.opacity(0.42), lineWidth: 1)
                .frame(width: 34, height: 34)
            XAgePanelCategoryGlyph(category: category, selected: true)
                .frame(width: 24, height: 24)
            Image(systemName: category.iconName)
                .font(.system(size: 9, weight: .black))
                .foregroundStyle(.white.opacity(0.92))
                .offset(x: 12, y: -12)
        }
        .frame(width: 48, height: 48)
        .accessibilityHidden(true)
    }
}

private enum XAgeReportUploadAction {
    case camera
    case document
    case photoLibrary
}

private struct XAgeReportUploadFile: Identifiable, Equatable {
    let id = UUID()
    let data: Data
    let fileName: String

    var previewImage: UIImage? {
        UIImage(data: data)
    }
}

private struct XAgePendingReportUpload: Identifiable, Equatable {
    let id = UUID()
    let title: String
    let source: String
    let files: [XAgeReportUploadFile]

    var totalSizeText: String {
        let totalBytes = files.reduce(0) { $0 + $1.data.count }
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = totalBytes >= 1_000_000 ? [.useMB] : [.useKB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: Int64(totalBytes))
    }
}

private struct XAgePanelDestinationView: View {
    let category: XAgeDataPanelCategory
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    var onClose: (() -> Void)?
    @Environment(\.dismiss) private var dismiss
    @StateObject private var reportUploadVM = HealthDataViewModel()
    @State private var selectedRowID: String?
    @State private var completedActionIDs: Set<String> = []
    @State private var selectedTagIDs: Set<String> = []
    @State private var primaryActionCount = 0
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showDocumentPicker = false
    @State private var showReportUploadOptions = false
    @State private var showReportHistory = false
    @State private var pendingUpload: XAgePendingReportUpload?
    @State private var uploadQualityWarning: String?

    private var activeRow: XAgePanelRow {
        category.rows.first { $0.id == selectedRowID } ?? category.rows[0]
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 16) {
                    header
                        .padding(.top, 18)

                    VStack(alignment: .leading, spacing: 16) {
                        HStack(spacing: 14) {
                            XAgePanelHeroAsset(category: category)
                                .frame(width: 62, height: 62)
                            VStack(alignment: .leading, spacing: 5) {
                                Text(category.headline)
                                    .font(.system(size: 27, weight: .bold))
                                    .foregroundStyle(Color(hex: "123E67"))
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.82)
                                Text(category.subtitle)
                                    .font(.system(size: 14, weight: .semibold))
                                    .foregroundStyle(Color(hex: "5D7890"))
                                    .lineLimit(1)
                            }
                            Spacer(minLength: 0)
                        }

                        Text(category.detailSummary)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    HStack(spacing: 9) {
                        ForEach(snapshot.stats(for: category)) { stat in
                            VStack(spacing: 5) {
                                Text(stat.title)
                                    .font(.system(size: 11, weight: .bold))
                                    .foregroundStyle(Color(hex: "6C8194"))
                                    .lineLimit(1)
                                HStack(alignment: .firstTextBaseline, spacing: 2) {
                                    Text(stat.value)
                                        .font(.system(size: 20, weight: .bold))
                                        .foregroundStyle(Color(hex: "12324F"))
                                        .lineLimit(1)
                                        .minimumScaleFactor(0.76)
                                    if !stat.unit.isEmpty {
                                        Text(stat.unit)
                                            .font(.system(size: 10, weight: .semibold))
                                            .foregroundStyle(Color(hex: "6C8194"))
                                    }
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .frame(height: 70)
                            .background(XAgeGlassCardBackground(cornerRadius: 22))
                        }
                    }

                    VStack(spacing: 10) {
                        ForEach(category.rows) { row in
                            let isSelected = activeRow.id == row.id
                            if category == .daily && row.title == "Apple Health" {
                                Button {
                                    select(row)
                                    Task { await appleHealthSync.requestAccessAndSync() }
                                } label: {
                                    XAgePanelActionRow(
                                        category: category,
                                        row: row,
                                        trailingTitle: appleHealthSync.isWorking ? nil : appleHealthSync.statusTitle,
                                        showsProgress: appleHealthSync.isWorking,
                                        isSelected: isSelected
                                    )
                                }
                                .buttonStyle(.plain)
                                .disabled(appleHealthSync.isWorking)
                                .accessibilityIdentifier("xage.appleHealth.destination.sync")
                            } else {
                                Button {
                                    select(row)
                                } label: {
                                    XAgePanelActionRow(
                                        category: category,
                                        row: row,
                                        trailingTitle: isSelected ? "查看中" : nil,
                                        isSelected: isSelected
                                    )
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.panel.\(category.id).row.\(row.key)")
                            }

                            if isSelected {
                                XAgePanelInteractiveDetail(
                                    category: category,
                                    row: activeRow,
                                    appleHealthSync: appleHealthSync,
                                    snapshot: snapshot,
                                    completedActionIDs: $completedActionIDs,
                                    selectedTagIDs: $selectedTagIDs,
                                    primaryActionCount: $primaryActionCount,
                                    onReportUploadAction: handleReportUploadAction,
                                    onReportHistoryAction: { showReportHistory = true }
                                )
                                .transition(.opacity.combined(with: .move(edge: .top)))
                            }
                        }
                    }

                    if category == .reports,
                       reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil {
                        XAgeChatUploadStatusCard(
                            uploading: reportUploadVM.uploading,
                            title: reportUploadVM.uploading
                                ? (reportUploadVM.uploadStage.isEmpty ? "正在上传报告…" : reportUploadVM.uploadStage)
                                : "报告已上传，AI 正在识别",
                            subtitle: reportUploadVM.backgroundTaskHint ?? "完成后会继续写入用户端数据。"
                        )
                        .accessibilityIdentifier("xage.panel.reports.upload.status")
                    }

                }
                .padding(.horizontal, 24)
                .padding(.bottom, 18)
            }
            .safeAreaInset(edge: .bottom) {
                primaryActionButton
                    .padding(.horizontal, 24)
                    .padding(.top, 8)
                    .padding(.bottom, 12)
                    .background(
                        LinearGradient(
                            colors: [
                                Color(hex: "E9F8FF").opacity(0),
                                Color(hex: "E9F8FF").opacity(0.92)
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                        .ignoresSafeArea()
                    )
            }
        }
        .navigationBarBackButtonHidden(true)
        .toolbar(.hidden, for: .navigationBar)
        .fullScreenCover(isPresented: $showCamera) {
            CameraImagePicker(
                onPick: { data, name in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: name)],
                        title: "确认数据上传",
                        source: "相机"
                    )
                },
                fileNamePrefix: "xage_panel_report_camera"
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $showPhotoLibrary) {
            MultiPhotoPicker(
                selectionLimit: 9,
                fileNamePrefix: "xage_panel_report_album",
                onPick: { photos in
                    preparePendingReportUpload(
                        files: photos.map { XAgeReportUploadFile(data: $0.data, fileName: $0.fileName) },
                        title: photos.count > 1 ? "确认上传 \(photos.count) 张照片" : "确认相册上传",
                        source: "相册"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $showDocumentPicker) {
            DocumentPickerView(
                onPick: { data, fileName in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: fileName)],
                        title: "确认上传文件",
                        source: "文件"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $showReportUploadOptions) {
            XAgeReportUploadSourceSheet(
                onCamera: { presentReportUploadActionFromOptions(.camera) },
                onDocument: { presentReportUploadActionFromOptions(.document) },
                onPhotoLibrary: { presentReportUploadActionFromOptions(.photoLibrary) }
            )
            .presentationDetents([.height(330)])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showReportHistory) {
            XAgeReportHistorySheet()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $pendingUpload) { upload in
            XAgeReportUploadConfirmSheet(
                upload: upload,
                isUploading: reportUploadVM.uploading,
                onCancel: { pendingUpload = nil },
                onConfirm: {
                    pendingUpload = nil
                    uploadReports(upload.files)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .alert("拍摄质量不足", isPresented: Binding(
            get: { uploadQualityWarning != nil },
            set: { if !$0 { uploadQualityWarning = nil } }
        )) {
            Button("重新拍摄") { uploadQualityWarning = nil; showCamera = true }
            Button("取消", role: .cancel) { uploadQualityWarning = nil }
        } message: {
            Text(uploadQualityWarning ?? "")
        }
        .alert("上传提示", isPresented: Binding(
            get: { reportUploadVM.infoMessage != nil },
            set: { if !$0 { reportUploadVM.infoMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(reportUploadVM.infoMessage ?? "")
        }
        .alert("上传失败", isPresented: Binding(
            get: { reportUploadVM.errorMessage != nil },
            set: { if !$0 { reportUploadVM.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(reportUploadVM.errorMessage ?? "")
        }
    }

    private var primaryActionButton: some View {
        Button {
            runPrimaryAction()
        } label: {
            Text(primaryButtonTitle)
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 46)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .shadow(color: (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.22), radius: 12, x: 0, y: 7)
                )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("xage.panel.\(category.id).primary")
    }

    private var primaryButtonTitle: String {
        switch category {
        case .reports:
            switch activeRow.key {
            case "upload": return "开始入库"
            case "history": return "查看历史报告"
            case "recognition": return "刷新识别状态"
            default: return "确认并入库"
            }
        case .daily:
            return activeRow.title == "Apple Health" ? "同步日常数据" : "更新日常解释"
        case .medical:
            return activeRow.title == "随访提醒" ? "保存提醒" : "整理到时间线"
        case .profile:
            return activeRow.title == "安全信息" ? "保存安全信息" : "保存画像"
        }
    }

    private func select(_ row: XAgePanelRow) {
        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            selectedRowID = row.id
        }
    }

    private func runPrimaryAction() {
        let row = activeRow
        if category == .reports {
            switch row.key {
            case "upload":
                showReportUploadOptions = true
                return
            case "history":
                showReportHistory = true
                return
            case "recognition":
                Task { await reportUploadVM.fetchAll() }
            default:
                break
            }
        }

        if category == .daily && row.title == "Apple Health" {
            Task { await appleHealthSync.requestAccessAndSync() }
            return
        }

        withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
            completedActionIDs.insert("primary-\(category.id)-\(row.key)-\(primaryActionCount)")
            primaryActionCount += 1
        }
    }

    private func runHeaderAction() {
        if category == .reports {
            showReportUploadOptions = true
            return
        }
        runPrimaryAction()
    }

    private func handleReportUploadAction(_ action: XAgeReportUploadAction) {
        guard category == .reports else { return }
        switch action {
        case .camera:
            showCamera = true
        case .document:
            showDocumentPicker = true
        case .photoLibrary:
            showPhotoLibrary = true
        }
    }

    private func presentReportUploadActionFromOptions(_ action: XAgeReportUploadAction) {
        showReportUploadOptions = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.28) {
            handleReportUploadAction(action)
        }
    }

    private func preparePendingReportUpload(files: [XAgeReportUploadFile], title: String, source: String) {
        guard !files.isEmpty else { return }
        for file in files {
            if let warning = validateReportImageQuality(data: file.data, fileName: file.fileName) {
                uploadQualityWarning = "\(file.fileName)：\(warning)"
                return
            }
        }
        let upload = XAgePendingReportUpload(title: title, source: source, files: files)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            pendingUpload = upload
        }
    }

    private func uploadReports(_ files: [XAgeReportUploadFile]) {
        guard !files.isEmpty else { return }
        reportUploadVM.uploadDocType = "exam"
        Task {
            var successCount = 0
            for file in files {
                if await reportUploadVM.uploadFile(data: file.data, fileName: file.fileName) != nil {
                    successCount += 1
                }
            }
            if successCount > 0 {
                withAnimation(.spring(response: 0.24, dampingFraction: 0.88)) {
                    completedActionIDs.insert("reports-upload-success-\(primaryActionCount)")
                    primaryActionCount += 1
                }
            }
        }
    }

    private func validateReportImageQuality(data: Data, fileName: String) -> String? {
        let lower = fileName.lowercased()
        let isImage = [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"].contains { lower.hasSuffix($0) }
        guard isImage else { return nil }
        if data.count < 30 * 1024 {
            return "图片过小（小于 30KB），可能不是完整报告。请重新拍摄。"
        }
        if let img = UIImage(data: data) {
            let shortEdge = min(img.size.width, img.size.height) * img.scale
            if shortEdge < 600 {
                return "图片分辨率过低（短边 \(Int(shortEdge))px），识别可能失败。请重新拍摄。"
            }
        } else {
            return "未能读取图片数据，请重新拍摄或选择 PDF。"
        }
        return nil
    }

    private var header: some View {
        HStack {
            Button {
                if let onClose {
                    onClose()
                } else {
                    dismiss()
                }
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 42, height: 34)
                    .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("返回")

            Spacer()

            Text(category.rawValue)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "123E67"))
                .frame(height: 34)
                .padding(.horizontal, 18)
                .background(XAgeCapsuleFill())

            Spacer()

            Button {
                runHeaderAction()
            } label: {
                Image(systemName: category.iconName)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 42, height: 34)
                    .background(
                        Capsule()
                            .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                            .overlay(Capsule().stroke(.white.opacity(0.72), lineWidth: 1))
                    )
            }
            .buttonStyle(.plain)
            .accessibilityLabel(category == .reports ? "上传报告" : "\(category.rawValue)快捷操作")
        }
    }
}

private struct XAgePanelInteractiveDetail: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    @Binding var completedActionIDs: Set<String>
    @Binding var selectedTagIDs: Set<String>
    @Binding var primaryActionCount: Int
    let onReportUploadAction: (XAgeReportUploadAction) -> Void
    let onReportHistoryAction: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(row.title)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(detailSubtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(2)
                }
                Spacer(minLength: 10)
                Text(primaryActionCount > 0 ? "已更新" : "可编辑")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 62, height: 28)
                    .background(XAgeCapsuleFill())
            }

            content
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
        .accessibilityIdentifier("xage.panel.\(category.id).detail.\(row.key)")
    }

    private var detailSubtitle: String {
        switch category {
        case .reports:
            return "选择入口、检查识别队列，并确认关键报告字段。"
        case .daily:
            return "把可穿戴与日常信号转成今天的压力、恢复、炎症解释。"
        case .medical:
            return "把就医资料整理成时间线、处方核对和复查提醒。"
        case .profile:
            return "维护画像信息，让问答、计划和风险提示更贴近个人状态。"
        }
    }

    @ViewBuilder
    private var content: some View {
        switch category {
        case .reports:
            reportsContent
        case .daily:
            dailyContent
        case .medical:
            medicalContent
        case .profile:
            profileContent
        }
    }

    @ViewBuilder
    private var reportsContent: some View {
        if row.key == "upload" {
            HStack(spacing: 9) {
                chip("拍照", icon: "camera.fill") { onReportUploadAction(.camera) }
                chip("选 PDF", icon: "doc.fill") { onReportUploadAction(.document) }
                chip("相册", icon: "photo.fill") { onReportUploadAction(.photoLibrary) }
            }
            toggleRow("姓名与报告一致", subtitle: "未匹配时会进入人工确认", key: "name")
            toggleRow("最近报告 \(snapshot.latestDocumentLabel)", subtitle: "用于排列时间线和趋势", key: "date")
            toggleRow("\(snapshot.indicatorCount) 项指标已入库", subtitle: "新增报告确认后会继续写入用户端数据", key: "indicators")
        } else if row.key == "recognition" {
            progressLine("病历资料", value: progress(snapshot.recordCount, cap: 20), trailing: "\(snapshot.recordCount) 份")
            progressLine("体检化验", value: progress(snapshot.examCount, cap: 300), trailing: "\(snapshot.examCount) 份")
            progressLine("指标趋势", value: progress(snapshot.indicatorCount, cap: 300), trailing: "\(snapshot.indicatorCount) 项")
            HStack(spacing: 9) {
                chip("仅异常", icon: "exclamationmark.triangle.fill")
                chip("全部字段", icon: "list.bullet.rectangle")
            }
        } else if row.key == "history" {
            Button(action: onReportHistoryAction) {
                HStack(spacing: 10) {
                    Image(systemName: "clock.arrow.circlepath")
                        .font(.system(size: 15, weight: .bold))
                    VStack(alignment: .leading, spacing: 2) {
                        Text("打开历史报告")
                            .font(.system(size: 13, weight: .bold))
                        Text("查看已上传报告、病历和单份 AI 摘要")
                            .font(.system(size: 11, weight: .medium))
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12, weight: .bold))
                }
                .foregroundStyle(Color(hex: "347FB7"))
                .padding(.horizontal, 12)
                .frame(height: 52)
                .background(XAgeCapsuleFill())
            }
            .buttonStyle(.plain)
            progressLine("历史报告", value: progress(snapshot.examCount, cap: 30), trailing: "\(snapshot.examCount) 份")
            progressLine("历史病历", value: progress(snapshot.recordCount, cap: 20), trailing: "\(snapshot.recordCount) 份")
            toggleRow("单份报告摘要", subtitle: "识别完成后显示关键指标、异常项和入库状态", key: "single-summary")
        } else {
            toggleRow(snapshot.primaryWatchedLabel, subtitle: "\(snapshot.trendPointCount) 个历史趋势点可用于复核", key: "watched")
            toggleRow("健康摘要", subtitle: snapshot.hasSummary ? "已生成，可作为问答上下文" : "暂无摘要，建议生成后再问答", key: "summary")
            toggleRow("报告日期 \(snapshot.latestDocumentLabel)", subtitle: "确认后会用于排序", key: "report-date")
        }
    }

    @ViewBuilder
    private var dailyContent: some View {
        if row.title == "Apple Health" {
            Text(appleHealthSync.statusSubtitle)
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                badge(appleHealthSync.statusTitle)
                badge("\(appleHealthSync.samples.count) 项")
                badge("只读授权")
            }
            Button {
                Task { await appleHealthSync.requestAccessAndSync() }
            } label: {
                HStack(spacing: 8) {
                    if appleHealthSync.isWorking {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .font(.system(size: 13, weight: .bold))
                    }
                    Text(appleHealthSync.isWorking ? "同步中" : "立即同步")
                        .font(.system(size: 13, weight: .bold))
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 38)
                .background(
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing))
                )
            }
            .buttonStyle(.plain)
            .disabled(appleHealthSync.isWorking)
            .accessibilityIdentifier("xage.panel.daily.detail.appleHealth.sync")
        } else if row.title == "恢复信号" {
            progressLine("关注指标", value: progress(snapshot.watchedIndicatorCount, cap: 8), trailing: "\(snapshot.watchedIndicatorCount) 项")
            progressLine("历史趋势", value: progress(snapshot.trendPointCount, cap: 60), trailing: "\(snapshot.trendPointCount) 点")
            progressLine("今日目标", value: progress(snapshot.todayGoalCount, cap: 5), trailing: "\(snapshot.todayGoalCount) 条")
            HStack(spacing: 9) {
                chip("用于恢复", icon: "heart.fill")
                chip("加入压力解释", icon: "bolt.heart.fill")
            }
        } else {
            toggleRow("关注 \(snapshot.primaryWatchedLabel)", subtitle: "已同步服务端关注指标", key: "watched")
            toggleRow("趋势点 \(snapshot.trendPointCount)", subtitle: "用于解释日常变化与评分", key: "trend-points")
            toggleRow("健康摘要", subtitle: snapshot.hasSummary ? "已接入问答上下文" : "等待生成摘要", key: "daily-summary")
        }
    }

    @ViewBuilder
    private var medicalContent: some View {
        if row.title == "诊断摘要" {
            timelineRow(snapshot.latestDocumentLabel, title: "最近报告", detail: "已同步 \(snapshot.recordCount + snapshot.examCount) 份文档")
            timelineRow("问答记录", title: "历史咨询", detail: "已同步 \(snapshot.conversationCount) 次对话")
            toggleRow("生成问诊前摘要", subtitle: snapshot.hasSummary ? "可直接引用健康摘要" : "建议先生成健康摘要", key: "visit-summary")
        } else if row.title == "处方核对" {
            toggleRow("健康计划 \(snapshot.planCount) 个", subtitle: "可用于核对执行和提醒", key: "plans")
            toggleRow("已入库指标 \(snapshot.indicatorCount) 项", subtitle: "处方核对时结合关键检验值", key: "medicine-indicators")
            toggleRow("提醒医生复核", subtitle: "结合最新报告和健康摘要", key: "dose-check")
        } else {
            HStack(spacing: 9) {
                chip("下周", icon: "calendar")
                chip("一月内", icon: "calendar.badge.clock")
                chip("报告回传", icon: "tray.and.arrow.up.fill")
            }
            toggleRow("最近报告 \(snapshot.latestDocumentLabel)", subtitle: "问诊前优先回看", key: "latest-report")
            toggleRow("把新报告带到问诊", subtitle: "上传后自动更新摘要和指标", key: "upload-next")
        }
    }

    @ViewBuilder
    private var profileContent: some View {
        if row.title == "基础资料" {
            progressLine("资料完整度", value: CGFloat(snapshot.profileCompletion) / 100, trailing: "\(snapshot.profileCompletion)%")
            HStack(spacing: 9) {
                chip("减脂", icon: "target")
                chip("控糖", icon: "drop.fill")
                chip("提升睡眠", icon: "moon.fill")
            }
            toggleRow("同步体重到画像", subtitle: "来自 Apple 健康或手动记录", key: "weight")
        } else if row.title == "长期标签" {
            HStack(spacing: 9) {
                chip("\(snapshot.indicatorCount)项指标", icon: "tag.fill")
                chip("\(snapshot.watchedIndicatorCount)项关注", icon: "tag.fill")
                chip("\(snapshot.planCount)个计划", icon: "person.2.fill")
            }
            HStack(spacing: 9) {
                chip("历史报告", icon: "doc.text.fill")
                chip("问答上下文", icon: "brain.head.profile")
            }
        } else {
            toggleRow("健康摘要", subtitle: snapshot.hasSummary ? "已同步，可辅助风险提示" : "暂无摘要", key: "summary")
            toggleRow("长期用药提示", subtitle: "处方核对时避免冲突", key: "medicine")
            toggleRow("家庭共享需单独授权", subtitle: "默认不共享敏感健康资料", key: "family")
        }
    }

    private func progress(_ value: Int, cap: Int) -> CGFloat {
        guard cap > 0 else { return 0 }
        return min(1, CGFloat(value) / CGFloat(cap))
    }

    private func chip(_ title: String, icon: String, action: (() -> Void)? = nil) -> some View {
        let selected = action == nil && selectedTagIDs.contains(selectionKey(title))
        return Button {
            if let action {
                action()
            } else {
                toggleTag(title)
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .bold))
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .foregroundStyle(selected ? .white : Color(hex: "347FB7"))
            .frame(maxWidth: .infinity)
            .frame(height: 34)
            .background(
                Capsule()
                    .fill(selected ? AnyShapeStyle(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing)) : AnyShapeStyle(Color.white.opacity(0.62)))
                    .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
            )
        }
        .buttonStyle(.plain)
    }

    private func toggleRow(_ title: String, subtitle: String, key: String) -> some View {
        let done = completedActionIDs.contains(actionKey(key))
        return Button {
            toggleAction(key)
        } label: {
            HStack(spacing: 10) {
                Image(systemName: done ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(done ? category.gradient.last ?? Color(hex: "20CDB1") : Color(hex: "9BB6C9"))
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.82)
                    Text(subtitle)
                        .font(.system(size: 11))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)
                }
                Spacer(minLength: 6)
            }
            .padding(.horizontal, 12)
            .frame(height: 52)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(.white.opacity(done ? 0.72 : 0.48))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(done ? (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.35) : .white.opacity(0.7), lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
    }

    private func progressLine(_ title: String, value: CGFloat, trailing: String) -> some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(trailing)
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(.white.opacity(0.54))
                    Capsule()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(14, proxy.size.width * min(max(value, 0), 1)))
                }
            }
            .frame(height: 8)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.white.opacity(0.48))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.7), lineWidth: 1))
        )
    }

    private func timelineRow(_ date: String, title: String, detail: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 4) {
                Circle()
                    .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 12, height: 12)
                Rectangle()
                    .fill(Color(hex: "B9DDF2").opacity(0.6))
                    .frame(width: 2, height: 34)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(date)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                Text(title)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text(detail)
                    .font(.system(size: 11))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(2)
            }
            Spacer(minLength: 0)
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(.white.opacity(0.48))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(.white.opacity(0.7), lineWidth: 1))
        )
    }

    private func badge(_ title: String) -> some View {
        Text(title)
            .font(.system(size: 11, weight: .bold))
            .foregroundStyle(Color(hex: "347FB7"))
            .lineLimit(1)
            .minimumScaleFactor(0.76)
            .frame(maxWidth: .infinity)
            .frame(height: 28)
            .background(XAgeCapsuleFill())
    }

    private func selectionKey(_ value: String) -> String {
        "\(category.id)-\(row.key)-tag-\(value)"
    }

    private func actionKey(_ value: String) -> String {
        "\(category.id)-\(row.key)-action-\(value)"
    }

    private func toggleTag(_ value: String) {
        let key = selectionKey(value)
        withAnimation(.spring(response: 0.22, dampingFraction: 0.88)) {
            var next = selectedTagIDs
            if next.contains(key) {
                next.remove(key)
            } else {
                next.insert(key)
            }
            selectedTagIDs = next
        }
    }

    private func toggleAction(_ value: String) {
        let key = actionKey(value)
        withAnimation(.spring(response: 0.22, dampingFraction: 0.88)) {
            var next = completedActionIDs
            if next.contains(key) {
                next.remove(key)
            } else {
                next.insert(key)
            }
            completedActionIDs = next
        }
    }
}

private struct XAgeReportUploadSourceSheet: View {
    let onCamera: () -> Void
    let onDocument: () -> Void
    let onPhotoLibrary: () -> Void

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                        Image(systemName: "arrow.up.doc.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(.white)
                    }
                    .frame(width: 52, height: 52)

                    VStack(alignment: .leading, spacing: 3) {
                        Text("数据上传")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("选择报告、化验单或影像截图来源")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                }

                uploadSourceRow(title: "拍照采集", subtitle: "拍摄纸质报告或检查单", icon: "camera.fill", action: onCamera)
                uploadSourceRow(title: "选择 PDF / 图片", subtitle: "从文件中上传报告、病历或扫描件", icon: "doc.badge.plus", action: onDocument)
                uploadSourceRow(title: "从相册选择", subtitle: "一次可选择多张报告图片", icon: "photo.on.rectangle.angled", action: onPhotoLibrary)
            }
            .padding(24)
        }
    }

    private func uploadSourceRow(title: String, subtitle: String, icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
            .padding(.horizontal, 14)
            .frame(height: 62)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
        }
        .buttonStyle(.plain)
    }
}

@MainActor
private final class XAgeReportHistoryViewModel: ObservableObject {
    @Published var loading = false
    @Published var reports: [HealthDocument] = []
    @Published var records: [HealthDocument] = []
    @Published var selectedFilter: XAgeReportHistoryFilter = .reports
    @Published var selectedDocument: HealthDocument?
    @Published var errorMessage: String?

    private let repository: HealthDataRepositoryProtocol

    init(repository: HealthDataRepositoryProtocol = HealthDataRepository()) {
        self.repository = repository
    }

    var visibleDocuments: [HealthDocument] {
        switch selectedFilter {
        case .reports: return reports
        case .records: return records
        }
    }

    func load() async {
        loading = true
        defer { loading = false }
        do {
            async let examDocs = repository.fetchDocuments(docType: "exam")
            async let recordDocs = repository.fetchDocuments(docType: "record")
            let loadedReports = try await examDocs
            let loadedRecords = try await recordDocs
            reports = loadedReports.sortedForXAgeHistory()
            records = loadedRecords.sortedForXAgeHistory()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private enum XAgeReportHistoryFilter: String, CaseIterable, Identifiable {
    case reports = "报告"
    case records = "病历"

    var id: String { rawValue }
}

private struct XAgeReportHistorySheet: View {
    @StateObject private var vm = XAgeReportHistoryViewModel()
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("历史报告")
                            .font(.system(size: 25, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("识别完成后展示单份摘要、异常项和入库状态")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                    Spacer()
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .frame(width: 34, height: 34)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("关闭历史报告")
                }

                HStack(spacing: 8) {
                    ForEach(XAgeReportHistoryFilter.allCases) { filter in
                        Button {
                            withAnimation(.spring(response: 0.22, dampingFraction: 0.88)) {
                                vm.selectedFilter = filter
                            }
                        } label: {
                            Text("\(filter.rawValue) \(count(for: filter))")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(vm.selectedFilter == filter ? .white : Color(hex: "347FB7"))
                                .frame(maxWidth: .infinity)
                                .frame(height: 36)
                                .background(
                                    Capsule()
                                        .fill(vm.selectedFilter == filter ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing)) : AnyShapeStyle(Color.white.opacity(0.62)))
                                        .overlay(Capsule().stroke(.white.opacity(0.78), lineWidth: 1))
                                )
                        }
                        .buttonStyle(.plain)
                    }
                }

                Group {
                    if vm.loading && vm.visibleDocuments.isEmpty {
                        VStack(spacing: 10) {
                            ProgressView()
                                .tint(Color(hex: "18AFA7"))
                            Text("正在读取历史资料")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(XAgeGlassCardBackground(cornerRadius: 24))
                    } else if vm.visibleDocuments.isEmpty {
                        XAgeReportHistoryEmptyState(filter: vm.selectedFilter)
                    } else {
                        ScrollView {
                            LazyVStack(spacing: 10) {
                                ForEach(vm.visibleDocuments) { document in
                                    Button {
                                        vm.selectedDocument = document
                                    } label: {
                                        XAgeReportHistoryRow(document: document, filter: vm.selectedFilter)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                            .padding(2)
                        }
                        .scrollIndicators(.hidden)
                    }
                }
            }
            .padding(24)
        }
        .task { await vm.load() }
        .refreshable { await vm.load() }
        .sheet(item: $vm.selectedDocument) { document in
            XAgeReportDocumentSummarySheet(document: document)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .alert("读取失败", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    private func count(for filter: XAgeReportHistoryFilter) -> Int {
        switch filter {
        case .reports: return vm.reports.count
        case .records: return vm.records.count
        }
    }
}

private struct XAgeReportHistoryEmptyState: View {
    let filter: XAgeReportHistoryFilter

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: filter == .reports ? "doc.text.magnifyingglass" : "list.clipboard.fill")
                .font(.system(size: 28, weight: .bold))
                .foregroundStyle(Color(hex: "347FB7"))
            Text(filter == .reports ? "暂无历史报告" : "暂无历史病历")
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(filter == .reports ? "上传体检、化验或影像资料后，这里会显示单份摘要。" : "上传病历资料后，这里会显示就医时间线摘要。")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
                .multilineTextAlignment(.center)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(20)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}

private struct XAgeReportHistoryRow: View {
    let document: HealthDocument
    let filter: XAgeReportHistoryFilter

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Circle()
                        .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    Image(systemName: filter == .reports ? "doc.text.fill" : "list.clipboard.fill")
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(.white)
                }
                .frame(width: 40, height: 40)

                VStack(alignment: .leading, spacing: 4) {
                    Text(document.xAgeDisplayTitle)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(1)
                    Text(document.xAgeDateLabel)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }

                Spacer(minLength: 0)

                Text(document.xAgeStatusLabel)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(document.xAgeStatusColor)
                    .lineLimit(1)
                    .padding(.horizontal, 9)
                    .frame(height: 28)
                    .background(XAgeCapsuleFill())
            }

            Text(document.xAgeBriefSummary)
                .font(.system(size: 12))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 8) {
                XAgeReportHistoryBadge(title: "\(document.xAgeAbnormalCount) 项异常", icon: "exclamationmark.triangle.fill")
                XAgeReportHistoryBadge(title: "\(document.xAgeIndicatorCount) 项指标", icon: "list.bullet.rectangle")
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeReportHistoryBadge: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .bold))
            Text(title)
                .font(.system(size: 11, weight: .bold))
                .lineLimit(1)
        }
        .foregroundStyle(Color(hex: "347FB7"))
        .padding(.horizontal, 9)
        .frame(height: 26)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeReportDocumentSummarySheet: View {
    let document: HealthDocument
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(document.xAgeDisplayTitle)
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                                .fixedSize(horizontal: false, vertical: true)
                            Text("\(document.xAgeDateLabel) · \(document.xAgeStatusLabel)")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .buttonStyle(.plain)
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("此次报告汇总")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(document.xAgeDetailedSummary)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("异常项")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        if document.xAgeAbnormalFlags.isEmpty {
                            Text("当前资料未提取到异常项。")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "6C8194"))
                                .padding(12)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(XAgeCapsuleFill())
                        } else {
                            ForEach(document.xAgeAbnormalFlags.prefix(8)) { flag in
                                HStack(alignment: .top, spacing: 10) {
                                    Image(systemName: "exclamationmark.triangle.fill")
                                        .font(.system(size: 12, weight: .bold))
                                        .foregroundStyle(Color(hex: "F39A34"))
                                        .frame(width: 18, height: 18)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(flag.name ?? flag.field ?? "异常指标")
                                            .font(.system(size: 13, weight: .bold))
                                            .foregroundStyle(Color(hex: "173F64"))
                                        Text([flag.value, flag.unit, flag.ref_range].compactMap { $0 }.joined(separator: " "))
                                            .font(.system(size: 12))
                                            .foregroundStyle(Color(hex: "6C8194"))
                                    }
                                    Spacer(minLength: 0)
                                }
                                .padding(12)
                                .background(XAgeCapsuleFill())
                            }
                        }
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }
}

private extension Array where Element == HealthDocument {
    func sortedForXAgeHistory() -> [HealthDocument] {
        sorted { lhs, rhs in
            (lhs.doc_date ?? lhs.id) > (rhs.doc_date ?? rhs.id)
        }
    }
}

private extension HealthDocument {
    var xAgeDisplayTitle: String {
        let title = (name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !title.isEmpty { return title }
        let urlName = (file_url ?? "").split(separator: "/").last.map(String.init) ?? ""
        if !urlName.isEmpty { return urlName }
        return doc_type == "record" ? "未命名病历" : "未命名报告"
    }

    var xAgeDateLabel: String {
        if let doc_date, !doc_date.isEmpty {
            return Utils.formatDate(doc_date)
        }
        return "日期待确认"
    }

    var xAgeStatusLabel: String {
        switch extraction_status?.lowercased() {
        case "pending": return "识别中"
        case "failed": return "识别失败"
        case "done", "completed", "success": return "已完成"
        default: return "待确认"
        }
    }

    var xAgeStatusColor: Color {
        switch extraction_status?.lowercased() {
        case "pending": return Color(hex: "238AD6")
        case "failed": return Color(hex: "D85A66")
        case "done", "completed", "success": return Color(hex: "18AFA7")
        default: return Color(hex: "6C8194")
        }
    }

    var xAgeAbnormalFlags: [AbnormalFlag] {
        abnormal_flags ?? []
    }

    var xAgeAbnormalCount: Int {
        xAgeAbnormalFlags.count
    }

    var xAgeIndicatorCount: Int {
        csv_data?.rows?.count ?? 0
    }

    var xAgeBriefSummary: String {
        let candidates = [ai_brief, ai_summary]
        if let text = candidates.compactMap({ $0?.trimmingCharacters(in: .whitespacesAndNewlines) }).first(where: { !$0.isEmpty }) {
            return text
        }
        if extraction_status == "pending" {
            return "AI 正在识别这份资料，完成后会显示单份摘要。"
        }
        if xAgeIndicatorCount > 0 {
            return "已提取 \(xAgeIndicatorCount) 项指标，\(xAgeAbnormalCount) 项标记为异常。"
        }
        return "这份资料已入库，暂未生成摘要。"
    }

    var xAgeDetailedSummary: String {
        if let text = ai_summary?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty {
            return ChatViewModel.cleanAnalysis(text) ?? text
        }
        if let text = ai_brief?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty {
            return ChatViewModel.cleanAnalysis(text) ?? text
        }
        if extraction_status == "pending" {
            return "这份资料已进入 AI 识别队列。识别完成后，小捷会把可结构化的指标写入趋势，并在这里显示本次报告的关键结论。"
        }
        if xAgeIndicatorCount > 0 || xAgeAbnormalCount > 0 {
            return "本次资料已提取 \(xAgeIndicatorCount) 项指标，其中 \(xAgeAbnormalCount) 项被标记为异常。异常项用于报告复核和问答上下文，完整趋势以数据页最新有效测量时间为准。"
        }
        return "这份资料已保存在健康资料库中，暂未提取到可汇总的结构化内容。"
    }
}

private struct XAgePanelActionRow: View {
    let category: XAgeDataPanelCategory
    let row: XAgePanelRow
    var trailingTitle: String?
    var showsProgress: Bool = false
    var isSelected: Bool = false

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: row.icon)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 38, height: 38)
                .background(
                    Circle()
                        .fill(LinearGradient(colors: category.gradient, startPoint: .topLeading, endPoint: .bottomTrailing))
                        .shadow(color: (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.18), radius: 10, x: 0, y: 5)
                )
            VStack(alignment: .leading, spacing: 3) {
                Text(row.title)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                Text(row.subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }
            Spacer(minLength: 8)
            if showsProgress {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 52, height: 30)
            } else if let trailingTitle {
                Text(trailingTitle)
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.74)
                    .frame(width: 72, height: 30)
                    .background(XAgeCapsuleFill())
            } else {
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 66)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .overlay(
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .stroke(isSelected ? (category.gradient.last ?? Color(hex: "20CDB1")).opacity(0.58) : .clear, lineWidth: 1.2)
        )
    }
}

private struct XAgeReportUploadConfirmSheet: View {
    let upload: XAgePendingReportUpload
    let isUploading: Bool
    let onCancel: () -> Void
    let onConfirm: () -> Void

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .top, spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                        Image(systemName: upload.files.count > 1 ? "photo.stack.fill" : "arrow.up.doc.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(.white)
                    }
                    .frame(width: 54, height: 54)

                    VStack(alignment: .leading, spacing: 4) {
                        Text(upload.title)
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                            .fixedSize(horizontal: false, vertical: true)
                        Text("\(upload.source) · \(upload.files.count) 个文件 · \(upload.totalSizeText)")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer(minLength: 0)
                }

                Text("确认后才会上传到你的健康资料库，并进入 AI 识别队列。取消不会保存这些图片或文件。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())

                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 92), spacing: 10)], spacing: 10) {
                        ForEach(upload.files) { file in
                            XAgeReportUploadPreviewCell(file: file)
                        }
                    }
                    .padding(2)
                }
                .scrollIndicators(.hidden)
                .frame(maxHeight: 230)

                HStack(spacing: 10) {
                    Button(action: onCancel) {
                        Text("取消")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "365F80"))
                            .frame(maxWidth: .infinity)
                            .frame(height: 46)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .disabled(isUploading)

                    Button(action: onConfirm) {
                        HStack(spacing: 8) {
                            if isUploading {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(isUploading ? "上传中" : "确认上传")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(
                                    LinearGradient(
                                        colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")],
                                        startPoint: .topLeading,
                                        endPoint: .bottomTrailing
                                    )
                                )
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(isUploading)
                    .accessibilityIdentifier("xage.reportUpload.confirm")
                }
            }
            .padding(24)
        }
    }
}

private struct XAgeReportUploadPreviewCell: View {
    let file: XAgeReportUploadFile

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(.white.opacity(0.54))
                    .overlay(
                        RoundedRectangle(cornerRadius: 18, style: .continuous)
                            .stroke(.white.opacity(0.74), lineWidth: 1)
                    )
                if let image = file.previewImage {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                        .frame(height: 86)
                        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                } else {
                    Image(systemName: "doc.fill")
                        .font(.system(size: 25, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                }
            }
            .frame(height: 86)

            Text(file.fileName)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Color(hex: "5D7890"))
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(height: 28)
        }
        .padding(8)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
    }
}

private struct XAgeDataDetailView: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    let onSyncAppleHealth: () -> Void
    let onOpenGuide: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()
            ScrollView {
                VStack(spacing: 16) {
                    ZStack {
                        VStack(spacing: 3) {
                            Text(kind.rawValue)
                                .font(.system(size: 28, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                            Text("置信度 \(metric.confidence)%")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(kind.tint)
                                .padding(.horizontal, 10)
                                .padding(.vertical, 4)
                                .background(XAgeCapsuleFill())
                        }

                        HStack {
                            Spacer()
                            Button {
                                dismiss()
                            } label: {
                                Image(systemName: "xmark")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "1268BD"))
                                    .frame(width: 34, height: 34)
                                    .background(XAgeCapsuleFill())
                            }
                            .accessibilityLabel("关闭")
                        }
                    }
                    .padding(.top, 14)

                    XAgeScoreRing(kind: kind, metric: metric)
                        .frame(width: 150)
                        .padding(.vertical, 10)

                    if !metric.isReady {
                        XAgeMissingDataGuideCard(
                            kind: kind,
                            metric: metric,
                            onSyncAppleHealth: onSyncAppleHealth,
                            onOpenGuide: onOpenGuide
                        )
                    }

                    VStack(alignment: .leading, spacing: 12) {
                        Text("指标构成")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.fields) { field in
                            HStack {
                                Text(field.title)
                                    .font(.system(size: 14, weight: .medium))
                                    .foregroundStyle(Color(hex: "496A83"))
                                Spacer()
                                Text(field.value)
                                    .font(.system(size: 14, weight: .bold))
                                    .foregroundStyle(Color(hex: "17324E"))
                            }
                            Divider().opacity(0.24)
                        }
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("主要输入")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.drivers.prefix(3)) { driver in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(kind.tint)
                                    .frame(width: 7, height: 7)
                                    .padding(.top, 6)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(driver.title)
                                        .font(.system(size: 14, weight: .bold))
                                        .foregroundStyle(Color(hex: "17324E"))
                                    Text(driver.note)
                                        .font(.system(size: 12))
                                        .foregroundStyle(Color(hex: "5D7890"))
                                        .lineSpacing(2)
                                }
                            }
                        }
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))

                    VStack(alignment: .leading, spacing: 8) {
                        Text("先看结论")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(metric.simpleExplanation)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(3)
                        DisclosureGroup {
                            Text(metric.explanation)
                                .font(.system(size: 13))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineSpacing(3)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.top, 6)
                        } label: {
                            Text("专业依据")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(kind.tint)
                        }
                        .tint(kind.tint)

                        Text(metric.nextAction)
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(kind.tint)
                            .lineSpacing(3)
                            .padding(12)
                            .background(XAgeCapsuleFill())
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))
                }
                .padding(24)
            }
        }
    }
}

private struct XAgeMissingDataGuideCard: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    let onSyncAppleHealth: () -> Void
    let onOpenGuide: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "tray.and.arrow.up.fill")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(kind.tint)
                    .frame(width: 34, height: 34)
                    .background(XAgeCapsuleFill())
                VStack(alignment: .leading, spacing: 3) {
                    Text("补齐后再评估")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(metric.summary)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "5D7890"))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            HStack(spacing: 10) {
                Button(action: onSyncAppleHealth) {
                    guideButtonTitle("同步 Apple 健康", icon: "heart.text.square.fill", filled: true)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.score.missing.syncAppleHealth")

                Button(action: onOpenGuide) {
                    guideButtonTitle(kind == .inflammation ? "上传报告" : "打开指标", icon: kind == .inflammation ? "arrow.up.doc.fill" : "list.bullet.rectangle", filled: false)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("xage.score.missing.openGuide")
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private func guideButtonTitle(_ title: String, icon: String, filled: Bool) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .bold))
            Text(title)
                .font(.system(size: 13, weight: .bold))
                .lineLimit(1)
                .minimumScaleFactor(0.82)
        }
        .foregroundStyle(filled ? .white : kind.tint)
        .frame(maxWidth: .infinity)
        .frame(height: 38)
        .background(
            Capsule()
                .fill(filled ? AnyShapeStyle(LinearGradient(colors: [kind.tint, Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing)) : AnyShapeStyle(Color.white.opacity(0.62)))
                .overlay(Capsule().stroke(.white.opacity(0.8), lineWidth: 1))
        )
    }
}

private struct XAgeScoreInfoSheet: View {
    let kind: XAgeDataKind
    let metric: XAgeMetricScore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        Image(systemName: "info.circle.fill")
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(kind.tint)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("\(kind.rawValue)原理")
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "173F64"))
                            Text(metric.isReady ? (metric.isProxy ? "代理信号 · 置信度 \(metric.confidence)%" : "综合评分 · 置信度 \(metric.confidence)%") : "待评估 · 置信度 \(metric.confidence)%")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 14, weight: .bold))
                                .foregroundStyle(Color(hex: "2A79BB"))
                                .frame(width: 36, height: 36)
                                .background(XAgeCapsuleFill())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭\(kind.rawValue)原理")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("先看结论")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(metric.simpleExplanation)
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "496A83"))
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)
                        DisclosureGroup {
                            Text(metric.explanation)
                                .font(.system(size: 13))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineSpacing(4)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.top, 6)
                        } label: {
                            Text("专业依据")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(kind.tint)
                        }
                        .tint(kind.tint)
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("主要输入")
                            .font(.system(size: 17, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(metric.drivers.prefix(3)) { driver in
                            HStack {
                                Text(driver.title)
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "17324E"))
                                Spacer()
                                Text(driver.value)
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(kind.tint)
                            }
                            .padding(11)
                            .background(XAgeCapsuleFill())
                        }
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 24))

                    Text(metric.nextAction)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(kind.tint)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }
}

private struct XAgeConversationSurface: View {
    private static let bottomAnchorID = "xage.chat.bottom"

    @Binding var selectedSection: XAgeTopSection
    let historyRequest: Int
    @StateObject private var vm = ChatViewModel()
    @StateObject private var reportUploadVM = HealthDataViewModel()
    @StateObject private var speechInput = XAgeSpeechInputManager()
    @State private var selectedAnalysis: ChatMessageItem?
    @State private var selectedEvidence: ChatMessageItem?
    @State private var showCamera = false
    @State private var showPhotoLibrary = false
    @State private var showDocumentPicker = false
    @State private var showAttachmentMenu = false
    @State private var pendingUpload: XAgePendingReportUpload?
    @State private var uploadQualityWarning: String?

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            if vm.messages.isEmpty {
                                XAgeChatWelcome(vm: vm)
                                    .padding(.top, 34)
                            }

                            ForEach(vm.messages) { msg in
                                XAgeChatBubble(
                                    message: msg,
                                    onRetry: { Task { await vm.retryMessage(id: msg.id) } },
                                    onAnalysis: { selectedAnalysis = msg },
                                    onEvidence: { selectedEvidence = msg }
                                )
                                .id(msg.id)
                            }

                            if reportUploadVM.uploading || reportUploadVM.backgroundTaskHint != nil {
                                XAgeChatUploadStatusCard(
                                    uploading: reportUploadVM.uploading,
                                    title: reportUploadVM.uploading
                                        ? (reportUploadVM.uploadStage.isEmpty ? "正在上传报告…" : reportUploadVM.uploadStage)
                                        : "报告已上传，AI 正在识别",
                                    subtitle: reportUploadVM.backgroundTaskHint ?? "完成后会继续进入问答解读。"
                                )
                                .id("xage.upload.status")
                            }

                            if vm.sending {
                                XAgeChatThinkingCard(
                                    currentHint: vm.thinkingHint.isEmpty ? "正在思考…" : vm.thinkingHint,
                                    steps: vm.thinkingProgressItems
                                )
                                .id("xage.chat.thinking")
                            }

                            Color.clear
                                .frame(height: 1)
                                .id(Self.bottomAnchorID)
                        }
                        .padding(.horizontal, 24)
                        .padding(.bottom, 96)
                    }
                    .scrollIndicators(.hidden)
                    .onChange(of: vm.messages.count) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: vm.sending) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: vm.thinkingStepIndex) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: reportUploadVM.uploading) { _, _ in
                        scrollToBottom(proxy)
                    }
                    .onChange(of: reportUploadVM.backgroundTaskHint ?? "") { _, _ in
                        scrollToBottom(proxy)
                    }
                }

                XAgeChatInputBar(
                    vm: vm,
                    isRecording: speechInput.isRecording,
                    isUploading: reportUploadVM.uploading,
                    onMicTap: toggleSpeechInput,
                    onPlusTap: { withAnimation(.spring(response: 0.22, dampingFraction: 0.9)) { showAttachmentMenu.toggle() } }
                )
                .padding(.horizontal, 24)
                .padding(.bottom, 20)
            }

            if showAttachmentMenu {
                attachmentMenuOverlay
                    .transition(.opacity)
                    .zIndex(5)
            }
        }
        .task { await vm.loadConversations(showErrors: false) }
        .onChange(of: historyRequest) { _, _ in
            openHistorySheet()
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraImagePicker(
                onPick: { data, name in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: name)],
                        title: "确认数据上传",
                        source: "相机"
                    )
                },
                fileNamePrefix: "xage_report_camera"
            )
            .ignoresSafeArea()
        }
        .sheet(isPresented: $showPhotoLibrary) {
            MultiPhotoPicker(
                selectionLimit: 9,
                fileNamePrefix: "xage_report_album",
                onPick: { photos in
                    preparePendingReportUpload(
                        files: photos.map { XAgeReportUploadFile(data: $0.data, fileName: $0.fileName) },
                        title: photos.count > 1 ? "确认上传 \(photos.count) 张照片" : "确认相册上传",
                        source: "相册"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(isPresented: $showDocumentPicker) {
            DocumentPickerView(
                onPick: { data, fileName in
                    preparePendingReportUpload(
                        files: [XAgeReportUploadFile(data: data, fileName: fileName)],
                        title: "确认上传文件",
                        source: "文件"
                    )
                },
                onError: { message in
                    reportUploadVM.errorMessage = message
                }
            )
        }
        .sheet(item: $pendingUpload) { upload in
            XAgeReportUploadConfirmSheet(
                upload: upload,
                isUploading: reportUploadVM.uploading,
                onCancel: { pendingUpload = nil },
                onConfirm: {
                    pendingUpload = nil
                    uploadReports(upload.files)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $vm.showHistory) {
            XAgeChatHistorySheet(vm: vm)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $selectedAnalysis) { msg in
            XAgeAnalysisSheet(message: msg)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(item: $selectedEvidence) { msg in
            XAgeEvidenceSheet(message: msg)
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .alert("语音输入", isPresented: Binding(
            get: { speechInput.errorMessage != nil },
            set: { if !$0 { speechInput.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(speechInput.errorMessage ?? "")
        }
        .alert("拍摄质量不足", isPresented: Binding(
            get: { uploadQualityWarning != nil },
            set: { if !$0 { uploadQualityWarning = nil } }
        )) {
            Button("重新拍摄") { uploadQualityWarning = nil; showCamera = true }
            Button("取消", role: .cancel) { uploadQualityWarning = nil }
        } message: {
            Text(uploadQualityWarning ?? "")
        }
        .alert("上传提示", isPresented: Binding(
            get: { reportUploadVM.infoMessage != nil },
            set: { if !$0 { reportUploadVM.infoMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(reportUploadVM.infoMessage ?? "")
        }
        .alert("上传失败", isPresented: Binding(
            get: { reportUploadVM.errorMessage != nil },
            set: { if !$0 { reportUploadVM.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(reportUploadVM.errorMessage ?? "")
        }
        .alert("提示", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("确定", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy, animated: Bool = true) {
        DispatchQueue.main.async {
            if animated {
                withAnimation(.easeOut(duration: 0.22)) {
                    proxy.scrollTo(Self.bottomAnchorID, anchor: .bottom)
                }
            } else {
                proxy.scrollTo(Self.bottomAnchorID, anchor: .bottom)
            }
        }
    }

    private var attachmentMenuOverlay: some View {
        ZStack(alignment: .bottomTrailing) {
            Color.black.opacity(0.001)
                .ignoresSafeArea()
                .onTapGesture {
                    withAnimation(.spring(response: 0.22, dampingFraction: 0.9)) {
                        showAttachmentMenu = false
                    }
                }

            XAgeAttachmentMenu(
                onCamera: { presentAttachmentActionAfterMenu(.camera) },
                onDocument: { presentAttachmentActionAfterMenu(.documentPicker) },
                onPhotoLibrary: { presentAttachmentActionAfterMenu(.photoLibrary) },
                onNewChat: { presentAttachmentActionAfterMenu(.newChat) }
            )
            .padding(.trailing, 42)
            .padding(.bottom, 88)
        }
    }

    private enum XAgeAttachmentAction {
        case camera
        case documentPicker
        case photoLibrary
        case newChat
    }

    private func presentAttachmentActionAfterMenu(_ action: XAgeAttachmentAction) {
        showAttachmentMenu = false
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
            performAttachmentAction(action)
        }
    }

    private func performAttachmentAction(_ action: XAgeAttachmentAction) {
        switch action {
        case .camera:
            showCamera = true
        case .documentPicker:
            showDocumentPicker = true
        case .photoLibrary:
            showPhotoLibrary = true
        case .newChat:
            vm.newChat()
        }
    }

    private func openHistorySheet() {
        guard selectedSection == .chat else { return }
        showAttachmentMenu = false
        vm.showHistory = true
        Task { await vm.loadConversations(showErrors: false) }
    }

    private func toggleSpeechInput() {
        if speechInput.isRecording {
            speechInput.stop()
            return
        }
        hideKeyboard()
        speechInput.start { recognizedText in
            vm.inputValue = recognizedText
        }
    }

    private func preparePendingReportUpload(files: [XAgeReportUploadFile], title: String, source: String) {
        guard !files.isEmpty else { return }
        for file in files {
            if let warning = validateReportImageQuality(data: file.data, fileName: file.fileName) {
                uploadQualityWarning = "\(file.fileName)：\(warning)"
                return
            }
        }
        let upload = XAgePendingReportUpload(title: title, source: source, files: files)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            pendingUpload = upload
        }
    }

    private func uploadReports(_ files: [XAgeReportUploadFile]) {
        guard !files.isEmpty else { return }
        hideKeyboard()
        reportUploadVM.uploadDocType = "exam"
        Task {
            var uploaded: [(fileName: String, documentId: String)] = []
            for file in files {
                if let doc = await reportUploadVM.uploadFile(data: file.data, fileName: file.fileName) {
                    uploaded.append((file.fileName, doc.id))
                }
            }
            if !uploaded.isEmpty {
                let prompt = reportAnalysisPrompt(uploaded: uploaded)
                if vm.sending {
                    vm.inputValue = prompt
                } else {
                    await vm.sendText(prompt)
                }
            }
        }
    }

    private func reportAnalysisPrompt(uploaded: [(fileName: String, documentId: String)]) -> String {
        if uploaded.count == 1, let item = uploaded.first {
            return "我刚上传了一份体检/化验报告（\(item.fileName)，文档ID：\(item.documentId)）。请结合我的健康档案和这份报告的识别结果，帮我总结关键指标、异常项、趋势变化和下一步建议。若后台识别仍在进行，请先说明正在识别，并告诉我完成后应该重点关注哪些项目。"
        }
        let list = uploaded
            .map { "\($0.fileName)，文档ID：\($0.documentId)" }
            .joined(separator: "；")
        return "我刚上传了 \(uploaded.count) 张/份体检化验报告（\(list)）。请把这些报告作为同一批资料，结合我的健康档案总结关键指标、异常项、同批次之间的重复/互补信息和下一步建议。若后台识别仍在进行，请先说明正在识别，并告诉我完成后应该重点关注哪些项目。"
    }

    private func validateReportImageQuality(data: Data, fileName: String) -> String? {
        let lower = fileName.lowercased()
        let isImage = [".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff"].contains { lower.hasSuffix($0) }
        guard isImage else { return nil }
        if data.count < 30 * 1024 {
            return "图片过小（小于 30KB），可能不是完整报告。请重新拍摄。"
        }
        if let img = UIImage(data: data) {
            let shortEdge = min(img.size.width, img.size.height) * img.scale
            if shortEdge < 600 {
                return "图片分辨率过低（短边 \(Int(shortEdge))px），识别可能失败。请重新拍摄。"
            }
        } else {
            return "未能读取图片数据，请重新拍摄或选择 PDF。"
        }
        return nil
    }

    private func hideKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }
}

private struct XAgeChatThinkingCard: View {
    let currentHint: String
    let steps: [String]

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            XAgeAssistantOrb()
                .frame(width: 34, height: 34)

            VStack(alignment: .leading, spacing: 9) {
                HStack(spacing: 7) {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Color(hex: "18AFA7"))
                    Text(currentHint)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }

                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                        HStack(alignment: .top, spacing: 7) {
                            Image(systemName: index == steps.count - 1 ? "ellipsis.circle.fill" : "checkmark.circle.fill")
                                .font(.system(size: 12, weight: .bold))
                                .foregroundStyle(index == steps.count - 1 ? Color(hex: "238AD6") : Color(hex: "20CDB1"))
                                .frame(width: 16, height: 16)
                            Text(step)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                                .lineLimit(2)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .padding(14)
            .background(XAgeGlassCardBackground(cornerRadius: 22))

            Spacer(minLength: 0)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("xage.chat.thinking.card")
    }
}

private struct XAgeChatWelcome: View {
    @ObservedObject var vm: ChatViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 16) {
                XAgeAssistantOrb()
                    .frame(width: 40, height: 40)
                VStack(alignment: .leading, spacing: 4) {
                    Text("下午好，想问什么？")
                        .font(.system(size: 25, weight: .bold))
                        .foregroundStyle(Color(hex: "111827"))
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                    Text("小捷先帮你问清关键问题。")
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "637083"))
                        .lineLimit(1)
                }
            }

            Spacer()
                .frame(height: 50)

            Text("你可以这样问")
                .font(.system(size: 21, weight: .bold))
                .foregroundStyle(Color(hex: "111827"))
                .lineLimit(1)

            Spacer()
                .frame(height: 28)

            Button {
                vm.inputValue = "帮我整理病史摘要"
                Task { await vm.sendMessage() }
            } label: {
                XAgeStarterRow(icon: "doc.text", title: "整理病史摘要", subtitle: "诊断、用药、过敏信息", primary: true)
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)

            Spacer()
                .frame(height: 32)

            Button {
                vm.inputValue = "帮我分析最近报告趋势"
                Task { await vm.sendMessage() }
            } label: {
                XAgeStarterRow(icon: "chart.bar", title: "分析报告趋势", subtitle: nil, primary: false)
            }
            .buttonStyle(.plain)
            .disabled(vm.sending)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct XAgeStarterRow: View {
    let icon: String
    let title: String
    let subtitle: String?
    let primary: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 19, weight: .semibold))
                .foregroundStyle(Color.appPrimary)
                .frame(width: 36, height: 36)
                .background(
                    Circle()
                        .fill(Color(hex: "E7FAFF").opacity(0.46))
                        .overlay(Circle().stroke(.white.opacity(0.62), lineWidth: 1))
                )
            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "111827"))
                    .lineLimit(1)
                if let subtitle {
                    Text(subtitle)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "637083"))
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            Image(systemName: "chevron.right")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Color(hex: "6F7F91").opacity(0.72))
                .frame(width: 24, height: 24)
        }
        .padding(.horizontal, 18)
        .frame(height: primary ? 84 : 66)
        .background(XAgeGlassCardBackground(cornerRadius: primary ? 34 : 33))
    }
}

private struct XAgeAssistantOrb: View {
    var body: some View {
        ZStack {
            Circle()
                .fill(.white.opacity(0.42))
                .shadow(color: Color(hex: "00C9A7").opacity(0.25), radius: 16, x: 0, y: 8)
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [Color(hex: "00C9A7"), Color(hex: "1565C0")],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: 20, height: 20)
            Capsule()
                .fill(.white.opacity(0.26))
                .frame(width: 10, height: 28)
                .blur(radius: 1)
                .offset(x: 8, y: -4)
        }
    }
}

private struct XAgeChatBubble: View {
    let message: ChatMessageItem
    let onRetry: () -> Void
    let onAnalysis: () -> Void
    let onEvidence: () -> Void

    var body: some View {
        let isUser = message.role == "user"
        HStack {
            if isUser { Spacer(minLength: 44) }
            VStack(alignment: isUser ? .trailing : .leading, spacing: 8) {
                Text(message.content)
                    .font(.system(size: 15, weight: isUser ? .semibold : .regular))
                    .foregroundStyle(isUser ? .white : Color(hex: "244E6D"))
                    .lineSpacing(2)
                    .padding(.horizontal, isUser ? 15 : 15)
                    .padding(.vertical, isUser ? 11 : 14)
                    .background(
                        RoundedRectangle(cornerRadius: isUser ? 24 : 20, style: .continuous)
                            .fill(isUser ? AnyShapeStyle(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing)) : AnyShapeStyle(.white.opacity(0.56)))
                            .overlay(
                                RoundedRectangle(cornerRadius: isUser ? 24 : 20, style: .continuous)
                                    .stroke(.white.opacity(0.72), lineWidth: 1)
                            )
                    )
                    .fixedSize(horizontal: false, vertical: true)

                if let status = message.status {
                    HStack(spacing: 8) {
                        Text(status.rawValue)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(isUser ? .white.opacity(0.82) : Color(hex: "6C8194"))
                        if status == .failed {
                            Button("重试", action: onRetry)
                                .font(.system(size: 11, weight: .bold))
                        }
                    }
                }

                if !isUser {
                    HStack(spacing: 8) {
                        if let analysis = message.analysis, !analysis.isEmpty {
                            CapsuleButton(title: "查看分析", action: onAnalysis)
                        }
                        if !message.relevantCitations.isEmpty {
                            CapsuleButton(title: "证据展示", action: onEvidence)
                        }
                    }
                }
            }
            if !isUser { Spacer(minLength: 44) }
        }
    }
}

private struct XAgeChatInputBar: View {
    @ObservedObject var vm: ChatViewModel
    let isRecording: Bool
    let isUploading: Bool
    let onMicTap: () -> Void
    let onPlusTap: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Button(action: onMicTap) {
                Image(systemName: isRecording ? "stop.circle.fill" : "mic.fill")
                    .frame(width: 32, height: 32)
            }
            .buttonStyle(.plain)
            .foregroundStyle(isRecording ? Color(hex: "12B59C") : Color(hex: "172033"))
            .accessibilityIdentifier("xage.chat.mic")
            .accessibilityLabel(isRecording ? "停止语音输入" : "语音输入")

            TextField("输入或长按说话", text: $vm.inputValue)
                .font(.system(size: 15))
                .textFieldStyle(.plain)
                .frame(height: 44)
                .accessibilityIdentifier("xage.chat.input")

            Button(action: onPlusTap) {
                Image(systemName: "plus")
                    .font(.system(size: 19, weight: .semibold))
                    .frame(width: 32, height: 32)
                    .background(
                        Circle()
                            .fill(.white.opacity(0.58))
                            .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1))
                    )
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color(hex: "172033"))
            .disabled(isUploading)
            .accessibilityIdentifier("xage.chat.plus")
            .accessibilityLabel("添加内容")

            Button {
                Task { await vm.sendMessage() }
            } label: {
                Image(systemName: "paperplane.fill")
                    .font(.system(size: 17, weight: .bold))
                    .offset(x: -1, y: 1)
                    .frame(width: 36, height: 36)
                    .background(
                        Circle()
                            .fill(LinearGradient(colors: [Color(hex: "228DD8"), Color(hex: "1DC8AE")], startPoint: .topLeading, endPoint: .bottomTrailing))
                    )
                    .foregroundStyle(.white)
            }
            .buttonStyle(.plain)
            .disabled(vm.inputValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || vm.sending)
            .accessibilityIdentifier("xage.chat.send")
            .accessibilityLabel("发送")
        }
        .padding(.horizontal, 10)
        .frame(height: 58)
        .background(XAgeGlassCardBackground(cornerRadius: 29))
    }
}

private struct XAgeAttachmentMenu: View {
    let onCamera: () -> Void
    let onDocument: () -> Void
    let onPhotoLibrary: () -> Void
    let onNewChat: () -> Void

    var body: some View {
        VStack(spacing: 8) {
            Text("添加内容")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .frame(maxWidth: .infinity)
                .padding(.bottom, 2)

            menuButton(
                title: "拍照采集报告",
                icon: "camera.fill",
                identifier: "xage.chat.attachment.camera",
                action: onCamera
            )
            menuButton(
                title: "数据上传 PDF / 图片",
                icon: "doc.badge.plus",
                identifier: "xage.chat.attachment.documents",
                action: onDocument
            )
            menuButton(
                title: "从相册上传报告",
                icon: "photo.on.rectangle.angled",
                identifier: "xage.chat.attachment.photos",
                action: onPhotoLibrary
            )
            menuButton(
                title: "新对话",
                icon: "plus.message.fill",
                identifier: "xage.chat.attachment.new",
                action: onNewChat
            )
        }
        .padding(12)
        .frame(width: 220)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
        .shadow(color: Color(hex: "7CCAF5").opacity(0.22), radius: 22, x: 0, y: 10)
        .accessibilityElement(children: .contain)
    }

    private func menuButton(
        title: String,
        icon: String,
        identifier: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: icon)
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
                    .frame(width: 22, height: 22)
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .frame(height: 42)
            .background(XAgeCapsuleFill())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }
}

private struct XAgeChatHistorySheet: View {
    @ObservedObject var vm: ChatViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("历史对话")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("继续之前的健康问答")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }

                    Spacer()

                    Button {
                        vm.showHistory = false
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "2A79BB"))
                            .frame(width: 36, height: 36)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.chat.history.close")
                    .accessibilityLabel("关闭历史对话")
                }

                ScrollView {
                    LazyVStack(spacing: 12) {
                        if vm.conversations.isEmpty {
                            emptyState
                        } else {
                            ForEach(vm.conversations) { conversation in
                                Button {
                                    Task {
                                        await vm.loadConversation(id: conversation.id)
                                        vm.showHistory = false
                                        dismiss()
                                    }
                                } label: {
                                    conversationRow(conversation)
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.chat.history.row.\(conversation.id)")
                            }

                            if vm.hasMoreConversations {
                                Button {
                                    Task { await vm.loadMoreConversations() }
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(systemName: "arrow.down.circle.fill")
                                            .font(.system(size: 15, weight: .bold))
                                        Text("加载更多")
                                            .font(.system(size: 15, weight: .bold))
                                    }
                                    .foregroundStyle(Color(hex: "237FC4"))
                                    .frame(maxWidth: .infinity)
                                    .frame(height: 48)
                                    .background(XAgeCapsuleFill())
                                }
                                .buttonStyle(.plain)
                                .accessibilityIdentifier("xage.chat.history.more")
                            }
                        }
                    }
                    .padding(.bottom, 24)
                }
                .scrollIndicators(.hidden)
            }
            .padding(.horizontal, 24)
            .padding(.top, 24)
        }
        .accessibilityIdentifier("xage.chat.history.sheet")
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color(hex: "6CD8DA").opacity(0.22))
                    .frame(width: 54, height: 54)
                Image(systemName: "clock.arrow.circlepath")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "237FC4"))
            }

            Text("暂无历史对话")
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))

            Text("登录并完成问答后，会在这里继续查看历史记录。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "5D7890"))
                .multilineTextAlignment(.center)
                .lineSpacing(3)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 34)
        .padding(.horizontal, 18)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private func conversationRow(_ conversation: ChatConversation) -> some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color(hex: "25C8BE").opacity(0.18))
                    .frame(width: 42, height: 42)
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "159D8F"))
            }

            VStack(alignment: .leading, spacing: 6) {
                Text(conversation.title ?? "健康问答")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)

                HStack(spacing: 8) {
                    Text("\(conversation.message_count ?? 0) 条消息")
                    if let timestamp = conversation.updated_at ?? conversation.created_at {
                        Text("·")
                        Text(Self.formatTimestamp(timestamp))
                    }
                }
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6F879B"))
            }

            Spacer(minLength: 8)

            Image(systemName: "chevron.right")
                .font(.system(size: 13, weight: .bold))
                .foregroundStyle(Color(hex: "8BA6BA"))
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private static func formatTimestamp(_ iso: String) -> String {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = fractional.date(from: iso) ?? ISO8601DateFormatter().date(from: iso) else {
            return String(iso.prefix(10))
        }

        let diff = Date().timeIntervalSince(date)
        if diff < 60 { return "刚刚" }
        if diff < 3600 { return "\(Int(diff / 60))分钟前" }
        if diff < 86400 { return "\(Int(diff / 3600))小时前" }
        if diff < 86400 * 7 { return "\(Int(diff / 86400))天前" }

        let formatter = DateFormatter()
        formatter.dateFormat = "MM-dd HH:mm"
        return formatter.string(from: date)
    }
}

private struct XAgeChatUploadStatusCard: View {
    let uploading: Bool
    let title: String
    let subtitle: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ZStack {
                Circle()
                    .fill(.white.opacity(0.52))
                    .overlay(Circle().stroke(.white.opacity(0.7), lineWidth: 1))
                    .frame(width: 34, height: 34)
                if uploading {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Image(systemName: "sparkles")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(Color(hex: "159D8F"))
                }
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .lineLimit(2)
                Text(subtitle)
                    .font(.system(size: 12))
                    .foregroundStyle(Color(hex: "5D7890"))
                    .lineLimit(3)
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 22))
        .accessibilityIdentifier("xage.chat.upload.status")
    }
}

@MainActor
private final class XAgeSpeechInputManager: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var onResult: ((String) -> Void)?

    func start(onResult: @escaping (String) -> Void) {
        guard !isRecording else { return }
        self.onResult = onResult
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                guard let self else { return }
                guard status == .authorized else {
                    self.errorMessage = "请在系统设置中允许语音识别权限。"
                    return
                }
                self.requestRecordPermission()
            }
        }
    }

    private func requestRecordPermission() {
        if #available(iOS 17.0, *) {
            AVAudioApplication.requestRecordPermission { [weak self] allowed in
                Task { @MainActor in
                    self?.handleRecordPermission(allowed)
                }
            }
        } else {
            AVAudioSession.sharedInstance().requestRecordPermission { [weak self] allowed in
                DispatchQueue.main.async {
                    self?.handleRecordPermission(allowed)
                }
            }
        }
    }

    private func handleRecordPermission(_ allowed: Bool) {
        guard allowed else {
            errorMessage = "请在系统设置中允许麦克风权限。"
            return
        }
        startRecording()
    }

    func stop() {
        stopRecording(cancelTask: true)
    }

    private func startRecording() {
        guard recognizer?.isAvailable == true else {
            errorMessage = "当前设备语音识别暂不可用。"
            return
        }

#if targetEnvironment(simulator)
        errorMessage = "模拟器无法进行真实语音输入，请在真机上使用麦克风。"
        return
#else
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest else { return }
        recognitionRequest.shouldReportPartialResults = true

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let inputNode = audioEngine.inputNode
            inputNode.removeTap(onBus: 0)
            let format = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak recognitionRequest] buffer, _ in
                recognitionRequest?.append(buffer)
            }

            audioEngine.prepare()
            try audioEngine.start()
            isRecording = true

            recognitionTask = recognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if let result {
                        self.onResult?(result.bestTranscription.formattedString)
                    }
                    if error != nil || result?.isFinal == true {
                        self.stopRecording(cancelTask: false)
                    }
                }
            }
        } catch {
            errorMessage = "语音输入启动失败：\(error.localizedDescription)"
            stopRecording(cancelTask: true)
        }
#endif
    }

    private func stopRecording(cancelTask: Bool) {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        if cancelTask {
            recognitionTask?.cancel()
        }
        recognitionRequest = nil
        recognitionTask = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}

private struct XAgeAnalysisSheet: View {
    let message: ChatMessageItem
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("详细分析")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color(hex: "123E67"))
                    Spacer()
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1268BD"))
                            .frame(width: 34, height: 34)
                            .background(XAgeCapsuleFill())
                    }
                    .accessibilityLabel("关闭")
                }
                ScrollView {
                    MarkdownTextView(text: ChatViewModel.cleanAnalysis(message.analysis) ?? "当前回答没有额外分析。")
                        .padding(16)
                        .background(XAgeGlassCardBackground(cornerRadius: 22))
                }
                .scrollIndicators(.hidden)
            }
            .padding(24)
        }
    }
}

private struct XAgeEvidenceSheet: View {
    let message: ChatMessageItem
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack {
                        Text("证据展示")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .accessibilityLabel("关闭")
                    }
                    ForEach(Array(message.relevantCitations.enumerated()), id: \.element.id) { index, citation in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text("[\(index + 1)]")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color.appPrimary)
                                Text(citation.evidence_level)
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Color.appAccent)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 3)
                                    .background(Capsule().fill(Color.appAccent.opacity(0.12)))
                                Spacer()
                                Text(citation.confidence)
                                    .font(.system(size: 12, weight: .medium))
                                    .foregroundStyle(Color(hex: "6C8194"))
                            }
                            Text(citation.claim_text)
                                .font(.system(size: 14))
                                .foregroundStyle(Color(hex: "244E6D"))
                            Text("\(citation.short_ref) · \(citation.journal ?? "source") · \(citation.year.map(String.init) ?? "year")")
                                .font(.system(size: 12))
                                .foregroundStyle(Color(hex: "6C8194"))
                                .lineLimit(1)
                        }
                        .padding(14)
                        .background(XAgeGlassCardBackground(cornerRadius: 20))
                    }
                    if message.relevantCitations.isEmpty {
                        Text("当前回答暂无文献引用。")
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "6C8194"))
                            .padding(16)
                            .background(XAgeGlassCardBackground(cornerRadius: 20))
                    }
                }
                .padding(24)
            }
        }
    }
}

private struct XAgeSnapshot {
    let range: String
    let updateHint: String
    let isReady: Bool
    let age: String
    let ageRange: String
    let delta: String
    let pace: Double
    let confidence: Int
    let status: String
    let summary: String
    let explanation: String
    let nextAction: String
    let drivers: [XAgeScoreDriver]
}

private struct XAgeInfoSheet: View {
    let snapshot: XAgeSnapshot
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("X年龄原理")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text("\(snapshot.range) · 区间 \(snapshot.ageRange)")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .lineLimit(1)
                            .minimumScaleFactor(0.76)
                    }

                    Spacer()

                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "2A79BB"))
                            .frame(width: 36, height: 36)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.info.close")
                    .accessibilityLabel("关闭 X年龄原理")
                }

                VStack(alignment: .leading, spacing: 14) {
                    HStack(spacing: 12) {
                        infoMetric(title: "当前", value: snapshot.age)
                        infoMetric(title: "差值", value: snapshot.delta)
                        infoMetric(title: "进度", value: snapshot.isReady ? String(format: "%.1fx", snapshot.pace) : "--")
                        infoMetric(title: "置信", value: "\(snapshot.confidence)%")
                    }

                    Text(snapshot.explanation)
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true)

                    Text(snapshot.summary)
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(Color(hex: "173F64"))
                        .lineSpacing(4)
                        .fixedSize(horizontal: false, vertical: true)
                        .padding(14)
                        .background(XAgeCapsuleFill())

                    VStack(alignment: .leading, spacing: 8) {
                        Text("主要输入")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        ForEach(snapshot.drivers.prefix(3)) { driver in
                            HStack {
                                Text(driver.title)
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Color(hex: "17324E"))
                                Spacer()
                                Text(driver.value)
                                    .font(.system(size: 12, weight: .bold))
                                    .foregroundStyle(Color(hex: "18AFA7"))
                            }
                            .padding(10)
                            .background(XAgeCapsuleFill())
                        }
                    }

                    Text(snapshot.nextAction)
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Color(hex: "128F92"))
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(16)
                .background(XAgeGlassCardBackground(cornerRadius: 26))
            }
            .padding(24)
        }
    }

    private func infoMetric(title: String, value: String) -> some View {
        VStack(spacing: 5) {
            Text(value)
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
                .lineLimit(1)
                .minimumScaleFactor(0.72)
            Text(title)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color(hex: "6F879B"))
        }
        .frame(maxWidth: .infinity)
        .frame(height: 58)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeHealthspanView: View {
    @Binding var selectedSection: XAgeTopSection
    let infoRequest: Int
    let scores: XAgeCompositeScores
    @State private var snapshotIndex = 0
    @State private var showInfo = false

    private var snapshots: [XAgeSnapshot] {
        weekSnapshots(from: scores.xAge)
    }

    private var snapshot: XAgeSnapshot {
        snapshots[min(snapshotIndex, snapshots.count - 1)]
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                Text("X年龄")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "123E67"))
                    .padding(.top, 12)
                Text(snapshot.updateHint)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "5D7B95"))

                HStack(spacing: 10) {
                    Button {
                        selectSnapshot(snapshotIndex - 1)
                    } label: {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 26, height: 26)
                    }
                    .buttonStyle(.plain)
                    .disabled(snapshotIndex == snapshots.startIndex)
                    .opacity(snapshotIndex == snapshots.startIndex ? 0.35 : 1)
                    .accessibilityIdentifier("xage.week.previous")
                    .accessibilityLabel("上一周")

                    Text(snapshot.range)
                        .font(.system(size: 14, weight: .bold))

                    Button {
                        selectSnapshot(snapshotIndex + 1)
                    } label: {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 13, weight: .bold))
                            .frame(width: 26, height: 26)
                    }
                    .buttonStyle(.plain)
                    .disabled(snapshotIndex == snapshots.index(before: snapshots.endIndex))
                    .opacity(snapshotIndex == snapshots.index(before: snapshots.endIndex) ? 0.35 : 1)
                    .accessibilityIdentifier("xage.week.next")
                    .accessibilityLabel("下一周")
                }
                .foregroundStyle(Color(hex: "347FB7"))
                .padding(.horizontal, 6)
                .frame(height: 32)
                .background(XAgeCapsuleFill())

                ZStack {
                    Circle()
                        .fill(
                            RadialGradient(colors: [Color(hex: "8EF7E6").opacity(0.24), Color(hex: "21B5FF").opacity(0.12), .clear], center: .center, startRadius: 20, endRadius: 170)
                        )
                        .frame(width: 272, height: 272)
                        .blur(radius: 7)
                    Image("x_age_particle_ring_blue_green")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 254, height: 254)
                        .accessibilityIdentifier("xage.particle.ring")
                    Circle()
                        .fill(.white.opacity(0.54))
                        .background(.ultraThinMaterial, in: Circle())
                        .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                        .frame(width: 154, height: 154)
                    VStack(spacing: 4) {
                        Text(snapshot.age)
                            .font(.system(size: 44, weight: .bold))
                            .foregroundStyle(Color(hex: "12324F"))
                        HStack(alignment: .center, spacing: 5) {
                            Text("X年龄")
                                .font(.system(size: 15, weight: .bold))
                                .foregroundStyle(Color(hex: "45677F"))
                                .frame(height: 20)
                            Button {
                                showInfo = true
                            } label: {
                                Image(systemName: "info.circle.fill")
                                    .font(.system(size: 13, weight: .bold))
                                    .foregroundStyle(Color(hex: "18AFA7"))
                                    .frame(width: 20, height: 20)
                                    .background(
                                        Circle()
                                            .fill(.white.opacity(0.62))
                                            .overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1))
                                    )
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("xage.xage.info.inline")
                            .accessibilityLabel("X年龄原理")
                        }
                        Text(snapshot.delta)
                            .font(.system(size: 14, weight: .bold))
                            .foregroundStyle(Color(hex: "10A88E"))
                    }
                }
                .frame(height: 262)
                .padding(.top, 2)

                XAgePaceCard(pace: snapshot.pace, isReady: snapshot.isReady)

                VStack(alignment: .leading, spacing: 7) {
                    Text(snapshot.status)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(snapshot.summary)
                        .font(.system(size: 12))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(2)
                        .lineLimit(3)
                }
                .padding(14)
                .background(XAgeGlassCardBackground(cornerRadius: 26))
                .padding(.bottom, 20)
            }
            .padding(.horizontal, 24)
        }
        .scrollIndicators(.hidden)
        .onChange(of: infoRequest) { _, _ in
            guard selectedSection == .xAge else { return }
            showInfo = true
        }
        .sheet(isPresented: $showInfo) {
            XAgeInfoSheet(snapshot: snapshot)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
    }

    private func selectSnapshot(_ index: Int) {
        guard snapshots.indices.contains(index) else { return }
        withAnimation(.spring(response: 0.28, dampingFraction: 0.86)) {
            snapshotIndex = index
        }
    }

    private func weekSnapshots(from score: XAgeAgeScore) -> [XAgeSnapshot] {
        [-1, 0].map { offset in
            let ageShift = Double(offset) * (score.pace - 1) * 0.18
            let shiftedAge = score.ageValue + ageShift
            let shiftedDelta = shiftedAge - score.chronologicalAge
            let isCurrentPrediction = offset == 0
            let canShowAge = score.isReady && !isCurrentPrediction
            return XAgeSnapshot(
                range: weekRange(offset: offset),
                updateHint: updateHint(offset: offset),
                isReady: canShowAge,
                age: canShowAge ? String(format: "%.1f", shiftedAge) : "--",
                ageRange: score.ageRange,
                delta: isCurrentPrediction ? "本周收集中" : (canShowAge ? deltaLabel(shiftedDelta) : "待评估"),
                pace: score.pace,
                confidence: score.confidence,
                status: isCurrentPrediction ? "本周预测中" : score.status,
                summary: isCurrentPrediction
                    ? "\(weekRange(offset: offset)) 的数据仍在收集中。小捷会先保留趋势输入，本周结束后再生成这一周的 X年龄。"
                    : score.summary,
                explanation: score.explanation,
                nextAction: score.nextAction,
                drivers: score.drivers
            )
        }
    }

    private func deltaLabel(_ value: Double) -> String {
        if value <= -0.15 { return "年轻 \(String(format: "%.1f", abs(value))) 岁" }
        if value >= 0.15 { return "偏大 \(String(format: "%.1f", value)) 岁" }
        return "接近实际年龄"
    }

    private func updateHint(offset: Int) -> String {
        switch offset {
        case -1:
            return "已完成更新"
        case 0:
            return "预测中 · 本周结束后更新"
        default:
            return "预测中"
        }
    }

    private func weekRange(offset: Int) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.locale = Locale(identifier: "zh_CN")
        calendar.firstWeekday = 2
        let today = Date()
        let weekStart = calendar.dateInterval(of: .weekOfYear, for: today)?.start ?? today
        let start = calendar.date(byAdding: .day, value: offset * 7, to: weekStart) ?? today
        let end = calendar.date(byAdding: .day, value: 6, to: start) ?? start
        return "\(Self.weekFormatter.string(from: start)) - \(Self.weekFormatter.string(from: end))"
    }

    private static let weekFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日"
        return formatter
    }()
}

private struct XAgePaceCard: View {
    let pace: Double
    let isReady: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("衰老进度")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text(isReady ? String(format: "%.1fx", pace) : "--")
                    .font(.system(size: 28, weight: .bold))
                    .foregroundStyle(Color(hex: "17324E"))
            }
            HStack {
                Text("慢")
                Spacer()
                Text("快")
            }
            .font(.system(size: 14, weight: .medium))
            .foregroundStyle(Color(hex: "6A8197"))

            ZStack(alignment: .leading) {
                HStack(spacing: 4) {
                    ForEach(0..<44, id: \.self) { i in
                        RoundedRectangle(cornerRadius: 1)
                            .fill(Color(hex: "577990").opacity(i % 10 == 0 ? 0.52 : 0.28))
                            .frame(width: 2, height: i % 10 == 0 ? 26 : 18)
                    }
                }
                RoundedRectangle(cornerRadius: 2)
                    .fill(LinearGradient(colors: [.white, Color(hex: "18C3B6")], startPoint: .top, endPoint: .bottom))
                    .frame(width: 4, height: 34)
                    .offset(x: markerOffset)
                    .opacity(isReady ? 1 : 0.28)
                    .shadow(color: Color(hex: "18B9D0").opacity(0.24), radius: 8, x: 0, y: 4)
            }
            .frame(height: 36)

            HStack {
                Text("-1.0x")
                Spacer()
                Text("1.0x")
                Spacer()
                Text("3.0x")
            }
            .font(.system(size: 12))
            .foregroundStyle(Color(hex: "6C8194"))
        }
        .padding(14)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }

    private var markerOffset: CGFloat {
        guard isReady else { return 130 }
        let clamped = min(max(pace, -1), 3)
        return CGFloat((clamped + 1) / 4) * 260
    }
}

private struct XAgeMoreMenu: View {
    @Binding var selectedCategory: XAgeDataPanelCategory
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    let snapshot: XAgeServerSyncSnapshot
    let onSelectCategory: (XAgeDataPanelCategory) -> Void
    let onClose: () -> Void
    @EnvironmentObject private var authManager: AuthManager
    @StateObject private var accountVM = XAgeAccountViewModel()
    @State private var showFamilyMode = false
    @State private var showPersonalInfo = false
    @State private var showMedicationManagement = false
    @State private var showHelpFeedback = false
    @State private var showAbout = false
    @State private var showLogoutConfirm = false
    @State private var showDeleteConfirm = false
    @State private var presentedCategory: XAgeDataPanelCategory?
    @State private var categoryDetailWasPresented = false

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        Text("设置")
                            .font(.system(size: 28, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Spacer()
                        Button {
                            onClose()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        Text("资料")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)
                        ForEach(XAgeDataPanelCategory.allCases) { category in
                            XAgeAccountMenuRow(
                                icon: category.iconName,
                                title: category.rawValue,
                                subtitle: category.headline
                            ) {
                                selectedCategory = category
                                onSelectCategory(category)
                                categoryDetailWasPresented = true
                                presentedCategory = category
                            }
                        }
                        XAgeAccountMenuRow(
                            icon: "pills.fill",
                            title: "用药管理",
                            subtitle: "用药记录、服药时间和本地提醒"
                        ) {
                            showMedicationManagement = true
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("账号管理")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)

                        XAgeAccountMenuRow(
                            icon: "person.text.rectangle.fill",
                            title: "个人信息与权限",
                            subtitle: "资料完整度、健康权限和隐私授权"
                        ) {
                            showPersonalInfo = true
                        }
                        XAgeAccountMenuRow(
                            icon: "person.2.fill",
                            title: "关联用户",
                            subtitle: "家庭模式、邀请和授权"
                        ) {
                            showFamilyMode = true
                        }
                        XAgeAccountMenuRow(
                            icon: "rectangle.portrait.and.arrow.right",
                            title: "退出登录",
                            subtitle: "切换账号或重新登录"
                        ) {
                            showLogoutConfirm = true
                        }
                        XAgeAccountMenuRow(
                            icon: "person.crop.circle.badge.xmark",
                            title: "注销账号",
                            subtitle: "停用账号并清除登录态",
                            destructive: true
                        ) {
                            showDeleteConfirm = true
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    VStack(alignment: .leading, spacing: 10) {
                        Text("帮助与关于")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "5D7890"))
                            .padding(.horizontal, 4)

                        XAgeAccountMenuRow(
                            icon: "questionmark.bubble.fill",
                            title: "帮助与反馈",
                            subtitle: "提交问题、查看常见操作"
                        ) {
                            showHelpFeedback = true
                        }
                        XAgeAccountMenuRow(
                            icon: "info.circle.fill",
                            title: "关于小捷",
                            subtitle: "版本说明与隐私声明"
                        ) {
                            showAbout = true
                        }
                    }
                    .padding(14)
                    .background(XAgeGlassCardBackground(cornerRadius: 28))

                    Text("皖ICP备2026008853号-2")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Color(hex: "7D9AB1"))
                        .frame(maxWidth: .infinity)
                        .padding(.top, 2)
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
        .sheet(isPresented: $showFamilyMode) {
            XAgeFamilyModeSheet()
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showPersonalInfo) {
            XAgePersonalInfoPermissionSheet(snapshot: snapshot, appleHealthSync: appleHealthSync)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showMedicationManagement) {
            XAgeMedicationManagementView {
                showMedicationManagement = false
                onClose()
            }
            .presentationDetents([.large])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showHelpFeedback) {
            XAgeHelpFeedbackSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showAbout) {
            XAgeAboutSheet()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .fullScreenCover(item: $presentedCategory, onDismiss: closeMenuAfterCategoryDetail) { category in
            XAgePanelDestinationView(
                category: category,
                appleHealthSync: appleHealthSync,
                snapshot: snapshot,
                onClose: {
                    presentedCategory = nil
                }
            )
        }
        .sheet(isPresented: $showDeleteConfirm) {
            XAgeDeleteAccountSheet(
                isWorking: accountVM.isWorking,
                onCancel: { showDeleteConfirm = false },
                onConfirm: {
                    Task {
                        let accountToken = authManager.token
                        if await accountVM.deleteAccountOnServer() {
                            showDeleteConfirm = false
                            onClose()
                            authManager.logout(ifCurrentToken: accountToken)
                        }
                    }
                }
            )
            .presentationDetents([.medium])
            .interactiveDismissDisabled(accountVM.isWorking)
        }
        .alert("确认退出", isPresented: $showLogoutConfirm) {
            Button("取消", role: .cancel) {}
            Button("退出", role: .destructive) {
                let accountToken = authManager.token
                onClose()
                authManager.logout(ifCurrentToken: accountToken)
                Task {
                    await accountVM.revokeLogoutToken(accountToken)
                }
            }
        } message: {
            Text("退出后会回到登录页，可使用其他账号登录。")
        }
        .alert("账号操作失败", isPresented: Binding(
            get: { accountVM.errorMessage != nil },
            set: { if !$0 { accountVM.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(accountVM.errorMessage ?? "")
        }
    }

    private func closeMenuAfterCategoryDetail() {
        guard categoryDetailWasPresented else { return }
        categoryDetailWasPresented = false
        DispatchQueue.main.async {
            onClose()
        }
    }
}

@MainActor
final class XAgeAccountViewModel: ObservableObject {
    @Published var isWorking = false
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func logout(authManager: AuthManager) async {
        let accountToken = authManager.token
        isWorking = true
        defer { isWorking = false }
        do {
            try await api.postVoid("/api/auth/logout")
        } catch {
            // 退出登录必须允许本地完成，避免网络错误把用户锁在当前账号。
        }
        authManager.logout(ifCurrentToken: accountToken)
    }

    func revokeLogoutToken(_ token: String) async {
        guard !token.isEmpty,
              let url = URL(string: AppEnvironment.apiBaseURL + "/api/auth/logout")
        else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 4
        _ = try? await URLSession.shared.data(for: request)
    }

    func deleteAccount(authManager: AuthManager) async {
        let accountToken = authManager.token
        if await deleteAccountOnServer() {
            authManager.logout(ifCurrentToken: accountToken)
        }
    }

    func deleteAccountOnServer() async -> Bool {
        isWorking = true
        defer { isWorking = false }
        do {
            try await api.deleteVoid("/api/users/me")
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }
}

private struct XAgeMoreMenuRow: View {
    let identifier: String
    let icon: String
    let title: String
    let subtitle: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 38, height: 38)
                    .background(
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: selected ? [Color(hex: "238AD6"), Color(hex: "20CDB1")] : [Color(hex: "7ABBE7"), Color(hex: "92DDCE")],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    )

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
            .padding(.horizontal, 14)
            .frame(height: 64)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(title)、\(subtitle)")
        .accessibilityValue(selected ? "已选中" : "")
        .xAgeAccessibilitySelected(selected)
        .accessibilityIdentifier("xage.more.category.\(identifier)")
    }
}

private struct XAgeAccountMenuRow: View {
    let icon: String
    let title: String
    let subtitle: String
    var destructive = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(destructive ? Color(hex: "D85A66") : Color(hex: "237FC4"))
                    .frame(width: 38, height: 38)
                    .background(Circle().fill(.white.opacity(0.6)).overlay(Circle().stroke(.white.opacity(0.78), lineWidth: 1)))

                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(destructive ? Color(hex: "B43D4B") : Color(hex: "173F64"))
                    Text(subtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                        .lineLimit(1)
                }

                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: "7D9AB1"))
            }
            .padding(.horizontal, 14)
            .frame(height: 62)
            .background(XAgeGlassCardBackground(cornerRadius: 22))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("xage.account.\(title)")
    }
}

private struct XAgeDeleteAccountSheet: View {
    let isWorking: Bool
    let onCancel: () -> Void
    let onConfirm: () -> Void
    @State private var confirmText = ""

    private var canConfirm: Bool {
        confirmText.trimmingCharacters(in: .whitespacesAndNewlines) == "注销"
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 12) {
                    Image(systemName: "person.crop.circle.badge.xmark")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color(hex: "D85A66"))
                        .frame(width: 52, height: 52)
                        .background(XAgeCapsuleFill())
                    VStack(alignment: .leading, spacing: 4) {
                        Text("注销账号")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(Color(hex: "123E67"))
                        Text("账号停用后会立即退出登录")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Color(hex: "5D7890"))
                    }
                }

                Text("系统会停用当前账号并清除本机登录态。为避免误触，请输入“注销”后再确认。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())

                TextField("输入：注销", text: $confirmText)
                    .font(.system(size: 16, weight: .bold))
                    .textInputAutocapitalization(.never)
                    .disableAutocorrection(true)
                    .padding(.horizontal, 14)
                    .frame(height: 48)
                    .background(XAgeGlassCardBackground(cornerRadius: 22))

                HStack(spacing: 10) {
                    Button(action: onCancel) {
                        Text("取消")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(hex: "365F80"))
                            .frame(maxWidth: .infinity)
                            .frame(height: 46)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .disabled(isWorking)

                    Button(action: onConfirm) {
                        HStack(spacing: 8) {
                            if isWorking {
                                ProgressView()
                                    .tint(.white)
                            }
                            Text(isWorking ? "处理中" : "确认注销")
                                .font(.system(size: 15, weight: .bold))
                        }
                        .foregroundStyle(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 46)
                        .background(
                            Capsule()
                                .fill(canConfirm ? AnyShapeStyle(Color(hex: "D85A66")) : AnyShapeStyle(Color(hex: "AEBFCD")))
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(!canConfirm || isWorking)
                    .accessibilityIdentifier("xage.account.delete.confirm")
                }
            }
            .padding(24)
        }
    }
}

private struct XAgePersonalInfoPermissionSheet: View {
    let snapshot: XAgeServerSyncSnapshot
    @ObservedObject var appleHealthSync: AppleHealthSyncViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "个人信息与权限",
            subtitle: "查看资料完整度和健康数据授权",
            icon: "person.text.rectangle.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "资料完整度", value: "\(snapshot.profileCompletion)%")
            XAgeMetricDetailRow(title: "身高", value: snapshot.profileHeightCm.map { "\(Int($0.rounded())) cm" } ?? "待补充")
            XAgeMetricDetailRow(title: "体重", value: snapshot.profileWeightKg.map { String(format: "%.1f kg", $0) } ?? "待补充")
            XAgeMetricDetailRow(title: "Apple 健康", value: appleHealthSync.lastSyncedAt == nil ? "未同步" : appleHealthSync.statusTitle)
            XAgeMetricDetailRow(title: "健康资料", value: "\(snapshot.recordCount + snapshot.examCount) 份")
            Text("家庭共享、Apple 健康和报告资料都需要单独授权。小捷只在你允许后读取数据，并按来源和测量时间写入用户端趋势。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

private struct XAgeHelpFeedbackSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "帮助与反馈",
            subtitle: "常见操作和问题反馈入口",
            icon: "questionmark.bubble.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "上传报告", value: "资料 > 报告")
            XAgeMetricDetailRow(title: "补录指标", value: "数据卡片 > 手动记录")
            XAgeMetricDetailRow(title: "同步日常", value: "资料 > 日常")
            Text("遇到识别失败、数据不同步或评分异常时，可以把问题截图和发生时间发给小捷团队。后续版本会把反馈入口接入线上工单。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

private struct XAgeAboutSheet: View {
    @Environment(\.dismiss) private var dismiss

    private var versionText: String {
        let info = Bundle.main.infoDictionary
        let version = info?["CFBundleShortVersionString"] as? String ?? "1.0"
        let build = info?["CFBundleVersion"] as? String ?? "-"
        return "\(version)(\(build))"
    }

    var body: some View {
        XAgeSettingsInfoSheetScaffold(
            title: "关于小捷",
            subtitle: "版本说明",
            icon: "info.circle.fill",
            onClose: { dismiss() }
        ) {
            XAgeMetricDetailRow(title: "当前版本", value: versionText)
            XAgeMetricDetailRow(title: "应用名称", value: "小捷")
            XAgeMetricDetailRow(title: "备案信息", value: "皖ICP备2026008853号-2")
            Text("本版本聚焦 XAGE 数据、问答和 X年龄体验：健康数据按来源和测量时间同步，报告上传进入 AI 识别队列，评分在数据不足时先显示待评估。")
                .font(.system(size: 13))
                .foregroundStyle(Color(hex: "496A83"))
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
                .padding(14)
                .background(XAgeCapsuleFill())
        }
    }
}

private struct XAgeSettingsInfoSheetScaffold<Content: View>: View {
    let title: String
    let subtitle: String
    let icon: String
    let onClose: () -> Void
    let content: () -> Content

    init(
        title: String,
        subtitle: String,
        icon: String,
        onClose: @escaping () -> Void,
        @ViewBuilder content: @escaping () -> Content
    ) {
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.onClose = onClose
        self.content = content
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 12) {
                        Image(systemName: icon)
                            .font(.system(size: 22, weight: .bold))
                            .foregroundStyle(Color(hex: "237FC4"))
                            .frame(width: 52, height: 52)
                            .background(XAgeCapsuleFill())
                        VStack(alignment: .leading, spacing: 4) {
                            Text(title)
                                .font(.system(size: 24, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                            Text(subtitle)
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button(action: onClose) {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("关闭")
                    }

                    VStack(alignment: .leading, spacing: 10) {
                        content()
                    }
                    .padding(16)
                    .background(XAgeGlassCardBackground(cornerRadius: 26))
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
        }
    }
}

private struct XAgeFamilyModeSheet: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var vm = FamilyViewModel()
    @State private var invitePhone = ""
    @State private var inviteRelation = ""
    @State private var inviteCode = ""
    @State private var displayName = ""

    var body: some View {
        ZStack {
            XAgeLiquidBackground()
                .ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("关联用户")
                                .font(.system(size: 28, weight: .bold))
                                .foregroundStyle(Color(hex: "123E67"))
                            Text("家庭模式需要逐项授权，敏感健康资料默认不共享。")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(Color(hex: "5D7890"))
                        }
                        Spacer()
                        Button {
                            dismiss()
                        } label: {
                            Image(systemName: "xmark")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(Color(hex: "1268BD"))
                                .frame(width: 34, height: 34)
                                .background(XAgeCapsuleFill())
                        }
                        .buttonStyle(.plain)
                    }
                    .padding(.top, 10)

                    inviteCard
                    acceptCard
                    membersCard
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)

            if vm.loading {
                ProgressView()
                    .controlSize(.large)
                    .padding(18)
                    .background(XAgeGlassCardBackground(cornerRadius: 22))
            }
        }
        .task { await vm.load() }
        .alert("家庭模式提示", isPresented: Binding(
            get: { vm.message != nil },
            set: { if !$0 { vm.message = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.message ?? "")
        }
        .alert("家庭模式错误", isPresented: Binding(
            get: { vm.errorMessage != nil },
            set: { if !$0 { vm.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(vm.errorMessage ?? "")
        }
    }

    private var inviteCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "邀请家人", subtitle: "生成 7 天有效的邀请码")
            HStack(spacing: 8) {
                XAgeGlassTextField(placeholder: "手机号（可选）", text: $invitePhone, keyboardType: .phonePad)
                XAgeGlassTextField(placeholder: "关系", text: $inviteRelation)
            }
            Button {
                Task { await vm.createInvite(targetPhone: invitePhone, relation: inviteRelation) }
            } label: {
                XAgeGradientActionLabel(title: "生成邀请码", icon: "person.badge.plus")
            }
            .buttonStyle(.plain)

            if let invite = vm.latestInvite {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(invite.invite_code)
                            .font(.system(size: 26, weight: .bold, design: .monospaced))
                            .foregroundStyle(Color(hex: "12324F"))
                        Text("家人在自己的账号中输入后加入")
                            .font(.system(size: 12))
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                    Spacer()
                    Text("7天有效")
                        .font(.system(size: 11, weight: .bold))
                        .foregroundStyle(Color(hex: "347FB7"))
                        .padding(.horizontal, 10)
                        .frame(height: 28)
                        .background(XAgeCapsuleFill())
                }
                .padding(14)
                .background(XAgeCapsuleFill())
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private var acceptCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "加入家庭", subtitle: "输入对方分享的邀请码")
            XAgeGlassTextField(placeholder: "邀请码", text: $inviteCode)
            XAgeGlassTextField(placeholder: "我的显示名（可选）", text: $displayName)
            Button {
                Task { await vm.acceptInvite(code: inviteCode, displayName: displayName) }
            } label: {
                XAgeGradientActionLabel(title: "确认加入", icon: "number.square")
            }
            .buttonStyle(.plain)
            .disabled(inviteCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private var membersCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            XAgeSectionHeader(title: "授权管理", subtitle: "家人加入后才会出现在这里")
            let members = vm.members.filter { $0.user_id != vm.currentUserId }
            if members.isEmpty {
                Text("暂无关联用户。邀请或加入家庭后，可以在这里给家人单独开启查看权限。")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(14)
                    .background(XAgeCapsuleFill())
            } else {
                ForEach(members) { member in
                    XAgeFamilyMemberCard(member: member, vm: vm)
                }
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }
}

private struct XAgeFamilyMemberCard: View {
    let member: FamilyMember
    @ObservedObject var vm: FamilyViewModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text(member.bestName)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text(member.relation ?? member.role)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }
                Spacer()
                Text(member.status == "active" ? "已关联" : "待加入")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color(hex: "347FB7"))
                    .frame(width: 58, height: 28)
                    .background(XAgeCapsuleFill())
            }

            ForEach(FamilyPermissionField.allCases) { field in
                Toggle(isOn: Binding(
                    get: { vm.value(for: member.user_id, field: field) },
                    set: { value in
                        Task { await vm.togglePermission(viewerUserId: member.user_id, field: field, value: value) }
                    }
                )) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(field.title)
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "173F64"))
                        Text(field.subtitle)
                            .font(.system(size: 11))
                            .foregroundStyle(Color(hex: "6C8194"))
                    }
                }
                .tint(Color(hex: "20CDB1"))
            }
        }
        .padding(14)
        .background(XAgeCapsuleFill())
    }
}

private struct XAgeSectionHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            Text(subtitle)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
        }
    }
}

private struct XAgeGlassTextField: View {
    let placeholder: String
    @Binding var text: String
    var keyboardType: UIKeyboardType = .default

    var body: some View {
        TextField(placeholder, text: $text)
            .font(.system(size: 14, weight: .semibold))
            .keyboardType(keyboardType)
            .textInputAutocapitalization(.never)
            .disableAutocorrection(true)
            .padding(.horizontal, 12)
            .frame(height: 42)
            .background(XAgeCapsuleFill())
    }
}

private struct XAgeGradientActionLabel: View {
    let title: String
    let icon: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .bold))
            Text(title)
                .font(.system(size: 14, weight: .bold))
        }
        .foregroundStyle(.white)
        .frame(maxWidth: .infinity)
        .frame(height: 42)
        .background(
            Capsule()
                .fill(LinearGradient(colors: [Color(hex: "238AD6"), Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
        )
    }
}

private struct CapsuleButton: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(Color(hex: "365F80"))
                .frame(width: 56, height: 30)
                .background(XAgeCapsuleFill())
        }
        .buttonStyle(.plain)
    }
}

private struct XAgeGlassCardBackground: View {
    var cornerRadius: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
            .fill(.white.opacity(0.56))
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.84), lineWidth: 1)
            )
            .shadow(color: Color(hex: "73C8F0").opacity(0.18), radius: 28, x: 0, y: 14)
    }
}

private struct XAgeCapsuleFill: View {
    var body: some View {
        Capsule()
            .fill(.white.opacity(0.58))
            .background(.ultraThinMaterial, in: Capsule())
            .overlay(Capsule().stroke(.white.opacity(0.88), lineWidth: 1))
            .shadow(color: Color(hex: "7ACAF5").opacity(0.12), radius: 14, x: 0, y: 7)
    }
}

private struct XAgeLiquidBackground: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(hex: "E8F7FF"), Color(hex: "D5ECFF"), Color(hex: "F7FCFF")],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            Circle()
                .fill(Color(hex: "61E7E1").opacity(0.28))
                .frame(width: 235, height: 235)
                .blur(radius: 26)
                .offset(x: -150, y: -260)
            Circle()
                .fill(Color(hex: "8CC8FF").opacity(0.32))
                .frame(width: 260, height: 300)
                .blur(radius: 30)
                .offset(x: 160, y: -320)
            Circle()
                .fill(Color(hex: "C9C2FF").opacity(0.22))
                .frame(width: 230, height: 260)
                .blur(radius: 34)
                .offset(x: 135, y: 150)
            Rectangle()
                .fill(.white.opacity(0.2))
                .frame(width: 88)
                .blur(radius: 22)
                .rotationEffect(.degrees(5))
                .offset(x: -6)
        }
    }
}
