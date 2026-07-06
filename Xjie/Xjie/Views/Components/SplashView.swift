import SwiftUI

/// 启动画面 — 对齐 Android 端的渐变、Logo 弹入、双层光环脉冲和文案上滑。
struct SplashView: View {
    @State private var contentOpacity: Double = 1
    @State private var exitScale: CGFloat = 1
    @State private var logoOpacity: Double = 0
    @State private var logoScale: CGFloat = 0.4
    @State private var showText = false
    let onFinished: () -> Void

    private let gradientColors = [
        Color(hex: "0E7C66"),
        Color(hex: "14B8A6"),
        Color(hex: "67E8F9")
    ]

    var body: some View {
        ZStack {
            LinearGradient(
                colors: gradientColors,
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            SplashPulseRings()
                .opacity(contentOpacity)

            VStack(spacing: 16) {
                Image("Logo")
                    .resizable()
                    .scaledToFill()
                    .frame(width: 112, height: 112)
                    .clipShape(RoundedRectangle(cornerRadius: 28, style: .continuous))
                    .opacity(logoOpacity)
                    .scaleEffect(logoScale)

                VStack(spacing: 4) {
                    Text("小捷")
                        .font(.system(size: 28, weight: .bold))
                    Text("你的智能健康管家")
                        .font(.subheadline.weight(.medium))
                        .opacity(0.85)
                }
                .foregroundColor(.white)
                .offset(y: showText ? 0 : 24)
                .opacity(showText ? 1 : 0)
            }
            .scaleEffect(exitScale)
            .opacity(contentOpacity)
        }
        .onAppear(perform: play)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("小捷 你的智能健康管家")
    }

    private func play() {
        withAnimation(.linear(duration: 0.42)) {
            logoOpacity = 1
        }
        withAnimation(.spring(response: 0.62, dampingFraction: 0.58, blendDuration: 0)) {
            logoScale = 1
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.62) {
            withAnimation(.easeOut(duration: 0.48)) {
                showText = true
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.52) {
            withAnimation(.easeOut(duration: 0.42)) {
                contentOpacity = 0
                exitScale = 1.08
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.42) {
                onFinished()
            }
        }
    }
}

private struct SplashPulseRings: View {
    var body: some View {
        ZStack {
            SplashPulseRing(delay: 0)
            SplashPulseRing(delay: 0.6)
        }
        .frame(width: 320, height: 320)
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

private struct SplashPulseRing: View {
    let delay: Double
    @State private var expanded = false

    var body: some View {
        Circle()
            .stroke(Color.white.opacity(expanded ? 0 : 0.55), lineWidth: 3)
            .frame(width: 80, height: 80)
            .scaleEffect(expanded ? 4 : 1)
            .onAppear {
                withAnimation(
                    .easeOut(duration: 1.8)
                    .delay(delay)
                    .repeatForever(autoreverses: false)
                ) {
                    expanded = true
                }
            }
    }
}
