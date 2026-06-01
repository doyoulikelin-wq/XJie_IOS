import Foundation

@MainActor
final class HealthBriefViewModel: ObservableObject {
    @Published var loading = false
    @Published var briefing: TodayBriefing?
    @Published var reports: HealthReports?
    @Published var aiSummary = ""
    @Published var summaryLoading = false
    @Published var summaryProgress: Double = 0
    @Published var summaryStage: String = ""
    @Published var errorMessage: String?

    private let api: APIServiceProtocol

    init(api: APIServiceProtocol = APIService.shared) {
        self.api = api
    }

    func fetchData() async {
        loading = true
        defer { loading = false }
        async let b: TodayBriefing? = try? await api.get("/api/agent/today")
        async let r: HealthReports? = try? await api.get("/api/health-reports")
        async let s: HealthDataSummary? = try? await api.get("/api/health-data/summary")
        let fetchedBriefing = await b
        let fetchedReports = await r
        let fetchedSummary = await s
        guard !Task.isCancelled else { return }
        briefing = fetchedBriefing
        reports = fetchedReports
        if let text = fetchedSummary?.summary_text, !text.isEmpty {
            aiSummary = text
        }
    }

    func loadAISummary() async {
        summaryLoading = true
        summaryProgress = 0
        summaryStage = "提交任务..."
        defer { summaryLoading = false; summaryStage = "" }

        do {
            // 1. Submit async task
            let task: SummaryTaskResponse = try await api.post("/api/health-data/summary/generate-async")
            let taskId = task.task_id

            // 2. Poll every 3 seconds
            while !Task.isCancelled {
                try await Task.sleep(for: .seconds(3))
                guard !Task.isCancelled else { return }

                let status: SummaryTaskResponse = try await api.get("/api/health-data/summary/task/\(taskId)")

                summaryProgress = status.progress_pct ?? 0

                switch status.stage {
                case "l1":
                    summaryStage = "分析第 \(status.stage_current ?? 0)/\(status.stage_total ?? 0) 次检查..."
                case "l2":
                    summaryStage = "汇总第 \(status.stage_current ?? 0)/\(status.stage_total ?? 0) 年趋势..."
                case "l3":
                    summaryStage = "生成最终报告..."
                default:
                    summaryStage = "准备中..."
                }

                if status.status == "done" {
                    // Fetch the final summary
                    let result: HealthDataSummary = try await api.get("/api/health-data/summary")
                    guard !Task.isCancelled else { return }
                    aiSummary = result.summary_text ?? "暂无摘要"
                    summaryProgress = 1.0
                    return
                }

                if status.status == "failed" {
                    aiSummary = "生成失败: \(status.error_message ?? "未知错误")"
                    return
                }
            }
        } catch {
            guard !Task.isCancelled else { return }
            aiSummary = "获取失败，请重试"
            errorMessage = error.localizedDescription
        }
    }
}

@MainActor
final class HealthPlanViewModel: ObservableObject {
    @Published var plans: [HealthPlan] = []
    @Published var selectedPlan: HealthPlanDetail?
    @Published var week: TubeWeek?
    @Published var loading = false
    @Published var errorMessage: String?
    @Published var completingType: String?
    @Published var lastCompletedType: String?
    @Published var creatingPlan = false
    @Published var revisionProposal: PlanRevisionProposal?
    @Published var revisionLoading = false
    @Published var revisionApplying = false

    private let api: APIServiceProtocol
    private var weekStartDate: Date

    init(api: APIServiceProtocol = APIService.shared, today: Date = Date()) {
        self.api = api
        self.weekStartDate = Self.startOfWeek(for: today)
    }

    func refresh() async {
        loading = true
        defer { loading = false }
        async let planResult: HealthPlanListResponse = api.get("/api/health-plans")
        async let weekResult: TubeWeek = api.get("/api/health-plans/week?week_start=\(Self.dayFormatter.string(from: weekStartDate))")
        do {
            let fetchedPlans = try await planResult
            let fetchedWeek = try await weekResult
            plans = fetchedPlans.items
            week = fetchedWeek
            if selectedPlan == nil, let first = plans.first {
                selectedPlan = try? await api.get("/api/health-plans/\(first.id)")
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func selectPlan(_ plan: HealthPlan) async {
        do {
            selectedPlan = try await api.get("/api/health-plans/\(plan.id)")
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func previousWeek() async {
        weekStartDate = Calendar.current.date(byAdding: .day, value: -7, to: weekStartDate) ?? weekStartDate
        await refresh()
    }

    func nextWeek() async {
        weekStartDate = Calendar.current.date(byAdding: .day, value: 7, to: weekStartDate) ?? weekStartDate
        await refresh()
    }

    func backToThisWeek() async {
        weekStartDate = Self.startOfWeek(for: Date())
        await refresh()
    }

    func completeToday(taskType: String) async {
        guard let today = week?.today else { return }
        completingType = taskType
        defer { completingType = nil }
        do {
            let res: TubeCompleteResponse = try await api.post(
                "/api/health-plans/tube/complete",
                body: TubeCompleteRequest(date: today, task_type: taskType, amount: 1, value: nil)
            )
            if let currentWeek = week,
               let index = currentWeek.days.firstIndex(where: { $0.date == res.day.date }) {
                var days = currentWeek.days
                days[index] = res.day
                week = TubeWeek(
                    week_start: currentWeek.week_start,
                    week_end: currentWeek.week_end,
                    today: currentWeek.today,
                    has_omics_data: currentWeek.has_omics_data,
                    has_medication_need: currentWeek.has_medication_need,
                    task_types: currentWeek.task_types,
                    days: days
                )
            } else {
                await refresh()
            }
            lastCompletedType = taskType
            NotificationCenter.default.post(name: .healthTreeDidChange, object: nil)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func updateTask(_ task: PlanTask, request: PlanTaskUpdateRequest) async -> Bool {
        do {
            let _: PlanTask = try await api.patch("/api/health-plans/tasks/\(task.id)", body: request)
            let selectedId = selectedPlan?.id
            await refresh()
            if let selectedId {
                selectedPlan = try? await api.get("/api/health-plans/\(selectedId)")
            }
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func generateAIRevision() async {
        guard !revisionLoading else { return }
        revisionLoading = true
        defer { revisionLoading = false }
        do {
            revisionProposal = try await api.post(
                "/api/health-plans/revision/generate",
                body: PlanRevisionGenerateRequest(date: week?.today, purpose: "根据用户基本信息、近期健康数据、病史和执行反馈修正整个计划"),
                timeout: 120
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func applyAIRevision(acceptedKeys: [String], acceptAll: Bool = false, rejectAll: Bool = false) async -> Bool {
        guard let proposal = revisionProposal else { return false }
        revisionApplying = true
        defer { revisionApplying = false }
        do {
            let _: PlanRevisionProposal = try await api.post(
                "/api/health-plans/revision/\(proposal.id)/apply",
                body: PlanRevisionApplyRequest(
                    accepted_task_keys: acceptedKeys,
                    accept_all: acceptAll,
                    reject_all: rejectAll
                )
            )
            revisionProposal = nil
            let selectedId = selectedPlan?.id
            await refresh()
            if let selectedId {
                selectedPlan = try? await api.get("/api/health-plans/\(selectedId)")
            }
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func createPlan(from questionnaire: HealthPlanQuestionnaireRequest) async -> Bool {
        creatingPlan = true
        defer { creatingPlan = false }
        do {
            selectedPlan = try await api.post("/api/health-plans/questionnaire", body: questionnaire)
            NotificationCenter.default.post(name: .healthTreeDidChange, object: nil)
            await refresh()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func clearCompletionEffect() {
        lastCompletedType = nil
    }

    var isViewingCurrentWeek: Bool {
        weekStartDate == Self.startOfWeek(for: Date())
    }

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private static func startOfWeek(for date: Date) -> Date {
        let calendar = Calendar.current
        let startOfDay = calendar.startOfDay(for: date)
        let weekday = calendar.component(.weekday, from: startOfDay)
        let daysFromMonday = (weekday + 5) % 7
        return calendar.date(byAdding: .day, value: -daysFromMonday, to: startOfDay) ?? startOfDay
    }
}

extension Notification.Name {
    static let healthTreeDidChange = Notification.Name("xjie.healthTreeDidChange")
}
