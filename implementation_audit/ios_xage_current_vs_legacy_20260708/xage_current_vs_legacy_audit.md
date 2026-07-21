# iOS XAGE 当前版与旧版差异审查

日期：2026-07-08

范围：只审查 iOS `XAGE` 分支。Android 仓库仅作历史参考，本轮不改 Android。

## 对比基线

- 旧版基线：`main`，commit `06be174bc05114ad920d1df1aa784c629a57f029`。
- 当前 XAGE：`XAGE` / `origin/XAGE`，commit `f1f39d46d300cc81b5cb09df917b3a2efa324424`。
- 分支关系：`main` 是 `XAGE` 的 merge-base，说明 XAGE 是从旧版主线直接分出的功能分支。
- 差异规模：`46` 个提交，`82` 个文件变化，`20312 insertions(+), 1998 deletions(-)`。

## 总体结论

当前 XAGE 不是旧版 App 的换皮，而是把旧版五 Tab 结构收敛成一个新的三栏健康管理壳层。旧版 `main` 的主入口是系统 `TabView`/iPad sidebar，包含 `首页 / 健康数据 / 计划 / 多组学 / 助手小捷`；当前 XAGE 的 `MainTabView` 只保留离线横幅，然后进入 `XAgeMainView`，由 `数据 / 问答 / X年龄` 三个内部区域承担主体验。

代码上，XAGE 同时做了三类变化：

- 新增：`XAgeMainView.swift`、Apple 健康同步、XAGE 评分算法、X年龄页、资料菜单、报告历史、手动指标、结构化健康 NLU 和高强度 UI 测试。
- 复用：登录、`APIService`、`ChatViewModel`、上传组件、部分健康数据/用药/报告 ViewModel 与后端模型仍沿用旧版体系。
- 替换或下沉：旧首页、旧健康数据、计划、多组学、旧助手页不再是主导航入口；报告/日常/就医/画像被放入 XAGE 左上资料菜单。

## 功能异同

| 模块 | 旧版 main | 当前 XAGE | 相同点/复用点 | 审查判断 |
| --- | --- | --- | --- | --- |
| 主导航 | 系统底部 Tab：首页、健康数据、计划、多组学、助手；iPad 使用 sidebar | 单一 `XAgeMainView`，顶部三段 `数据 / 问答 / X年龄`，左上资料菜单 | 仍保留离线横幅和登录门禁 | 架构明显变化，旧 Tab 被替换 |
| 数据页 | 旧 `HealthDataView` 和若干健康数据入口 | XAGE 数据仪表盘：压力/恢复/炎症评分、今日状态、Apple 健康同步、指标卡、排序、添加指标、手动记录、详情 sheet | 仍读服务端 dashboard、health-data、indicators/trend | 功能更集中，数据可信度和时效信息更强 |
| 资料/报告 | 旧健康数据与病历页面分散 | 左上资料菜单承载 `报告 / 日常 / 就医 / 画像`，报告页有数据上传、历史报告、AI 汇总 | 上传仍复用 `HealthDataViewModel` 和文档接口 | 入口已迁移，但部分旧能力通过旧 ViewModel 承载 |
| 问答 | 旧 `ChatView`，同样走 `/api/chat` | XAGE 液态玻璃对话页、底部输入栏、`+` 菜单、语音、PDF/图片上传、历史、分析、证据、等待进度 | `ChatViewModel` 和 `/api/chat` 仍复用 | UI 和上下文能力明显升级，模型调用入口保持一致 |
| X年龄 | 旧版无对应主功能 | 新增粒子环、X年龄/衰老进度、周切换、压力/恢复/炎症贡献、原理说明 | 数据来自 XAGE 算法上下文和服务端趋势 | 新增核心功能 |
| Apple 健康 | 旧版无完整 HealthKit 同步链路 | 新增 HealthKit entitlement、授权、读取、同步到 `/device-sync`、趋势合并 | 服务端仍用 `user_indicator_values` 做指标存储 | 新增硬件数据闭环 |
| 账号与登录 | 默认受试者 ID 模式，登录/注册入口偏旧品牌 | 默认手机号登录，小捷品牌 logo/启动动画，手机号空白归一，退出/注销账号 | AuthManager/APIService 复用并扩展 | 更接近真实用户账号体系 |
| 后端聊天 | 旧版主要靠 context_builder + provider prompt | 新增 `health_nlu`，message_structure 包含主体、意图、数据源、报告状态、冲突、重复策略；简单问题和急症有 fast path | 仍由 `/api/chat` 保存会话和消息 | 智能问答从 prompt 文案升级为结构化控制 |
| 测试 | 旧版已有部分单测 | 新增 AppleHealthSync、XAgeCompositeScores、账号、device-sync、health_nlu、message_structure 和 XAGE UI 自动化 | 仍使用 Xcode/pytest | 覆盖面增加 |

## 代码结构差异

### 新增核心文件

- `Xjie/Xjie/Views/Home/XAgeMainView.swift`：`9284` 行，承载 XAGE 三栏壳层、数据页、资料菜单、问答页、X年龄页、玻璃 UI 组件和账号菜单。
- `Xjie/Xjie/ViewModels/AppleHealthSyncViewModel.swift`：`456` 行，封装 HealthKit 授权、读取、状态文案和服务端同步。
- `backend/app/services/health_nlu.py`：`515` 行，负责健康概念、意图、安全等级、数据需求和宏观类别。
- `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`：新增 XAGE 高强度 UI 路径测试。
- `Xjie/Xjie/Xjie.entitlements`：新增 HealthKit capability。

### 复用和扩展的旧代码

- `ChatViewModel` 仍是问答发送、历史、消息状态的核心 ViewModel；XAGE 只是换成新的对话 surface 和等待卡片。
- `APIService` 仍是统一网络层；XAGE 增加匿名 auth 路径 401 不刷新 token、上传文件自动 refresh token 等补强。
- `HealthDataViewModel` 仍用于报告上传；XAGE 增加确认 sheet、图片质量校验和上传后自动问答分析。
- 后端 `context_builder.py` 仍是 LLM 上下文入口；XAGE 扩展成 `message_structure` 结构化上下文。

### 已替换的旧入口

- 当前 `MainTabView.swift` 不再直接实例化 `HomeView()`、`HealthDataView()`、`HealthPlanView()`、`OmicsView()`、`ChatView()`。
- `rg` 检查 XAGE 主入口时，旧主页面引用只剩 `MedicationListView()` 一处可达入口。

## 残留差异和风险

1. 顶部三栏没有横向滑动手势。
   - 旧设计决策要求三栏支持点击和横向滑动切换。
   - 当前 `XAgeTopBar` 只有三个 Button，`XAgeMainView.swift` 中没有 `DragGesture` / `gesture` 切换逻辑。
   - 影响：功能可点，但与最初“三栏切换”的交互目标不完全一致。

2. `用药管理` 仍打开旧 UI。
   - 当前 XAGE 设置菜单中 `用药管理` 使用 `NavigationStack { MedicationListView() }`。
   - `MedicationListView` 使用 `Color.appBackground`、白色卡片和普通 toolbar/menu，不是 XAGE 液态玻璃样式。
   - 影响：入口已迁移到资料菜单，但二级页风格没有完全迁移。

3. `XAgeMainView.swift` 过于集中。
   - 单文件 `9284` 行，包含 UI、状态、算法、服务端同步、上传、聊天、账号、家庭模式等多个职责。
   - 影响：短期迭代快，长期会增加回归风险；后续应拆为 `Data/Chat/Healthspan/Menu` 等文件和独立 ViewModel。

4. 指标排序/添加是本地 `@State`。
   - 当前 `metrics = XAgeMetric.defaultCards`，置顶、删除、追加候选主要在本地状态生效。
   - 影响：体验层可用，但如果用户期望跨会话记住排序，需要后续持久化到本地或服务器。

5. 旧页面代码仍保留在工程中。
   - `HomeView` 仍有跳 `HealthDataView`、`OmicsView`、`ChatView` 的旧链接，但当前主入口不再进入 `HomeView`。
   - 影响：不是当前 XAGE 主路径问题，但后续如果从其它入口意外进入旧页面，仍可能出现风格不一致。

6. 当前分支未等同于 TestFlight `1.0(13)`。
   - TestFlight `1.0(13)` 上传后，XAGE 分支继续增加了结构化对话和成熟健康 NLU。
   - 影响：当前审查对象是本地/远端 `XAGE` 最新代码，不代表用户已可在 TestFlight 安装到这些最新对话改动。

## 已验证证据

命令：

```bash
git merge-base XAGE main
git rev-list --count main..XAGE
git diff --shortstat main...XAGE
git diff --name-status main...XAGE
rg -n "HomeView\\(|HealthDataView\\(|HealthPlanView\\(|OmicsView\\(|ChatView\\(|MedicationListView" Xjie/Xjie/Views/Home/XAgeMainView.swift Xjie/Xjie/Views/Home/MainTabView.swift Xjie/Xjie/App/XjieApp.swift
rg -n "DragGesture|gesture|simultaneousGesture|selectedSection" Xjie/Xjie/Views/Home/XAgeMainView.swift
plutil -p Xjie/Xjie/Info.plist
plutil -p Xjie/Xjie/Xjie.entitlements
backend/.venv/bin/python -m pytest backend/tests/unit -q
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -skip-testing:XjieUITests -parallel-testing-enabled NO -derivedDataPath /tmp/xjie-xage-audit-tests test
```

结果：

- 后端 unit：`57 passed, 5 warnings`。
- iOS Simulator unit tests：通过；输出只有既有编译 warning。
- 当前 iOS 仓库：审查前工作区干净。

## 建议优先级

1. 先修交互契约：给 `数据 / 问答 / X年龄` 增加横向滑动切换，或明确产品决策改为只点击。
2. 再修残留旧 UI：把 `MedicationListView` 迁移为 XAGE 液态玻璃二级页。
3. 拆分 `XAgeMainView.swift`，先按数据页、问答页、X年龄页、资料菜单、共享玻璃组件拆文件，不改行为。
4. 决定指标排序/添加是否需要持久化；如果需要，应设计服务端 watched/order 字段或本地持久化策略。
5. 如果要让用户马上测试最新成熟问答能力，需要再走 TestFlight 发布流程；当前最新分支已超过 `1.0(13)`。
