import Charts
import SwiftUI

struct XAgeMetricTrendSample: Identifiable, Equatable {
    let id: String
    let date: Date
    let dateLabel: String
    let value: Double
    let displayValue: String
    let isAbnormal: Bool
}

enum XAgeMetricTrendContract {
    private static let pointSpacing: CGFloat = 52
    private static let horizontalPadding: CGFloat = 80
    private static let maximumChartWidth: CGFloat = 6_000

    static func samples(from trend: IndicatorTrend) -> [XAgeMetricTrendSample] {
        trend.points.enumerated().compactMap { index, point in
            guard point.value.isFinite, let date = date(from: point) else { return nil }
            return XAgeMetricTrendSample(
                id: "\(point.id)-\(index)",
                date: date,
                dateLabel: fullDateFormatter.string(from: date),
                value: point.value,
                displayValue: IndicatorTrendPresentationContract.displayValue(
                    for: point,
                    indicatorName: trend.name
                ),
                isAbnormal: point.abnormal
            )
        }
        .sorted {
            if $0.date == $1.date { return $0.id < $1.id }
            return $0.date < $1.date
        }
    }

    static func chartWidth(pointCount: Int, viewportWidth: CGFloat) -> CGFloat {
        let viewport = max(viewportWidth, 1)
        guard pointCount > 7 else { return viewport }
        return min(
            max(viewport, horizontalPadding + CGFloat(pointCount - 1) * pointSpacing),
            maximumChartWidth
        )
    }

    static func nearestIndex(to date: Date, in samples: [XAgeMetricTrendSample]) -> Int? {
        guard !samples.isEmpty else { return nil }
        return samples.indices.min { left, right in
            abs(samples[left].date.timeIntervalSince(date))
                < abs(samples[right].date.timeIntervalSince(date))
        }
    }

    static func steppedIndex(currentIndex: Int?, pointCount: Int, delta: Int) -> Int? {
        guard pointCount > 0 else { return nil }
        let current = currentIndex?.clamped(to: 0...(pointCount - 1)) ?? (pointCount - 1)
        return (current + delta).clamped(to: 0...(pointCount - 1))
    }

    static func recentWeightSamples(
        from trend: IndicatorTrend?,
        now: Date,
        calendar: Calendar = Calendar(identifier: .gregorian)
    ) -> [XAgeMetricTrendSample] {
        guard let trend,
              let start = calendar.date(byAdding: .month, value: -3, to: now) else { return [] }
        return samples(from: trend).filter { $0.date >= start && $0.date <= now }
    }

    static func weightYDomain(values: [Double]) -> ClosedRange<Double> {
        let finiteValues = values.filter(\.isFinite)
        guard let minimum = finiteValues.min(), let maximum = finiteValues.max() else {
            return 45...75
        }
        return (minimum - 5)...(maximum + 5)
    }

    static func weightChartWidth(
        windowStart: Date,
        windowEnd: Date,
        viewportWidth: CGFloat,
        calendar: Calendar = Calendar(identifier: .gregorian)
    ) -> CGFloat {
        let dayCount = max(calendar.dateComponents([.day], from: windowStart, to: windowEnd).day ?? 0, 15)
        return max(viewportWidth, viewportWidth * CGFloat(dayCount) / 15)
    }

    static func bodyMassIndex(weightKilograms: Double?, heightCentimeters: Double?) -> Double? {
        guard let weightKilograms,
              weightKilograms.isFinite,
              weightKilograms > 0,
              let heightCentimeters,
              heightCentimeters.isFinite,
              heightCentimeters > 0 else { return nil }
        let heightMeters = heightCentimeters / 100
        return weightKilograms / (heightMeters * heightMeters)
    }

    static func latestWeight(
        from trend: IndicatorTrend?,
        fallbackValue: String,
        fallbackIsPlaceholder: Bool
    ) -> Double? {
        if let trend, let latest = samples(from: trend).last?.value {
            return latest
        }
        guard !fallbackIsPlaceholder else { return nil }
        return Double(fallbackValue.replacingOccurrences(of: ",", with: "."))
    }

    private static func date(from point: TrendPoint) -> Date? {
        let raw = point.displayDate.trimmingCharacters(in: .whitespacesAndNewlines)
        if let parsed = dayFormatter.date(from: String(raw.prefix(10))) {
            return parsed
        }
        if let measuredAt = point.measured_at {
            return Utils.parseISO(measuredAt)
        }
        return nil
    }

    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    private static let fullDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy年M月d日"
        return formatter
    }()
}

enum XAgeWeightPickerContract {
    static let integerRange = 20...250
    static let tenthRange = 0...9

    static func components(for weight: Double?) -> (integer: Int, tenth: Int) {
        guard let weight, weight.isFinite else { return (65, 0) }
        let tenths = Int((weight * 10).rounded())
        let clampedTenths = min(max(tenths, integerRange.lowerBound * 10), integerRange.upperBound * 10 + 9)
        return (clampedTenths / 10, clampedTenths % 10)
    }

    static func weight(integer: Int, tenth: Int) -> Double {
        Double(integer) + Double(tenth) / 10
    }
}

enum XAgeHeightEntryContract {
    static let validRange = 60...210
    static let errorMessage = "数据范围异常，请填写正确数字。"

    static func appending(_ digit: Int, to input: String) -> String {
        guard (0...9).contains(digit), input.count < 3 else { return input }
        if input == "0" { return String(digit) }
        return input + String(digit)
    }

    static func deletingLast(from input: String) -> String {
        String(input.dropLast())
    }

    static func validatedHeight(from input: String) -> Int? {
        guard let value = Int(input), validRange.contains(value) else { return nil }
        return value
    }
}

struct XAgeWeightRecordSnapshot {
    let metric: XAgeMetric
    let trend: IndicatorTrend?
    let heightCentimeters: Double?
}

struct XAgeWeightRecordFlowView: View {
    let refresh: () async -> XAgeWeightRecordSnapshot

    @State private var snapshot: XAgeWeightRecordSnapshot
    @State private var showsPicker = false
    @State private var showsHeightEntry = false

    init(
        metric: XAgeMetric,
        trend: IndicatorTrend?,
        heightCentimeters: Double?,
        refresh: @escaping () async -> XAgeWeightRecordSnapshot
    ) {
        self.refresh = refresh
        _snapshot = State(initialValue: XAgeWeightRecordSnapshot(
            metric: metric,
            trend: trend,
            heightCentimeters: heightCentimeters
        ))
    }

    var body: some View {
        XAgeWeightRecordDetailView(
            metric: snapshot.metric,
            trend: snapshot.trend,
            heightCentimeters: snapshot.heightCentimeters,
            onRecordWeight: { showsPicker = true },
            onRecordHeight: { showsHeightEntry = true }
        )
        .sheet(isPresented: $showsPicker) {
            XAgeWeightPickerSheet(
                metric: snapshot.metric,
                initialWeight: snapshot.trend
                    .flatMap { XAgeMetricTrendContract.samples(from: $0).last?.value }
                    ?? Double(snapshot.metric.value.replacingOccurrences(of: ",", with: ".")),
                onCancel: { showsPicker = false },
                onSaved: refreshAfterSaving
            )
            .presentationDetents([.height(390)])
            .presentationDragIndicator(.visible)
        }
        .sheet(isPresented: $showsHeightEntry) {
            XAgeHeightEntrySheet(
                initialHeight: snapshot.heightCentimeters.map { Int($0.rounded()) },
                onCancel: { showsHeightEntry = false },
                onSaved: refreshAfterSavingHeight
            )
            .presentationDetents([.height(610)])
            .presentationDragIndicator(.hidden)
        }
        .accessibilityIdentifier("xage.weight.page")
    }

    private func refreshAfterSaving() {
        Task {
            let refreshedSnapshot = await refresh()
            await MainActor.run {
                snapshot = refreshedSnapshot
                showsPicker = false
                showsHeightEntry = false
            }
        }
    }

    private func refreshAfterSavingHeight(_ height: Int) {
        snapshot = XAgeWeightRecordSnapshot(
            metric: snapshot.metric,
            trend: snapshot.trend,
            heightCentimeters: Double(height)
        )
        showsHeightEntry = false

        Task {
            let refreshedSnapshot = await refresh()
            await MainActor.run {
                snapshot = XAgeWeightRecordSnapshot(
                    metric: refreshedSnapshot.metric,
                    trend: refreshedSnapshot.trend,
                    heightCentimeters: refreshedSnapshot.heightCentimeters ?? Double(height)
                )
            }
        }
    }
}

struct XAgeHeightEntrySheet: View {
    let onCancel: () -> Void
    let onSaved: (Int) -> Void

    @StateObject private var viewModel = ManualIndicatorViewModel()
    @State private var input: String
    @State private var validationMessage: String?

    init(initialHeight: Int?, onCancel: @escaping () -> Void, onSaved: @escaping (Int) -> Void) {
        self.onCancel = onCancel
        self.onSaved = onSaved
        _input = State(initialValue: initialHeight.map(String.init) ?? "")
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            valuePanel
            keypad
        }
        .background(Color(hex: "F3F6FA").ignoresSafeArea())
        .interactiveDismissDisabled(viewModel.saving)
        .onChange(of: viewModel.savedOk) { _, saved in
            guard saved else { return }
            guard let height = XAgeHeightEntryContract.validatedHeight(from: input) else { return }
            onSaved(height)
        }
        .alert("保存失败", isPresented: Binding(
            get: { viewModel.errorMessage != nil },
            set: { if !$0 { viewModel.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
        .accessibilityIdentifier("xage.height.entry")
    }

    private var header: some View {
        HStack {
            Spacer()
            VStack(spacing: 2) {
                Text("记录身高")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text("单位：cm")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color(hex: "71869A"))
            }
            Spacer()
            Button(action: onCancel) {
                Image(systemName: "xmark")
                    .font(.system(size: 17, weight: .bold))
                    .foregroundStyle(Color(hex: "7B8796"))
                    .frame(width: 44, height: 44)
            }
            .disabled(viewModel.saving)
            .accessibilityLabel("关闭记录身高")
            .accessibilityIdentifier("xage.height.entry.close")
        }
        .overlay(alignment: .leading) {
            Color.clear.frame(width: 44, height: 44)
        }
        .padding(.horizontal, 14)
        .padding(.top, 8)
        .padding(.bottom, 10)
        .background(.white)
    }

    private var valuePanel: some View {
        VStack(spacing: 10) {
            HStack(alignment: .lastTextBaseline, spacing: 8) {
                Text(input.isEmpty ? "---" : input)
                    .font(.system(size: 58, weight: .medium, design: .rounded))
                    .foregroundStyle(input.isEmpty ? Color(hex: "AAB5C1") : Color(hex: "15B88A"))
                    .monospacedDigit()
                    .accessibilityIdentifier("xage.height.entry.value")
                Text("cm")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundStyle(Color(hex: "15B88A"))
            }

            Rectangle()
                .fill(Color(hex: "15B88A"))
                .frame(width: 210, height: 2)

//            Text(validationMessage ?? "请输入 60–210 cm 之间的整数")
//                .font(.system(size: 13, weight: validationMessage == nil ? .medium : .bold))
//                .foregroundStyle(validationMessage == nil ? Color(hex: "71869A") : Color(hex: "E44C4C"))
//                .accessibilityIdentifier("xage.height.entry.validation")
        }
        .frame(maxWidth: .infinity)
        .frame(height: 190)
        .background(.white)
    }

    private var keypad: some View {
        VStack(spacing: 8) {
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 8) {
                ForEach(1...9, id: \.self) { digit in
                    digitButton(digit)
                }
                Button("清除") {
                    input = ""
                    validationMessage = nil
                }
                .accessibilityIdentifier("xage.height.entry.clear")
                digitButton(0)
                Button {
                    input = XAgeHeightEntryContract.deletingLast(from: input)
                    validationMessage = nil
                } label: {
                    Image(systemName: "delete.left")
                }
                .accessibilityLabel("退格")
                .accessibilityIdentifier("xage.height.entry.delete")
            }
            .buttonStyle(XAgeHeightKeyButtonStyle())

            Button(viewModel.saving ? "保存中" : "保存") {
                save()
            }
            .font(.system(size: 18, weight: .bold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 62, maxHeight: 62)
            .background(Color(hex: "15B88A"), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            .disabled(viewModel.saving)
            .accessibilityIdentifier("xage.height.entry.save")
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .top)
    }

    private func digitButton(_ digit: Int) -> some View {
        Button(String(digit)) {
            input = XAgeHeightEntryContract.appending(digit, to: input)
            validationMessage = nil
        }
        .accessibilityIdentifier("xage.height.entry.digit.\(digit)")
    }

    private func save() {
        guard let height = XAgeHeightEntryContract.validatedHeight(from: input) else {
            validationMessage = XAgeHeightEntryContract.errorMessage
            return
        }
        Task {
            await viewModel.submit(
                indicatorName: "身高",
                value: Double(height),
                unit: "cm",
                measuredAt: Date(),
                notes: nil
            )
        }
    }
}

private struct XAgeHeightKeyButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 24, weight: .medium))
            .foregroundStyle(Color(hex: "24364B"))
            .frame(maxWidth: .infinity, minHeight: 62, maxHeight: 62)
            .background(
                configuration.isPressed ? Color(hex: "E4EAF1") : .white,
                in: RoundedRectangle(cornerRadius: 10, style: .continuous)
            )
    }
}

struct XAgeWeightPickerSheet: View {
    let metric: XAgeMetric
    let onCancel: () -> Void
    let onSaved: () -> Void

    @StateObject private var viewModel = ManualIndicatorViewModel()
    @State private var integerPart: Int
    @State private var tenthPart: Int

    init(
        metric: XAgeMetric,
        initialWeight: Double?,
        onCancel: @escaping () -> Void,
        onSaved: @escaping () -> Void
    ) {
        self.metric = metric
        self.onCancel = onCancel
        self.onSaved = onSaved
        let components = XAgeWeightPickerContract.components(for: initialWeight)
        _integerPart = State(initialValue: components.integer)
        _tenthPart = State(initialValue: components.tenth)
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button("取消", action: onCancel)
                    .frame(minWidth: 44, minHeight: 44)
                    .accessibilityIdentifier("xage.weight.picker.cancel")

                Spacer()

                Text("选择体重")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))

                Spacer()

                Button(viewModel.saving ? "保存中" : "保存") {
                    Task { await save() }
                }
                .font(.system(size: 16, weight: .bold))
                .frame(minWidth: 44, minHeight: 44)
                .disabled(viewModel.saving)
                .accessibilityIdentifier("xage.weight.picker.save")
            }
            .foregroundStyle(Color(hex: "168BC0"))
            .padding(.horizontal, 20)
            .padding(.top, 8)

            Divider().opacity(0.35)

            HStack(spacing: 0) {
                Picker("体重整数", selection: $integerPart) {
                    ForEach(XAgeWeightPickerContract.integerRange, id: \.self) { value in
                        Text("\(value)").tag(value)
                    }
                }
                .pickerStyle(.wheel)
                .frame(maxWidth: .infinity)
                .clipped()
                .accessibilityIdentifier("xage.weight.picker.integer")

                Text(".")
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .accessibilityHidden(true)

                Picker("体重小数", selection: $tenthPart) {
                    ForEach(XAgeWeightPickerContract.tenthRange, id: \.self) { value in
                        Text("\(value)").tag(value)
                    }
                }
                .pickerStyle(.wheel)
                .frame(width: 92)
                .clipped()
                .accessibilityIdentifier("xage.weight.picker.tenth")

                Text("公斤")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(Color(hex: "173F64"))
                    .frame(width: 82, alignment: .leading)
            }
            .frame(height: 245)

            if viewModel.saving {
                ProgressView()
                    .tint(Color(hex: "168BC0"))
            } else {
                Text("当前选择 \(String(format: "%.1f", selectedWeight)) 公斤")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color(hex: "6C8194"))
                    .accessibilityIdentifier("xage.weight.picker.value")
            }
        }
        .background(XAgeLiquidBackground().ignoresSafeArea())
        .interactiveDismissDisabled(viewModel.saving)
        .onChange(of: viewModel.savedOk) { _, saved in
            guard saved else { return }
            onSaved()
        }
        .alert("保存失败", isPresented: Binding(
            get: { viewModel.errorMessage != nil },
            set: { if !$0 { viewModel.errorMessage = nil } }
        )) {
            Button("知道了", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage ?? "")
        }
        .accessibilityIdentifier("xage.weight.picker")
    }

    private var selectedWeight: Double {
        XAgeWeightPickerContract.weight(integer: integerPart, tenth: tenthPart)
    }

    private func save() async {
        await viewModel.submit(
            indicatorName: metric.title,
            value: selectedWeight,
            unit: "kg",
            measuredAt: Date(),
            notes: nil
        )
    }
}

struct XAgeWeightRecordDetailView: View {
    let metric: XAgeMetric
    let trend: IndicatorTrend?
    let heightCentimeters: Double?
    let onRecordWeight: () -> Void
    let onRecordHeight: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var selectedID: String?
    private let now = Date()

    private var samples: [XAgeMetricTrendSample] {
        XAgeMetricTrendContract.recentWeightSamples(from: trend, now: now)
    }

    private var latestSample: XAgeMetricTrendSample? {
        guard let trend else { return nil }
        return XAgeMetricTrendContract.samples(from: trend).last
    }

    private var selectedSample: XAgeMetricTrendSample? {
        selectedID.flatMap { id in samples.first(where: { $0.id == id }) }
    }

    private var latestWeight: Double? {
        XAgeMetricTrendContract.latestWeight(
            from: trend,
            fallbackValue: metric.value,
            fallbackIsPlaceholder: metric.isPlaceholder
        )
    }

    private var bmi: Double? {
        XAgeMetricTrendContract.bodyMassIndex(
            weightKilograms: latestWeight,
            heightCentimeters: heightCentimeters
        )
    }

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    latestCard
                    trendCard
                    recordButton
                }
                .padding(.horizontal, 24)
                .padding(.top, 18)
                .padding(.bottom, 30)
            }
            .scrollIndicators(.hidden)
        }
        .accessibilityIdentifier("xage.weight.detail")
    }

    private var header: some View {
        HStack(spacing: 12) {
            Button { dismiss() } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "2A79BB"))
                    .frame(width: 44, height: 44)
                    .background { XAgeCapsuleFill().frame(width: 36, height: 36) }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("返回上一页")

            ZStack {
                Circle()
                    .fill(LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .topLeading, endPoint: .bottomTrailing))
                Image(systemName: "scalemass.fill")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(.white)
            }
            .frame(width: 46, height: 46)

            VStack(alignment: .leading, spacing: 2) {
                Text("体重记录")
                    .font(.system(size: 24, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Text("关注最近三个月的体重变化")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color(hex: "668097"))
            }
            Spacer()
        }
    }

    private var latestCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("最新一次记录")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "496A83"))

            HStack(alignment: .bottom, spacing: 16) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Text(latestWeight.map { Self.number($0, digits: 1) } ?? "--")
                            .font(.system(size: 42, weight: .bold))
                            .foregroundStyle(Color(hex: "102B4C"))
                        Text("kg")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(Color(hex: "70879D"))
                    }
                    Text(latestDateLabel)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }

                Spacer(minLength: 8)

                VStack(alignment: .leading, spacing: 4) {
                    Text("BMI")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(Color(hex: "70879D"))
                    Text(bmi.map { Self.number($0, digits: 1) } ?? "--")
                        .font(.system(size: 28, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                }
                .frame(minWidth: 72, alignment: .leading)
            }

            if heightCentimeters == nil {
                VStack(alignment: .leading, spacing: 10) {
                    Text("还没有记录身高，无法计算BMI")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Color(hex: "5D7890"))
                    Button(action: onRecordHeight) {
                        Label("记录身高", systemImage: "figure.stand")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(Color(hex: "1878BE"))
                            .frame(minWidth: 104, minHeight: 44)
                            .background(XAgeCapsuleFill())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.weight.recordHeight")
                }
            }
        }
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
    }

    private var trendCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("体重变化")
                        .font(.system(size: 18, weight: .bold))
                        .foregroundStyle(Color(hex: "173F64"))
                    Text("近三个月 · 左右滑动查看")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Color(hex: "6C8194"))
                }
                Spacer()
                Text("长按查看")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(metric.accent)
            }

            if samples.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "chart.xyaxis.line")
                        .font(.system(size: 25, weight: .semibold))
                    Text("近三个月暂无体重记录")
                        .font(.system(size: 14, weight: .bold))
                    Text("记录体重后，这里会按日期生成趋势")
                        .font(.system(size: 11, weight: .medium))
                }
                .foregroundStyle(Color(hex: "7890A5"))
                .frame(maxWidth: .infinity, minHeight: 190)
            } else {
                GeometryReader { geometry in
                    ScrollView(.horizontal, showsIndicators: false) {
                        weightChart
                            .frame(width: chartWidth(viewportWidth: geometry.size.width), height: 224)
                    }
                    .defaultScrollAnchor(.trailing)
                }
                .frame(height: 224)
            }
        }
        .padding(16)
        .background(XAgeGlassCardBackground(cornerRadius: 26))
        .accessibilityIdentifier("xage.weight.trend")
    }

    private var weightChart: some View {
        Chart {
            ForEach(samples) { sample in
                LineMark(
                    x: .value("日期", sample.date),
                    y: .value("体重", sample.value)
                )
                .interpolationMethod(.catmullRom)
                .foregroundStyle(metric.accent)
                .lineStyle(StrokeStyle(lineWidth: 2.5, lineCap: .round, lineJoin: .round))

                PointMark(
                    x: .value("日期", sample.date),
                    y: .value("体重", sample.value)
                )
                .foregroundStyle(metric.accent)
                .symbolSize(selectedSample?.id == sample.id ? 105 : 34)
            }

            if let selectedSample {
                RuleMark(x: .value("选中日期", selectedSample.date))
                    .foregroundStyle(metric.accent.opacity(0.45))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 3]))
                    .annotation(position: .top, spacing: 8) {
                        VStack(spacing: 2) {
                            Text(selectedSample.dateLabel)
                                .font(.system(size: 11, weight: .semibold))
                            Text("\(Self.number(selectedSample.value, digits: 1)) kg")
                                .font(.system(size: 18, weight: .bold))
                        }
                        .foregroundStyle(Color(hex: "173F64"))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(XAgeRoundedFieldBackground(cornerRadius: 12))
                    }
            }
        }
        .chartXScale(domain: chartWindow)
        .chartYScale(domain: XAgeMetricTrendContract.weightYDomain(values: samples.map(\.value)))
        .chartXAxis {
            AxisMarks(values: .stride(by: .day, count: 5)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.35))
                AxisValueLabel {
                    if let date = value.as(Date.self) {
                        Text(Self.axisDateFormatter.string(from: date))
                            .font(.system(size: 9))
                    }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.35))
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        Text(Self.number(number, digits: 0))
                            .font(.system(size: 9))
                    }
                }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle()
                    .fill(.clear)
                    .contentShape(Rectangle())
                    .simultaneousGesture(
                        LongPressGesture(minimumDuration: 0.3)
                            .sequenced(before: DragGesture(minimumDistance: 0))
                            .onChanged { phase in
                                if case .second(true, let drag?) = phase {
                                    select(at: drag.location, proxy: proxy, geometry: geometry)
                                }
                            }
                    )
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(weightChartAccessibilityLabel)
        .accessibilityHint("左右滑动查看日期；长按图表选择某次体重记录")
    }

    private var recordButton: some View {
        Button(action: onRecordWeight) {
            Label("记录体重", systemImage: "plus.circle.fill")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, minHeight: 50)
                .background(
                    Capsule().fill(
                        LinearGradient(colors: [metric.accent, Color(hex: "20CDB1")], startPoint: .leading, endPoint: .trailing)
                    )
                )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("xage.metric.manualEntry")
    }

    private var latestDateLabel: String {
        if let latestSample { return latestSample.dateLabel }
        if let measuredAt = metric.measuredAt, let date = Utils.parseISO(measuredAt) {
            return Self.fullDateFormatter.string(from: date)
        }
        return metric.isPlaceholder ? "暂无记录日期" : metric.time
    }

    private var chartWindow: ClosedRange<Date> {
        let calendar = Calendar(identifier: .gregorian)
        let start = calendar.date(byAdding: .month, value: -3, to: now) ?? now.addingTimeInterval(-7_776_000)
        return start...now
    }

    private func chartWidth(viewportWidth: CGFloat) -> CGFloat {
        XAgeMetricTrendContract.weightChartWidth(
            windowStart: chartWindow.lowerBound,
            windowEnd: chartWindow.upperBound,
            viewportWidth: viewportWidth
        )
    }

    private func select(at location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) {
        guard let plotFrame = proxy.plotFrame else { return }
        let frame = geometry[plotFrame]
        let x = location.x - frame.origin.x
        guard x >= 0, x <= frame.width,
              let date: Date = proxy.value(atX: x),
              let index = XAgeMetricTrendContract.nearestIndex(to: date, in: samples) else { return }
        selectedID = samples[index].id
    }

    private var weightChartAccessibilityLabel: String {
        var label = "近三个月体重趋势，共\(samples.count)个数据点。"
        if let selectedSample {
            label += "当前选择\(selectedSample.dateLabel)，\(Self.number(selectedSample.value, digits: 1))公斤。"
        }
        return label
    }

    private static func number(_ value: Double, digits: Int) -> String {
        String(format: "%.*f", digits, value)
    }

    private static let axisDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = "M/d"
        return formatter
    }()

    private static let fullDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = "yyyy年M月d日"
        return formatter
    }()
}

struct XAgeMetricTrendView: View {
    let trend: IndicatorTrend?
    let fallbackUnit: String
    let accent: Color

    @State private var selectedID: String?

    private var samples: [XAgeMetricTrendSample] {
        trend.map(XAgeMetricTrendContract.samples(from:)) ?? []
    }

    private var selectedSample: XAgeMetricTrendSample? {
        if let selectedID,
           let selected = samples.first(where: { $0.id == selectedID }) {
            return selected
        }
        return samples.last
    }

    private var unit: String {
        trend?.unit?.trimmingCharacters(in: .whitespacesAndNewlines).nonEmpty ?? fallbackUnit
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("历史趋势")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(Color(hex: "173F64"))
                Spacer()
                Text("\(samples.count) 个数据点")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Color(hex: "6C8194"))
            }

            if samples.isEmpty {
                emptyState
            } else {
                selectionSummary

                Text("轻点选择；长按拖动查看连续数据；左右滑动查看历史")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color(hex: "6C8194"))

                GeometryReader { geometry in
                    ScrollView(.horizontal, showsIndicators: true) {
                        chart
                            .frame(
                                width: XAgeMetricTrendContract.chartWidth(
                                    pointCount: samples.count,
                                    viewportWidth: geometry.size.width
                                ),
                                height: 204
                            )
                    }
                    .defaultScrollAnchor(.trailing)
                }
                .frame(height: 204)
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(Color.white.opacity(0.7))
                .overlay(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .stroke(Color.white.opacity(0.88), lineWidth: 1)
                )
        )
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "chart.xyaxis.line")
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(Color(hex: "8AA1B5"))
            Text("暂无可用历史趋势")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(Color(hex: "496A83"))
            Text("同步、手动记录或确认报告后再查看；这里不会补造缺失数据。")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Color(hex: "6C8194"))
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: 124)
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var selectionSummary: some View {
        if let selected = selectedSample {
            HStack(spacing: 8) {
                Text(selected.dateLabel)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color(hex: "5D7890"))
                Spacer(minLength: 8)
                Text(selected.displayValue)
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(selected.isAbnormal ? .red : accent)
                if !unit.isEmpty {
                    Text(unit)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Color(hex: "70879D"))
                }
                if selected.isAbnormal {
                    Text("异常")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(Capsule().fill(.red))
                }
            }
            .padding(.horizontal, 10)
            .frame(minHeight: 38)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(accent.opacity(0.08))
            )
            .accessibilityElement(children: .combine)
            .accessibilityLabel(
                "\(selected.dateLabel)，\(selected.displayValue)\(unit.isEmpty ? "" : " \(unit)")\(selected.isAbnormal ? "，异常" : "")"
            )
        }
    }

    private var chart: some View {
        Chart {
            if let trend,
               let first = samples.first,
               let last = samples.last,
               let low = trend.ref_low,
               let high = trend.ref_high,
               low.isFinite,
               high.isFinite,
               low <= high {
                RectangleMark(
                    xStart: .value("开始", first.date),
                    xEnd: .value("结束", last.date),
                    yStart: .value("参考下限", low),
                    yEnd: .value("参考上限", high)
                )
                .foregroundStyle(.green.opacity(0.08))
            }

            if samples.count >= 2,
               let trend,
               IndicatorTrendPresentationContract.shouldDrawContinuousLine(for: trend) {
                ForEach(samples) { sample in
                    LineMark(
                        x: .value("日期", sample.date),
                        y: .value("数值", sample.value)
                    )
                    .foregroundStyle(accent)
                    .lineStyle(StrokeStyle(lineWidth: 2.2, lineCap: .round, lineJoin: .round))
                }
            }

            ForEach(samples) { sample in
                PointMark(
                    x: .value("日期", sample.date),
                    y: .value("数值", sample.value)
                )
                .foregroundStyle(sample.isAbnormal ? .red : accent)
                .symbolSize(sample.isAbnormal ? 48 : 30)
            }

            if let selected = selectedSample {
                RuleMark(x: .value("当前选择", selected.date))
                    .foregroundStyle(accent.opacity(0.45))
                    .lineStyle(StrokeStyle(lineWidth: 1, dash: [4, 3]))
                PointMark(
                    x: .value("当前选择", selected.date),
                    y: .value("当前数值", selected.value)
                )
                .foregroundStyle(selected.isAbnormal ? .red : accent)
                .symbolSize(94)
            }
        }
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 5)) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.4))
                AxisValueLabel {
                    if let date = value.as(Date.self) {
                        Text(Self.axisDateFormatter.string(from: date))
                            .font(.system(size: 9))
                    }
                }
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading) { value in
                AxisGridLine(stroke: StrokeStyle(lineWidth: 0.35))
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        Text(Self.axisValue(number))
                            .font(.system(size: 9))
                    }
                }
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geometry in
                Rectangle()
                    .fill(.clear)
                    .contentShape(Rectangle())
                    .simultaneousGesture(
                        SpatialTapGesture().onEnded { tap in
                            select(at: tap.location, proxy: proxy, geometry: geometry)
                        }
                    )
                    .simultaneousGesture(
                        LongPressGesture(minimumDuration: 0.28)
                            .sequenced(before: DragGesture(minimumDistance: 0))
                            .onChanged { phase in
                                if case .second(true, let drag?) = phase {
                                    select(at: drag.location, proxy: proxy, geometry: geometry)
                                }
                            }
                    )
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(chartAccessibilityLabel)
        .accessibilityHint("上下轻扫切换前一个或后一个数据点")
        .accessibilityAdjustableAction { direction in
            adjustSelection(direction)
        }
    }

    private func select(at location: CGPoint, proxy: ChartProxy, geometry: GeometryProxy) {
        guard let plotFrame = proxy.plotFrame else { return }
        let frame = geometry[plotFrame]
        let x = location.x - frame.origin.x
        guard x >= 0, x <= frame.width,
              let date: Date = proxy.value(atX: x),
              let index = XAgeMetricTrendContract.nearestIndex(to: date, in: samples) else { return }
        selectedID = samples[index].id
    }

    private func adjustSelection(_ direction: AccessibilityAdjustmentDirection) {
        let currentIndex = selectedSample.flatMap { selected in
            samples.firstIndex(where: { $0.id == selected.id })
        }
        let delta: Int
        switch direction {
        case .increment:
            delta = 1
        case .decrement:
            delta = -1
        @unknown default:
            return
        }
        guard let nextIndex = XAgeMetricTrendContract.steppedIndex(
            currentIndex: currentIndex,
            pointCount: samples.count,
            delta: delta
        ) else { return }
        selectedID = samples[nextIndex].id
    }

    private var chartAccessibilityLabel: String {
        var result = "\(trend?.name ?? "健康指标")趋势图，共\(samples.count)个数据点。"
        if let selected = selectedSample {
            result += "当前选择\(selected.dateLabel)，\(selected.displayValue)"
            if !unit.isEmpty { result += " \(unit)" }
            if selected.isAbnormal { result += "，异常" }
            result += "。"
        }
        return result + "左右滑动查看历史；轻点选择；长按拖动查看连续数据。"
    }

    private static let axisDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = "yy/MM/dd"
        return formatter
    }()

    private static func axisValue(_ value: Double) -> String {
        String(format: "%.2f", value)
            .replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression)
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}
