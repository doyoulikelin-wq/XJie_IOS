# XAGE 更多菜单拆分与 upstream 门禁适配设计

日期：2026-07-14

## 背景

当前 `XAGE` 分支已经推送到 `origin/XAGE`，但 `upstream/XAGE` 在此期间新增了聊天可访问性稳定性修复和强制质量门禁。预合并存在 `XjieApp.swift`、`XAgeMainView.swift` 两处内容冲突；解决冲突后，`regression_guard validate` 仍会拒绝当前树：

- `XAgeMainView.swift` 为约 11404 行，超过 upstream 的 10305 行上限。
- 文件中的结构体、sheet、full-screen cover 和 alert 数量超过各自上限。
- 当前分支新增的测试尚未纳入 upstream 的精确 XCTest 清单。

用户选择先完成最小合规架构拆分，再创建可合并的 Pull Request。

## 目标

1. 将“更多菜单、账号安全、法律与权限说明、问题反馈、关于、家庭管理”从 `XAgeMainView.swift` 整体迁移到一个聚焦文件。
2. 保持所有现有 UI、导航、状态、接口调用和 accessibility identifier 不变。
3. 合入最新 `upstream/XAGE`，保留 upstream 的聊天稳定性实现和当前分支的 XAGE 功能。
4. 将当前分支新增的单元测试和 UI 测试纳入精确测试清单，并通过 upstream 强制门禁。
5. 推送合并后的 `origin/XAGE`，创建以 `upstream/XAGE` 为 base 的 Draft PR。

## 不采用的方案

### 多文件细分

不在本轮把账号安全、法律文档、问题反馈和家庭管理进一步拆成多个文件。该方案长期边界更细，但会增加工程引用、跨文件可见性和合并冲突面，不利于本次最小风险适配。

### 只移动菜单容器

只移动 `XAgeMoreMenu` 本身无法充分降低 `XAgeMainView.swift` 的行数、结构体、sheet、full-screen cover 和 alert 数量，因此不能稳定通过门禁。

### 提高架构上限

不修改 `quality/regression_contracts.json` 中 `XAgeMainView.swift` 的架构上限。upstream 明确要求通过职责拆分降低复杂度，不允许把当前超限值登记为新基线来绕过检查。

## 文件架构

### 新文件：XAgeMoreMenuViews.swift

在 `Xjie/Xjie/Views/Home/` 创建 `XAgeMoreMenuViews.swift`，整体迁移当前 `XAgeMainView.swift` 中从：

```swift
// MARK: - 设置、资料与账号管理
```

到文件末尾的全部实现，包含：

- `XAgeMoreMenu`
- `XAgeAccountSecurityViewModel`
- `XAgeAccountSecurityView`
- 账号安全页的密码修改和账号注销界面
- 隐私政策、权限申请与使用说明
- 更多菜单行和账号菜单行
- 个人信息与权限页
- 帮助与问题反馈页
- 关于页和通用设置页容器
- `XAgeFamilyField`
- 家庭关联、邀请码和成员授权界面
- 家庭成员卡片和区域标题

新文件只负责更多菜单及其子页面，不接管数据首页、聊天、报告上传、评分或 X 年龄页面。

### XAgeMainView.swift

原文件删除上述完整区域，只保留根页面、数据、报告、聊天和 X 年龄相关实现。根页面继续通过相同初始化参数创建 `XAgeMoreMenu`，不改变状态所有权和回调方向。

迁移后预计主文件约 9640 行，低于 upstream 的 10305 行上限；结构体、sheet、full-screen cover 和 alert 数量也会下降到门禁限制内。

### Xcode 工程

`project.pbxproj` 只新增 `XAgeMoreMenuViews.swift` 所需的：

- PBXBuildFile
- PBXFileReference
- Home group 条目
- APP target Sources 条目

不得产生无关排序或工程结构变化。

## 跨文件接口

移动后仅将跨文件确实需要的符号从文件级 `private` 改为模块内可见：

- `XAgeMoreMenu`
- `XAgeKeyboard`
- `XAgeServerSyncSnapshot`
- `XAgeDataPanelCategory`
- `XAgePanelDestinationView`
- `XAgeMetricDetailRow`

如果编译器发现移动区域还引用其他文件私有符号，只允许对真实跨文件依赖做同类最小可见性调整；不得借此公开无关类型或重构业务接口。

`XAgeMoreMenu` 的接口保持：

```swift
XAgeMoreMenu(
    selectedCategory: Binding<XAgeDataPanelCategory>,
    appleHealthSync: AppleHealthSyncViewModel,
    snapshot: XAgeServerSyncSnapshot,
    onSyncAppleHealth: @escaping () async -> Void,
    onSelectCategory: @escaping (XAgeDataPanelCategory) -> Void,
    onClose: @escaping () -> Void
)
```

## upstream 合并冲突策略

### XjieApp.swift

同时保留：

- upstream 新增的 `runUIAutomationNetworkProbeIfNeeded()` 和调用点。
- 当前分支已有的 `debugFlag(_:)` 及中文说明。

两者都位于 `#if DEBUG` 中，生产 Release 行为不变化。

### XAgeMainView.swift

聊天自动滚动采用 upstream 的：

```swift
ChatAutoScroll.toBottom(Self.bottomAnchorID, using: proxy)
```

并保留 upstream 的 `dismissChatKeyboard()`、`sendStarterPrompt(_:)`、`retryMessage(id:)` 路径。当前分支原有异步动画滚动实现不保留，因为 upstream 的 `UX-CHAT-QUIESCENCE-001` 明确要求同步、禁动画、唯一入口。

中文方法注释可以保留，但不得改变 upstream 固定的调用结构。

## 精确测试清单适配

当前分支相对 upstream 新增 9 个 `UtilsTests`：

- 3 个共享样式契约测试。
- 2 个手机号脱敏测试。
- 4 个用药快捷输入测试。

其中 3 个样式测试当前以方法级 `@MainActor` 标注，upstream 的源码清单解析器不能稳定识别这种声明。调整为普通 `test...` 方法，并在方法体内使用 `MainActor.assumeIsolated` 或等价的显式主线程执行方式，使源码清单与 XCTest 运行时都能识别相同 ID。

当前分支还新增 4 个完整 UI 测试：

- 账号与安全导航。
- 隐私政策和权限说明返回语义。
- 用药快捷输入。
- 问题反馈入口。

这些测试迁移到 upstream 的 `XAgeUITestCase` 共享基类约束下，不创建或启动独立 `XCUIApplication`，并保留 fail-closed 网络审计。

精确清单预期更新为：

- iOS Unit：149 → 158
- 完整 UI：5 → 9
- 小屏 UI：保持 2
- Unit + 完整 UI 合集：154 → 167

同步更新以下受版本控制的精确声明和断言：

- `quality/expected_xctests.json`
- `AGENTS.md`
- `docs/quality/REGRESSION_POLICY.md`
- `quality/change_impact.json`
- `tools/tests/test_validate_xcresult.py`

不得使用最低数量、通配符或跳过测试代替精确 ID。

## 影响清单

合入 upstream 后更新 `quality/change_impact.json`，在 upstream 已登记的聊天稳定性影响基础上补充：

- `XAgeMainView` 更多菜单区域拆分。
- 账号安全、法律说明、家庭管理、用药快捷输入和问题反馈同类入口。
- 新增 Swift 文件与 PBX Sources 一致性。
- 9 个单元测试和 4 个 UI 测试的精确清单变化。
- 拆分不改变行为但会触发 UI、交互、AI、Health、账号、工程和测试完整性域。

## 实施顺序

1. 再次合并最新 `upstream/XAGE`，按本设计解决两处已知冲突。
2. 读取合并后生效的 `AGENTS.md` 和质量制度，保存此前门禁失败证据。
3. 创建 `XAgeMoreMenuViews.swift` 并迁移完整更多菜单区域。
4. 做最小跨文件可见性调整和 PBX 工程引用。
5. 调整样式测试主线程写法、迁移 4 个 UI 测试到 upstream 共享基类结构。
6. 更新精确测试清单、数量断言、制度文字和 `change_impact.json`。
7. 运行全部强制门禁。
8. 门禁全部通过后提交合并结果、push 到 `origin/XAGE`，创建 Draft PR。

## 强制验证

必须遵循合并后 `AGENTS.md`，至少执行：

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --working
/usr/bin/python3 -I tools/run_regression_gate.py impacted
```

所有强制 `xcodebuild test` 必须生成 `.xcresult`，并通过：

```bash
/usr/bin/python3 -I tools/validate_xcresult.py
```

还必须完成：

- Unit 精确 158 项。
- 完整 UI 精确 9 项。
- iPhone SE（第 3 代）小屏精确 2 项。
- Unit/完整 UI 合集精确 167 项。
- tools Python 精确清单。
- backend 受影响门禁。
- `git diff --check`。
- 全新无签名 `generic/platform=iOS` Release archive。
- `tools/verify_release_bundle.py` 校验 device archive。
- pre-commit 和 pre-push hook，不使用 `--no-verify`。

任何一次必需门禁失败都保持阻断，必须保存证据、说明根因并在新提交上重新完成闭环，不能用简单重跑覆盖。

## 提交与 PR

- 合并提交包含 upstream 更新、冲突解决、架构拆分和门禁适配。
- 用户既有未跟踪 workspace 和历史文档不纳入提交。
- push 目标为 `origin/XAGE`。
- Draft PR 目标为 `doyoulikelin-wq/XJie_IOS:XAGE`，head 为 `LoveWood233:XAGE`。
- PR 描述明确列出架构拆分、功能增量、冲突策略、精确测试清单和验证证据。

## 成功标准

- `XAgeMainView.swift` 满足 upstream 原有架构上限，不提高限制。
- 更多菜单及全部子页面行为和视觉保持不变。
- 聊天滚动与键盘路径采用 upstream 的稳定实现。
- 9 个新增单元测试和 4 个新增 UI 测试进入精确清单并真实执行。
- 所有 mandatory gate、hook 和 unsigned device archive 验证通过。
- `origin/XAGE` 包含最新 upstream 与当前功能提交。
- Draft PR 可合并且没有内容冲突。

