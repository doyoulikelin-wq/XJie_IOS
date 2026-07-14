# iOS XAGE 连续问答 AX 静止边界修复验证

日期：2026-07-14
范围：iOS XAGE 客户端、UI 自动化与永久回归门禁
环境：macOS 26.2，Xcode 26.3（17C529）

## 结论

这次问题不是“第三条问题本身有错”，也不是业务回答没有完成。PR #4 的 exact-SHA 检查曾通过，但完全相同 Git tree 的合并后 push 检查在连续问答第 3 条后失败。修复前本机复现时，画面已经显示助手回复、输入框已经清空、键盘已经关闭；进程 sample 显示主线程仍在构造 SwiftUI 辅助功能树、解析 `AttributedString` 和 `UITextView` 可访问属性，导致 XCTest 无法取得稳定 AX snapshot。

直接原因是一次即时回复会由 `messages`、发送状态、思考状态和上传提示等多个监听分别排入动画 `scrollTo`。当键盘退场、内容第一次溢出并且历史开始增长时，这些主队列动画互相叠加。与此同时，普通助手文本也无条件创建 Markdown `AttributedString`，使每次 AX 查询都承担不必要的富文本和 link-rotor 解析成本。业务状态已经结束，但界面没有一个可预测的静止边界。

之所以历史错误可能“改好后又犯”，是因为文字记录只能提醒人，不能拒绝代码；单次绿灯不能证明并发时序；旧测试只看最终画面，没有锁定实现结构和 App 自己的终态；旧 CI 也曾存在分支覆盖不足和吞错。此次把这些要求改成机器可执行契约，后续同类实现一旦回流会在提交、完整本地门禁或托管 `quality-gate` 中直接变红。

## 修复内容

- XAGE 与旧聊天入口各保留唯一且顺序固定的底部 anchor，统一使用同步、禁动画的 `ChatAutoScroll` transaction，不再向主队列叠加动画滚动。
- Return 只在草稿中插入换行，不发送也不关闭键盘；纸飞机是唯一的草稿发送动作。
- 纸飞机发送先同步捕获不可变草稿、释放焦点并显式关闭键盘，之后才启动异步任务；快捷问题、初始提示、重试、同意后继续、报告上传后续和相邻 outbound 入口也必须走审计过的 dismissal/wiring。
- thinking 与 upload 状态卡共用 `ChatProgressIndicator`：只有明确的 Debug UI automation 使用静态图标，普通 Debug 与 Release 使用正常 `ProgressView`。
- Debug UI automation 暴露唯一的 `phase / messages / latest / focused` 生命周期状态。测试先等待 `idle + 精确消息数 + latest assistant + focused false + thinking 消失`，再查询键盘和正文。
- 普通文本走 `Text(verbatim:)`；真正带 Markdown 视觉语义的文本继续由系统 parser 渲染。无链接富文本使用单一去标记辅助功能文本；含链接富文本按实际 URL run 合并为 `Text`/`Link(destination:)` 分段并显式保留 `.isLink`，避免为了降低 AX 成本而删除链接动作。
- SE 小屏用例先输入显式换行并证明没有发送，再点击纸飞机，随后核对终态、键盘、完整多行用户消息和对应助手回显。

## 永久约束

契约 `UX-CHAT-QUIESCENCE-001` 和既有 policy test 现在共同固定：

- 全仓库 SwiftUI/UIKit 滚动 API、代理、transaction、`onChange` 与 continuous-animation 标识符清单；
- XAGE 五个状态监听、旧聊天消息监听、共享及本地 helper、唯一底部 anchor 及其顺序；
- Return 不发送、纸飞机唯一发送、同步草稿/失焦/退键盘顺序，以及全部相邻 outbound 入口和方法别名；
- thinking/upload 对共享 `ChatProgressIndicator` 的真实 consumer wiring；
- 完整 app source root 中的消息/Markdown consumer、辅助功能 replacement/Link tree，以及 `#if DEBUG / #else / #endif` compiler block，防止 Release 与 UI automation 偷换实现；
- App-owned 完整终态、真实可命中 Link、小屏多行发送，以及 UI test base 的真实 wait helper 和每次 launch network-audit live call；
- required failure 必须保留证据并完成复现、根因、同类扫描、永久不变量及新提交完整门禁；同树 rerun 变绿不构成豁免。

focused policy test 当前实际构造并拒绝 **68 个**对抗变异：其中 **66 个**属于聊天静止/输入/consumer/构建边界，另外 **2 个**属于共享 UI test support，分别阻止把 base wait helper 改成恒真和保留“看似正确但从不调用”的网络审计。变异范围覆盖直接/动画/排队滚动、anchor 丢失或乱序、helper/overload/alias 绕过、Return 偷换发送、纸飞机或相邻发送入口旁路、同步退键盘删除、thinking/upload consumer 绕过、真实 root consumer 隐藏、Release/automation compiler 分叉、Markdown/Link/AX 退化、完整终态/多行断言削弱、continuous animation 回流，以及 UI base wait/network audit 假绿。

## 根因与失败证据

- PR #4 exact feature tree 的 run `29287041288` 成功。
- 同一 tree 合并为 `8e1ea34a15b626e78670081a41bc46858d0c61de` 后，push run `29288925828` 的 iOS job `86947874119` 失败；required failure 被保留，没有用 rerun 作废。
- 修复前本机重复同一 12-prompt 用例后复现；原始临时 sample 为 `/tmp/xjie-chat-race-stuck.sample.txt`，脱敏关键调用链保存在 [root_cause_stack_excerpt.txt](root_cause_stack_excerpt.txt)。
- 首次加入 Markdown 链接 UI 断言时，`/tmp/xjie-markdown-link-ui.xcresult` 诚实失败：XCTest 在 iOS 26.3.1 把 `accessibilityRepresentation` 内的 SwiftUI `Link` 暴露为可操作 `Button`，不是 `XCUIElementTypeLink`。实际层级和修正边界保存在 [markdown_link_ax_failure_excerpt.txt](markdown_link_ax_failure_excerpt.txt)。
- 把系统 Return 键错误假设成发送动作后，`/tmp/xjie-chat-keyboard-submit-ui.xcresult` 诚实失败：用例耗时 `108.594s`，预期 `phase=idle;messages=2;latest=assistant;focused=false`，实际仍为 `phase=idle;messages=0;latest=none;focused=true`。这证明 Return 保留了多行草稿而没有激活纸飞机；完整红灯保存在 [keyboard_return_failure_excerpt.txt](keyboard_return_failure_excerpt.txt)，没有被后续绿灯豁免。
- 现场截图只用于本机诊断，没有纳入仓库，因为自动化画面不能替代真机 VoiceOver 证据。

## 本地验证

### 1. Focused Swift 行为与代表性 Markdown 路由

命令使用 iPhone 17 Pro / iOS 26.3.1 Simulator 执行 `ChatViewModelTests.testSendMessageAppendsUserMessage`；结果 `1/1 passed`，临时结果包为 `/tmp/xjie-chat-unit-render5.xcresult`。

仓库跟踪测试锁定连续两轮各恰好追加 user + assistant 并收口为 `sending=false`、thinking 清空；Markdown 路由使用可复现的代表性确定性 case，包括普通医学文本、乘法、视觉不变的 inline 列表、单行/跨行强调、删除线、行内代码、转义、HTML entity、显式链接、裸 HTTP/FTP/www、邮箱、CR/CRLF 和 NUL 规范化，以及 Link accessibility 分段、阅读顺序和真实 URL。仓库没有与此前“百万级 fuzz”数字对应的跟踪脚本或结果，因此本报告不再引用那些无法复现的数量。

### 2. 纠正后的 focused UI 行为

- `/tmp/xjie-markdown-link-ui2.xcresult`：iPhone 17 Pro / iOS 26.3.1，13-prompt 用例 `1/1 passed`，测试耗时 `210.986s`；实际可访问动作存在且可命中。
- `/tmp/xjie-chat-multiline-se.xcresult`：iPhone SE（第 3 代）/ iOS 26.3.1，`testMetricManagerPageAndChatKeyboardLifecycle()` 为 `1/1 passed`，测试耗时 `70.354s`；覆盖 Return 换行、纸飞机发送、完整多行正文、终态与键盘关闭。
- `/tmp/xjie-chat-final-focused4.xcresult`：iPhone 17 Pro / iOS 26.3.1，最终 focused 13-prompt 用例 `1/1 passed`，测试耗时 `210.874s`。

### 3. 重复运行证据账本

- `/tmp/xjie-chat-final-repeat2.xcresult` 属于加入最终对抗边界前的历史 12-prompt tree：`5/5 passed`，五轮共发送 60 条问题并核对 120 条消息。它只证明当时树，不能代替当前 68-mutation 树的最终重复。
- `/tmp/xjie-chat-final-13-repeat.xcresult` 计划运行 5 次，实际只产生 3 个 repetition：前 2 次通过，第 3 次因 `Testing was canceled` 失败。该运行在进一步对抗审查时中止，结果为 failed，明确不计作 5/5 或最终绿灯。
- `/tmp/xjie-chat-final-audited-repeat.xcresult` 在新的审计缺口出现后被主动中止，只留下 1 个 `Testing was canceled` 的失败 repetition；它同样不计作通过。
- 当前 68-mutation 最终树的 `/tmp/xjie-chat-final-68-repeat.xcresult` 已完整结束。`xcresulttool get test-results summary` 独立回读为 **5 passed、0 failed、0 skipped**，五次 relaunch 测试耗时分别为 `212.779s`、`209.488s`、`207.343s`、`210.778s`、`210.878s`；每轮 13 个 prompt、26 条 user/assistant 消息，共核对 65 个问题和 130 条消息。该结果只证明当前本地 tree 的确定性 UI/AX 行为，不代替下方完整 `impacted` 与托管闭环。

### 4. 完整 working-tree impacted gate（历史第一轮）

精确命令：

```bash
/usr/bin/python3 -I tools/run_regression_gate.py impacted
```

2026-07-14 08:16（Asia/Shanghai）的第一轮结果曾通过 tools `74/74`、iOS Unit `149/149`、完整 UI `5/5`、SE 小屏 UI `2/2`、无签名 generic-device Release archive/bundle verifier、backend AI `213/213`、backend Health `25/25` 和 diff check。但此后生产代码、UI tests、policy 与文档继续变化，该结果已被后续变更取代，只保留为历史过程证据，不能作为当前树最终门禁。

### 5. 最终 working-tree impacted gate

2026-07-14 10:24（Asia/Shanghai）对最终源代码、测试、政策和已重建历史页从头执行同一命令并通过：tools `74/74`、iOS Unit `149/149`、完整 UI `5/5`、iPhone SE（第 3 代）小屏 UI `2/2`、无签名 generic-device Release archive 与 bundle verifier、backend AI `213/213`、backend Health `25/25`、最终 working-tree diff check 全绿。三个 `.xcresult` 又分别由结果工具确认 `149/0/0`、`5/0/0`、`2/0/0`。该结果计作当前本地 tree 的最终完整门禁；托管 exact-SHA 闭环仍独立待完成。

## 托管闭环与分支保护

本报告当前仍处于 hosted closure pending：新修复尚待 feature commit、PR exact feature SHA workflow、GitHub Actions app `15368` 的 `quality-gate`、XAGE merge 后 exact SHA push workflow，以及 XAGE 分支保护安装和独立回读。任一红灯都重新进入根因闭环。

`main` 当前比 XAGE 落后 72 commits 且仍是旧 CI；同步、CI 引导和保护 main 不在本次 iOS XAGE 修复范围。即使随后完成 XAGE 保护，要求两分支都受保护的 TestFlight release gate 仍保持 blocked。

## 仍然存在的边界

- Simulator AX/XCTest 不能代替真实 iPhone 上的 VoiceOver、大字号和第三方中文输入法签核。
- 确定性聊天 transport 只证明客户端壳层、终态和交互，不证明真实 AI 内容、主体隔离、医学安全、引用或公网 SSE 恢复。
- thinking 与 upload 状态卡已经共用 `ChatProgressIndicator` 并受 compiler block/consumer 静态门禁约束；但真实报告上传、后台识别、公网后续发送和系统文件选择并未由本次 focused 聊天 UI 证明，仍需要候选集成证据。
- 当前仓库只有 owner。0 approval 的分支保护能防误操作，但不能提供独立审查；有真实 collaborator 后应升级为 1 个批准、last-push approval 和受保护质量路径。
- 最新已上传 TestFlight 仍是 `1.0(17)`。build 17 已不合格，本轮不递增 build、不签名归档、不上传；未来候选至少 build 18，并重新取得五项候选绑定签核。

本报告不包含手机号、密码、JWT、GitHub token、Apple 账号、签名材料或任何其他凭据。Android、生产后端和数据库未修改。
