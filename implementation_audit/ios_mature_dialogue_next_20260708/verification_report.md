# iOS XAGE 成熟对话下一步验证报告

日期：2026-07-08

## 代码范围

- `backend/app/services/health_nlu.py`
  - 扩展普通症状、生活方式、睡眠压力和心理压力概念。
  - 新增 `symptom_triage`、`lifestyle_coaching`、`mental_health_support` 意图和对应宏观类别。
  - 补充安全分层、质量门控、潜在目的和数据需求。
  - 收窄 `蛋白/脂肪` 相关别名，避免误命中糖化血红蛋白和脂肪肝。
- `backend/app/services/context_builder.py`
  - 扩展健康问题识别范围到症状、生活方式和情绪压力。
  - 增加重复建议识别和 follow-up 判断。
  - 新增 `session_memory.repetition_policy`，支持同一 session 追问时只回答新增问题。
  - 进度文案按症状、生活方式、心理压力等意图区分。
- `backend/app/providers/openai_provider.py`
  - Prompt 明确普通症状、生活方式和心理压力的回答边界。
  - Prompt 明确 `delta_only` 时只补新增判断，不重讲旧结论。
- `Xjie/Xjie/Views/Home/XAgeMainView.swift`
  - XAGE 问答 ScrollView 增加底部锚点。
  - 消息、发送态、thinking 步骤、报告上传状态变化时自动滚到底部，保证等待卡片和最终回答可见。
- `backend/tests/unit/test_health_nlu.py`
  - 新增普通症状、腹泻胃痛、焦虑失眠和生活方式意图测试。
- `backend/tests/unit/test_chat_message_structure.py`
  - 新增 follow-up 增量记忆测试，覆盖 `delta_only` 和重复建议规避。

## 验证命令

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_health_nlu.py backend/tests/unit/test_chat_message_structure.py -q
backend/.venv/bin/python -m pytest backend/tests/unit -q
git diff --check
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-mature-dialogue-derived build
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -skip-testing:XjieUITests -parallel-testing-enabled NO -derivedDataPath /tmp/xjie-mature-dialogue-tests test
```

结果：

- 后端新增专项测试：45 passed。
- 后端完整 unit：57 passed。
- `git diff --check`：通过。
- iOS Debug build：通过。
- iOS unit tests on Simulator：通过。
- 手动 Simulator：9 个场景完成，截图保存在 `screenshots/`。

## 手动验证证据

- `screenshots/01b_apple_health_memory_real_provider.png`：Apple 健康同步记忆。
- `screenshots/02_symptom_waiting_bottom_visible.png`：慢响应等待卡片保持底部可见。
- `screenshots/03_symptom_response_manual.png`：普通症状分诊。
- `screenshots/04_lifestyle_hrv_response_manual.png`：生活方式和 HRV/睡眠指导。
- `screenshots/05_relative_nt_response_manual.png`：妻子 NT 主体边界。
- `screenshots/06_bp_conflict_fast_path_manual.png`：血压多来源冲突 fast path。
- `screenshots/07_followup_delta_response_manual.png`：同一 session 增量追问。
- `screenshots/08_emergency_fast_path_manual.png`：急症 fast path。
- `screenshots/09_report_status_fast_path_manual.png`：报告状态 fast path。

## 数据与安全说明

- 本轮手动验证只使用本地临时 SQLite 和合成健康数据。
- 本轮没有使用真机。
- 审计记录、开发记录和 memory 不包含真实密码、JWT、API key 或其它 secret。
- 本轮未发布 TestFlight，属于 iOS XAGE 本地分支功能改造与 Simulator 复测。

## 剩余观察

- 真实线上用户的自然语言质量仍需要在有效线上登录态下继续人工抽样，但本轮结构层和 UI 等待可见性已经用本地真实 LLM 调用路径验证。
- 后续继续扩展疾病/指标时，要优先补概念、主体、数据时效、安全边界和重复策略，而不是只补关键词。
