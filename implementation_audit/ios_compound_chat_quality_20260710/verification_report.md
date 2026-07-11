# iOS XAGE 复合健康问答完整性与证据一致性验证

日期：2026-07-10 至 2026-07-11

范围：iOS `XAGE`、同仓 FastAPI 后端、iPhone 17 Pro Simulator

限制：仅使用 Simulator、本地合成账号和生产合成账号；未使用真机、真实用户资料或真实账号。客户端改动已于 2026-07-11 随 TestFlight `1.0(15)` 上传。

## 结果

- 复合因果问题会拆分鼻炎、失眠、情绪低落、脊柱侧弯、睡眠呼吸和缺氧等概念，逐项区分研究关联、可能机制、个体是否已证实及能改变判断的客观评估。
- 严格 JSON 响应会检查 provider `finish_reason`、未闭合结构、残句、Markdown 完整性、深度回答长度及复合概念覆盖；第一次失败从头重试，第二次仍失败时返回可重试状态，不持久化半句话。
- 深度回答在 iOS 主气泡显示完整正文；短摘要残缺时回退到完整正文；正文与分析相同时不再重复显示“查看分析”。
- 文献只保留正文实际使用、编号有效、关系主体一致、方向/否定一致且证据强度足够的条目；不再猜测换绑论文。最终编号在 summary、analysis、answer_markdown、历史回载和幂等重放中保持一致。
- assistant 元数据保存版本化 citation 快照；后续 claim 更新不会改变既有历史证据含义。旧 ID-only 历史仅在整组 claim 均可还原时展示，避免缺项后压缩错号。
- 证据卡新增适用人群、中文研究类型、样本量和年份；旧 payload 无人群字段时明确提示谨慎外推，且参考信息允许自然换行。
- 核心证据 seed 是显式、幂等、可审计的运维动作：预览不连接数据库或调用 embedding，只有 `--apply` 才写入；重复 seed 保留人工 disabled 状态。

## 反例审查

在自动化测试之外，额外执行三轮独立反例审查并修正：

- 普通“血压和心率有关系吗”不会被硬塞入鼻炎、脊柱侧弯或缺氧检查。
- 足够长但漏答某个因素的正文会被判定不完整；“问题提到了心率，但本次不讨论它”不算覆盖。
- “鼻炎造成缺氧，从而引起失眠和抑郁”不会与“现有信息不能确认缺氧”的边界同时保留而形成自相矛盾。
- “焦虑与失眠相关”不能借用“鼻炎与失眠相关”的论文；“无关”不能引用“相关”的论文；观察性关联不能支撑无条件的“导致 / 证明 / 确诊”。
- `结论。[1]` 可正确识别引用上下文；`但[1]。`、`但。[1]` 仍会被判定为残句。
- 稀疏旧引用 `[2]` 在 iOS 证据页继续显示 `[2]`，不会因过滤后数组下标变成 `[1]`。

## 自动化验证

- 后端完整 pytest：`236 passed, 3 skipped`，保留 3 个 Pydantic v2 迁移警告和 2 个测试环境短 JWT key 警告。
- 后端变更范围 Ruff：通过。
- Python compileall：通过。
- 核心证据 CLI preview：`mode=preview`、`manifest_count=4`；seed shell 语法检查通过。生产部署后再执行 preview 和显式 apply，结果见下方生产验证。
- iPhone 17 Pro Simulator iOS 单元测试：`92 passed, 0 failed`，跳过 UI target。
- iOS Debug Simulator build：通过；存在一个本轮前已有的 iOS 17 麦克风权限 API deprecation warning。
- `git diff --check`：通过。

## Simulator 人工验证

- 使用本地临时 SQLite、合成账号和本机 API，逐步验证问答历史、完整长正文、证据弹层、关闭/重开历史及引用顺序。
- 最终证据卡可见 `[1]` 失眠/情绪、`[2]` 鼻炎/睡眠、`[3]` 严重侧弯/夜间低氧，正文与卡片顺序一致。
- 适用人群、中文研究类型、样本量、年份和 `short_ref` 均自然换行，无单行省略、重复期刊、胶囊越界或底部遮挡。
- 最终脱敏视觉证据：`screenshots/23_final_evidence_population_layout.png`。

## 生产部署与公网验证

- 源码提交 `43c3501` 已推送到 `origin/XAGE`；服务器干净工作树 `/home/mayl/XJie_IOS_XAGE` 快进到该提交，候选镜像 `xjie-backend:xage-43c3501` 内完整测试为 `236 passed, 3 skipped`，敏感/运行时文件扫描命中数为 0。
- 正式 `xjie-api` 已切换到 `xjie-backend:xage-43c3501`，原 `xjie-backend:xage-e663f80` 容器保留为带时间戳的停止态回滚副本；新容器 `restart_count=0`，最近 15 分钟运行日志错误命中数为 0。
- 核心证据先 preview，再通过 `backend/deploy/seed_core_evidence.sh --apply` 显式写入：4 篇文献、4 条 claim，audit job `82`，manifest SHA256 为 `1738d50f79889fd77698b7f3da89cab8f048e5447800266659e4eb5aafd6fde7`。只读数据库复核确认 4 个 PMID、4 条启用 claim、reviewer、审计状态和 manifest 元数据全部一致。
- 容器内与公开域名 `/healthz` 均返回 `{"ok":true}`，未授权 `/api/chat/stream` 返回 401。
- 生产合成账号完成注册、显式 AI 授权、复合问题 SSE、幂等重放、会话列表/历史和清理全链路。问题命中 `llm.health.deep` / `causal_assessment`，正文 1617 字，返回 2 条已校验证据；每条均包含适用人群和研究类型，正文角标连续有效。重放和历史中的 citation 快照与首次结果深度一致。
- 合成会话先删除、合成账号随后软注销；手机号、密码、token、回答正文及其它 secret 均未写入报告、日志摘录或提交。

## 隐私与交付处理

- 本地调试数据库由 `*.sqlite3` 忽略，不进入 Git。
- 原始登录步骤截图可能包含合成手机号，整个截图目录默认忽略；只强制纳入人工复核后不含账号标识的最终截图。
- 报告、memory、开发记录和提交中不包含手机号、密码、JWT、SSH、API key、Apple 凭据或其它 secret。

## TestFlight 发布状态

- iOS `CURRENT_PROJECT_VERSION` 已从 14 递增到 15；全新 Release archive 使用生产 HTTPS 域名并通过 HealthKit、签名、Debug 标记、敏感字符串、旧 API 地址和禁入文件检查。
- `xcodebuild -exportArchive` 返回 `Uploaded Xjie`、`Upload succeeded` 和 `EXPORT SUCCEEDED`。`1.0(15)` 已进入 App Store Connect processing，包含 7 月 10 日稳健 SSE 路由和本轮复合问答客户端改动；测试员可见性仍需等待 Apple 完成处理。
