# iOS XAGE 成熟健康对话验证报告

日期：2026-07-08

## 代码范围

- 新增 `backend/app/services/health_nlu.py`：健康语义概念、意图、安全等级、数据需求、质量门控和宏观类别。
- 扩展 `context_builder.py`：`message_structure.health_nlu`、语义意图、数据需求、风险计划、进度步骤。
- 扩展 `openai_provider.py`：prompt 读取 NLU 结构，并在家属/他人主体下清理本人事实、数据源和历史 assistant 结论。
- 扩展 `chat.py`：报告状态、数据源、血压等多来源冲突 fast path；急症返回短摘要。
- 扩展 `safety_service.py`：胸痛、冒冷汗、喘不上气、卒中、失血、自伤等急症关键词。
- 调整 `glucose_sync.py`：本地 sqlite 验证环境跳过 PostgreSQL 专用后台循环，避免干扰手动测试。

## 验证命令

```bash
python3 -m py_compile backend/app/services/health_nlu.py backend/app/services/context_builder.py backend/app/providers/openai_provider.py backend/app/routers/chat.py backend/app/services/safety_service.py backend/app/services/glucose_sync.py
backend/.venv/bin/python -m pytest backend/tests/unit/test_health_nlu.py backend/tests/unit/test_chat_message_structure.py -q
backend/.venv/bin/python -m pytest backend/tests/unit -q
xcodebuild -quiet -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -derivedDataPath /tmp/xjie-healthnlu-derived build
```

结果：

- 后端专项测试：40 passed。
- 后端 unit：52 passed，只有既有 Pydantic/JWT 测试警告。
- iOS Debug build：通过。
- 手动 Simulator：8 个代表场景完成，截图保存在 `screenshots/`。

## 生产部署

已同步到生产服务器源码和运行容器：

- `/home/mayl/XJie_IOS/backend/app/services/health_nlu.py`
- `/home/mayl/XJie_IOS/backend/app/services/context_builder.py`
- `/home/mayl/XJie_IOS/backend/app/providers/openai_provider.py`
- `/home/mayl/XJie_IOS/backend/app/routers/chat.py`
- `/home/mayl/XJie_IOS/backend/app/services/safety_service.py`
- `/home/mayl/XJie_IOS/backend/app/services/glucose_sync.py`
- `/home/mayl/XJie_IOS/backend/tests/unit/test_health_nlu.py`
- `/home/mayl/XJie_IOS/backend/tests/unit/test_chat_message_structure.py`

生产容器验证：

- `xjie-api` 容器内 `py_compile` 通过。
- `xjie-api` 容器内专项测试 40 passed。
- 重启后服务器本机 `/healthz` 返回 `{"ok":true}`。
- 公网 `http://8.130.213.44:8000/healthz` 返回 `{"ok":true}`。
- 域名 `https://www.jianjieaitech.com/healthz` 返回 `{"ok":true}`。
- 已提交 `xjie-backend:latest` 镜像。

## 截图索引

- `screenshots/00_data_page_seeded.png`：数据页测试数据确认。
- `screenshots/01_apple_health_memory_fast_path.png`：Apple 健康同步记忆。
- `screenshots/02_hrv_uses_synced_context.png`：HRV 使用已同步上下文。
- `screenshots/03_relative_nt_subject_boundary.png`：妻子 NT 主体边界。
- `screenshots/04_relative_mother_glucose_history_sanitized.png`：母亲血糖主体隔离修复后。
- `screenshots/05_bp_conflict_and_report_status_fast_paths.png`：血压多来源冲突与报告状态。
- `screenshots/06_medication_safety_boundary.png`：药物安全边界。
- `screenshots/07_emergency_fast_template_sent_state.png`：急症输入与后端急症 fast path。

## 剩余观察

- 本轮没有使用真机，符合用户“先用 simulator”的要求。
- iOS 问答 ScrollView 在极长会话中手动上滑/下滑不总是能立刻定位到最后一条，急症场景因此同时保留了 UI 发送截图和后端返回证据。后续如继续优化 UI，可单独处理聊天自动滚动和可见性。
- 本轮重点在后端语义和 prompt 结构，未改变 iOS 视觉结构。
