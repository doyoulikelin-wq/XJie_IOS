import AVFoundation
import Speech
import SwiftUI
import UIKit

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
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("xage.info.close")
                    .accessibilityLabel("关闭 X年龄原理")
                }

                ScrollView {
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
                    .padding(.bottom, 8)
                }
                .scrollIndicators(.hidden)
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

struct XAgeHealthspanView: View {
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
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
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
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
                    .buttonStyle(.plain)
                    .disabled(snapshotIndex == snapshots.index(before: snapshots.endIndex))
                    .opacity(snapshotIndex == snapshots.index(before: snapshots.endIndex) ? 0.35 : 1)
                    .accessibilityIdentifier("xage.week.next")
                    .accessibilityLabel("下一周")
                }
                .foregroundStyle(Color(hex: "347FB7"))
                .padding(.horizontal, 6)
                .frame(height: 44)
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
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                            .padding(.horizontal, -12)
                            .padding(.vertical, -12)
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
