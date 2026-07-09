# iOS XAGE 稳健对话路由审查与验证报告

日期：2026-07-10

范围：iOS `XAGE` 分支、同仓后端、iPhone 17 Pro Simulator

限制：严格只使用 Simulator，未尝试真机，未在本轮发布 TestFlight。

## 结论

本轮把对话从“所有问题都交给 LLM”调整为分层路由：急症模板、确定性高风险数值、证据不足澄清、低延迟状态快答和需要推理的 LLM 路径。主体、数据来源、时效、报告状态、同会话记忆和安全边界先由后端结构化，再进入模型；iOS 通过 SSE 接收路由与进度，失败消息保留并可用同一消息标识重试。

最终验证结果：

- 后端：`156 passed, 3 skipped`，5 个既有依赖/测试密钥警告。
- iOS：`80` 个单元测试和 `2` 个高强度 UI 测试通过，0 失败。
- iOS xcresult：`/Users/linlin/Library/Developer/Xcode/DerivedData/Xjie-btsfjwntcfvodbgisfyvscwnmldt/Logs/Test/Test-Xjie-2026.07.10_05-20-04-+0800.xcresult`。
- 变更范围 Ruff：通过。
- `git diff --check`、Python compileall、Info.plist lint：通过。
- 迁移 `0020_chat_request_receipts`：升级后表存在、降级后移除、再次升级后恢复，结果 `1/0/1`。

## 架构修改

### 后端

- 新增统一 `ChatRouteDecision`，同步和 SSE 共用同一准备、执行、保存和响应守卫流程。
- 新增数据库幂等租约 `chat_request_receipts`，同一用户和 `client_message_id` 只允许一个执行者；租约接管后旧执行者不能落库重复回答。
- NLU 按当前主体解析概念、意图、否定、假设、历史症状、数值和安全等级，不把关键词命中直接等同于当前急症。
- 会话结构明确区分本人、家属和其他病例；非本人默认阻断本人 Apple 健康、CGM、报告和用药数据。
- 数据源记忆记录连接状态、指标、来源、测量时间和冲突；已同步硬件不再被反问是否佩戴设备。
- 回答守卫移除内部字段、ISO 时间、原始异常和重复建议，限制无证据趋势、跨主体事实及模糊式追问。
- AI 授权默认关闭；LLM 审计仅保存消息哈希和长度，不保存原始问句。

### iOS

- 问答改用 SSE，先展示服务器路由进度，再接收最终结果；旧服务器 404/405 时兼容同步接口。
- 请求使用 `client_message_id`；网络失败保留用户气泡和重试入口，不生成伪助手错误气泡。
- 新对话会取消当前请求归属，旧回答不能落入新会话。
- 普通请求、SSE 和上传统一使用 token 绑定刷新，旧请求不能清除新登录态。
- 前台网络不无限等待连接；TLS 完全交由系统校验，生产 API 使用 HTTPS，移除任意证书信任。
- AI 授权由用户明确接受、拒绝；接受后重用原消息标识，不重复生成用户消息。
- 修复中文输入法候选词提交后输入框残留：发送动作同步消费草稿、收起焦点，并在 IME 提交回写后再次按原文清空，同时保留用户新输入的下一条草稿。

## 审查中发现并修复的问题

| 类别 | 发现 | 修复 |
| --- | --- | --- |
| 路由 | 报告状态、趋势和上传意图可能互相覆盖 | 明确优先级并增加确定性 route ID |
| 数值 | `SBP 190`、无单位血糖、仅给一半血压会被忽略或误判 | 按指标上下文解析，危险歧义走安全路径，不完整值先澄清 |
| 会话 | 上轮血压主题会污染本轮明确血糖问题 | 当前消息概念和数值风险优先于历史主题 |
| 主体 | 家属病例可能混入本人指标 | active subject + blocked context + 响应守卫三层隔离 |
| 状态 | “曾经怀孕”可能覆盖后来的“确认未怀孕” | 同主体最新明确状态优先，使用是/否/未提及三态解析 |
| 孕产 | 普通成人 `>180/120` 阈值错误用于孕期 | 孕期/产后六周内使用 `>=160` 或 `>=110` 严重阈值 |
| 症状 | 急症模板会把未出现的腹痛/深快呼吸写成事实 | 仅回显当前、未否定、未缓解的实际症状 |
| 儿童 | 严重低血糖固定套用成人 15 克 | 已知儿童按个体方案，明确幼儿通常少于成人 15 克；年龄未知时分别说明儿童和成人路径 |
| 幂等 | 同步接口可能从 SQLAlchemy identity map 读到旧租约 | 所有权检查直接查询数据库状态/租约列，并用双会话接管测试覆盖 |
| iOS | 中文 IME 发送后原文残留，可能重复发送 | 同步消费草稿、焦点退出、IME 回写二次清理并保护新草稿 |

## 医疗边界依据

- 普通成人严重高血压采用美国心脏协会 `>180/120 mmHg` 的复测和症状急救边界：[AHA severe hypertension](https://www.heart.org/en/health-topics/high-blood-pressure/understanding-blood-pressure-readings/when-to-call-911-for-high-blood-pressure)。
- 孕期/产后严重高血压采用 ACOG `>=160` 收缩压或 `>=110` 舒张压阈值：[ACOG preeclampsia and high blood pressure](https://www.acog.org/womens-health/faqs/preeclampsia-and-high-blood-pressure-during-pregnancy)。
- 严重低血糖、成人 15-15 规则及幼儿通常需要更少快速糖依据 ADA：[ADA hypoglycemia treatment](https://diabetes.org/living-with-diabetes/hypoglycemia-low-blood-glucose/symptoms-treatment)。
- 高血糖达到约 `240 mg/dL` 时检查酮体及酮症急症边界依据 ADA：[ADA hyperglycemia](https://diabetes.org/living-with-diabetes/treatment-care/hyperglycemia)、[ADA ketones](https://diabetes.org/living-with-diabetes/managing-ketones)。

这些规则用于分诊和下一步行动，不用于远程确诊，也不允许回答自行加药、减药或停药。

## 自动化验证

- 后端完整 pytest：`156 passed, 3 skipped`。
- iOS 完整 xcodebuild：80 unit + 2 UI，0 failed。
- 认证/API 聚焦测试曾连续运行 3 轮，均通过，用于排除固定 sleep 和真实网络副作用造成的偶发失败。
- UI 测试实际点击：数据卡片管理与持久化、四分类菜单、用药、排序底部完成、附件菜单、新对话、连续问答、X 年龄说明。
- 迁移独立升级/降级/重升级通过；旧 `0001` 使用 PostgreSQL JSONB，SQLite 从零完整升级仍不是支持路径，生产迁移必须在 PostgreSQL 验证。

## 人工 Simulator 验证

共保存 32 张逐场景截图，详见 [scenario_matrix.md](scenario_matrix.md) 和 [manual_simulator_log.md](manual_simulator_log.md)。新增特殊人群场景覆盖：

- 孕期 `160/110` 使用产科阈值。
- “她”延续到同一妻子主体。
- “说回我”后恢复普通成人规则。
- 孕期高压只回显实际剧烈头痛，不虚构已否定的上腹痛。
- 5 岁儿童低血糖不固定套用成人剂量，中文输入发送后输入框清空。
- 成人低血糖仍保留 15 克/15 分钟规则。
- 同一主体最新“确认没怀孕”覆盖旧孕期状态。

## 剩余限制

- Simulator 不能提供真实 HealthKit 样本，本轮没有声称完成真机 Apple 健康读取验证。
- 全仓 Ruff 仍有 28 个本轮前已存在的问题，主要是无关模块的未使用 import 和刻意后置 import；本次变更文件检查通过，未为追求数字而扩大无关改动范围。
- Pydantic v2 对旧 class Config 的弃用警告和测试环境短 JWT key 警告仍存在；生产部署会只检查密钥长度，不输出密钥。
- 医疗知识边界仍需持续按指南版本维护；确定性规则有版本字段，后续变更必须配套反例测试。
- 本轮未上传 TestFlight；已安装的 TestFlight 1.0(14) 不包含本次修改，若要测试员获得新 iOS 客户端仍需另行发布。
