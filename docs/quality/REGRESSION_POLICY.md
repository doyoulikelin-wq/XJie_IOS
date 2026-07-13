# XAGE 防回归开发与发布制度

生效日期：2026-07-13
适用范围：iOS XAGE、仓库内生产后端、数据库迁移、CI 与 TestFlight 发布

## 一、唯一完成定义

修复完成不是“当前页面看起来好了”，而是：

> 根因确认 + 同类入口扫描 + 永久约束 + 命名回归测试 + 受影响/全量门禁通过 + 证据落档。

任一必需项未执行、失败、被跳过或没有证据时，不得说“已完成”，不得提交发布记录，更不得上传 TestFlight。

## 二、修改前

1. 明确授权范围：iOS XAGE 线程只改 iOS；共享 API/schema 必须保持另一端兼容，不能借防回归擅自扩范围。
2. 搜索 `memory/resolved_issues.md`、`memory/known_risks.md`、UI memory、`quality/regression_contracts.json`、相关代码与测试。
3. 先复现问题，写出最小步骤、实际结果和期望结果。
4. 区分“表面症状”和“真实根因”。没有根因时先诊断，不以坐标、延时、单个 if 或单页特判冒充修复。
5. 更新 `quality/change_impact.json`：影响域、同类入口、契约 ID、回归测试、人工矩阵和剩余风险必须完整。

## 三、编码规则

- 先增加能在旧行为上失败的测试，再修生产代码；若只能扩展现有测试，必须增加能识别本次回归的断言或真实交互。
- 同一规则优先进入共享组件、单一 presentation route、状态机、API/schema 约束或统一测试辅助层。
- 不允许只修用户指出的那个入口；必须搜索同类 sheet、表单、键盘、返回、账号、数据源和 AI 路由。
- 无法自动化时必须停下说明原因，取得用户明确批准后才能使用人工例外；人工例外必须有可重复脚本、截图/录屏和未覆盖风险。
- 不允许用 `try?`、空 catch、`|| true`、测试内吞错误、关闭错误弹窗等方式把失败变成成功。

## 四、永久契约

机器可读契约位于 `quality/regression_contracts.json`。它同时校验契约测试锚点、影响域、XAGE 架构上限和发布命令。

当前关键契约包括：

- `UX-NAV-001`：页面和 sheet 的关闭语义一致。
- `UX-KEYBOARD-001`：点击、下拉、菜单、切页和离开均正确释放焦点；输入框 1–5 行；中文输入不回写。
- `UX-ACCESSIBILITY-001`：真实命中区至少 44pt，父子可访问语义不冲突。
- `UX-FORM-001`：干净/脏表单、提交锁和危险操作确认一致。
- `DATA-CARD-001`：数据卡片选择和顺序按账号持久化，同步不恢复已移出卡片。
- `CHAT-SESSION-001`：幂等重试和迟到回答隔离。
- `AI-SUBJECT-001`：本人和家属主体绝不串用数据。
- `AI-SAFETY-001`：急症/确定性风险优先，不给危险或绝对保证。
- `AI-EVIDENCE-001`：正文、引用、重放和历史快照一致。
- `HEALTH-REGISTRY-001`：目录、读取、上传和趋势共用稳定 registry。
- `HEALTH-ACCOUNT-001`：健康同步账号隔离、来源幂等、手工数据保护。
- `PROCESS-GATE-001`：行为修改必须伴随影响清单和有意义的测试变更。

新增一种历史错误时，必须新增或扩展相应契约；不能只在聊天或 devlog 中写一句提醒。

## 五、XAgeMainView 临时保守规则

`XAgeMainView.swift` 当前超过一万行，跨越多个业务域。拆分完成前：

- 任意修改保守触发 UI/交互、AI 客户端、Health 客户端和账号相关回归。
- 文件总行数、struct/enum、sheet、full-screen cover、alert、固定延时 presentation 和静默 API 失败数量不得超过 2026-07-13 基线。
- 不得重新引入旧 `HomeView`、`ChatView`、`SettingsView` 或 `MedicationListView` 路由。
- 新职责必须拆到 Data、Chat、XAge、Settings 或 Shared 的聚焦文件中；不能继续堆入巨型文件。

这是一条“停止恶化”门禁，不等于拆分已经完成。

## 六、验证矩阵

每次至少运行：新增回归测试、影响域既有测试、同类相邻路径。UI/交互还要按本次影响覆盖：

- 空、加载、成功、失败、重试、长内容和重启恢复；
- 点空白、明显纵向下拉、提交、切页、返回、打开菜单/附件/历史时的键盘和焦点；
- 单行到最大行数、中文输入法；第三方输入法不能实测时记录真机风险；
- 页面、sheet、干净/脏表单、忙碌态和二次进入；
- 横滑/纵滑方向冲突和首尾边界；
- 44pt 命中、VoiceOver 语义、大字号、小屏和安全区；
- 前后截图或可重复几何/快照断言。

AI 修改必须跑主体隔离、急症/特殊人群、数据证据、引用、幂等、历史回载和内部字段防泄漏。Health 修改必须跑 registry、权限/无样本/部分成功/失败状态、账号切换、迟到回调、来源身份、手工数据保护和迁移。

## 七、对现有测试结论的边界

`XAgeHighIntensityContextUITests` 中的 12 个 prompt 当前只验证输入、发送动作、键盘关闭和输入框清空。测试使用 UI validation token，错误弹窗可能被关闭；因此它不能证明服务端返回了正确 AI 回答。

以后：

- UI 壳层结论可以引用该测试；
- AI 内容、安全、主体、引用或路由结论必须引用确定性 Swift/Python 测试，或引用真正断言最终助手回答的受控端到端评测；
- 不得再把“输入过 12 个问题”描述为“验证了 12 个 AI 回答”。

## 八、执行命令

```bash
cd /Users/linlin/Desktop/X/XJie_IOS

# 契约、锚点和架构上限
python3 tools/regression_guard.py validate

# 提交前检查当前修改
python3 tools/regression_guard.py check --working

# 按 change_impact.json 运行受影响门禁
python3 tools/run_regression_gate.py impacted

# 发布候选：必须是干净且已推送的精确 HEAD
python3 tools/run_regression_gate.py release

# archive/export 前再次确认结果仍属于当前 HEAD
python3 tools/run_regression_gate.py assert-release

# 唯一允许的归档/上传入口
scripts/release_testflight.sh --archive-only
scripts/release_testflight.sh --upload
```

本地 `.githooks/pre-commit` 和 `.githooks/pre-push` 会执行静态门禁；build 号变化在 push 前还会要求有效 release evidence。禁止 `--no-verify`。

## 九、CI 与发布

GitHub Actions 必须监听 `XAGE` 和 `main`，覆盖 iOS、backend、quality 和 gate 工具；不得使用 `|| true` 吞掉失败。最终 `quality-gate` 只有在 policy、后端完整测试、iOS 完整测试和 Release build 都成功时才通过。

仓库管理员应在首次 CI 成功后，将 `quality-gate` 设为 `XAGE` 和 `main` 的 required check。分支保护未启用前，本地 hook 与 AGENTS 是当前机器上的硬门禁，但不能诚称能够阻止拥有管理员权限的人故意绕过。

## 十、证据格式

每次解决问题都在 `memory/resolved_issues.md` 使用统一模板，并在 `development_records.json` 记录：

- 最小复现和根因；
- 永久不变量/契约 ID；
- 同类入口扫描范围；
- 新增或增强的测试名和路径；
- 执行命令、通过数量和证据；
- 未验证项、真机限制和剩余风险。

只写“已修复、测试通过”不再算有效记录。
