# iOS XAGE 页面导航与问答输入体验修复验证

日期：2026-07-12

设备：iPhone 17 Pro Simulator，iOS 26.3.1

分支：`XAGE`

## 问题与根因

1. 数据卡片管理使用了带拖拽横线的 large sheet，同时又通过 `interactiveDismissDisabled(true)` 禁止手势关闭，形成“看起来能下拉、实际上只能点勾”的错误预期。
2. 问答页的输入焦点只保存在输入栏内部；父级三栏通过状态切换保留页面实例，切换页面时没有统一释放第一响应者。
3. 对话滚动区没有键盘交互式关闭策略，空白点击和下拉手势不会结束输入焦点。
4. 文本框和输入栏使用固定高度，只适合单行输入，长问题无法按内容换行增长。

## 实现结果

- 数据卡片管理改为 `NavigationStack` 内的独立页面，使用系统导航标题和返回按钮；移除弹窗横线、勾选关闭和禁止下拉之间的矛盾。
- 指标置顶、排序、搜索、解释和持久化逻辑保持不变；从管理页仍可打开指标详情，关闭详情后返回管理页。
- 问答输入框改为垂直多行 `TextField`，从 1 行自动增长到最多 5 行，输入栏随内容增长并保持语音、附件、发送按钮底部对齐。
- 点击对话空白、向下拖动对话区、打开更多菜单、打开历史/附件/语音/上传，以及切换“数据 / 问答 / X年龄”时统一关闭输入法。
- 新增 UI 自动化覆盖独立管理页、详情返回、管理页滚动稳定、长文本增长、点击空白关闭、下拉关闭和切页关闭。

## 验证结果

- iOS 单元测试：`142 passed, 0 failed`。
- 新增交互 UI 测试 `testMetricManagerPageAndChatKeyboardLifecycle`：`1 passed`，55.776 秒。
- 数据卡片重启持久化 UI 回归：`1 passed`，69.310 秒。
- 原高强度 XAGE 按钮全流程 UI 回归：`1 passed`，164.104 秒。
- Release Simulator build：通过；输出只有项目既有的弃用和多余 `await` 警告。
- `git diff --check`：通过。

## 截图

- `00_data_page_entry.jpg`：数据页入口。
- `01_metric_manager_page.jpg`：独立的数据卡片管理页面与系统返回导航。
- `02_chat_multiline_input.jpg`：长问题输入后自动扩展的多行输入框。
- `03_keyboard_dismissed_on_section_switch.jpg`：输入法显示时切换到数据页后已自动关闭。
- `xcui_manifest.json`：最终通过用例导出的 XCUITest 附件清单。

## 发布边界

- 本轮没有递增构建号、归档或上传 TestFlight。
- 当前已上传的 TestFlight `1.0(16)` 不包含本次页面导航和输入法体验修复；如需外部测试，需要另发新构建。
- Simulator 已覆盖系统键盘交互，第三方输入法与真实设备手感仍建议在下一次 TestFlight 上做一次真机验收。
