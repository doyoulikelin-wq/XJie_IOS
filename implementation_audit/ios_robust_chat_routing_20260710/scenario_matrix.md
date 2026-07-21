# Simulator 人工场景矩阵

设备：iPhone 17 Pro Simulator，iOS 26.3.1

执行方式：每一步由 Codex 通过 Simulator UI 实际点击、输入、发送、重试和切换；截图来自对应执行完成状态。

| # | 场景 | 预期边界 | 结果 | 证据 |
| --- | --- | --- | --- | --- |
| 01 | 本地 HTTPS/登录后数据首页 | 登录态和新壳层可进入 | 通过 | [01](screenshots/01_login_data_home_https_local.jpg) |
| 02 | 已同步 Apple 健康询问 | 直接使用同步记忆，不反问 Apple Watch | 通过 | [02](screenshots/02_apple_health_memory.jpg) |
| 03 | 未授权 AI 问答 | 明确弹出授权，不自动同意 | 通过 | [03](screenshots/03_explicit_ai_consent_prompt.jpg) |
| 04 | 拒绝 AI 授权 | 原消息保留，状态可恢复 | 通过 | [04](screenshots/04_consent_declined_keeps_message.jpg) |
| 05 | 接受授权并重试 | 使用同一消息标识，不重复气泡 | 通过 | [05](screenshots/05_consent_accept_reuses_message.png) |
| 06 | HRV 深度问题 | 展示服务器 route/progress | 通过 | [06](screenshots/06_hrv_server_route_progress.jpg) |
| 07 | HRV 趋势证据不足 | 不编造趋势，说明缺少时段/样本 | 通过 | [07](screenshots/07_hrv_insufficient_evidence_fixed.png) |
| 08 | 家属询问同步状态 | 不读取本人设备数据代替家属 | 通过 | [08](screenshots/08_relative_data_source_boundary.png) |
| 09 | 高血糖合并 DKA 症状 | 直接急症路由，不等待 LLM | 通过 | [09](screenshots/09_high_numeric_and_dka_routes.png) |
| 10 | 上下文中的裸数字 | 缺少指标/单位时先澄清 | 通过 | [10](screenshots/10_contextual_bare_number_clarification.png) |
| 11 | 普通症状分诊 | 先筛红旗，再给观察窗口 | 通过 | [11](screenshots/11_symptom_triage_clean_summary.png) |
| 12 | 家属连续追问 | 延续同一主体，只回答新增问题 | 通过 | [12](screenshots/12_relative_subject_memory_delta.png) |
| 13 | SSE 多个进度事件 | 进度去重，最终仅一条回答 | 通过 | [13](screenshots/13_server_progress_no_duplicate.jpg) |
| 14 | 网络断开 | 有限时间失败，用户气泡可重试 | 通过 | [14](screenshots/14_network_failure_retry_state.png) |
| 15 | 网络恢复后重试 | 同一消息仅落库一次 | 通过 | [15](screenshots/15_network_retry_success_no_duplicate.png) |
| 16 | 回答处理中创建新对话 | 新会话立即清空旧请求归属 | 通过 | [16](screenshots/16_new_chat_while_previous_inflight.png) |
| 17 | 旧回答稍后返回 | 不能进入新对话 | 通过 | [17](screenshots/17_old_answer_does_not_cross_new_chat.png) |
| 18 | `SBP 190` | 单项严重收缩压不能被忽略 | 通过 | [18](screenshots/18_unitless_severe_systolic_route.png) |
| 19 | `SBP 120` | 舒张压缺失时澄清，不构造 120/120 | 通过 | [19](screenshots/19_incomplete_systolic_clarification.png) |
| 20 | 血糖 20 无单位 | 两种常见单位均危险，先核对并复测 | 通过 | [20](screenshots/20_unitless_glucose_ambiguous_high_risk.png) |
| 21 | 血压后改问血糖 5.5 | 当前概念优先，不沿用血压主题 | 通过 | [21](screenshots/21_cross_topic_glucose_clarification_fixed.png) |
| 22 | 血糖 50 mg/dL | 严重低血糖确定性处理 | 通过 | [22](screenshots/22_explicit_unit_severe_hypoglycemia.png) |
| 23 | 家属切回本人 | 主体状态与数据范围一起切换 | 通过 | [23](screenshots/23_relative_to_self_subject_switch.png) |
| 24 | 朋友病例 | 不注入本人尿酸、血糖或设备数据 | 通过 | [24](screenshots/24_friend_subject_data_isolation.png) |
| 25 | 血糖 20 + 呕吐、否认腹痛 | 只回显呕吐，不虚构腹痛/深快呼吸 | 通过 | [25](screenshots/25_emergency_symptom_fact_accuracy_fixed.png) |
| 26 | 妻子孕 32 周，160/110 | 使用孕产 `160/110` 严重阈值 | 通过 | [26](screenshots/26_pregnancy_severe_threshold.png) |
| 27 | 下一轮“她现在 165/112” | 延续妻子孕期主体 | 通过 | [27](screenshots/27_pregnancy_same_subject_continuity.png) |
| 28 | “说回我，我 190/125” | 恢复普通成人 `180/120` 规则 | 通过 | [28](screenshots/28_subject_switch_no_pregnancy_leak.png) |
| 29 | 孕 34 周 165/112 + 剧烈头痛，否认上腹痛 | 急诊；只陈述剧烈头痛 | 通过 | [29](screenshots/29_pregnancy_emergency_exact_symptom.png) |
| 30 | 5 岁孩子 2.8 mmol/L | 不固定套成人剂量；发送后 IME 草稿清空 | 通过 | [30](screenshots/30_child_hypoglycemia_and_ime_clear.png) |
| 31 | 成年本人 2.8 mmol/L | 保留成人 15 克/15 分钟规则 | 通过 | [31](screenshots/31_adult_hypoglycemia_counterexample.png) |
| 32 | 妻子旧孕期后确认未怀孕 | 最新同主体状态覆盖旧状态 | 通过 | [32](screenshots/32_latest_subject_state_overrides_history.png) |

## 自动化场景补充

- 意图：问候、同步状态、报告状态、上传、摘要、趋势、冲突、时效、指标解释、生活方式、用药、孕产、心理和急症。
- 数值：成对/单项血压、显式/缺失血糖单位、低血糖、高血糖、酮症症状组合和否定症状。
- 主体：本人、妻子、母亲、孩子、朋友、未明确他人、主体纠正和历史延续。
- 时态：当前、假设、科普、已缓解、最新状态覆盖旧状态。
- 证据：有趋势样本、样本不足、数据过期、多来源冲突、家属未授权。
- 传输：SSE、同步回退、401 刷新、网络失败重试、上传刷新、幂等重放和租约接管。
