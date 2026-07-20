# 北京时间每日饮食总结设计

## 目标

后端每天北京时间 04:00，仅为前一饮食日期存在有效、已确认饮食记录的用户生成总结。总结基于用户前一天确认的食物、份量、餐次、结构标签和营养估算，判断营养搭配是否均衡，并给出当天可执行的调整建议。

大模型不可用、超时或返回非法结构时，系统必须先保存并展示规则版保底总结，再按持久化重试计划自动补写 AI 总结。用户即使只确认了一餐也要生成总结，但不得把有限记录表述成完整的一日摄入。

## 范围

本功能只读取新版 `DietaryRecord` 中状态不为 `deleted` 的已确认记录。旧版 `meals`、未确认草稿、识别中的草稿和已删除记录不参与汇总，也不影响“是否记录过饮食”的判断。

本功能新增一个当前登录用户自助读取接口，不增加推送、通知或 iOS 页面改动。它复用现有 `DietaryDay` 和 `DietaryDailySummary`，不新增表或迁移。

## 方案选择

采用专用饮食总结 Provider 方法，而不复用普通聊天 `generate_text`。普通聊天路径包含会话历史、健康上下文和回答路由，不适合后台批量、结构化、可重试的总结任务。专用方法只接收最小饮食证据并返回固定结构，便于校验、隔离和测试。

不新增 outbox 或任务表。任务和重试状态写入现有 `DietaryDailySummary.evidence` JSONB；现有 `(user_id, subject_user_id, diet_date, record_version)` 唯一约束继续承担幂等边界。该方案满足当前需求，同时避免触发独立数据库迁移项目。

## 时间语义与候选用户

Celery 配置继续使用 `Asia/Shanghai`，主任务使用 `crontab(hour=4, minute=0)`，每天北京时间 04:00 触发一次。

目标日期为任务触发时的北京时间日历日期减一天。候选集合直接从有效 `DietaryRecord` 查询目标日期上不同的 `(user_id, subject_user_id)`，因此只有前一天存在至少一条已确认记录的用户会创建总结并调用模型。仅有历史记录但目标日期无记录、从未记录、仅有草稿或记录均已删除的用户均不进入批处理。

一条记录也属于有效候选。此时规则版和模型版都必须明确“记录有限，无法完整代表全天饮食”，模型评估应为 `insufficient_data`，或在结论中表达等价含义。

## 处理架构

每个候选用户独立处理，单个用户失败不得阻止其他用户。

### 阶段一：数据库内准备保底总结

1. 在短事务中锁定目标 `DietaryDay`。
2. 重新读取目标日期的有效已确认记录并计算 `record_version`、餐次数量、结构摘要和规则版结论。
3. 若同一用户、日期和记录版本的总结已存在，则复用它，不重复创建。
4. 若不存在，则先写入 `DietaryDailySummary`。`conclusion` 和 `today_suggestion` 使用规则模板；`evidence.generation_status` 初始为 `fallback_retryable`，并保存纳入的记录 ID、模型输入指纹、重试次数和下一重试时间。
5. 提交事务。到这一步后，即使模型或 Worker 随即失败，接口仍有可展示结果。

### 阶段二：事务外调用模型

从已确认记录构造最小、规范化的模型输入，在数据库事务之外调用专用 Provider。不得向模型发送原始图片、草稿、其他健康数据、聊天历史、访问令牌或其他用户信息。

### 阶段三：数据库内条件写回

模型输出通过严格结构校验后，在新的短事务中重新锁定饮食日。只有当前 `record_version` 与调用前版本一致、总结仍为待补写状态时，才能用模型结论和建议更新该总结，并把 `generation_status` 改为 `ai_completed`。

如果用户在模型调用期间修改或删除记录，版本检查必须拒绝旧结果。新记录版本通过现有 stale/recalculation 机制生成新总结，旧版本总结不得覆盖新版本。

## 模型契约

新增专用结果类型，包含：

- `balance_assessment`: `balanced`、`imbalanced` 或 `insufficient_data`。
- `conclusion`: 对昨日营养搭配的简短中文结论。
- `today_suggestion`: 当天可以执行的具体调整建议。
- `confidence`: `0` 到 `1`。

Provider 输入包含目标日期及按时间排序的餐食，每餐仅包含餐次、食物名称、份量、结构标签、营养估算和确认置信度。系统提示要求：

- 只依据给定记录，不补造食物、份量或营养数值。
- 一餐记录不能推断完整全天摄入。
- 使用中性、非羞辱性表述，不使用“好食物/坏食物”等道德化分类。
- 建议必须简单、可执行，不作诊断或替代医疗意见。
- 输出必须符合固定 JSON 结构。

Pydantic 校验失败、调用异常、超时或空输出均按模型失败处理。

## 降级和重试

模型失败不回滚规则版总结。失败信息只保存经过限制和清理的错误类别，不保存密钥、完整供应商响应或敏感请求体。

重试信息存放于 `DietaryDailySummary.evidence`：

- `generation_status`: `fallback_retryable`、`ai_completed` 或 `fallback_exhausted`。
- `retry_attempt_count`: 已执行的补写次数。
- `next_retry_at`: 下一次允许重试的 UTC 时间。
- `last_error_code`: 经过归一化的错误类别。
- `model_input_fingerprint`: 规范化输入的 SHA-256。

周期性重试 Sweep 只选择 `fallback_retryable` 且 `next_retry_at` 已到期的总结。退避间隔依次为 5 分钟、15 分钟、1 小时、3 小时和 6 小时。五次补写仍失败后改为 `fallback_exhausted`，继续展示规则版，不再主动消耗模型额度。

重试成功时更新同一记录版本的总结内容和证据，不创建重复总结。每次写回仍执行记录版本和输入指纹检查。

## 展示接口

新增认证接口：

`GET /api/dietary-records/daily-summary`

接口仅允许读取当前登录用户本人，目标日期固定为请求发生时的北京时间日期减一天，不接受客户端传入日期或时区覆盖。

响应顶层字段：

- `status`: `available`、`never_recorded`、`no_yesterday_records` 或 `processing`。
- `target_date`: 北京时间昨天。
- `message`: 状态提示；有总结时为 `null`。
- `summary`: 可空的总结对象。

状态判定按以下顺序执行：

1. 当前用户从未存在过有效、已确认的 `DietaryRecord`：返回 `never_recorded`，文案严格为“还没有记录过饮食呢，快记录你的第一餐吧”。
2. 当前用户历史上有有效、已确认记录，但目标日期没有：返回 `no_yesterday_records`，文案严格为“昨天忘记记录饮食啦”。
3. 目标日期有记录但保底总结尚未落库，例如 04:00 前查询或任务刚启动：返回 `processing`，不得误报为未记录。
4. 总结存在：返回 `available`。规则降级仍属于可用总结。

总结对象至少包含：

- `conclusion`
- `today_suggestion`
- `confirmed_meal_count`
- `confidence`
- `generation_source`: `ai` 或 `rule_fallback`
- `retry_pending`
- `generated_at`

当 `generation_status` 为 `ai_completed` 时，`generation_source` 为 `ai` 且 `retry_pending=false`；当状态为 `fallback_retryable` 时，分别为 `rule_fallback` 和 `true`；当状态为 `fallback_exhausted` 时，分别为 `rule_fallback` 和 `false`。

## 与现有行为的关系

现有手动完成接口继续可用。现有仪表盘读取和历史编辑后的 stale/recalculation 行为必须保留，但自动汇总时间不再根据记录自身时区分别触发。后台主任务和读取接口统一使用北京时间目标日期。

现有规则结构摘要仍是可解释的保底和模型输入之一。模型只负责自然语言均衡性结论和当日调整建议，不能改变已确认记录、餐次计数、结构摘要或记录完整性事实。

## 并发、幂等与隔离

- 候选查询和所有写入均包含 `user_id` 与 `subject_user_id`，禁止跨租户读取或写回。
- 同一版本总结由数据库唯一约束去重。
- 多个 Beat 或 Worker 重复执行时，行锁和状态检查确保只有一个调用获得有效写回资格。
- 模型调用不持有数据库事务或行锁。
- 单个候选失败被计入任务结果并继续处理其他候选。
- 记录版本或输入指纹不一致时丢弃旧模型响应，不能强行覆盖。

## 测试策略

新增或强化命名回归测试，至少覆盖：

1. Celery Beat 主任务严格为北京时间每日 04:00。
2. 候选查询只包含目标日期存在有效已确认记录的用户。
3. 旧版 `meals`、草稿、待确认和已删除记录不触发总结。
4. 单餐生成保底和模型总结，并明确记录不足。
5. 专用 Provider 收到最小化、租户隔离且顺序稳定的输入。
6. 合法模型结果写回；超时、异常、空输出和非法结构保留规则版。
7. 五档退避、到期筛选、成功补写和耗尽状态。
8. 重复投递、并发处理、记录修改和输入指纹变化不会重复写或错写。
9. 接口对从未记录、昨日漏记、处理中、AI 总结和规则降级分别返回精确契约。
10. 当前用户无法读取其他用户的总结或用参数覆盖目标日期、主体和时区。
11. 现有手动完成、仪表盘、历史编辑重算与周汇总测试继续通过。

## 质量与交付约束

实施前更新 `quality/change_impact.json`，真实声明后端、AI 客户端、饮食记录、调度、接口和测试完整性影响，扫描所有相邻入口并绑定相关 invariant ID。生产改动前先添加能在旧行为上按预期失败的命名测试。

正常编辑阶段运行 `/usr/bin/python3 -I tools/run_regression_gate.py fast`。实现稳定后、交付 PR 前只运行一次 `/usr/bin/python3 -I tools/run_regression_gate.py impacted`。任何当前阶段要求的失败都保持阻塞，不能把较低阶段结果描述为发布证据。

