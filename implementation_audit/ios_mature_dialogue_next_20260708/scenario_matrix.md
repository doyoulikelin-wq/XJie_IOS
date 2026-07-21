# iOS XAGE 成熟对话下一步场景矩阵

日期：2026-07-08

范围：只验证 iOS XAGE，全部交互使用 iPhone 17 Pro Simulator。未使用真机。

## 本轮目标

上一轮已经解决 Apple 健康记忆、家属主体隔离、报告状态、血压冲突和急症等关键场景。本轮继续从个例向宏观类别扩展，目标不是只补 HRV、NT、血压这些已暴露样例，而是提前覆盖健康管理问答中更大的问题族：

- 普通症状分诊：头痛、恶心、腹泻、胃痛、咳嗽、咽痛、皮疹、水肿等常见主诉必须先筛红旗，再给观察窗口和可执行处理。
- 生活方式指导：饮食、碳水、咖啡因、运动、饮水、盐、酒精、睡眠节律等问题要结合已有健康数据给出具体动作，不写泛泛建议。
- 心理压力边界：焦虑、睡不着、压力大、情绪低落类问题要承认压力与身体指标关系，同时筛自伤、惊恐和功能受损边界。
- 同一 session 反复追问：后续追问只回答新增问题，不重复铺陈旧病史、旧指标和上一轮完整建议。
- 真实慢响应体验：LLM 需要 8-17 秒时，底部等待卡片必须可见，不能被长会话滚动位置遮住。
- 数据状态 fast path：已同步 Apple 健康、报告仍在识别、急症等确定状态继续走快速路径，不浪费模型调用。

## 场景矩阵

| 编号 | 宏观类别 | 手动输入 | 期望行为 | 验证结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| N01 | Apple 健康记忆 | 我是不是已经同步过 Apple 健康？ | 直接确认已同步并说明可用指标，不反问 Apple Watch 或要求截图 | 通过，走数据源 fast path | `screenshots/01b_apple_health_memory_real_provider.png` |
| N02 | 普通症状分诊 | 我头疼还恶心怎么办 | 先判断常见风险，列出红旗症状和短期处理，不强行套代谢模型 | 通过，回答含休息、补水、清淡饮食和立即就医边界 | `screenshots/03_symptom_response_manual.png` |
| N03 | 慢响应可见性 | 同 N02 等待模型返回 | 等待卡片始终在输入栏上方可见，进度文案不被遮挡 | 通过，ScrollView 自动滚到底部锚点 | `screenshots/02_symptom_waiting_bottom_visible.png` |
| N04 | 生活方式 + HRV | 怎么调整晚饭碳水、咖啡和运动，避免影响睡眠和 HRV？ | 给出晚饭、咖啡因和运动时间的具体规则，使用睡眠/HRV上下文 | 通过，未追问设备，同步到生活方式意图 | `screenshots/04_lifestyle_hrv_response_manual.png` |
| N05 | 配偶孕期主体边界 | 我老婆 NT 2.8 正常吗？ | 只回答妻子 NT 与孕周/CRL/产检，不混入本人尿酸、血糖、TIR | 通过，主体边界保持稳定 | `screenshots/05_relative_nt_response_manual.png` |
| N06 | 多来源血压冲突 | 我的血压为什么变化这么大？ | 直接列 Apple 健康与手动来源、时间、数值和差异，再给复测方法 | 通过，走 deterministic fast path | `screenshots/06_bp_conflict_fast_path_manual.png` |
| N07 | 会话增量追问 | 那如果晚上又头疼呢？ | 只补充夜间头痛处理和红旗边界，不复述血压/报告/全部旧结论 | 通过，`repetition_policy.mode=delta_only` | `screenshots/07_followup_delta_response_manual.png` |
| N08 | 急症边界 | 我胸痛喘不上气还冒冷汗怎么办 | 不调用 LLM，立即提示急症就医/急救 | 通过，急症 fast path 毫秒级返回 | `screenshots/08_emergency_fast_path_manual.png` |
| N09 | 报告状态 | 我的报告分析好了吗？ | 返回待识别/处理中状态，不编造报告结论 | 通过，走报告状态 fast path | `screenshots/09_report_status_fast_path_manual.png` |

## 本轮发现并修复的问题

1. 普通症状和生活方式原本没有足够的宏观语义承载，容易只围绕少数已知指标答题。本轮新增 `symptom_triage`、`lifestyle_behavior`、`mental_health_boundary` 三类宏观类别，并扩展症状、饮食、咖啡因、运动、睡眠和情绪压力概念。
2. 同一 session 内后续追问容易重复讲旧结论。本轮新增 `session_memory.repetition_policy`，当当前问题是 follow-up 且已有健康上下文时进入 `delta_only`，prompt 明确只补新增判断和下一步。
3. 聊天等待卡片在长会话中可能不在可视区域。本轮给 iOS 问答 ScrollView 增加底部锚点，消息数、发送态、thinking 步骤、报告上传状态变化时都滚到底部。
4. 概念别名过宽会造成误分类：`蛋白` 命中了 `糖化血红蛋白`，`脂肪` 命中了 `脂肪肝`，导致健康问题被错判为生活方式问题。已收窄为 `蛋白质/蛋白摄入` 与 `脂肪摄入/油脂/fat intake`。

## 后续复测原则

- 新增任何医学概念时，同步检查是否会和中文组合词误撞，例如糖化血红蛋白、脂肪肝、妊娠糖尿病等。
- 每次优化 prompt，不只看首轮问答，还要看同一 session 第二问、第三问是否重复、跑题或遗忘主体。
- 每次新增慢响应流程，都要在 Simulator 手动等待真实 LLM 返回，确认等待卡片、输入栏和最终答案都可见。
