# X 年龄原生 2D 粒子圆环设计

日期：2026-07-16
状态：已确认设计，待实施计划

## 目标

将 X 年龄页面中央的静态粒子圆环图片替换为原生 SwiftUI 2D 粒子系统。粒子初始聚合为圆环，页面向下滚动时连续分散为径向粒子云，滚回顶部时重新聚合。颜色、聚合/分散速度和圆环宽度必须通过配置参数调整。

## 已确认的产品行为

- 页面首次进入时粒子聚合为圆环。
- 聚合状态下粒子沿圆周缓慢流动，并有轻微亮度变化。
- 页面向下滚动时，粒子按滚动距离从圆环连续过渡为径向扩散云。
- 滚回顶部时，粒子连续、可逆地重新聚合为圆环。
- 分散粒子可位于圆环内外两侧，但不得进入中央 X 年龄文字的安全区域。
- 中央年龄、说明按钮和状态文字始终保持静止且清晰可读。
- 系统开启“减少动态效果”时，停止持续圆周流动和亮度呼吸，只保留由滚动位置控制的短距离、无弹性形态切换。

## 技术选择

采用 SwiftUI `Canvas + TimelineView(.animation)`，不使用 Three.js、WebKit、JavaScript、网络请求或第三方依赖。

选择原生 Canvas 的原因：

- 符合仓库禁止 WebKit 的安全边界。
- 数百个粒子可在一个 Canvas 中批量绘制，避免 `ForEach + Circle` 产生庞大视图树。
- 时间、滚动进度和参数配置可以保持确定性，便于单元测试。
- 比 SpriteKit 更容易与现有 SwiftUI 布局、动态字体和减少动态效果环境联动。

## 组件边界

新增聚焦文件 `Xjie/Xjie/Views/Home/XAgeParticleRingView.swift`，包含以下类型：

### `XAgeParticleRingConfiguration`

集中保存可调参数：

```swift
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
}
```

默认配置：

- `particleCount = 420`
- `ringRadius = 108`
- `ringWidth = 30`
- `dispersionRadius = 132`
- `dispersionDuration = 0.38`
- `aggregationDuration = 0.52`
- `orbitSpeed = 0.08`
- 默认颜色为蓝、青绿和少量紫蓝的渐变组合

配置需要提供安全修正：

- 颜色为空时恢复默认颜色。
- 粒子数量限制在性能允许的区间。
- 粒子尺寸、圆环半径、圆环宽度、分散半径和中央安全半径限制为有效非负值。
- 圆环与分散范围不得超出 Canvas 可绘制区域。
- 动画时间为负或过小时使用安全下限。

### `XAgeParticleSeed`

保存单个粒子的确定性属性：

- 圆周基础角度
- 圆环径向偏移
- 分散方向和分散半径系数
- 粒子尺寸
- 颜色索引
- 透明度
- 圆周速度系数
- 漂移和亮度相位

使用固定随机种子生成。相同配置和种子必须得到相同粒子集合，SwiftUI 重绘不得导致粒子随机跳变。

### `XAgeParticleRingLayout`

纯计算层，负责：

- 计算聚合圆环坐标。
- 计算径向分散坐标。
- 在两组坐标间按 `0...1` 分散进度插值。
- 限制分散粒子不进入中央安全半径。
- 根据减少动态效果环境关闭时间相关的圆周流动、漂移和亮度变化。

该层不依赖 Canvas 绘制上下文，供 XCTest 直接验证。

### `XAgeParticleRingView`

- 使用 `TimelineView(.animation)`提供当前时间。
- 使用单个 `Canvas` 批量绘制粒子。
- 普通粒子绘制一次实心圆；少量高亮粒子可增加一次低透明度外圈，避免所有粒子都使用昂贵阴影。
- 粒子颜色、位置、尺寸和透明度均由配置及种子计算。
- Canvas 为装饰内容并从辅助功能树隐藏；中央真实文字和按钮继续使用原有 SwiftUI 语义。

### `XAgeParticleScrollOffsetProbe`

零高度滚动探针，放在 X 年龄 ScrollView 内容顶部，通过专用 `PreferenceKey` 上报相对于命名坐标空间的纵向位置。它只负责产生稳定的页面滚动偏移，不参与视觉布局或辅助功能树。

## 滚动数据流

X 年龄页面的 `ScrollView` 设置专用命名坐标空间。ScrollView 内容顶部放置 `XAgeParticleScrollOffsetProbe`，父视图把探针位置转换为分散目标值，再传给 `XAgeParticleRingView`。这种方式不依赖粒子环首次出现的位置，因此页面重新进入、保留滚动位置或动态字体改变时不会建立错误基准。

数据流如下：

1. 页面顶部时，探针在命名坐标空间中的位置为零附近。
2. 内容向上移动代表页面向下滚动，计算 `distance = max(0, -probeMinY)`。
3. `targetDispersion = clamp(distance / scrollDistance, 0...1)`。
4. 目标值增加时使用 `dispersionDuration`，目标值减少时使用 `aggregationDuration`。
5. SwiftUI 动画只重定向一个分散进度值，不为每个粒子创建独立动画，也不排队异步滚动操作。
6. Canvas 使用展示进度计算全部粒子当前位置。
7. 页面重新进入时直接从当前探针位置恢复正确分散进度，不保存或恢复独立动画状态。

滚动到顶部以外的下拉回弹会被限制为聚合进度 `0`，不会产生反向分散。

## 绘制算法

聚合坐标：

- 角度为粒子基础角度加时间驱动的圆周偏移。
- 半径为 `ringRadius` 加粒子的确定性径向偏移。
- 径向偏移被限制在 `ringWidth / 2` 内，因此所有粒子形成可调宽度的圆环带。

分散坐标：

- 使用粒子的确定性分散方向。
- 半径分布在 `centerExclusionRadius...dispersionRadius`。
- 加入小幅、低频漂移，但始终重新限制在有效范围内。
- 分散坐标不会覆盖中央文字安全区。

最终坐标使用平滑插值：

```text
position = ringPosition + (dispersedPosition - ringPosition) * easedDispersion
```

亮度和粒子尺寸可带轻微确定性变化；减少动态效果开启时使用稳定值。

## 与现有页面的集成

`XAgeMainView.swift` 仅进行最小集成修改：

- 为 `XAgeHealthspanView` 的 ScrollView 添加专用坐标空间。
- 将 `Image("x_age_particle_ring_blue_green")` 替换为 `XAgeParticleRingView(configuration: .xAgeDefault)`。
- 粒子 Canvas 使用与现有光晕一致的 `272 × 272pt` 绘制区域；圆环、分散半径和粒子尺寸按该区域动态限制。
- 保持现有 ZStack 的光晕、中央玻璃圆、年龄文字、信息按钮和页面卡片结构不变。

新动画、随机种子、布局算法和参数校验全部留在新文件中。旧 PNG 在新组件通过验证后删除。

## 无障碍与交互

- Canvas 是装饰图形，不新增重复的 VoiceOver 元素。
- 中央年龄文字和信息按钮保持原辅助功能顺序与命中区域。
- 粒子不接收点击或拖动手势，纵向滚动继续由外层 ScrollView 处理。
- 不改变顶层 TabView 的横向分页手势。
- 大字号时中央内容仍使用现有布局；分散安全区按实际 Canvas 尺寸限制。
- `accessibilityReduceMotion` 开启时停止所有持续圆周、漂移和呼吸动画；滚动形态只使用短时线性响应，不使用弹性或惯性效果。

## 性能约束

- 默认 420 个粒子，配置允许范围需要设置上限。
- 单个 Canvas 批量绘制，不创建数百个 SwiftUI 子视图。
- 不对全部粒子使用模糊和阴影。
- 页面不可见时 `TimelineView` 不应继续产生可见绘制工作。
- 重点检查 iPhone SE（第 3 代）快速滚动时的帧稳定性和触控响应。

## 测试设计

新增 `Xjie/XjieTests/XAgeParticleRingTests.swift`，至少包含以下命名回归：

1. `testParticleRingLayoutTransitionsBetweenAnnulusAndDispersedCloud`
   - 聚合进度为 0 时，粒子位于配置圆环带内。
   - 分散进度为 1 时，粒子位于中央安全半径之外和最大分散半径之内。
   - 中间进度坐标位于两端坐标之间。
   - 从分散进度返回 0 后得到相同聚合坐标。

2. `testParticleRingConfigurationAndSeedRemainSafeAndDeterministic`
   - 相同种子和配置生成相同布局。
   - 空颜色、负速度、异常宽度和过大粒子数得到安全配置。
   - 减少动态效果开启时，不同时间得到相同的时间相关位置与亮度。

加强现有 XAGE UI 流程：

- 进入 X 年龄页。
- 确认中央年龄文字可见，信息按钮存在且可点击。
- 执行纵向滚动并确认页面仍保持在 X 年龄分页。
- 滚回顶部后中央信息按钮仍可点击。

新增两个 XCTest ID 后，iOS Unit 精确清单由 158 增加为 160，Unit/完整 UI 并集由 167 增加为 169；同步更新精确 XCTest 清单、清单数量断言和相关质量影响记录，不通过降低、改名或跳过既有测试来腾出数量。完整 UI 仍为 9，小屏 UI 仍为 2。

## 人工验证矩阵

- iPhone 17 Pro：顶部聚合、完全分散、滚回聚合。
- iPhone SE（第 3 代）：同样三种状态及快速连续滚动。
- 减少动态效果开启/关闭。
- 默认字号与大字号。
- 快速上下滚动、下拉回弹、页面离开后重新进入。
- X 年龄纵向滚动与顶层横向分页手势。
- 中央年龄文字、信息按钮和后续卡片没有被粒子遮挡或抢夺触控。

## 质量与交付范围

修改 `XAgeMainView.swift` 会按仓库保守规则触发 iOS UI、聊天客户端、Health 客户端和账号域验证。新增 Swift 源文件和测试文件还涉及 Xcode 工程、精确测试清单、测试完整性和质量流程域。

实施前后必须运行：

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --working
/usr/bin/python3 -I tools/run_regression_gate.py impacted
```

所有 iOS 源码/工程变化还必须生成新的无签名 `generic/platform=iOS` Release archive，并通过 `tools/verify_release_bundle.py`。任何必需门禁失败或跳过都会阻止完成声明。

## 明确不在本次范围内

- Three.js、WebKit 或任何网页运行时。
- 远程下载粒子脚本或纹理。
- 修改 X 年龄计算模型、周快照或健康数据。
- 改变中央年龄文字、信息页或其他数据卡片的业务逻辑。
- TestFlight 签名、导出或上传。
