# iOS XAGE 成熟对话下一步手动 Simulator 验证记录

日期：2026-07-08

设备：iPhone 17 Pro Simulator

方式：手动点击、手动输入、手动等待模型返回和手动截图。中文输入通过 Simulator 剪贴板粘贴完成；没有使用真机。

## 准备

1. 安装 iOS Debug 构建到 iPhone 17 Pro Simulator。
2. 启动本地后端，数据库使用临时 SQLite 文件，只写入本轮合成测试数据。
3. 合成数据包含：Apple Health 来源 HRV、睡眠、步数、血压；CGM 来源 TIR 和血糖；手动来源尿酸、胱抑素 C、血压；一份待识别报告。
4. 启动 App 时 API 指向本地后端，并注入仅本地有效的调试登录态。记录中不保存 JWT、密码或 API key。

## 手动交互

1. 输入“我是不是已经同步过 Apple 健康？”。
   - 观察：助手直接确认 Apple 健康已经同步，并列出可用数据源/指标；没有问“平时戴 Apple Watch 吗”。
   - 截图：`screenshots/01b_apple_health_memory_real_provider.png`。

2. 输入“我头疼还恶心怎么办”。
   - 等待阶段观察：进度卡片停留在输入栏上方，长会话滚动位置没有卡住。
   - 等待截图：`screenshots/02_symptom_waiting_bottom_visible.png`。
   - 回答观察：助手先按普通症状分诊处理，提示休息、补水、清淡饮食，同时列出严重头痛、高热、意识异常等就医边界。
   - 回答截图：`screenshots/03_symptom_response_manual.png`。

3. 输入“怎么调整晚饭碳水、咖啡和运动，避免影响睡眠和 HRV？”。
   - 观察：回答围绕晚饭碳水、咖啡因截止时间、运动强度和睡前节律给出具体动作，并使用 HRV/睡眠上下文；没有反问设备。
   - 截图：`screenshots/04_lifestyle_hrv_response_manual.png`。

4. 输入“我老婆 NT 2.8 正常吗？”。
   - 观察：助手把主体识别为妻子，只讨论 NT、孕周、CRL 和产检复核；没有引用本人尿酸、血糖或 TIR。
   - 截图：`screenshots/05_relative_nt_response_manual.png`。

5. 输入“我的血压为什么变化这么大？”。
   - 观察：助手直接列出 Apple Health 与手动血压的来源、时间、数值和差异，并建议同一手臂坐位复测。
   - 截图：`screenshots/06_bp_conflict_fast_path_manual.png`。

6. 输入“那如果晚上又头疼呢？”。
   - 观察：助手只回答夜间头痛新增处理，未重复展开上一轮血压来源、报告状态或全部旧建议。
   - 截图：`screenshots/07_followup_delta_response_manual.png`。

7. 输入“我胸痛喘不上气还冒冷汗怎么办”。
   - 观察：后端命中急症 fast path，立即显示“检测到紧急症状，请立即就医”，没有进入长时间模型分析。
   - 截图：`screenshots/08_emergency_fast_path_manual.png`。

8. 输入“我的报告分析好了吗？”。
   - 观察：助手显示待识别报告仍在后台处理中，没有编造报告结论。
   - 截图：`screenshots/09_report_status_fast_path_manual.png`。

## 结论

本轮手动验证覆盖了数据源记忆、普通症状、生活方式、家属主体、多来源冲突、会话增量追问、急症和报告状态。所有交互均在 iPhone 17 Pro Simulator 完成，等待态和最终回答都保留截图证据。
