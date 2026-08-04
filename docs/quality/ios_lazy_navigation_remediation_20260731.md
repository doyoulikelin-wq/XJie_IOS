# iOS 数据页惰性导航修复计划（2026-07-31）

## 最小复现

1. 从 XAGE 数据页右上角进入“数据卡片管理”，或点击快捷功能“体重记录”。
2. 页面仍可被部分 UI 自动化打开，但运行日志出现 SwiftUI 警告：`navigationDestination` 位于 lazy container 内，目标注册会被忽略。
3. 这两个入口都来自 `XAgeDataDashboardView`；该视图本身是分页 `TabView` 的子页面。

## 实际根因

`XAgeDataDashboardView` 在自己的视图修饰链上注册了两个
`navigationDestination(isPresented:)`。它位于 `XAgeMainView` 的 page-style
`TabView` 子树中，而 `TabView` 会惰性创建页面。SwiftUI 要求目标注册在对应
`NavigationStack` 的稳定、非惰性祖先上；当前实现把“路由状态、目标注册、页面内容”
都留在了惰性子页，因此系统明确警告目标可能失效。

## 永久约束

- XAGE 数据页只产生类型化的导航意图，不在 `TabView` 子页面注册
  `navigationDestination`。
- 数据页路由统一由 `XAgeMainView` 的根 `NavigationStack` 注册和消费。
- 指标管理、体重记录、指标详情与评分说明共享同一账号隔离协调状态；切换账号时必须
  同时清空活动路由和 sheet，不能把旧账号页面带入新账号。
- 账号配置只允许由常驻根页面执行；分页子页的可取消任务不得重新配置账号。
- 每个导航和 Sheet 请求都携带创建时的账号 generation；保存、刷新和延迟跳转跨
  `await`/延时后必须复核 generation，A→B→A 也不得接纳旧回调。
- 不用嵌套 `NavigationStack`、隐藏 `NavigationLink` 或坐标点击绕过警告。

## 同类入口扫描

- 全仓生产 Swift 共 6 个 `navigationDestination`；只有数据页的指标管理与体重记录
  两个注册位于分页 `TabView` 子树。
- 根页面的外部报告审核目标位于稳定根节点。
- 报告、历史和数据面板的其余目标均注册在各自 `NavigationStack` 的常驻根或
  非惰性 `Group` 上。
- 传统 `NavigationLink(destination:)` 可合法位于 `List`/`ForEach` 行内，本次不做
  无关替换。

## 验证计划

1. 强化命名回归
   `RegressionGuardTests.test_xage_dashboard_is_split_by_function_and_comments_do_not_consume_code_budget`：
   数据页源码不得再注册 `navigationDestination`，根页面必须绑定类型化数据页路由。
2. 新增 Unit 回归
   `testDataNavigationRouteClearsOnAccountChangeAndSupportsRepeatedPresentation`，覆盖同账号
   重绘、重复路由、跨账号清空，以及旧 generation 回调不得关闭新账号 Sheet。
3. 新增 UI 回归
   `testDataNavigationRoutesSurvivePageTabRecreationAndReturnToDataRoot`，覆盖数据→问答→
   X 年龄→数据、指标管理搜索键盘与详情 Sheet、体重身高 Sheet、体重转轮、返回和
   重复打开管理页。
4. 对 UI 结果保存 `.xcresult`，核对日志不再出现 lazy-container
   `navigationDestination` 警告；再运行 `fast` 与稳定后的 `impacted` 门禁。
5. 记录模拟器限制：通知授权、HealthKit 授权和真实 TestFlight 安装不由这组确定性
   导航回归证明。

## 最终证据

- Unit：
  `/tmp/xjie-data-navigation-generation-unit-20260731.xcresult`，命名用例 1/1 通过，
  精确结果校验通过。
- UI：
  `/tmp/xjie-data-navigation-generation-ui-20260731.xcresult`，命名用例 1/1 通过，
  精确结果校验通过；xcodebuild 文本日志与 xcresult action log 中
  `navigationDestination`、`lazy container`、`invalid configuration` 匹配均为 0。
  该结果包没有可用的独立 console log，因此不把 console 检查写成证据。
- `RegressionGuardTests.test_xage_dashboard_is_split_by_function_and_comments_do_not_consume_code_budget`
  通过，`regression_guard.py validate`、`git diff --check` 通过。
- 最终 `fast` 与 `impacted` 均通过；两者为 lightweight 开发门禁，不是 strict
  全量回归或发布证据。

## 剩余风险

- `XAgeMainView` 仍有更多菜单、数据详情和外部导入三个独立 Sheet modifier；正常路径
  未发现故障，但外部文件恰在数据 Sheet 活动时到达仍可能发生呈现竞争，后续应以统一
  modal 仲裁器单独处理。
- 就医助手资料行、健康画像长期用药和健康计划三个合法 `NavigationLink` 入口尚缺
  专门的点击/返回 UI 回归。
- 模拟器结果不证明真实 HealthKit、通知权限、辅助功能完整性或 TestFlight 安装行为。
