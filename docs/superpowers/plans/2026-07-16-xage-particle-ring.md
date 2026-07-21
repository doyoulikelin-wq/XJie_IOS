# X Age Particle Ring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static X Age particle-ring asset with a deterministic native SwiftUI 2D particle system that disperses as the X Age page scrolls down and re-aggregates when it returns to the top.

**Architecture:** Put particle configuration, deterministic seeding, pure layout math, the Canvas renderer, and the scroll-offset probe in one focused `XAgeParticleRingView.swift` file. Keep `XAgeMainView.swift` integration limited to owning one scroll-derived progress value, installing the probe and named coordinate space, and replacing the static image. Validate the pure geometry with two named unit regressions and strengthen the existing XAGE UI flow without creating another UI test ID.

**Tech Stack:** Swift 5, SwiftUI `Canvas`, `TimelineView(.animation)`, `PreferenceKey`, XCTest/XCUITest, Xcode project OpenStep source graph, repository regression gates.

## Global Constraints

- Work directly on the current `XAGE` branch; do not create another branch or worktree.
- Preserve every pre-existing tracked and untracked workspace change. Temporarily stash those bytes before implementation and restore them only after the particle commit and mandatory gates are complete.
- Do not use Three.js, WebKit, JavaScript, SpriteKit, network requests, remote textures, or third-party dependencies.
- Default particle parameters are exactly `particleCount = 420`, `ringRadius = 108`, `ringWidth = 30`, `dispersionRadius = 132`, `dispersionDuration = 0.38`, `aggregationDuration = 0.52`, and `orbitSpeed = 0.08`.
- The initial/top state is an aggregated annulus. Downward scrolling continuously disperses it into a radial cloud; returning to the top continuously restores the same annulus.
- Dispersed particles may occupy both sides of the original annulus but must never enter the central text exclusion radius.
- The central age, status text, and information button remain static, legible, accessible, and interactive.
- With Reduce Motion enabled, continuous orbit, drift, and twinkle stop; only a short linear scroll-linked morph remains.
- Use one Canvas for the particle batch. Do not create hundreds of SwiftUI `Circle` views and do not apply blur/shadow to every particle.
- `XAgeMainView.swift` is subject to the conservative XAGE rule: treat the change as UI interaction, chat client, Health client, account client, project/release, process-gate, and test-integrity risk.
- Add exactly two unit XCTest IDs. The tracked inventories become iOS Unit `160`, full UI `9`, small-screen UI `2`, and Unit/full-UI union `169`.
- Every `xcodebuild test` used as passing evidence must write an `.xcresult` and that result must pass `tools/validate_xcresult.py`.
- Run `/usr/bin/python3 -I tools/regression_guard.py validate` before and after editing, `/usr/bin/python3 -I tools/regression_guard.py check --working`, and `/usr/bin/python3 -I tools/run_regression_gate.py impacted` before claiming completion.
- The iOS source/project change requires a fresh unsigned `generic/platform=iOS` Release archive and `tools/verify_release_bundle.py`; `run_regression_gate.py impacted` owns that mandatory path.
- Do not sign, export, upload, or publish a TestFlight build.

## File Map

- Create `Xjie/Xjie/Views/Home/XAgeParticleRingView.swift`: configuration normalization, seeded particle attributes, pure interpolation, scroll progress conversion, offset probe, Canvas rendering, and Reduce Motion behavior.
- Create `Xjie/XjieTests/XAgeParticleRingTests.swift`: deterministic geometry, configuration bounds, reversible transition, scroll clamping, and Reduce Motion regressions.
- Modify `Xjie/Xjie/Views/Home/XAgeMainView.swift`: own scroll progress, install probe/coordinate space/identifier, and replace the static ring image.
- Modify `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`: strengthen `testNavigationTouchTargetsAndFormDismissalConventions` to exercise vertical scroll while remaining on the X Age tab.
- Modify `Xjie/Xjie.xcodeproj/project.pbxproj`: add one app source and one unit-test source to their exact groups and Sources phases.
- Modify `quality/expected_xctests.json`: add the two new sorted unit IDs to `ios_unit` and `ios_all`.
- Modify `tools/tests/test_validate_xcresult.py`: pin the new exact counts `160` and `169`.
- Modify `quality/change_impact.json`: record the actual static-image root cause, complete conservative domains/contracts, sibling scans, tests, manual matrix, and residual risks.
- Delete `Xjie/Xjie/Assets.xcassets/x_age_particle_ring_blue_green.imageset`: remove the unused PNG only after the replacement has passed focused tests.

---

### Task 1: Protect the Existing Workspace and Register the Change

**Files:**
- Preserve without editing: every path reported by `git status --short` before this task
- Modify: `quality/change_impact.json`

**Interfaces:**
- Consumes: current `XAGE` working tree and commit `10e8ae1` or its descendant containing the approved design spec
- Produces: a clean implementation baseline, `/tmp/xjie-pre-particle-status.txt`, `/tmp/xjie-pre-particle-stash.txt`, and the particle-specific impact contract

- [ ] **Step 1: Capture and stash the pre-existing workspace exactly**

Run:

```bash
git status --porcelain=v1 > /tmp/xjie-pre-particle-status.txt
test -s /tmp/xjie-pre-particle-status.txt
git stash push --include-untracked --message pre-xage-particle-ring-20260716
git rev-parse stash@{0} > /tmp/xjie-pre-particle-stash.txt
git status --porcelain=v1
```

Expected: the first `test` succeeds, `git stash push` reports saved local changes, the stash file contains one 40-character commit ID, and the final status is empty. Do not drop this stash during implementation.

- [ ] **Step 2: Run the mandatory pre-edit guard on the clean baseline**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
```

Expected: exit code `0` and validation success. If this clean-HEAD guard fails, stop before editing and preserve the full output.

- [ ] **Step 3: Replace the clean baseline impact file with the particle contract**

Use `apply_patch` to make `quality/change_impact.json` exactly:

```json
{
  "schema_version": 1,
  "change_id": "2026-07-16-ios-xage-native-particle-ring",
  "change_type": "feature",
  "summary": "将 X年龄页中央静态 PNG 圆环替换为原生 SwiftUI Canvas 二维粒子系统，并让聚合/分散状态由页面纵向滚动位置连续、可逆地驱动。",
  "root_cause": "现有 x_age_particle_ring_blue_green 只是静态图片，既没有时间驱动的粒子运动，也没有 X年龄 ScrollView 的偏移输入，因此页面滚动时不可能形成聚合到分散的变化；继续在 XAgeMainView.swift 内堆积随机数、绘制和滚动逻辑还会扩大该超大文件的职责与编译风险。",
  "risk_hypothesis": "若每次重绘重新随机生成粒子会造成跳变；若分散坐标不限制中央安全半径会遮挡年龄和信息按钮；若对每粒子创建 SwiftUI 子视图、阴影或独立动画会引发滚动掉帧；若偏移基准依赖粒子首次出现位置会在动态字体或重新进入页面时漂移；若 Canvas 抢手势、增加辅助功能节点或 Reduce Motion 仍持续运转会分别破坏纵向滚动、横向分页、VoiceOver 与系统动效偏好；若工程 Sources 图或精确测试清单遗漏，新文件和回归测试可能不会进入真实目标。",
  "impacted_domains": [
    "ios_ui_interaction",
    "ios_chat_client",
    "ios_health_client",
    "ios_account_client",
    "ios_project_release",
    "quality_process_gate",
    "test_suite_integrity"
  ],
  "regression_contracts": [
    "UX-NAV-001",
    "UX-KEYBOARD-001",
    "UX-CHAT-QUIESCENCE-001",
    "UX-ACCESSIBILITY-001",
    "UX-FORM-001",
    "DATA-CARD-001",
    "CHAT-SESSION-001",
    "AI-EVIDENCE-001",
    "HEALTH-REGISTRY-001",
    "HEALTH-ACCOUNT-001",
    "TEST-SUITE-INTEGRITY-001",
    "TEST-DETERMINISM-001",
    "RELEASE-GATE-001",
    "PROCESS-GATE-001"
  ],
  "same_class_scan": [
    "扫描 XAgeMainView.swift 中 XAgeHealthspanView、三栏 TabView、数据页滚动探针、直接 SwiftUI 滚动 API、PreferenceKey、onChange、transaction 和动画调用，确认新探针只服务 X年龄纵向形态进度，不改变聊天自动滚动、数据页排序或顶层横向分页。",
    "扫描 Xjie iOS 源码中的 Canvas、TimelineView、accessibilityReduceMotion 和装饰性动画，采用单 Canvas、固定种子、时间纯输入与 accessibilityHidden，避免数百子视图、随机重建和重复 VoiceOver 节点。",
    "扫描 x_age_particle_ring_blue_green 的全部源码和资产引用，要求替换后引用数为零再删除 imageset，中央光晕、玻璃圆、年龄、状态和信息按钮保持原有 ZStack 顺序。",
    "扫描 WebKit、WKWebView、JavaScript、Three.js、URLSession、AsyncImage 和远程资源入口，确认本功能不新增网页运行时、传输构造器、远程脚本或纹理。",
    "扫描 project.pbxproj 的 PBXBuildFile、PBXFileReference、Home group、XjieTests group 和两个 Sources phase，要求新 app/test 文件各有且仅有一条完整引用链并与磁盘源集合精确一致。",
    "扫描 quality/expected_xctests.json 和 tools/tests/test_validate_xcresult.py 的精确 XCTest 清单，新增两个稳定 Unit ID 后固定 Unit 160、完整 UI 9、小屏 UI 2、并集 169，不改名、跳过或删除既有测试。",
    "扫描 XAgeHighIntensityContextUITests 的共享 XAgeUITestCase、单一 XCUIApplication 生命周期和网络审计，扩展现有导航用例而不新增应用构造、launch、terminate 或直接网络入口。"
  ],
  "tests_added_or_updated": [
    "Xjie/XjieTests/XAgeParticleRingTests.swift",
    "Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift",
    "quality/expected_xctests.json",
    "tools/tests/test_validate_xcresult.py"
  ],
  "verification_plan": [
    "修改前后运行 /usr/bin/python3 -I tools/regression_guard.py validate，并在生产代码完成后运行 check --working。",
    "先新增两个确定性粒子单元测试并保存缺少 XAgeParticleRingConfiguration/XAgeParticleRingLayout 的预期 RED xcresult，再实现最小纯计算与 Canvas 组件并让同一测试生成通过的 xcresult。",
    "先加强现有 testNavigationTouchTargetsAndFormDismissalConventions 并保存缺少 xage.xage.scroll 标识的预期 RED xcresult，再完成 X年龄滚动集成并让同一 UI 测试通过。",
    "用 tools/validate_xcresult.py 校验每个绿色 focused xcresult 的精确 required-test，并让完整清单固定为 Unit 160、完整 UI 9、小屏 UI 2、并集 169。",
    "运行 /usr/bin/python3 -I tools/run_regression_gate.py impacted；该门禁必须执行相关域测试、全量精确 xcresult 校验、新鲜 unsigned generic iOS Release archive 与 verify_release_bundle.py。",
    "运行 git diff --check、regression_guard check --working 和正常 git hook；不使用 --no-verify，不签名、不导出 IPA、不上传 TestFlight。"
  ],
  "manual_checks": [
    "iPhone 17 Pro 顶部确认 420 粒子聚合圆环、向下滚动完全分散、滚回顶部重新聚合且中央文字始终清晰。",
    "iPhone SE（第 3 代）重复聚合/分散/回聚和快速连续上下滚动，检查帧稳定、卡片触控与横向分页。",
    "分别关闭和开启减少动态效果：关闭时有缓慢圆周流动与轻微亮度变化，开启时持续运动停止且滚动形态为短线性响应。",
    "默认字号与大号动态字体下检查中央年龄、X年龄标签、状态、信息按钮和后续卡片不裁切、不被粒子遮挡。",
    "执行下拉回弹、离开 X年龄分页再返回、纵向滚动后横向切换，确认进度限制在 0...1 且手势不冲突。",
    "使用真机 VoiceOver 检查 Canvas 不形成节点、中央文本阅读顺序不变、信息按钮可聚焦激活；Simulator UI 自动化不替代 rotor 与朗读签核。"
  ],
  "unresolved_risks": [
    "确定性单元测试验证几何边界和 Reduce Motion 时间稳定性，但不能验证最终像素密度、配色观感或真实设备帧率。",
    "Simulator UI 测试能验证滚动、分页和按钮可用性，不能替代 iPhone SE 与 iPhone 17 Pro 真机的 GPU 性能、触控竞争、VoiceOver 和动态字体人工签核。",
    "本地完整门禁固定要求受信任 Xcode 26.3（17C529）；若当前机器 toolchain 身份不符，impacted 与 Release bundle 门禁保持阻断并必须如实报告。",
    "本轮不修改 X年龄评分、健康数据、账号、聊天、网络或发布逻辑；XAgeMainView.swift 的保守域验证只证明这些边界未被本次集成破坏，不证明 AI 内容或 HealthKit 真机行为。"
  ]
}
```

- [ ] **Step 4: Validate the registered impact before behavior edits**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
git diff --check -- quality/change_impact.json
```

Expected: both commands exit `0`.

---

### Task 2: Add Deterministic Particle Geometry and Its Unit Regression

**Files:**
- Create: `Xjie/Xjie/Views/Home/XAgeParticleRingView.swift`
- Create: `Xjie/XjieTests/XAgeParticleRingTests.swift`
- Modify: `Xjie/Xjie.xcodeproj/project.pbxproj`
- Modify: `quality/expected_xctests.json`
- Modify: `tools/tests/test_validate_xcresult.py:170-173`
- Modify: `quality/change_impact.json`

**Interfaces:**
- Consumes: SwiftUI `Color`, `Canvas`, `TimelineView`, `PreferenceKey`, `accessibilityReduceMotion`, and the impact contract from Task 1
- Produces: `XAgeParticleRingConfiguration.xAgeDefault`, `resolved(for:)`, `XAgeParticleSeed.make(count:seed:)`, `XAgeParticleRingLayout.sample(for:configuration:canvasSize:dispersionProgress:time:reduceMotion:index:)`, `XAgeParticleScrollMetrics.progress(probeMinY:scrollDistance:)`, `XAgeParticleScrollOffsetProbe`, and `XAgeParticleRingView.init(dispersionProgress:configuration:isActive:seed:)`

- [ ] **Step 1: Create the two failing unit tests**

Create `Xjie/XjieTests/XAgeParticleRingTests.swift` with:

```swift
import XCTest
@testable import Xjie

final class XAgeParticleRingTests: XCTestCase {
    func testParticleRingLayoutTransitionsBetweenAnnulusAndDispersedCloud() {
        let size = CGSize(width: 272, height: 272)
        let configuration = XAgeParticleRingConfiguration.xAgeDefault.resolved(for: size)
        let seeds = XAgeParticleSeed.make(count: 128, seed: 42)
        let center = CGPoint(x: size.width / 2, y: size.height / 2)

        for (index, seed) in seeds.enumerated() {
            let aggregated = XAgeParticleRingLayout.sample(
                for: seed,
                configuration: configuration,
                canvasSize: size,
                dispersionProgress: 0,
                time: 9,
                reduceMotion: true,
                index: index
            )
            let dispersed = XAgeParticleRingLayout.sample(
                for: seed,
                configuration: configuration,
                canvasSize: size,
                dispersionProgress: 1,
                time: 9,
                reduceMotion: true,
                index: index
            )
            let midpoint = XAgeParticleRingLayout.sample(
                for: seed,
                configuration: configuration,
                canvasSize: size,
                dispersionProgress: 0.5,
                time: 9,
                reduceMotion: true,
                index: index
            )
            let returned = XAgeParticleRingLayout.sample(
                for: seed,
                configuration: configuration,
                canvasSize: size,
                dispersionProgress: 0,
                time: 9,
                reduceMotion: true,
                index: index
            )

            let aggregatedRadius = hypot(aggregated.position.x - center.x, aggregated.position.y - center.y)
            XCTAssertGreaterThanOrEqual(aggregatedRadius, configuration.ringRadius - configuration.ringWidth / 2 - 0.001)
            XCTAssertLessThanOrEqual(aggregatedRadius, configuration.ringRadius + configuration.ringWidth / 2 + 0.001)

            let dispersedRadius = hypot(dispersed.position.x - center.x, dispersed.position.y - center.y)
            XCTAssertGreaterThanOrEqual(dispersedRadius, configuration.centerExclusionRadius - 0.001)
            XCTAssertLessThanOrEqual(dispersedRadius, configuration.dispersionRadius + 0.001)

            XCTAssertEqual(midpoint.position.x, (aggregated.position.x + dispersed.position.x) / 2, accuracy: 0.001)
            XCTAssertEqual(midpoint.position.y, (aggregated.position.y + dispersed.position.y) / 2, accuracy: 0.001)
            XCTAssertEqual(returned, aggregated)
        }

        XCTAssertEqual(XAgeParticleScrollMetrics.progress(probeMinY: 12, scrollDistance: 160), 0)
        XCTAssertEqual(XAgeParticleScrollMetrics.progress(probeMinY: -80, scrollDistance: 160), 0.5, accuracy: 0.001)
        XCTAssertEqual(XAgeParticleScrollMetrics.progress(probeMinY: -320, scrollDistance: 160), 1)
        XCTAssertEqual(XAgeParticleScrollMetrics.progress(probeMinY: -CGFloat.infinity, scrollDistance: 160), 1)
    }

    func testParticleRingConfigurationAndSeedRemainSafeAndDeterministic() {
        var unsafe = XAgeParticleRingConfiguration.xAgeDefault
        unsafe.colors = []
        unsafe.particleCount = 5_000
        unsafe.particleSize = -4 ... -1
        unsafe.ringRadius = -20
        unsafe.ringWidth = 2_000
        unsafe.dispersionRadius = -30
        unsafe.centerExclusionRadius = 2_000
        unsafe.scrollDistance = -1
        unsafe.dispersionDuration = -1
        unsafe.aggregationDuration = 0
        unsafe.orbitSpeed = -1
        unsafe.driftSpeed = -1
        unsafe.twinkleSpeed = -1

        let size = CGSize(width: 272, height: 272)
        let resolved = unsafe.resolved(for: size)
        XCTAssertEqual(resolved.colors.count, 3)
        XCTAssertEqual(resolved.particleCount, 800)
        XCTAssertGreaterThanOrEqual(resolved.particleSize.lowerBound, 0.5)
        XCTAssertGreaterThanOrEqual(resolved.particleSize.upperBound, resolved.particleSize.lowerBound)
        XCTAssertGreaterThanOrEqual(resolved.ringRadius - resolved.ringWidth / 2, 0)
        XCTAssertLessThanOrEqual(resolved.ringRadius + resolved.ringWidth / 2, min(size.width, size.height) / 2)
        XCTAssertGreaterThanOrEqual(resolved.dispersionRadius, resolved.centerExclusionRadius)
        XCTAssertGreaterThanOrEqual(resolved.scrollDistance, 1)
        XCTAssertGreaterThanOrEqual(resolved.dispersionDuration, 0.08)
        XCTAssertGreaterThanOrEqual(resolved.aggregationDuration, 0.08)
        XCTAssertEqual(resolved.orbitSpeed, 0)
        XCTAssertEqual(resolved.driftSpeed, 0)
        XCTAssertEqual(resolved.twinkleSpeed, 0)

        let firstSeeds = XAgeParticleSeed.make(count: 128, seed: 0x5841474552494E47)
        let secondSeeds = XAgeParticleSeed.make(count: 128, seed: 0x5841474552494E47)
        XCTAssertEqual(firstSeeds, secondSeeds)

        let early = XAgeParticleRingLayout.sample(
            for: firstSeeds[0],
            configuration: resolved,
            canvasSize: size,
            dispersionProgress: 1,
            time: 0,
            reduceMotion: true,
            index: 0
        )
        let late = XAgeParticleRingLayout.sample(
            for: firstSeeds[0],
            configuration: resolved,
            canvasSize: size,
            dispersionProgress: 1,
            time: 10_000,
            reduceMotion: true,
            index: 0
        )
        XCTAssertEqual(early, late)
    }
}
```

- [ ] **Step 2: Register the test file and update the exact XCTest inventories**

First prove the chosen IDs are unused:

```bash
! rg -n 'A290000000000000000002|B290000000000000000002|A90006|B90006' Xjie/Xjie.xcodeproj/project.pbxproj
```

Add the test PBX objects and references with `apply_patch`:

```text
A290000000000000000002 /* XAgeParticleRingTests.swift in Sources */ -> B290000000000000000002 /* XAgeParticleRingTests.swift */
```

Place `B290000000000000000002` immediately after `B290000000000000000001` in the XjieTests group and its build file immediately after `A290000000000000000001` in the test Sources phase. The exact declarations are:

```pbxproj
		A290000000000000000002 /* XAgeParticleRingTests.swift in Sources */ = {isa = PBXBuildFile; fileRef = B290000000000000000002 /* XAgeParticleRingTests.swift */; };
		B290000000000000000002 /* XAgeParticleRingTests.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = XAgeParticleRingTests.swift; sourceTree = "<group>"; };
```

Insert these two identifiers in sorted order into both `ios_unit` and `ios_all` in `quality/expected_xctests.json`:

```json
"XjieTests/XAgeParticleRingTests/testParticleRingConfigurationAndSeedRemainSafeAndDeterministic",
"XjieTests/XAgeParticleRingTests/testParticleRingLayoutTransitionsBetweenAnnulusAndDispersedCloud"
```

Change the two count assertions in `tools/tests/test_validate_xcresult.py` to:

```python
self.assertEqual(len(profiles["ios_unit"]), 160)
self.assertEqual(len(profiles["ios_ui_full"]), 9)
self.assertEqual(len(profiles["ios_ui_small"]), 2)
self.assertEqual(len(profiles["ios_all"]), 169)
```

- [ ] **Step 3: Run the focused unit test to record the expected RED**

Run:

```bash
rm -rf /tmp/xjie-particle-red-unit.xcresult /tmp/xjie-particle-red-unit-derived
set -o pipefail
if xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/xjie-particle-red-unit-derived \
  -resultBundlePath /tmp/xjie-particle-red-unit.xcresult \
  -parallel-testing-enabled NO \
  -only-testing:XjieTests/XAgeParticleRingTests \
  2>&1 | tee /tmp/xjie-particle-red-unit.log; then
  echo "Expected the particle unit regression to fail before production types exist"
  exit 1
fi
rg 'cannot find.*XAgeParticleRing|not found in scope' /tmp/xjie-particle-red-unit.log
```

Expected: the `xcodebuild` leg fails because the particle production types do not exist yet, the shell command as a whole succeeds because that failure is asserted, and the `.xcresult` plus log remain under `/tmp` as RED evidence.

- [ ] **Step 4: Register and implement the focused particle component**

Add the app-source PBX chain with `apply_patch`:

```text
A90006 /* XAgeParticleRingView.swift in Sources */ -> B90006 /* XAgeParticleRingView.swift */
```

Place `B90006` immediately after `B90004` in the Home group and `A90006` immediately after `A90004` in the app Sources phase. Add these exact declarations:

```pbxproj
		A90006 /* XAgeParticleRingView.swift in Sources */ = {isa = PBXBuildFile; fileRef = B90006 /* XAgeParticleRingView.swift */; };
		B90006 /* XAgeParticleRingView.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = XAgeParticleRingView.swift; sourceTree = "<group>"; };
```

Create `Xjie/Xjie/Views/Home/XAgeParticleRingView.swift` with this complete implementation:

```swift
import SwiftUI

struct XAgeParticleRingConfiguration {
    var colors: [Color]
    var particleCount: Int
    var particleSize: ClosedRange<CGFloat>
    var ringRadius: CGFloat
    var ringWidth: CGFloat
    var dispersionRadius: CGFloat
    var centerExclusionRadius: CGFloat
    var scrollDistance: CGFloat
    var dispersionDuration: TimeInterval
    var aggregationDuration: TimeInterval
    var orbitSpeed: Double
    var driftSpeed: Double
    var twinkleSpeed: Double

    private static let defaultColors = [
        Color(hex: "22AFFF"),
        Color(hex: "24D8B1"),
        Color(hex: "6D7CFF")
    ]

    static let xAgeDefault = XAgeParticleRingConfiguration(
        colors: defaultColors,
        particleCount: 420,
        particleSize: 1.1 ... 3.2,
        ringRadius: 108,
        ringWidth: 30,
        dispersionRadius: 132,
        centerExclusionRadius: 78,
        scrollDistance: 160,
        dispersionDuration: 0.38,
        aggregationDuration: 0.52,
        orbitSpeed: 0.08,
        driftSpeed: 0.62,
        twinkleSpeed: 1.15
    )

    func resolved(for size: CGSize) -> XAgeResolvedParticleRingConfiguration {
        let maximumRadius = max(1, min(size.width, size.height) / 2 - 4)
        let lowerSize = min(max(particleSize.lowerBound, 0.5), 8)
        let upperSize = min(max(particleSize.upperBound, lowerSize), 8)
        let safeRingWidth = min(max(ringWidth, 2), maximumRadius)
        let minimumRingRadius = safeRingWidth / 2
        let maximumRingRadius = max(minimumRingRadius, maximumRadius - safeRingWidth / 2)
        let safeRingRadius = min(max(ringRadius, minimumRingRadius), maximumRingRadius)
        let safeExclusion = min(max(centerExclusionRadius, 0), maximumRadius)
        let safeDispersion = min(max(dispersionRadius, safeExclusion), maximumRadius)

        return XAgeResolvedParticleRingConfiguration(
            colors: colors.isEmpty ? Self.defaultColors : colors,
            particleCount: min(max(particleCount, 80), 800),
            particleSize: lowerSize ... upperSize,
            ringRadius: safeRingRadius,
            ringWidth: safeRingWidth,
            dispersionRadius: safeDispersion,
            centerExclusionRadius: safeExclusion,
            scrollDistance: max(scrollDistance, 1),
            dispersionDuration: max(dispersionDuration, 0.08),
            aggregationDuration: max(aggregationDuration, 0.08),
            orbitSpeed: max(orbitSpeed, 0),
            driftSpeed: max(driftSpeed, 0),
            twinkleSpeed: max(twinkleSpeed, 0)
        )
    }
}

struct XAgeResolvedParticleRingConfiguration {
    let colors: [Color]
    let particleCount: Int
    let particleSize: ClosedRange<CGFloat>
    let ringRadius: CGFloat
    let ringWidth: CGFloat
    let dispersionRadius: CGFloat
    let centerExclusionRadius: CGFloat
    let scrollDistance: CGFloat
    let dispersionDuration: TimeInterval
    let aggregationDuration: TimeInterval
    let orbitSpeed: Double
    let driftSpeed: Double
    let twinkleSpeed: Double
}

private struct XAgeSeededGenerator {
    private var state: UInt64

    init(seed: UInt64) {
        state = seed
    }

    mutating func nextUnit() -> Double {
        state &+= 0x9E3779B97F4A7C15
        var value = state
        value = (value ^ (value >> 30)) &* 0xBF58476D1CE4E5B9
        value = (value ^ (value >> 27)) &* 0x94D049BB133111EB
        value ^= value >> 31
        return Double(value >> 11) / 9_007_199_254_740_992
    }
}

struct XAgeParticleSeed: Equatable {
    let baseAngle: Double
    let ringRadialUnit: Double
    let dispersionAngle: Double
    let dispersionRadiusUnit: Double
    let sizeUnit: Double
    let colorUnit: Double
    let baseOpacity: Double
    let orbitScale: Double
    let phase: Double

    static func make(count: Int, seed: UInt64) -> [XAgeParticleSeed] {
        var generator = XAgeSeededGenerator(seed: seed)
        return (0 ..< max(count, 0)).map { _ in
            XAgeParticleSeed(
                baseAngle: generator.nextUnit() * .pi * 2,
                ringRadialUnit: generator.nextUnit() * 2 - 1,
                dispersionAngle: generator.nextUnit() * .pi * 2,
                dispersionRadiusUnit: generator.nextUnit(),
                sizeUnit: generator.nextUnit(),
                colorUnit: generator.nextUnit(),
                baseOpacity: 0.58 + generator.nextUnit() * 0.42,
                orbitScale: 0.65 + generator.nextUnit() * 0.7,
                phase: generator.nextUnit() * .pi * 2
            )
        }
    }
}

struct XAgeParticleSample: Equatable {
    let position: CGPoint
    let size: CGFloat
    let opacity: Double
    let colorIndex: Int
    let isHighlighted: Bool
}

enum XAgeParticleRingLayout {
    static func sample(
        for seed: XAgeParticleSeed,
        configuration: XAgeResolvedParticleRingConfiguration,
        canvasSize: CGSize,
        dispersionProgress: CGFloat,
        time: TimeInterval,
        reduceMotion: Bool,
        index: Int
    ) -> XAgeParticleSample {
        let center = CGPoint(x: canvasSize.width / 2, y: canvasSize.height / 2)
        let progress = min(max(dispersionProgress.isFinite ? dispersionProgress : 0, 0), 1)
        let easedProgress = progress * progress * (3 - 2 * progress)
        let orbitOffset = reduceMotion ? 0 : time * configuration.orbitSpeed * seed.orbitScale
        let ringAngle = seed.baseAngle + orbitOffset
        let ringRadius = configuration.ringRadius + CGFloat(seed.ringRadialUnit) * configuration.ringWidth / 2
        let ringPoint = point(center: center, radius: ringRadius, angle: ringAngle)

        let availableDispersion = max(configuration.dispersionRadius - configuration.centerExclusionRadius, 0)
        let baseDispersionRadius = configuration.centerExclusionRadius
            + CGFloat(sqrt(seed.dispersionRadiusUnit)) * availableDispersion
        let driftAmplitude = min(6, availableDispersion * 0.06)
        let radialDrift = reduceMotion
            ? 0
            : CGFloat(sin(time * configuration.driftSpeed + seed.phase)) * driftAmplitude
        let dispersedRadius = min(
            max(baseDispersionRadius + radialDrift, configuration.centerExclusionRadius),
            configuration.dispersionRadius
        )
        let angularDrift = reduceMotion
            ? 0
            : sin(time * configuration.driftSpeed * 0.65 + seed.phase) * 0.08
        let dispersedPoint = point(
            center: center,
            radius: dispersedRadius,
            angle: seed.dispersionAngle + angularDrift
        )

        let sizeRange = configuration.particleSize.upperBound - configuration.particleSize.lowerBound
        let particleSize = configuration.particleSize.lowerBound + CGFloat(seed.sizeUnit) * sizeRange
        let twinkle = reduceMotion
            ? 1
            : 0.86 + 0.14 * sin(time * configuration.twinkleSpeed + seed.phase)
        let colorIndex = min(Int(seed.colorUnit * Double(configuration.colors.count)), configuration.colors.count - 1)

        return XAgeParticleSample(
            position: CGPoint(
                x: ringPoint.x + (dispersedPoint.x - ringPoint.x) * easedProgress,
                y: ringPoint.y + (dispersedPoint.y - ringPoint.y) * easedProgress
            ),
            size: particleSize,
            opacity: min(max(seed.baseOpacity * twinkle, 0.2), 1),
            colorIndex: max(colorIndex, 0),
            isHighlighted: index.isMultiple(of: 23)
        )
    }

    private static func point(center: CGPoint, radius: CGFloat, angle: Double) -> CGPoint {
        CGPoint(
            x: center.x + radius * CGFloat(cos(angle)),
            y: center.y + radius * CGFloat(sin(angle))
        )
    }
}

enum XAgeParticleScrollMetrics {
    static func progress(probeMinY: CGFloat, scrollDistance: CGFloat) -> CGFloat {
        guard probeMinY.isFinite else {
            return probeMinY.sign == .minus ? 1 : 0
        }
        let distance = max(0, -probeMinY)
        return min(max(distance / max(scrollDistance, 1), 0), 1)
    }
}

enum XAgeParticleScrollSpace {
    static let name = "xageParticleScroll"
}

struct XAgeParticleScrollOffsetPreferenceKey: PreferenceKey {
    static var defaultValue: CGFloat = 0

    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = nextValue()
    }
}

struct XAgeParticleScrollOffsetProbe: View {
    var body: some View {
        Color.clear
            .frame(height: 0)
            .background {
                GeometryReader { proxy in
                    Color.clear.preference(
                        key: XAgeParticleScrollOffsetPreferenceKey.self,
                        value: proxy.frame(in: .named(XAgeParticleScrollSpace.name)).minY
                    )
                }
            }
            .accessibilityHidden(true)
    }
}

struct XAgeParticleRingView: View {
    let dispersionProgress: CGFloat
    let configuration: XAgeParticleRingConfiguration
    let isActive: Bool

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var renderedProgress: CGFloat
    private let particles: [XAgeParticleSeed]

    init(
        dispersionProgress: CGFloat,
        configuration: XAgeParticleRingConfiguration = .xAgeDefault,
        isActive: Bool = true,
        seed: UInt64 = 0x5841474552494E47
    ) {
        let clampedProgress = min(max(dispersionProgress.isFinite ? dispersionProgress : 0, 0), 1)
        self.dispersionProgress = clampedProgress
        self.configuration = configuration
        self.isActive = isActive
        _renderedProgress = State(initialValue: clampedProgress)
        particles = XAgeParticleSeed.make(
            count: min(max(configuration.particleCount, 80), 800),
            seed: seed
        )
    }

    var body: some View {
        let isTimelinePaused = reduceMotion || !isActive
        TimelineView(.animation(minimumInterval: isTimelinePaused ? 1 : nil, paused: isTimelinePaused)) { timeline in
            Canvas(opaque: false, colorMode: .linear, rendersAsynchronously: true) { graphics, size in
                let resolved = configuration.resolved(for: size)
                let time = timeline.date.timeIntervalSinceReferenceDate

                for (index, seed) in particles.prefix(resolved.particleCount).enumerated() {
                    let sample = XAgeParticleRingLayout.sample(
                        for: seed,
                        configuration: resolved,
                        canvasSize: size,
                        dispersionProgress: renderedProgress,
                        time: time,
                        reduceMotion: reduceMotion,
                        index: index
                    )
                    let color = resolved.colors[sample.colorIndex]

                    if sample.isHighlighted {
                        let glowSize = sample.size * 3.2
                        let glowRect = CGRect(
                            x: sample.position.x - glowSize / 2,
                            y: sample.position.y - glowSize / 2,
                            width: glowSize,
                            height: glowSize
                        )
                        graphics.fill(
                            Path(ellipseIn: glowRect),
                            with: .color(color.opacity(sample.opacity * 0.18))
                        )
                    }

                    let particleRect = CGRect(
                        x: sample.position.x - sample.size / 2,
                        y: sample.position.y - sample.size / 2,
                        width: sample.size,
                        height: sample.size
                    )
                    graphics.fill(
                        Path(ellipseIn: particleRect),
                        with: .color(color.opacity(sample.opacity))
                    )
                }
            }
        }
        .onChange(of: dispersionProgress) { oldValue, newValue in
            let target = min(max(newValue.isFinite ? newValue : 0, 0), 1)
            let duration = reduceMotion
                ? 0.12
                : (target >= oldValue ? configuration.dispersionDuration : configuration.aggregationDuration)
            let animation: Animation = reduceMotion
                ? .linear(duration: duration)
                : .easeInOut(duration: max(duration, 0.08))
            withAnimation(animation) {
                renderedProgress = target
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
```

- [ ] **Step 5: Run the focused unit tests and validate the green xcresult**

Run:

```bash
rm -rf /tmp/xjie-particle-unit.xcresult /tmp/xjie-particle-unit-derived
set -o pipefail
if xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/xjie-particle-unit-derived \
  -resultBundlePath /tmp/xjie-particle-unit.xcresult \
  -parallel-testing-enabled NO \
  -only-testing:XjieTests/XAgeParticleRingTests \
  2>&1 | tee /tmp/xjie-particle-unit.log
/usr/bin/python3 -I tools/validate_xcresult.py \
  --path /tmp/xjie-particle-unit.xcresult \
  --minimum-tests 2 \
  --required-test XjieTests/XAgeParticleRingTests/testParticleRingConfigurationAndSeedRemainSafeAndDeterministic \
  --required-test XjieTests/XAgeParticleRingTests/testParticleRingLayoutTransitionsBetweenAnnulusAndDispersedCloud
/usr/bin/python3 -I -m unittest tools.tests.test_validate_xcresult
```

Expected: `xcodebuild` reports two executed tests and `TEST SUCCEEDED`; the xcresult validator exits `0` with both required IDs; the Python validator tests pass with no skip.

- [ ] **Step 6: Run the post-component guard and commit the deterministic component**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
git diff --check
git add \
  quality/change_impact.json \
  quality/expected_xctests.json \
  tools/tests/test_validate_xcresult.py \
  Xjie/Xjie.xcodeproj/project.pbxproj \
  Xjie/Xjie/Views/Home/XAgeParticleRingView.swift \
  Xjie/XjieTests/XAgeParticleRingTests.swift
git diff --cached --check
git commit -m "feat: add deterministic X age particle ring"
```

Expected: both guards pass, only the six listed paths are staged, and the commit succeeds through the real pre-commit hook without `--no-verify`.

---

### Task 3: Integrate Scroll-Driven Particles into the X Age Page

**Files:**
- Modify: `Xjie/Xjie/Views/Home/XAgeMainView.swift:9355-9510`
- Modify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift:379-410`
- Delete: `Xjie/Xjie/Assets.xcassets/x_age_particle_ring_blue_green.imageset/Contents.json`
- Delete: `Xjie/Xjie/Assets.xcassets/x_age_particle_ring_blue_green.imageset/x_age_particle_ring_blue_green.png`

**Interfaces:**
- Consumes: `XAgeParticleRingView`, `XAgeParticleScrollOffsetProbe`, `XAgeParticleScrollSpace.name`, `XAgeParticleScrollOffsetPreferenceKey`, and `XAgeParticleScrollMetrics.progress(...)` from Task 2
- Produces: an X Age scroll view identified as `xage.xage.scroll`, reversible `particleDispersion`, and the native particle renderer in the existing central ZStack

- [ ] **Step 1: Strengthen the existing UI flow before production integration**

In `verifyHorizontalSectionNavigationAndTopInfo()`, insert the following immediately after the assertion that `topInfo` is hittable and before the boundary-left swipe:

```swift
        let xAgeScroll = app.scrollViews["xage.xage.scroll"]
        XCTAssertTrue(xAgeScroll.waitForExistence(timeout: 6), "X年龄页应暴露稳定的纵向滚动区域")
        let inlineInfo = app.buttons["xage.xage.info.inline"]
        XCTAssertTrue(inlineInfo.waitForExistence(timeout: 5), "粒子圆环中央信息按钮应保持可见")
        attachScreenshot(named: "ux-xage-particles-aggregated")

        xAgeScroll.swipeUp()
        XCTAssertTrue(app.buttons["xage.segment.X年龄"].isHittable, "纵向分散粒子时仍应停留在 X年龄分页")
        XCTAssertFalse(app.textFields["xage.chat.input"].isHittable, "X年龄纵向滚动不应误切到问答分页")
        attachScreenshot(named: "ux-xage-particles-dispersed")

        xAgeScroll.swipeDown()
        XCTAssertTrue(inlineInfo.waitForExistence(timeout: 5), "滚回顶部聚合后中央信息按钮仍应存在")
        assertMinimumTouchTarget(inlineInfo, name: "圆环中央 X年龄原理")
```

Do not add another test method, `XCUIApplication`, `.launch()`, or `.terminate()`.

- [ ] **Step 2: Run the strengthened UI test to record the expected RED**

Run:

```bash
rm -rf /tmp/xjie-particle-red-ui.xcresult /tmp/xjie-particle-red-ui-derived
set -o pipefail
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/xjie-particle-red-ui-derived \
  -resultBundlePath /tmp/xjie-particle-red-ui.xcresult \
  -parallel-testing-enabled NO \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testNavigationTouchTargetsAndFormDismissalConventions \
  2>&1 | tee /tmp/xjie-particle-red-ui.log; then
  echo "Expected the X age scroll UI regression to fail before integration"
  exit 1
fi
rg 'X年龄页应暴露稳定的纵向滚动区域|xage.xage.scroll' /tmp/xjie-particle-red-ui.log
```

Expected: the UI test fails at the new scroll-view assertion because `xage.xage.scroll` has not been added yet, and the log plus xcresult remain under `/tmp`.

- [ ] **Step 3: Add scroll progress ownership and the zero-height probe**

In `XAgeHealthspanView`, add this state next to `showInfo`:

```swift
    @State private var particleDispersion: CGFloat = 0
```

Attach the probe to the top of the existing `VStack(spacing: 10)` without adding a child-spacing gap. Change the modifier boundary immediately before `.padding(.horizontal, 24)` to:

```swift
            }
            .overlay(alignment: .top) {
                XAgeParticleScrollOffsetProbe()
            }
            .padding(.horizontal, 24)
```

This replaces the existing closing brace plus `.padding(.horizontal, 24)` pair; it does not add a second closing brace or a second padding modifier.

Extend the existing ScrollView modifiers from:

```swift
        .scrollIndicators(.hidden)
```

to:

```swift
        .coordinateSpace(name: XAgeParticleScrollSpace.name)
        .scrollIndicators(.hidden)
        .accessibilityIdentifier("xage.xage.scroll")
        .onPreferenceChange(XAgeParticleScrollOffsetPreferenceKey.self) { minY in
            particleDispersion = XAgeParticleScrollMetrics.progress(
                probeMinY: minY,
                scrollDistance: XAgeParticleRingConfiguration.xAgeDefault.scrollDistance
            )
        }
```

The existing `infoRequest` change observer and information sheet remain immediately after these modifiers.

- [ ] **Step 4: Replace only the static image layer**

Replace:

```swift
                    Image("x_age_particle_ring_blue_green")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 254, height: 254)
                        .accessibilityIdentifier("xage.particle.ring")
```

with:

```swift
                    XAgeParticleRingView(
                        dispersionProgress: particleDispersion,
                        configuration: .xAgeDefault,
                        isActive: selectedSection == .xAge
                    )
                    .frame(width: 272, height: 272)
```

Do not reorder the radial glow before it or the glass circle, age text, status text, and information button after it.

- [ ] **Step 5: Verify compilation before deleting the asset**

Run:

```bash
rm -rf /tmp/xjie-particle-build-derived
xcodebuild build \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/xjie-particle-build-derived \
  CODE_SIGNING_ALLOWED=NO
rg -n 'x_age_particle_ring_blue_green' Xjie --glob '!Assets.xcassets/x_age_particle_ring_blue_green.imageset/**'
```

Expected: `BUILD SUCCEEDED`; the final `rg` returns no matches and therefore exits `1`.

- [ ] **Step 6: Delete the now-unused static imageset**

Run:

```bash
git rm -r Xjie/Xjie/Assets.xcassets/x_age_particle_ring_blue_green.imageset
test ! -e Xjie/Xjie/Assets.xcassets/x_age_particle_ring_blue_green.imageset
```

Expected: Git stages deletion of `Contents.json` and the PNG, and the directory no longer exists. This deletion is in scope because the approved design replaces the asset and Step 5 proved it has no remaining consumer.

- [ ] **Step 7: Run the focused UI flow and validate its green xcresult**

Run:

```bash
rm -rf /tmp/xjie-particle-ui.xcresult /tmp/xjie-particle-ui-derived
set -o pipefail
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/xjie-particle-ui-derived \
  -resultBundlePath /tmp/xjie-particle-ui.xcresult \
  -parallel-testing-enabled NO \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testNavigationTouchTargetsAndFormDismissalConventions \
  2>&1 | tee /tmp/xjie-particle-ui.log
/usr/bin/python3 -I tools/validate_xcresult.py \
  --path /tmp/xjie-particle-ui.xcresult \
  --minimum-tests 1 \
  --required-test XjieUITests/XAgeHighIntensityContextUITests/testNavigationTouchTargetsAndFormDismissalConventions
```

Expected: `TEST SUCCEEDED`, exactly the required existing UI ID is present and passed, and the network/lifecycle audit inherited from `XAgeUITestCase` remains green.

- [ ] **Step 8: Check the focused diff and commit the integration**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --working
git diff --check
git diff -- Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
git add \
  Xjie/Xjie/Views/Home/XAgeMainView.swift \
  Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift
git diff --cached --check
git commit -m "feat: animate X age particles with scroll"
```

Expected: the production diff contains only the X Age progress/probe/view replacement, the UI diff contains only the four scroll assertions/screenshots, the asset deletion is staged, and the commit passes the real hook.

---

### Task 4: Run the Complete Required Gates on the Exact Particle Commit

**Files:**
- Verify: all paths committed by Tasks 2 and 3
- Preserve evidence: `/tmp/xjie-particle-*.log` and `/tmp/xjie-particle-*.xcresult`

**Interfaces:**
- Consumes: a clean exact particle `HEAD` with the two implementation commits
- Produces: post-edit guard evidence, exact working-change evidence, impacted-domain test evidence, and the fresh unsigned device Release archive verification required by repository policy

- [ ] **Step 1: Confirm the exact committed scope and clean state**

Run:

```bash
git status --porcelain=v1
git show --stat --oneline HEAD~1..HEAD
git diff --check HEAD~2..HEAD
```

Expected: status is empty, the last two commits contain only the planned particle/test/project/quality paths, and whitespace validation passes.

- [ ] **Step 2: Run the post-commit regression guard**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate 2>&1 | tee /tmp/xjie-particle-post-validate.log
```

Expected: the command exits `0`. The required `check --working` evidence was produced against the uncommitted integration diff in Task 3 before the exact particle commit was created.

- [ ] **Step 3: Run the complete impacted gate**

Run:

```bash
set -o pipefail
/usr/bin/python3 -I tools/run_regression_gate.py impacted 2>&1 | tee /tmp/xjie-particle-impacted.log
```

Expected: exit code `0`; exact iOS inventories are Unit `160`, full UI `9`, small-screen UI `2`, union `169`; required Python inventories remain exact; a fresh unsigned generic iOS Release archive is produced and `tools/verify_release_bundle.py` accepts its thin arm64 device executable and bundle boundaries. A required failure or skip remains blocking even if a later rerun passes; preserve the failing output and close its root cause before starting a new exact run.

- [ ] **Step 4: Run final source-boundary and whitespace checks**

Run:

```bash
git diff --check HEAD~2..HEAD
test "$(rg -n 'x_age_particle_ring_blue_green' Xjie | wc -l | tr -d ' ')" = "0"
test "$(rg -n 'import WebKit|WKWebView|three\\.js|URLSession\\(' Xjie/Xjie/Views/Home/XAgeParticleRingView.swift | wc -l | tr -d ' ')" = "0"
test "$(rg -n 'Canvas\\(' Xjie/Xjie/Views/Home/XAgeParticleRingView.swift | wc -l | tr -d ' ')" = "1"
git status --porcelain=v1
```

Expected: all boundary tests pass and status remains empty. If a mandatory gate created tracked changes, inspect them and do not hide or discard them.

---

### Task 5: Restore the User's Pre-Existing Workspace Changes

**Files:**
- Restore: every path listed in `/tmp/xjie-pre-particle-status.txt`
- Preserve: both particle commits and every restored tracked/untracked user change

**Interfaces:**
- Consumes: the untouched stash commit ID in `/tmp/xjie-pre-particle-stash.txt` and the fully verified particle `HEAD`
- Produces: the user's original dirty workspace layered over the committed particle implementation on the same `XAGE` branch

- [ ] **Step 1: Apply the exact recorded stash without dropping it**

Run:

```bash
test -s /tmp/xjie-pre-particle-stash.txt
particle_head=$(git rev-parse HEAD)
git stash apply "$(cat /tmp/xjie-pre-particle-stash.txt)"
test "$(git rev-parse HEAD)" = "$particle_head"
```

Expected: `HEAD` remains the verified particle commit and the pre-existing paths reappear. Use `apply`, not `pop`, so the recovery copy remains available until byte restoration is verified.

- [ ] **Step 2: Resolve only additive overlaps while preserving both bodies of work**

If `git status --short` shows conflicts, resolve with `apply_patch` according to these exact invariants:

- `Xjie/Xjie.xcodeproj/project.pbxproj` contains both the restored legal-document `A90005/B90005` chain and the committed particle `A90006/B90006` plus `A290000000000000000002/B290000000000000000002` chains, each exactly once in its group and Sources phase.
- `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift` contains both the restored legal-page flow and the particle scroll block inside `verifyHorizontalSectionNavigationAndTopInfo()`.
- `quality/change_impact.json` returns to the restored legal-document working-tree record; the particle impact record stays preserved in the particle commit history and must not replace the user's active uncommitted legal record.
- All other restored paths retain their stash bytes exactly because the particle commits do not modify them.

Then run:

```bash
test "$(rg -n 'A90005 .*XAgeLegalDocumentViews.swift in Sources' Xjie/Xjie.xcodeproj/project.pbxproj | wc -l | tr -d ' ')" = "1"
test "$(rg -n 'A90006 .*XAgeParticleRingView.swift in Sources' Xjie/Xjie.xcodeproj/project.pbxproj | wc -l | tr -d ' ')" = "1"
test "$(rg -n 'A290000000000000000002 .*XAgeParticleRingTests.swift in Sources' Xjie/Xjie.xcodeproj/project.pbxproj | wc -l | tr -d ' ')" = "1"
test "$(rg -n 'xage.xage.scroll' Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift | wc -l | tr -d ' ')" -ge "2"
```

Expected: every exact union invariant passes.

- [ ] **Step 3: Compare restored path coverage and keep the recovery stash**

Run:

```bash
cut -c4- /tmp/xjie-pre-particle-status.txt | sort -u > /tmp/xjie-pre-particle-paths.txt
git status --porcelain=v1 | cut -c4- | sort -u > /tmp/xjie-restored-particle-paths.txt
comm -23 /tmp/xjie-pre-particle-paths.txt /tmp/xjie-restored-particle-paths.txt
git stash list | rg "$(cat /tmp/xjie-pre-particle-stash.txt)|pre-xage-particle-ring-20260716"
```

Expected: `comm -23` prints nothing, meaning no originally dirty path disappeared, and the recovery stash still exists. Do not drop it in the same session; report its commit ID so the user can remove it after independently checking the restored work.

- [ ] **Step 4: Report completion without misrepresenting the restored dirty tree**

The handoff must state:

- the two particle commit hashes;
- focused unit/UI xcresult paths and the full impacted-gate result;
- exact XCTest counts `160 / 9 / 2 / 169`;
- that the original dirty workspace was restored on top of those commits;
- that the named recovery stash remains intentionally available;
- any real-device checks still outstanding from the manual matrix.

Do not claim the restored combined working tree is release-qualified: the mandatory gates apply to the exact clean particle commit tested in Task 4, and any later restored or edited bytes require their own relevant impact record and gates before delivery.
