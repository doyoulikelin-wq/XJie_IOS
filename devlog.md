# Xjie iOS 开发日志 (DevLog)

> 项目：Xjie iOS App (SwiftUI)  
> 起始日期：2026-03-24  
> 当前状态：v1.6.0 已上传 TestFlight (build 2)

---

## 2026-07-04 — XAGE 全互动复检与修复

### iOS / XAGE ✅

- 对 iPhone 17 Pro Simulator 上的 XAGE 数据、问答、X年龄和左上更多菜单做逐项复检，确认不再跳旧版页面。
- 修复数据页底部四分类可访问性选中态：`报告 / 日常 / 就医 / 画像` 的 selected trait 现在随点击正确移动，装饰图形不再干扰按钮语义。
- 修复问答输入栏加号菜单：从系统 `confirmationDialog` 改为 XAGE 液态玻璃自定义菜单，`选择 PDF / 图片报告`、`从相册上传报告`、`新对话` 都能触发真实入口；Files、相册、相机均已在 Simulator 打开并关闭回到 XAGE。
- 修复语音按钮在 Simulator 上触发 `AVAudioEngine.inputNode` 崩溃的问题：模拟器显示明确不可录音提示，真机仍保留原语音识别/麦克风路径。
- 修复问答右上历史按钮无动作的问题：接入 `ChatViewModel.conversations`，新增 XAGE 液态玻璃历史面板、空态、加载更多和历史会话选择入口。
- 补齐 X年龄页互动：右上简介按钮打开同风格说明 sheet，日期胶囊左右箭头变为真实周切换，X年龄、差值、衰老进度和说明内容随周同步更新并在边界禁用按钮。
- 验证：Debug build 通过，`xcodebuild test` 通过，`git diff --check` 通过；最近 20 分钟无新增 `Xjie` 崩溃报告。逐项截图保存到 `X_new/implementation_audit/ios_full_interaction_recheck_20260704/`。

## 2026-07-02 — XAGE 数据页上滑隐藏今日状态

### iOS / XAGE ✅

- 数据页 `今日状态` 玻璃摘要现在会在用户上滑指标列表时隐藏，回到顶部附近后自动恢复。
- 保持三枚评分圆环 sticky 可见，不恢复此前导致卡顿的逐卡片 offset/3D peel 监听。
- iOS 18+ 使用 `onScrollGeometryChange` 读取 ScrollView `contentOffset.y`；iOS 17 保留单个顶部 probe fallback，并补充可访问性滚动动作。
- iPhone 17 Pro Simulator 真实拖拽验证初始可见、上滑隐藏、下滑恢复；截图保存到 `X_new/implementation_audit/ios_today_status_scroll_hide_20260702/`。
- 验证：Debug build 通过，`xcodebuild test` 49 个测试 0 失败，`git diff --check` 通过。

## 2026-07-02 — XAGE 四分类详情页互动内容

### iOS / XAGE ✅

- 数据页底部 `报告 / 日常 / 就医 / 画像` 四分类进入后的详情页新增行内互动内容，不再只是静态信息展示。
- 三行操作入口统一变为可点击行，选中后在当前页内切换对应互动面板，并显示 `查看中` 状态。
- `报告` 支持上传入口 chip、AI 识别进度、字段确认勾选；`日常` 支持 Apple Health 同步状态、恢复信号进度、趋势因子勾选。
- `就医` 支持诊断时间线、处方核对、随访提醒；`画像` 支持资料完整度、长期标签选择、安全信息勾选。
- 底部 CTA 变为可点击按钮，点击后在面板中反馈 `已更新`，全程保持 XAGE 液态玻璃风格和页面内交互。

## 2026-07-02 — XAGE Apple 健康授权与同步

### iOS / XAGE ✅

- iOS target 增加 HealthKit capability、`Xjie.entitlements` 和 `NSHealthShareUsageDescription`，以只读方式申请 Apple 健康数据。
- 新增 `AppleHealthSyncViewModel`，读取 Apple 健康步数、距离、活动能量、运动分钟、爬楼层、睡眠、HRV、静息心率、呼吸率、血氧、体重和体脂率等今日或最近样本。
- XAGE 数据页新增液态玻璃 `Apple 健康同步` 卡，日常目标页新增 `Apple Health` 同步行；授权、读取、同步和无数据状态共享同一 ViewModel。
- 后端新增 `/api/health-data/indicators/device-sync`，把 Apple 健康样本幂等写入 `user_indicator_values`，复用现有用户端指标和趋势接口展示同步结果。
- 补充后端单测与 iOS ViewModel 单测；Simulator 验证同步卡、HealthKit 权限弹窗、中文无数据态和日常详情页同步入口。

## 2026-07-02 — XAGE 问答输入栏按钮与报告上传修复

### iOS / XAGE ✅

- 问答输入栏四个入口接通：麦克风启动系统语音识别、相机入口拍照上传、加号入口提供 PDF/图片报告、相册报告和新对话，发送按钮继续走正文发送。
- XAGE 问答发送统一通过 `ChatViewModel` 的 `/api/chat` 链路；iOS 不硬编码 LLM 模型，模型与 provider 仍由后端集中选择并写入审计日志。
- 报告上传修复系统文件读取：`DocumentPickerView` 改用 copy 模式和安全作用域读取，支持 PDF、图片、HEIC、PNG、JPEG 与 CSV，并把失败原因回传到界面。
- 图片/PDF 上传完成后自动把文档 ID 带入问答上下文；如果当前正在发送，则将问题预填进输入框，避免重复并发请求。
- `MIMETypeHelper` 补齐 HEIC/HEIF/WebP/GIF/TIFF 类型，减少图片报告被后端拒绝的概率。
- 补充单元测试覆盖 `/api/chat` 路由和新增 MIME 类型；模拟器逐项验证按钮弹层、Files、相册、相机、语音权限和新对话入口。

## 2026-04-22 — v1.6.0 多组学五幕演示 + UI 重做 + TestFlight 上线

### 多组学演示模式（后端 + iOS）✅

**后端**
- `services/omics_demo.py`：确定性合成数据生成器（以 user_id 为种子）
- `routers/omics.py`：新增 5 个 `/api/omics/demo/*` 接口
  - `metabolomics` 代谢组指纹 + 代谢年龄差
  - `genomics` 基因风险变体与故事
  - `microbiome` 肠道菌群丰度与多样性
  - `triad` 代谢×血糖×心率三系统联动洞察
  - `bundle` 一次返回全部

**iOS**
- `OmicsDemoModels.swift` / `DemoSettings.swift`：演示模式状态 + 数据模型
- `OmicsViewModel.swift`：`loadDemoIfNeeded()` + `citations(for:)` 带文献引用
- `Settings/SettingsView.swift`：`demoModeCard` 一键开启演示模式

### 组学页五幕剧本 ✅

重设 `OmicsView.swift` 为 5 个叙事幕章：
1. **幕一：代谢健康总览** — `MetabolicFingerprintView`
2. **幕二：三系统联动** — `OmicsTriadView`
3. **幕三：代谢物故事** — `MetaboliteStorySheet` + `metaboliteListCard`
4. **幕四：基因风险时间轴** — `GeneTimelineStrip`
5. **幕五：肠道菌群分布** — `MicrobiomeBubbleChart`

### UI 可读性重做✅

- **代谢指纹 → 代谢健康卡**：大健康分环 + 4 类系统占比条 + 重点关注 pills，丢弃抽象散点。
- **三圆交叠 → 三系统联动卡**：3 个并排健康度 + 箭头表达传递 + 一句话洞察，数字越大越健康。
- **菌群图中文化**：23 个常见菌属拉丁名 → 中文名（Bacteroides→拟杆菌等）。
- **菌群气泡布局修复**：细网格 + 弹性松弛算法驱散重叠。

### 文献子库✅

- `workers/omics_literature_seeds.json`：70 条多组学领域种子查询
- `workers/literature_tasks.py`：Celery beat 周一 03:00 增量抓取
- 复用现有 `topic=omics + tags` 机制，无需 migration

### TestFlight 上线 ✅

- 版本：`1.0 (2)`
- Bundle ID：`com.xjie.app`
- 上传时间：2026-04-22 02:37 (UTC+8)
- 后端 commit 同步 ECS。

### 仓库清理✅

- 删除历史微信小程序遗留文件（`app.js/json/wxss`、`pages/`、`utils/`、`sitemap.json`、`project.config.json`）。
- README 与 function.md 移除微信登录接口描述。
- LoginView 注释里的历史"微信登录按钮"表述一并清理。

---

## 2026-04-03 — v1.4.0 AI 文档摘要 + Kimi K2.5 温度修复 + UI 修复

### AI 文档摘要系统（全栈）✅

**后端**
- `health_document.py` (model)：新增 `ai_brief` (VARCHAR(20)) + `ai_summary` (TEXT) 两列
- `health_document.py` (schema)：`HealthDocumentOut` 新增 `ai_brief` / `ai_summary` 字段
- `health_data.py`：新增 `_generate_doc_summary(csv_data, abnormal_flags, doc_type)` 函数
  - 调用 LLM 生成 JSON `{"brief":"≤10字","summary":"详细内容"}`
  - 上传文档时自动生成摘要
  - `GET /documents/{doc_id}` 对历史文档进行懒加载生成（首次访问时触发）
- DB 迁移：`ALTER TABLE health_documents ADD COLUMN ai_brief VARCHAR(20); ADD COLUMN ai_summary TEXT;`

**iOS 端**
- `HealthModels.swift`：`HealthDocument` 新增 `ai_brief: String?` + `ai_summary: String?`
- `MedicalRecordViews.swift`：
  - 列表只显示日期 + ai_brief，删除改为 contextMenu 长按操作
  - 详情页主显 AI 摘要，"查看原件"/"收起原件" 按钮切换原始 CSV 数据
- `ExamReportViews.swift`：
  - 列表显示日期 + ai_brief + 异常指标数 Badge
  - 详情页 AI 摘要 + 异常警示 Banner + "查看原件" 切换

### 指标趋势图 Tooltip 修复 ✅
- `IndicatorTrendView.swift`：Tooltip 从 `RuleMark + .annotation(position: .top)` 改为 `PointMark + .annotation(position: .automatic, spacing: 6)`
- 日期格式：`yyyy-MM-dd` → `yyyy年M月d日`，字号增大（date 11pt, value 13pt, unit 10pt）
- 颜色方案：正常值 `Color.appPrimary`（蓝色），异常值 `.red`，解决暗色背景下灰色文字不可见

### CSVTableView 文字可见性修复 ✅
- `CSVTableView.swift`：为 Label 标题、表头、正常单元格添加 `.foregroundColor(.appText)`
- 异常行单元格使用 `.foregroundColor(.appDanger)`

### AI 助手更名 ✅
- 全局搜索替换：小杰 → 小捷（`933c7f3`）

### Gemini 清理 + 模型名集中化 ✅
- 移除 `gemini_provider.py` 及相关代码
- 模型名统一使用 `settings.OPENAI_MODEL_TEXT` / `settings.OPENAI_MODEL_VISION`（`81db247`）

### Kimi K2.5 Temperature 终极修复 ✅

**问题根因**：查阅 Kimi 官方 API 文档确认——`kimi-k2.5` 模型**不允许设置** temperature、top_p、n、presence_penalty、frequency_penalty 参数，必须完全省略。

**解决方案**：
- `config.py` 新增 `llm_temperature_kwargs(model)` 方法：
  - `kimi-k2.5` → 返回 `{}`（不发送 temperature）
  - 其他模型 → 返回 `{"temperature": x}`（若 `LLM_TEMPERATURE` 已配置）
- `LLM_TEMPERATURE` 类型从 `float = 0.6` 改为 `float | None = None`
- 全部 9 处调用点跨 5 个文件统一替换为 `**settings.llm_temperature_kwargs(model)`

**涉及文件**：
- `health_data.py`（3 处）：`_llm_vision_call`、`_generate_doc_summary`、指标解释
- `health_summary_service.py`（2 处）：`_llm_call`、L3 流式
- `openai_provider.py`（3 处）：食物识别、聊天非流式、聊天流式
- `health_reports.py`（1 处）：报告生成流式

### 修改文件

| 文件 | 变更 |
|---|---|
| `backend/app/models/health_document.py` | +ai_brief +ai_summary 列 |
| `backend/app/schemas/health_document.py` | HealthDocumentOut +ai_brief +ai_summary |
| `backend/app/routers/health_data.py` | _generate_doc_summary + 懒加载 + temperature 替换 |
| `backend/app/core/config.py` | llm_temperature_kwargs() + LLM_TEMPERATURE 类型改 |
| `backend/app/providers/openai_provider.py` | temperature 替换 ×3 |
| `backend/app/services/health_summary_service.py` | temperature 替换 ×2 |
| `backend/app/routers/health_reports.py` | temperature 替换 ×1 |
| `Xjie/Models/HealthModels.swift` | HealthDocument +ai_brief +ai_summary |
| `Xjie/Views/MedicalRecords/MedicalRecordViews.swift` | 列表 brief + 详情 AI 摘要 |
| `Xjie/Views/ExamReports/ExamReportViews.swift` | 列表 brief + 详情 AI 摘要 |
| `Xjie/Views/Health/IndicatorTrendView.swift` | Tooltip 位置/颜色/格式修复 |
| `Xjie/Views/Shared/CSVTableView.swift` | 文字颜色可见性修复 |

---

## 2026-04-02 — v1.3.0 管理后台指标知识库 + Bug 修复

### 管理后台指标知识库 CRUD ✅
- `admin.py` 新增 4 个端点：GET/POST/PUT/DELETE `/api/admin/indicator-knowledge`
- `admin.html` Web 管理后台新增"指标知识"Tab 页
- 支持管理员增删改查指标解释内容
- Commit: `18a4b2d`

### Kimi K2.5 Temperature 修复（阶段性）✅
- 统一所有 Kimi K2.5 API 调用的 temperature 参数为 0.6
- 涉及 `openai_provider.py`、`health_data.py` 等
- Commit: `d793177`

---

## 2026-04-01 — v1.2.0 Feature Flag + Skill 技能系统 + 健康摘要 + 指标趋势

### Feature Flag 功能开关系统 ✅

**后端**
- 新建 `models/feature_flag.py`：`FeatureFlag` 表（key/enabled/description/rollout_pct/metadata_json）+ `Skill` 表（key/name/priority/trigger_hint/prompt_template）
- 新建 `services/feature_service.py`：60 秒内存缓存 + `is_feature_enabled(key)` + `build_skill_prompt(query)` 关键词匹配
- 新建 `schemas/feature_flag.py`：CRUD Pydantic schemas
- Migration `0009_feature_flags_skills.py`：建表 + 种子数据（6 开关 + 6 技能）

**Chat 集成**
- `openai_provider.py`：`_build_messages()` 接受 `skill_prompt` 参数，匹配技能的 prompt 注入系统提示
- `chat.py`：sync/stream 端点增加 `ai_chat` 开关守卫（禁用时 503）+ 自动技能注入

**管理后台**
- `admin.py` 新增 8 个 CRUD 端点：GET/POST/PATCH/DELETE × feature-flags + skills
- `main.py` 新增公共 `GET /api/feature-flags`（非管理员可访问）
- `admin.html` 新增"开关"和"技能"两个 Tab 页，支持一键开关/新增/编辑/删除

**iOS 端**
- 新建 `Models/FeatureFlagModels.swift`：Admin CRUD 模型 + 公共响应模型
- 新建 `Services/FeatureFlagService.swift`：登录后自动拉取，5 分钟本地缓存，`isEnabled("key")` 查询
- `AdminViewModel.swift`：新增 featureFlags/skills 属性 + CRUD 方法（toggle/create/update/delete）
- `AdminView.swift`：新增"开关"和"技能"两个 Tab 页，支持 Sheet 表单编辑

**预设 6 个功能开关**：ai_chat、health_summary、meal_vision、omics_analysis、agent_proactive、indicator_trend

**预设 6 个技能**：
| 优先级 | Key | 触发关键词 |
|---|---|---|
| 10 | glucose_analysis | 血糖,glucose,CGM |
| 20 | diet_advice | 饮食,营养,食物 |
| 30 | exam_report | 检验,报告,化验 |
| 40 | omics_interpret | 组学,基因,微生物 |
| 50 | fatty_liver | 脂肪肝,肝脏,ALT |
| 90 | general_health | (无关键词，兜底) |

### 健康 AI 摘要管线 ✅
- 后端 `health_summary_service.py`：分阶段生成 AI 研究报告（overview → glucose → diet → omics → recommendations → final）
- 后端台任务系统：`threading.Thread` 异步执行，`summary_tasks` 表追踪状态/Token 消耗
- `SummaryTaskOut` schema：task_id/status/stage/token_used
- iOS `HealthBriefViewModel` 对接摘要 API

### 指标趋势图 ✅
- 后端 `GET /api/health-reports/{id}/indicator-trends`：从 AI 摘要提取时序指标
- iOS `IndicatorTrendView`：SwiftUI Charts 绘制趋势线，支持拖拽/点击 tooltip 交互
- `IndicatorTrendViewModel`：按指标分组，支持刷新

### Token 消耗面板增强 ✅
- `GET /api/admin/token-stats` 新增 `summary_task_tokens` + `summary_task_count`
- `GET /api/admin/token-stats/details`：按用户 Token 审计 + 近期摘要任务列表
- Web admin Token 面板 + iOS AdminView Token Tab：6 指标卡片 + 3 明细表

### 新增文件

| 文件 | 用途 |
|---|---|
| `backend/app/models/feature_flag.py` | FeatureFlag + Skill ORM 模型 |
| `backend/app/schemas/feature_flag.py` | 功能开关/技能 CRUD schemas |
| `backend/app/services/feature_service.py` | 缓存 + 开关检查 + 技能匹配 |
| `backend/app/db/migrations/versions/0009_feature_flags_skills.py` | 建表迁移 |
| `Xjie/Models/FeatureFlagModels.swift` | iOS Feature Flag 模型 |
| `Xjie/Services/FeatureFlagService.swift` | iOS 功能开关服务 |

### 修改文件

| 文件 | 变更 |
|---|---|
| `backend/app/providers/openai_provider.py` | skill_prompt 注入系统提示 |
| `backend/app/providers/base.py` | generate_text/stream_text 增加 skill_prompt 参数 |
| `backend/app/routers/chat.py` | 开关守卫 + 技能注入 |
| `backend/app/routers/admin.py` | 8 个 flags/skills CRUD 端点 + Token 详情端点 |
| `backend/app/main.py` | 公共 /api/feature-flags 端点 |
| `backend/app/static/admin.html` | 开关/技能 Tab 页 + Token 面板 |
| `Xjie/ViewModels/AdminViewModel.swift` | flags/skills 属性 + CRUD 方法 |
| `Xjie/Views/Admin/AdminView.swift` | 开关/技能 Tab 页 + SkillEditSheet |
| `Xjie/App/XjieApp.swift` | 登录后自动拉取 Feature Flags |

---

## 2026-03-31 — v1.1.0 管理后台 + 品牌升级 + Kimi K2.5 + 推送通知

### 管理后台（iOS + Web）✅
- 后端 `routers/admin.py`：`require_admin` 依赖 + stats/users/conversations/omics 端点
- iOS `AdminView`：5 Tab 管理面板（概览/用户/对话/组学/Token）
- iOS `AdminViewModel`：并发加载所有管理数据
- Web `admin.html`：独立前端，JWT 登录 + 4 个数据表格 + 统计卡片

### Kimi K2.5 思考模式 ✅
- `openai_provider.py` 适配 Kimi K2.5 API（temperature=0.6 强制要求）
- 流式输出过滤 `<think>...</think>` 标签，仅返回正文
- Token 消耗追踪：`token_audit` 表记录每次调用的 prompt/completion tokens

### 品牌视觉升级 ✅
- Logo：XJ+ 标志，青绿→深蓝渐变配色方案
- AI 助手形象：小护士封面 + 小捷助手头像
- 多组学 Tab 图标替换为品牌 Logo

### APNs 推送通知 ✅
- 后端 `push_service.py`：Apple APNs HTTP/2 推送（JWT 认证）
- iOS `PushNotificationManager`：注册 Device Token + 权限请求
- 首页干预级别滑块：实时调节 AI 主动推送频率

### 膳食图像真实识别 ✅
- 替换 mock OCR 为 Kimi K2.5 多模态图片识别
- 体检报告提取 prompt 优化 + 批量上传脚本

### AI 聊天优化 ✅
- 历史消息时间戳显示
- 跨会话记忆（context_builder 汇总近期对话摘要）
- 提示词工程优化：数据感知 + 三要素 summary
- 移除所有后端/前端输出中的 emoji，防止 iOS 乱码
- Followups 交互重新设计

### 新增文件

| 文件 | 用途 |
|---|---|
| `backend/app/routers/admin.py` | 管理员 API 路由 |
| `backend/app/static/admin.html` | Web 管理后台 |
| `Xjie/ViewModels/AdminViewModel.swift` | 管理后台 ViewModel |
| `Xjie/Views/Admin/AdminView.swift` | 管理后台 View |
| `Xjie/Services/PushNotificationManager.swift` | APNs 推送管理 |
| `Xjie/App/AppDelegate.swift` | Device Token 注册 |

---

## 2026-03-30 — v1.0.0 多组学模块 + AI 体验升级 + 服务器部署

### 多组学模块 ✅
- 蛋白组/基因组 Tab 锁定（敬请期待）
- 代谢组上传功能：文件上传 + LLM 解读 + 风险等级评估
- 后端 `omics` model FK 引用修正（users → user_account）

### AI 体验全面升级 ✅
- AI 助手「小杰」：温暖友好风格系统提示词
- 可展开分析气泡：summary(1-2句) + 点击展开详细 analysis
- 用户画像自动提取：AI 从对话中识别性别/年龄/身高/体重
- Followups 追问建议交互

### 服务器部署 ✅
- Aliyun 服务器 8.130.213.44 部署
- Docker 容器：FastAPI + TimescaleDB
- iOS `API_BASE_URL` 切换至生产环境
- Aliyun pip 镜像加速 Docker 构建

---

## 2026-03-28 — v0.8.0 后端适配 + Kimi LLM 接入

### 后端 Schema 适配 ✅
- 适配服务器数据库：BigInteger IDs、`user_account` 表名、phone/password 字段
- 移除 UUID 主键，改用自增整数
- iOS 登录流程适配 phone 认证

### Kimi/Moonshot LLM 接入 ✅
- 通过 `OPENAI_BASE_URL` 配置 Moonshot API
- 支持 Kimi 大模型作为 AI 后端
- README 更新 iOS 应用说明

### 修改文件

| 文件 | 变更 |
|---|---|
| `backend/app/models/` | BigInteger + user_account 表适配 |
| `backend/app/routers/auth.py` | phone/password 登录 |
| `Xjie/Services/Environment.swift` | 生产 API_BASE_URL |
| `Xjie/ViewModels/LoginViewModel.swift` | phone 登录适配 |

---

## 2026-03-27 — v0.7.0 AI 体验全面升级

### 数据库修复 ✅
- `user_profiles` 表补齐 6 个缺失列: `display_name`, `sex`, `height_cm`, `weight_kg`, `liver_risk_level`, `cohort`
- `chat_messages` 表已包含 `analysis` 列（存储详细分析）

### AI 聊天修复 ✅
- **thread_id 缺失**: `ChatResult` 新增 `thread_id` 字段，iOS 可追踪会话
- **403 授权问题**: iOS 端自动开启 AI 授权 (login/signup 后 PATCH `/api/users/consent`)，403 时自动重试

### AI 系统提示词重写 ✅
- AI 助手命名「小杰」，温暖友好风格，像一个懂医学的朋友
- **数据感知策略**: 有数据直接引用分析；无数据绝不说"缺乏数据"，基于描述给建议
- 自然引导用户关注代谢健康话题（血糖、饮食、体检）
- 结构化 JSON 输出: `summary`(1-2 句) + `analysis`(详细 Markdown) + `followups` + `profile_extracted`

### 用户画像自动提取 ✅
- AI 从对话中提取用户信息（性别/年龄/身高/体重/昵称）
- 后端 `_apply_profile_extraction()` 自动写入 `user_profiles` 表
- 仅在字段为空时更新，不覆盖已有数据

### 可展开分析气泡 UI ✅
- `ChatView` 气泡显示 summary（简洁 1-2 句话）
- 助手消息下方「查看详细分析 ▸」按钮，点击展开完整 Markdown 分析
- 动画展开/收起，`@State expandedIDs` 追踪展开状态

### 修改文件

| 文件 | 变更 |
|---|---|
| `backend/app/providers/openai_provider.py` | 重写 SYSTEM_PROMPT、数据感知消息构建、结构化响应解析 |
| `backend/app/providers/base.py` | `ChatLLMResult` 增加 `profile_extracted` |
| `backend/app/schemas/chat.py` | `ChatResult` 增加 `summary` + `analysis` |
| `backend/app/routers/chat.py` | 新增 `_apply_profile_extraction()`，返回 summary+analysis |
| `Xjie/Models/ChatModels.swift` | `ChatResponse` 增加 `summary`/`analysis`，新增授权模型 |
| `Xjie/ViewModels/ChatViewModel.swift` | `ChatMessageItem` 加 `analysis` 字段，403 自动授权重试 |
| `Xjie/Views/Chat/ChatView.swift` | 可展开分析气泡 UI |
| `Xjie/ViewModels/LoginViewModel.swift` | 手机号验证修复 (email→phone) |

---

## 2026-03-26 — v0.6.0 P4+P5+P6 全部完成（39/39 ✅）

### P4 网络健壮性 (NET-01 ~ NET-04) ✅

**NET-01 网络状态监测**  
新建 `Utils/NetworkMonitor.swift`：`NWPathMonitor` 封装，@Published `isConnected` / `connectionType`。  
`XjieApp` 注入 `.environmentObject(networkMonitor)`，`MainTabView` 断网时显示全局 Banner（wifi.slash 图标 + "网络不可用"）。

**NET-02 请求重试策略**  
`APIService.request()` 增加 `retryCount` 参数，URLError（超时/断网）及 5xx 自动重试最多 2 次，指数退避 1s → 2s。

**NET-03 离线缓存**  
新建 `Utils/OfflineCacheManager.swift`：文件级 Codable 缓存（cachesDirectory/offline_cache/）。  
`HomeViewModel` 成功时缓存、失败时读取缓存 + `isOfflineData` 标记。

**NET-04 请求超时配置**  
`URLRequest.timeoutInterval` = `APIConstants.requestTimeout`(15s) / `APIConstants.uploadTimeout`(60s)。

### P5 代码质量 (CODE-01 ~ CODE-03) ✅

**CODE-01 抽取重复代码**  
- `Views/Shared/CSVTableView.swift` — ExamReportViews + MedicalRecordViews 共用 CSV 表格
- `Views/Shared/DocumentTagView.swift` — SourceTag / StatusTag / SourceDetailTag / StatusDetailTag 4 组件
- `Views/Shared/MetricItemView.swift` — HomeView + GlucoseView 共用指标卡片

**CODE-02 魔法数字常量化**  
新建 `Utils/Constants.swift`：`ChartConstants`（绘图参数）+ `APIConstants`（超时/分页）。  
GlucoseView Canvas、MealsViewModel、ChatViewModel 全面引用。

**CODE-03 移除/标记未使用代码**  
OmicsView 硬编码数据标记 `// TODO: CODE-03`；HealthDataView emoji 替换为 SF Symbol `brain.head.profile`。

### P6 生产就绪 (PROD-01 ~ PROD-06) ✅

**PROD-01 结构化日志**  
新建 `Utils/AppLogger.swift`：`os.Logger` 按 network/auth/data/ui 分类。APIService 关键路径已集成。

**PROD-02 崩溃上报**  
新建 `Utils/CrashReporter.swift`：`CrashReporting` 协议 + 默认实现（AppLogger 转发），可替换为 Crashlytics/Sentry。

**PROD-03 国际化 (i18n)**  
新建 `Resources/zh-Hans.lproj/Localizable.strings` + `Resources/en.lproj/Localizable.strings`（~150 键值对），覆盖标签栏、导航标题、通用文案。

**PROD-04 隐私清单**  
新建 `PrivacyInfo.xcprivacy`：声明健康信息 + 相册访问数据类型 + 文件时间戳 API 使用。

**PROD-05 CI/CD**  
新建 `.github/workflows/ci.yml`：GitHub Actions 自动构建 + 测试（macOS 15 + DerivedData 缓存）。

**PROD-06 App Store 准备（文档阶段）**  
隐私清单已就绪，i18n 基础已建立。应用图标/截图/描述待设计师介入。

### 新增文件 (12)

| 文件 | 用途 |
|---|---|
| `Utils/NetworkMonitor.swift` | NWPathMonitor 网络状态监测 |
| `Utils/OfflineCacheManager.swift` | 文件级离线缓存管理器 |
| `Utils/AppLogger.swift` | os.Logger 结构化日志 |
| `Utils/CrashReporter.swift` | 崩溃上报协议 + 默认实现 |
| `Utils/Constants.swift` | ChartConstants + APIConstants |
| `Views/Shared/CSVTableView.swift` | 可复用 CSV 表格组件 |
| `Views/Shared/DocumentTagView.swift` | 来源/状态标签组件 |
| `Views/Shared/MetricItemView.swift` | 指标卡片组件 |
| `PrivacyInfo.xcprivacy` | Apple 隐私清单 |
| `Resources/zh-Hans.lproj/Localizable.strings` | 中文本地化 |
| `Resources/en.lproj/Localizable.strings` | 英文本地化 |
| `.github/workflows/ci.yml` | GitHub Actions CI |

### 修改文件 (12)

`APIService.swift`、`XjieApp.swift`、`MainTabView.swift`、`HomeViewModel.swift`、`ExamReportViews.swift`、`MedicalRecordViews.swift`、`HomeView.swift`、`GlucoseView.swift`、`OmicsView.swift`、`HealthDataView.swift`、`MealsViewModel.swift`、`ChatViewModel.swift`

### 构建验证

- **BUILD SUCCEEDED** — 52 Swift 源文件
- **TEST SUCCEEDED** — 46 tests, 0 failures

---

## 2026-03-25 — v0.5.0 P3 性能优化完成

### PERF-01 DateFormatter 缓存 ✅

`Utils.swift` 顶层 `private let` 缓存 4 个 formatter（ISO8601 带/不带毫秒、yyyy-MM-dd HH:mm、HH:mm）。新增 `Utils.parseISO()` 统一入口。`HealthDataViewModel` / `MealsViewModel` / `GlucoseViewModel` 内联 formatter 同步替换。

### PERF-02 血糖图表数据预处理 ✅

`GlucoseViewModel` 新增 `chartData: [(Date, Double)]` 预计算属性，在 fetchPoints 成功后一次性解析。`GlucoseChartCanvas` 改为接收预计算数组，Canvas draw 闭包内零日期解析。

### PERF-03 列表分页加载 ✅

- `MealsViewModel`: pageSize=20 + offset 分页 + `loadMore()` + UI "加载更多"按钮
- `ChatViewModel`: 会话列表 pageSize=20 + `loadMoreConversations()` + 历史面板加载更多

### PERF-04 请求取消 (Task Cancellation) ✅

- `GlucoseViewModel`: `pointsTask` 存储引用，切换窗口时 cancel + 重建 Task
- 全部 ViewModel: await 后 `guard !Task.isCancelled else { return }` 守卫检查，页面消失后不更新 UI

涉及 ViewModel: Home、Glucose、Chat、Meals、HealthBrief、HealthData、ExamReport、MedicalRecord、Settings

### PERF-05 图片缓存（3 天 TTL）✅

- 新建 `Utils/ImageCacheManager.swift`: NSCache 内存缓存（100 张 / 50 MB）+ 磁盘缓存
- 3 天自动过期清理 `cleanExpired()` + `clearAll()` 公开方法
- 新建 `Views/Components/CachedAsyncImage.swift`: SwiftUI 组件，缓存优先 → 网络兜底

### 新增文件 (2)

| 文件 | 用途 |
|---|---|
| `Utils/ImageCacheManager.swift` | 图片缓存管理器（3 天 TTL） |
| `Views/Components/CachedAsyncImage.swift` | 带缓存的异步图片组件 |

### 修改文件 (11)

`Utils.swift`、`GlucoseViewModel.swift`、`GlucoseView.swift`、`HomeViewModel.swift`、`ChatViewModel.swift`、`ChatView.swift`、`MealsViewModel.swift`、`MealsView.swift`、`HealthBriefViewModel.swift`、`HealthDataViewModel.swift`、`ExamReportViewModels.swift`、`MedicalRecordViewModels.swift`、`SettingsViewModel.swift`

### 构建验证

- **BUILD SUCCEEDED** — 44 Swift 源文件
- **TEST SUCCEEDED** — 46 tests, 0 failures

---

## 2026-03-25 — v0.4.0 P2 UI/UX 完善完成

### UI-01 Dark Mode 全面适配 ✅

`Theme.swift`: `appBackground` → `systemBackground`、`appCardBg` → `secondarySystemBackground`、`appText` → `label`、`appMuted` → `secondaryLabel`。`CardStyle` 暗色模式自动移除阴影。

### UI-02 空状态页面 + UI-03 错误状态组件 ✅

新建 `Views/Components/`:
- `EmptyStateView.swift` — SF Symbol 图标 + 标题 + 副标题 + 可选操作按钮
- `ErrorStateView.swift` — 自动识别网络/认证/服务器错误，展示不同图标和文案，带重试按钮

已替换：HealthView、MealsView、ExamReportListView、MedicalRecordListView 的空状态

### UI-04 Accessibility 无障碍 ✅

30+ 硬编码 emoji 全部替换为 SF Symbols（`Image(systemName:)` / `Label(_:systemImage:)`）。所有可交互元素自动获得 VoiceOver 支持。

涉及文件：HomeView、ChatView、HealthDataView、HealthView、MealsView、SettingsView、OmicsView、ExamReportViews、MedicalRecordViews

### UI-05 弃用 API 替换 ✅

- `LoginView`: `.autocapitalization(.none)` → `.textInputAutocapitalization(.never)`
- `HealthDataView`: `UIDocumentPickerViewController(documentTypes:in:)` → `UTType` + `forOpeningContentTypes:`

### UI-06 启动画面 ✅

- Info.plist 添加 `UILaunchScreen` 配置
- 新建 `SplashView.swift`：品牌渐变背景 + Logo + 渐入缩放动画 (1.5s)
- `XjieApp.swift` 集成 ZStack 叠加 splash

### UI-07 iPad 自适应布局 ✅

`MainTabView` 使用 `@Environment(\.horizontalSizeClass)` 判断:
- iPhone (compact) → 保持 TabView
- iPad (regular) → NavigationSplitView + 侧边栏导航

### 新增文件 (3)

| 文件 | 用途 |
|---|---|
| `Views/Components/EmptyStateView.swift` | 通用空状态组件 |
| `Views/Components/ErrorStateView.swift` | 通用错误状态组件 |
| `Views/Components/SplashView.swift` | 启动品牌画面 |

### 修改文件 (13)

`Theme.swift`、`Info.plist`、`XjieApp.swift`、`MainTabView.swift`、`HomeView.swift`、`LoginView.swift`、`ChatView.swift`、`HealthDataView.swift`、`HealthView.swift`、`MealsView.swift`、`SettingsView.swift`、`OmicsView.swift`、`ExamReportViews.swift`、`MedicalRecordViews.swift`

### 构建验证

- **BUILD SUCCEEDED** — 42 Swift 源文件
- **TEST SUCCEEDED** — 46 tests, 0 failures

---

## 2026-03-25 — v0.2.0 P0 + P1 安全/架构重构完成

### 一、P0 安全与稳定性（全部完成 ✅）

| 编号 | 任务 | 状态 |
|---|---|---|
| SEC-01 | Token 迁移至 Keychain | ✅ `AuthManager` 全面改用 `KeychainHelper` |
| SEC-02 | 移除所有强制解包 (`!`) | ✅ `APIService`、`MealsViewModel` 中 URL/Response 均用 guard let |
| SEC-03 | BaseURL 环境配置 | ✅ `Environment.swift` — Info.plist 或 DEBUG fallback |
| SEC-04 | URL 参数安全构建 | ✅ `URLBuilder` 枚举 + `URLComponents`/`URLQueryItem` |
| ERR-01 | 清除空 catch 块 | ✅ 所有 ViewModel 增加 `@Published var errorMessage`，View 层 `.alert` 展示 |
| ERR-02 | Token 刷新并发竞态修复 | ✅ `refreshTask: Task<Void, Error>?` 排队机制 |
| BUG-01 | ChatMessage.id 存储属性 | ✅ `let id: String` + 自定义 `init(from decoder:)` |

### 二、P1 架构与可测试性（核心完成 ✅）

| 编号 | 任务 | 状态 |
|---|---|---|
| ARCH-01 | APIServiceProtocol 协议层 | ✅ `Services/APIServiceProtocol.swift` |
| ARCH-02 | ViewModel 依赖注入 | ✅ 所有 ViewModel 接收 `api: APIServiceProtocol` 参数 |
| ARCH-03 | ViewModel 从 View 拆分 | ✅ 10 个 ViewModel 独立至 `ViewModels/` 目录 |
| ARCH-04 | Models.swift 按 feature 拆分 | ✅ 6 个模型文件：Auth/Glucose/Meal/Health/Chat/Settings |
| ARCH-05 | Repository 层抽取 | ✅ `Repositories/HealthDataRepository.swift` |
| TEST-01 | 核心单元测试 | ✅ MockAPIService + Utils(22) + ChatMessage BUG-01 回归(4) |
| TEST-02 | ViewModel 单元测试 | ✅ Home(3) + Login(8) + Chat(6) + Glucose(3) = 20 tests |

---

## 2026-03-25 — v0.3.0 单元测试全覆盖

### 测试目标建立

- 新建 `XjieTests/` target（unit-test bundle，hosted in Xjie.app）
- xcscheme 更新 TestAction 引用

### 测试文件（7 个）

| 文件 | 测试数 | 覆盖内容 |
|---|---|---|
| MockAPIService.swift | — | 测试替身，符合 APIServiceProtocol |
| UtilsTests.swift | 22 | formatDate/formatTime/toFixed/glucoseColor/URLBuilder/MIMETypeHelper |
| ChatMessageTests.swift | 4 | BUG-01 回归：id decode/生成/稳定性 |
| HomeViewModelTests.swift | 3 | fetchData 成功/失败/loading |
| LoginViewModelTests.swift | 8 | 输入验证(3) + 登录成功(2) + 网络错误 + subjects 加载(2) |
| ChatViewModelTests.swift | 6 | 发消息/空消息/错误/新对话/历史加载 |
| GlucoseViewModelTests.swift | 3 | fetchRange/error/窗口切换 |

**合计：46 tests, 0 failures ✅**

### 附带修复

- 4 个 Model 文件 `Decodable` → `Codable`（MockAPIService 编码需要）
- ChatMessage 添加 memberwise `init(id:role:content:)`

### 三、新增文件清单（v0.2.0）

**Utils (2)**：`KeychainHelper.swift`、`MIMETypeHelper.swift`  
**Services (2)**：`Environment.swift`、`APIServiceProtocol.swift`  
**Models (6)**：`AuthModels.swift`、`GlucoseModels.swift`、`MealModels.swift`、`HealthModels.swift`、`ChatModels.swift`、`SettingsModels.swift`  
**Repositories (1)**：`HealthDataRepository.swift`  
**ViewModels (10)**：`HomeViewModel.swift`、`LoginViewModel.swift`、`GlucoseViewModel.swift`、`ChatViewModel.swift`、`HealthDataViewModel.swift`、`MedicalRecordViewModels.swift`、`ExamReportViewModels.swift`、`SettingsViewModel.swift`、`HealthBriefViewModel.swift`、`MealsViewModel.swift`

### 四、重写文件

- **AuthManager.swift**：全面 Keychain 存储
- **APIService.swift**：协议一致性、安全 URL、并发刷新
- **Models.swift**：内容拆分至 6 文件（保留空壳兼容）
- **Utils.swift**：新增 URLBuilder
- **10 个 View 文件**：移除内嵌 ViewModel、统一错误提示

### 五、LLM API 占位

以下位置标记了 `// TODO: [LLM API]`，等后端接口就绪后接入：
- `ChatViewModel.swift` — 对话请求/流式回复
- `HealthDataViewModel.swift` — AI 健康数据总结
- `HealthBriefViewModel.swift` — AI 摘要生成

### 六、编译验证

- **构建结果**：`BUILD SUCCEEDED` ✅（iPhone 17 Simulator, iOS 26.3.1）
- **39 个 Swift 源文件**
- **仅 1 个 deprecation warning**：`UIDocumentPickerViewController(documentTypes:)` — 计划在 UI-05 中更新

---

## 2026-03-24 — v0.1.0 初始转换完成

### 一、项目创建

从微信小程序（WXML + WXSS + JS）完整转换为 iOS 原生 SwiftUI 应用，保留全部架构和业务逻辑。

**转换映射**：

| 微信小程序 | iOS (SwiftUI) |
|---|---|
| `app.js globalData` | `AuthManager` @MainActor 单例 |
| `utils/api.js` (wx.request) | `APIService` actor (URLSession async/await) |
| `Page({data, onLoad, methods})` | SwiftUI View + @MainActor ViewModel (ObservableObject) |
| `tabBar` 4 标签 | `TabView` (首页/健康数据/多组学/AI助手) |
| Canvas 2D | SwiftUI `Canvas` + `GraphicsContext` |
| `wx.setStorageSync/getStorageSync` | `UserDefaults` |
| `wx.chooseMedia` | `PhotosPicker` (PhotosUI) |
| `wx.chooseMessageFile` | `UIDocumentPickerViewController` (UIViewControllerRepresentable) |
| `wx.showModal` (editable) | `.alert` + TextField |
| `wx.showActionSheet` | `.confirmationDialog` |

### 二、项目结构

```
Xjie/
├── Xjie.xcodeproj/          # Xcode 工程 + scheme
├── Xjie/
│   ├── App/
│   │   └── XjieApp.swift    # @main 入口，auth 路由
│   ├── Models/
│   │   └── Models.swift           # 30+ Codable 数据模型
│   ├── Services/
│   │   ├── AuthManager.swift      # 认证状态管理
│   │   └── APIService.swift       # HTTP 客户端 (JWT + 401 自动刷新)
│   ├── Utils/
│   │   ├── Theme.swift            # 颜色系统 + CardStyle
│   │   └── Utils.swift            # 日期格式化、血糖颜色
│   ├── Views/
│   │   ├── Home/                  # 首页仪表盘 + TabView
│   │   ├── Login/                 # 登录（Subject/Email 双模式）
│   │   ├── Glucose/               # 血糖曲线图（Canvas 绘制）
│   │   ├── Chat/                  # AI 对话（历史会话 + 追问建议）
│   │   ├── HealthData/            # 健康数据中心（AI 总结 + 上传）
│   │   ├── MedicalRecords/        # 病历列表 + 详情
│   │   ├── ExamReports/           # 体检报告列表 + 详情
│   │   ├── Omics/                 # 多组学（蛋白/代谢/基因）
│   │   ├── Health/                # 每日健康简报
│   │   ├── Meals/                 # 膳食记录（拍照 + 手动）
│   │   └── Settings/              # 设置（干预等级/同意书/登出）
│   ├── Assets.xcassets/           # 图标 + 主题色
│   ├── Preview Content/
│   └── Info.plist                 # ATS localhost 例外
```

### 三、编译验证

- **目标**：iOS 17.0+，iPhone + iPad
- **编译器**：Xcode 15.4+，Swift 5.0
- **构建结果**：`BUILD SUCCEEDED` ✅（iPhone 17 Simulator）
- **18 个 Swift 源文件**，约 2,837 行代码

### 四、技术栈

- **前端**：SwiftUI (iOS 17+)，MVVM 架构
- **后端**：FastAPI REST API (`http://localhost:8000`)
- **认证**：JWT Bearer Token，access 30min + refresh 7 天
- **网络**：URLSession async/await，自动 401 刷新重试

### 五、后端 API 接口

| 路由组 | 说明 |
|---|---|
| `/api/auth/` | 登录、注册、refresh、logout |
| `/api/dashboard/` | 仪表盘汇总 |
| `/api/glucose/` | 血糖数据（时间范围查询） |
| `/api/meals/` | 膳食记录（拍照上传 3 步流程） |
| `/api/chat/` | AI 对话、历史会话 |
| `/api/agent/` | 主动推送、每日简报、餐后补救 |
| `/api/health-data/` | AI 总结、文档上传/列表/详情/删除 |
| `/api/health-reports/` | AI 健康摘要 |
| `/api/settings/` | 用户设置、干预等级、同意书 |

### 六、已知问题（v0.1.0 代码审查）

经过完整代码审查，发现以下待修复项（详见 todolist.md）：

- 🔴 **安全**：Token 存 UserDefaults（应迁移 Keychain）
- 🔴 **错误处理**：5+ 处空 `catch {}` 吞掉错误，UI 无任何失败提示
- 🔴 **性能**：`ChatMessage.id` 计算属性导致无限重渲染
- 🔴 **生产就绪**：baseURL 硬编码 localhost，无环境配置
- 🟠 **架构**：单例硬耦合，无协议/DI，不可测试
- 🟠 **UI**：无 Dark Mode，无 Accessibility 标签
- 🟠 **网络**：无离线支持，无请求取消，URL 参数未编码

## 2026-07-04 iOS XAGE 线上账号历史同步验证

- 恢复 XAGE 正式启动登录门禁：未登录显示 `LoginView`，登录成功后进入新版 `MainTabView`；登录页默认进入手机号登录和登录模式，避免普通用户先看到 subject/debug 或注册态。
- 新增 `XAgeServerSyncViewModel`，登录态并行拉取健康摘要、病历/体检文档、指标、关注指标、趋势、问答历史、健康计划、用户画像等服务端数据，并合并进 XAGE 数据首页和底部四分类详情页。
- 数据页头部同步说明改为服务端快照日期，关注指标趋势会生成 ALT/AST/TG 等真实指标卡；`报告 / 日常 / 就医 / 画像` 详情页统计、进度和互动文案改为使用服务端数据，不再停留在固定样例数。
- 修正 `TodayBriefing` 解码，兼容 `/api/agent/today` 顶层 `today_goals`，使日常详情页能显示真实今日目标数量。
- 线上 API 和 Simulator 登录验证通过：该授权账号历史信息可同步到当前版本，UI 中可见病历 14 份、体检 271 份、指标 257 项、关注 3 项、趋势 46 点、今日目标 1 条、问答 2 次、计划 2 个、画像完整度 80%，最新报告日期为 `6月30日`。
- 验证命令：`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,id=B13D9E81-BE9F-4779-A2B1-415DB38DD7DE' build` 通过；`xcodebuild ... test` 49 个测试 0 失败；安装到 iPhone 17 Pro Simulator 后完成真实登录和 XAGE 数据/详情页视觉检查。
- 本记录不包含测试账号、密码或 token。

## 2026-07-04 iOS XAGE 继续复测与证据错配修复

- 继续在 iPhone 17 Pro Simulator 逐项复测 XAGE 登录态数据页、报告详情、问答附件、LLM 回复、X年龄说明和三栏切换，确认用户历史指标仍可同步到当前版本。
- 修复报告详情页上传入口：拍照、选 PDF、相册和 `开始入库` 均接入真实系统 picker；详情页底部 CTA 改用 safe-area inset，避免被底部安全区裁切。
- 修复顶层三栏半页残影：将 `数据 / 问答 / X年龄` 的 `PageTabViewStyle` 换成 ZStack opacity/hit-testing 切换，保留页面状态但禁用横向 page 容器的半屏停留。
- 修复 API 401 边界：匿名登录/注册/重置接口的 401 不触发 token refresh，受保护接口 401 刷新一次；上传文件遇受保护 401 也会刷新 token 后重试一次。
- 修复问答证据错配：新增 `ChatMessageItem.relevantCitations` 主题过滤；证据按钮和证据 sheet 只展示与当前回答/分析主题匹配的 citations，避免肝功能/血糖回复展示限时进食/血压证据。
- 验证：`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,id=B13D9E81-BE9F-4779-A2B1-415DB38DD7DE' test` 54 个测试 0 失败；`git diff --check` 通过；最近 10 分钟 Xjie 进程日志无 crash/Fatal/Exception/Terminating。
- Simulator 交互验证：报告详情 PDF/相册/主 CTA 能打开系统选择器，问答加号菜单文件/相册/新对话可用，LLM 回复只显示 `查看分析` 而不再显示错主题 `证据展示`，X年龄说明关闭后无半页残影。
- 本记录不包含测试账号、密码或 token。

## 2026-07-04 iOS XAGE 资料分类迁移到左上菜单

- 按用户截图调整数据页资料入口：底部固定资料面板移除 `报告 / 日常 / 就医 / 画像` 四个分类胶囊，只保留当前选中分类的单张液态玻璃入口卡，减少底部区域拥挤。
- 左上三横线菜单从原来的 `数据 / 问答 / X年龄` 改为 `报告 / 日常 / 就医 / 画像`，菜单标题改为 `资料`，每行保留图标、标题、副标题、选中勾和右侧箭头；左上按钮无障碍标签改为 `资料菜单`，避免系统符号默认读成不准确名称。
- 点击菜单任一分类会关闭 sheet、切回数据页并直接进入对应 `XAgePanelDestinationView`；从详情页返回后，底部入口卡同步显示当前分类。
- 将 `AppleHealthSyncViewModel` 和 `XAgeServerSyncViewModel` 上移到 `XAgeMainView` 共享，保证菜单导航和底部卡导航共用同一服务端快照与 Apple Health 状态。
- 验证：`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,id=B13D9E81-BE9F-4779-A2B1-415DB38DD7DE' test` 54 个测试 0 失败；`git diff --check` 通过；iPhone 17 Pro Simulator 登录态逐项验证菜单四项、详情页进入/返回、底部入口状态同步和旧菜单项消失；最近 15 分钟 Xjie 进程日志无 crash/Fatal/Exception/Terminating。
- 本记录不包含测试账号、密码或 token。

## 2026-07-04 iOS XAGE 底部资料残留彻底移除

- 按用户截图继续清理数据页底部残留：删除 `XAgeBottomDataPanel`，不再显示 `报告入库 / 上传` 单张底部入口卡。
- 数据页滚动列表底部 padding 恢复为普通 32pt，不再为旧资料面板保留 172pt 空白；首屏底部直接显示指标卡内容。
- 移除底部入口相关接口标识 `xage.data.upload`、`xage.data.panel.*`；`报告 / 日常 / 就医 / 画像` 仅保留在左上 `资料` 菜单中进入。
- 验证：`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,id=B13D9E81-BE9F-4779-A2B1-415DB38DD7DE' test` 54 个测试 0 失败；iPhone 17 Pro Simulator 登录态确认首屏无底部残留卡，左上菜单四项仍可见，点击 `日常` 能进入详情页并返回数据页后仍无底部残留；`git diff --check` 和最近日志检查通过。
- 本记录不包含测试账号、密码或 token。

## 2026-07-05 iOS XAGE 四项算法评分与说明入口

- 按 `XAge_Stress_Recovery_Inflammation_Algorithm_Spec_CN` 为 XAGE 数据页接入压力、恢复、炎症和 XAge 四项算法：所有分数输出 score、confidence、主要驱动和下一步建议；缺失数据不补零，按可用特征重加权。
- 压力高分代表身体后台负荷偏高；恢复高分代表当天承压能力较好；炎症区分实验室锚点和“身体小火苗”代理信号，缺少 hsCRP/CBC/NLR/炎症因子时置信度封顶并明确不是诊断；XAge 按实际年龄、恢复/炎症/活动/代谢/身体组成等域估计趋势年龄和区间。
- 三个数据页圆环下新增小 `i` 说明按钮，分别展示轻量可读的算法说明、置信度、主要驱动和下一步动作；XAge 中心数字旁新增 `i` 说明按钮，说明压力/恢复/炎症/日常节律如何换算成趋势年龄。
- 服务器同步快照补充用户年龄、身高、体重和实验室趋势解析；报告 abnormal flags / CSV 会转为算法候选特征。WBC 作为炎症专业锚点时新增可信性过滤：尿沉渣 `个/HP`、尿/镜检/沉渣/上皮/粪便语义，或无血常规单位/语义的“白细胞”不会升级为 CBC/WBC 锚点。
- 修复 XAge 说明中等 sheet 文本被省略的问题：XAge 说明改为大 detent，并让说明、摘要和建议自然多行展开。
- 新增 `XAgeCompositeScoresTests`，覆盖无实验室锚点代理炎症、hsCRP 专业锚点、尿检白细胞过滤、无单位白细胞过滤、带血常规单位 WBC 锚点和 XAge 可读说明。
- 验证：`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,id=B13D9E81-BE9F-4779-A2B1-415DB38DD7DE' test` 60 个测试 0 失败；`git diff --check` 通过。
- Simulator 逐项验证：登录态数据页最终显示压力 50、恢复 55、炎症 35；压力/恢复/炎症 `i` 说明均可打开关闭，炎症说明最终显示 `代理信号 · 置信度 12%` 且包含“不是炎症诊断”；XAge 页中心 `i` 说明可打开，正文完整无省略号。截图保存在 `X_new/implementation_audit/ios_xage_algorithm_scores_20260705/`。
- 本记录不包含测试账号、密码或 token。

## 2026-07-06 iOS XAGE 四项原理文案确定化

- 按用户要求将压力、恢复、炎症、X年龄四项解释性文案从“怎么算/说明/可能/建议”式表达改为确定的“原理”表达：标题统一为 `压力原理`、`恢复原理`、`炎症原理`、`X年龄原理`。
- 四项正文直接说明算法输入、0-100 子分、权重合成和每类输入影响结果的原因；压力/恢复/炎症驱动项和 next action 同步改为明确的计算输入说明。
- 炎症无实验室锚点时继续显示 `身体小火苗` 代理信号，但文案改为“代理子分并加权”和“该代理信号只表示算法风险负荷，不是炎症诊断”，避免模棱两可。
- X年龄说明改为按恢复、自主神经、睡眠、活动、炎症/小火苗、代谢、身体组成域分折算年龄差，并明确有效天数决定置信度和区间宽度。
- 修复三项圆环原理 sheet 的长文案压缩省略问题：压力/恢复/炎症原理弹层改为大 detent、可滚动内容，并让正文和行动文案纵向完整展开。
- 补充 Debug-only 启动参数 fallback：`XJIE_DEBUG_ACCESS_TOKEN`、`XJIE_DEBUG_SUBJECT_ID` 和 `XJIE_DEBUG_API_BASE_URL` 可通过启动参数注入，便于本地 UI 验证，Release 不受影响。
- 验证：`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,id=B13D9E81-BE9F-4779-A2B1-415DB38DD7DE' test` 60 个测试 0 失败；`git diff --check` 通过；旧标题关键词 `怎么算 / X年龄说明 / 计算说明 / 轻度解释 / 主要看这些` 搜索无残留。
- Simulator 本地验证：用 Debug-only token 和本地无服务端 API base 进入 XAGE 数据页，逐个打开/关闭压力、恢复、炎症、X年龄原理弹层，标题、无障碍标签和正文均正确，截图保存在 `X_new/implementation_audit/ios_xage_principle_copy_20260706/`。
- 本记录不包含测试账号、密码或 token。

## 2026-07-06 iOS XAGE 登录品牌与启动动画对齐

- 按用户截图将 iOS 登录页顶部旧渐变圆 `XJ+` 替换为现有 `Logo` 资产，登录页黑色标题从 `Xjie` 改为 `小捷`，并设置用户可见 app display name 为 `小捷`。
- 启动页按 Android 端参考重做：蓝绿渐变背景、112pt 圆角 logo、双层光环脉冲、logo 弹入、`小捷 / 你的智能健康管家` 文案上滑淡入，并在结束前先淡出内容再进入登录/主界面。
- 调整 push 通知权限请求时机：已登录用户也要等启动动画结束后才请求通知权限，避免系统权限弹窗打断启动动画或遮挡登录页视觉验证。
- 同步清理品牌残留：通知权限提示改为 `设置 → 小捷 → 通知`，Live Activity 标题改为 `小捷健康树`。
- 验证：`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,id=B13D9E81-BE9F-4779-A2B1-415DB38DD7DE' test` 60 个测试 0 失败；`git diff --check` 通过；登录/启动页旧 `XJ+`、旧 `Text("Xjie")`、旧启动页 `Xjie 智能` 文案搜索无残留。
- Simulator 视觉验证：重置 keychain、重新安装并启动 iPhone 17 Pro Simulator，确认启动页为 Android 同款蓝绿渐变、logo 光环和 `小捷` 文案，登录页显示真实 logo 和 `小捷`，无权限弹窗打断；截图保存在 `X_new/implementation_audit/ios_login_logo_splash_20260706/final_clean/`。
- 本记录不包含测试账号、密码或 token；本次仅更新 iOS `XAGE`，Android 只作为参考未修改。

## 2026-07-06 iOS TestFlight 1.0(8) 发布准备与签名阻断

- 按 iOS 单端发布请求将 iOS 工程 build number 从 `7` 提升到 `8`，版本号保持 `1.0`，准备上传 `1.0(8)` 到 TestFlight。
- 发布前验证通过：`git diff --check` 通过，`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -configuration Debug -destination 'platform=iOS Simulator,id=B13D9E81-BE9F-4779-A2B1-415DB38DD7DE' test` 60 个测试 0 失败；build settings 确认 `MARKETING_VERSION=1.0`、`CURRENT_PROJECT_VERSION=8`、bundle id `com.xjie.app`、display name `小捷`。
- Release archive 被 Apple Developer 账号状态阻断，未生成 `Xjie-TestFlight-1.0-8.xcarchive`，也未上传到 App Store Connect。Xcode 返回：账号需要同意最新 Program License Agreement，且当前自动 profile `iOS Team Provisioning Profile: com.xjie.app` 不包含 HealthKit capability / `com.apple.developer.healthkit` entitlement。
- 本版本已经接入 Apple 健康数据访问，不能移除 HealthKit entitlement 来绕过签名；TestFlight 发布前需要账号持有人在 Apple Developer 后台同意最新协议，并重新生成/下载包含 HealthKit 的 iOS Distribution provisioning profile。
- 本记录不包含 Apple 账号、密码、API key 或任何签名密钥。

## 2026-07-06 iOS TestFlight 1.0(8) 上传完成

- 在账号持有人同意 Apple Developer Program License Agreement 并为 `com.xjie.app` 保存 HealthKit capability 后，重新执行 iOS `1.0(8)` Release archive；自动签名获取到包含 `com.apple.developer.healthkit` 的 profile，archive 成功生成。
- 修复首次上传时 App Store Connect 返回的 HealthKit 隐私说明缺失：在 `Info.plist` 和 build settings 中补充 `NSHealthUpdateUsageDescription`，说明小捷在用户授权后会把记录的健康指标同步回 Apple 健康。
- 归档检查确认 app bundle 为 `com.xjie.app`，`CFBundleShortVersionString=1.0`，`CFBundleVersion=8`，`CFBundleDisplayName=小捷`，`NSHealthShareUsageDescription` 和 `NSHealthUpdateUsageDescription` 均已写入，entitlements 包含 `com.apple.developer.healthkit=true`。
- `xcodebuild -exportArchive` 使用 `ExportOptions.plist` 上传到 App Store Connect，返回 `Upload succeeded` 和 `EXPORT SUCCEEDED`；Apple 已开始 processing，TestFlight 可见性仍需等待 App Store Connect 处理完成。
- 验证命令：`xcodebuild ... -configuration Debug ... build` 通过；Release archive 通过；archive 元数据/entitlements 检查通过；export/upload 通过。
- 归档路径：`Xjie/build/Xjie-TestFlight-1.0-8.xcarchive`；上传导出路径：`Xjie/build/TestFlight-1.0-8`。
- 本记录不包含 Apple 账号、密码、API key、签名证书、provisioning profile 内容或任何 token。

## 2026-07-06 iOS Apple 健康同步线上 404 修复

- 排查用户反馈的 Apple 健康同步显示 `Not Found`：iOS Release base URL 指向生产 API，线上 `/api/health-data/indicators/device-sync` 返回 404，而 `/api/health-data/indicators` 返回 401，确认不是 HealthKit 权限或 iOS 路径拼写问题，而是生产后端缺少设备同步路由。
- 服务器 `xjie-api` 容器内旧 `indicators_extra.py` 只注册了搜索、手动录入、删除和 seed-common 5 个旧路由，缺少本地最新的 `POST /api/health-data/indicators/device-sync`。
- 已将 iOS 仓库当前 `backend/app/routers/indicators_extra.py` 同步到阿里云服务器源码目录和运行中的 `xjie-api` 容器，重启容器后再用同步后的源码重建 `xjie-backend` 镜像，避免未来重建容器后路由再次丢失。
- 线上验证：`OPTIONS http://8.130.213.44:8000/api/health-data/indicators/device-sync` 从 404 变为 405 且 `Allow: POST`；未带 token 的 `POST` 返回 401 `Missing Bearer token`，说明请求已进入受保护同步接口；容器路由表包含 `/api/health-data/indicators/device-sync`，`/healthz` 返回 200。
- 本地验证：`python3 -m py_compile backend/app/routers/indicators_extra.py backend/app/models/user_indicator_value.py` 通过；`git diff --check` 通过。`pytest backend/tests/unit/test_device_indicator_sync.py` 未运行，因为当前本机 Python 环境未安装 `pytest`。
- 本记录不包含 SSH、数据库、API key、JWT、Apple 账号或用户 token。

## 2026-07-06 iOS XAGE 指标缺失态、血压和 Apple 健康覆盖旧数据修复

- 修复 XAGE 数据页指标可信度问题：默认 HRV、睡眠、血糖波动、体温不再显示固定演示数值；缺失指标显示 `无`、`待同步` 或 `待上传`，添加指标候选表也不再用样例数字占位。
- 血压从旧的组合 `血压 118/76 mmHg` 改为 `收缩压`、`舒张压` 两个独立指标；iOS HealthKit 同步新增读取 `.bloodPressureSystolic` 和 `.bloodPressureDiastolic`，避免用户只有单项数据时被拼成错误血压。
- 指标卡整卡可点击进入新的液态玻璃详情页，展示数值、数据来源、更新时间和当前状态；缺失态、正常态、过期态分别给出明确说明。
- 服务端趋势接口新增 `source` 和 `measured_at` 字段；iOS 读取趋势时按来源和测量时间判断时效：日常/Apple 健康类 2 天、血压/体重/体脂 14 天、报告类 180 天，过期数据显示 `需更新` 并只作历史参考。
- 后端 `/api/health-data/indicators/device-sync` 调整为 Apple 健康同日同指标可覆盖旧 `manual/device` 行，并将来源更新为 `apple_health`，避免老版本小捷手动录入值压住新同步值；趋势合并时同日点按 `document < manual < device < cgm < apple_health` 和测量时间去重。
- 生产服务器已同步 `health_data.py`、`indicators_extra.py`、`health_document.py` 到源码和运行容器，容器内单测通过后重启 `xjie-api` 并重建 `xjie-backend` 镜像。
- 验证：本地 `py_compile` 通过；本地 `backend/.venv/bin/pytest backend/tests/unit/test_device_indicator_sync.py -q` 为 2 passed；iOS Debug build 和 `xcodebuild test` 在 iPhone 17 Pro Simulator 通过，60 tests 0 failures；生产容器 `py_compile` 和同一单测 2 passed；生产 `/healthz` 返回 `{"ok":true}`；`OPTIONS /device-sync` 返回 405 Allow POST，未登录 POST 返回 401；容器路由与 schema 检查确认 `TrendPoint` 带 `source/measured_at`。
- 限制：使用此前给出的测试账号登录当前生产后端时返回 `手机号或密码错误`，因此本轮未能用该账号做真实数据页复核；后端覆盖逻辑已通过本地和生产容器单测验证。
- 本记录不包含测试账号、密码、SSH、数据库、API key、JWT、Apple 账号或用户 token。

## 2026-07-07 iOS TestFlight 1.0(11) 上传完成

- 按用户要求再次发布 iOS TestFlight，工程 `CURRENT_PROJECT_VERSION` 从 `10` 递增到 `11`，`MARKETING_VERSION` 继续保持 `1.0`。
- 本包包含数据卡片管理交互修复：从编辑/全量列表打开指标详情不会再被嵌套 sheet 吞掉，置顶/取消置顶后行样式稳定，所有健康数据跨分区去重，Apple 健康式左侧减号/pin/check 操作位置生效。
- 服务器已入库指标改为独立来源和 `已入库` 状态解释，避免误显示为普通报告趋势或空占位。
- Debug UI 验证入口改为仅 Debug 内存态，不写入 Keychain；Release 二进制检查确认不包含 `UI 验证入口`、`ui-validation-token` 或 `xjie.debug.uiValidationLogin` 字符串。
- 发布前验证：`git diff --check` 通过；`xcodebuild -project Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test` 67 tests 0 failures；build settings 确认 `MARKETING_VERSION=1.0`、`CURRENT_PROJECT_VERSION=11`、bundle id `com.xjie.app`。
- Release archive `Xjie/build/Xjie-TestFlight-1.0-11.xcarchive` 生成成功；归档 Info.plist 确认 `CFBundleDisplayName=小捷`、版本 `1.0`、build `11`、HealthKit 读写说明存在；codesign entitlements 确认 `com.apple.developer.healthkit=true`。
- `xcodebuild -exportArchive` 使用 `Xjie/build/ExportOptions.plist` 上传，返回 `Upload succeeded` 和 `EXPORT SUCCEEDED`；App Store Connect 已开始 processing，TestFlight 可见性仍需等待 Apple 处理完成。
- 本记录不包含 Apple 账号、密码、API key、签名证书、provisioning profile 内容、用户密码或任何 token。

## 2026-07-07 iOS XAGE 数据页排序按钮修复

- 按用户截图修复数据页排序态：指标卡右下角原三横线改为 `置顶` 和 `删除` 两个液态玻璃胶囊按钮，继续保留左侧 `上移 / 下移`。
- `置顶` 会把当前指标卡移动到主数据列表第一张；`删除` 只从当前主界面展示列表移除该卡，不删除服务器指标、报告数据或 Apple 健康原始数据。
- 排序态新增底部 safe-area 固定 `完成排序` 工具条，用户不需要回到顶部也能退出排序；滚动内容增加底部 padding，避免最后一张卡被工具条遮住。
- 进入排序态时自动把滚动列表对齐到第一张指标卡，避免从滚动中部进入排序时首张卡被顶部状态区压住。
- 验证：`git diff --check` 通过；`xcodebuild -project Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build` 通过；iPhone 17 Pro Simulator 逐项验证排序、置顶、删除和底部完成排序，截图保存在 `X_new/implementation_audit/ios_sort_controls_20260707/`；`xcodebuild ... test` 67 tests 0 failures。
- 该排序修复已随 TestFlight `1.0(12)` 上传。排序态删除只移除当前主界面展示卡片，不删除服务器指标、报告数据或 Apple 健康原始数据。本记录不包含测试账号、密码、Apple 账号、签名凭据或任何 token。

## 2026-07-07 iOS TestFlight 1.0(12) 上传完成

- 按当前 iOS XAGE 修复结果发布 TestFlight，工程 `CURRENT_PROJECT_VERSION` 从 `11` 递增到 `12`，`MARKETING_VERSION` 继续保持 `1.0`。
- 本包包含数据页排序态修复：卡片右下角为 `置顶 / 删除` 两个液态玻璃胶囊，底部固定 `完成排序` 工具条，置顶后滚动校正，删除只影响当前主界面卡片展示。
- 同步纳入当前未发布的 iOS XAGE 修复：启动 logo 位置、外部 PDF/图片打开至报告上传、Apple 健康重新同步、动态血糖读取、设置资料/帮助结构、四项评分待评估门槛和缺失数据引导。
- 发布前验证：`git diff --check` 通过；`xcodebuild -project Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' build` 通过；`xcodebuild ... test` 67 tests 0 failures。
- iPhone 17 Pro Simulator 逐项验证排序、置顶、删除、底部完成排序；截图保存到 `X_new/implementation_audit/ios_sort_controls_20260707/`。
- Release archive `Xjie/build/Xjie-TestFlight-1.0-12.xcarchive` 生成成功；归档 Info.plist 确认 `CFBundleDisplayName=小捷`、版本 `1.0`、build `12`、HealthKit 读写说明和外部文件打开支持存在；codesign entitlements 确认 `com.apple.developer.healthkit=true`。
- Release 二进制检查确认不包含 `UI 验证入口`、`ui-validation-token`、`xjie.debug.uiValidationLogin` 或 `XJIE_DEBUG_ACCESS_TOKEN` 字符串。
- `xcodebuild -exportArchive` 使用 `Xjie/build/ExportOptions.plist` 上传，返回 `Upload succeeded` 和 `EXPORT SUCCEEDED`；App Store Connect 已开始 processing，TestFlight 可见性仍需等待 Apple 处理完成。
- 本记录不包含 Apple 账号、密码、API key、签名证书、provisioning profile 内容、用户密码或任何 token。

## 2026-07-07 iOS XAGE 报告历史、用药入口和问答等待修复

- 报告/病历上传流程新增识别等待和后台处理提示；上传后会轮询刷新报告状态，识别完成时调度本地通知提醒用户返回报告页查看摘要和入库结果。
- 资料菜单的报告详情页新增 `历史报告`，可查看报告/病历历史、单份 AI 汇总、异常项和入库指标概览；`拍照上传` 统一改为 `数据上传`，`开始入库` 打开拍照采集、PDF/图片、相册三种来源的液态玻璃 sheet。
- 左侧资料菜单新增 `用药管理` 卡片，入口放在资料管理内；资料分类详情返回时修正为先关闭子页再隐藏父菜单，避免短暂空白或父菜单闪回。
- Apple 健康睡眠同步改为读取最近 36 小时真实 asleep 阶段并合并重叠区间；无样本时显示可理解的待同步提示，不再把 `Not Found` 暴露给用户。
- X年龄中心 inline `i` 完成字体与框体对齐；问答发送等待期间显示读取档案、检索医学文献、核对趋势和整理结论等阶段提示；分析正文展示前清理每行开头的 Markdown `#`。
- 验证：`git diff --check` 通过；`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test` 70 tests 0 failures；Release Simulator build 通过；iPhone 17 Pro Simulator 逐项截图验证数据页、资料菜单、用药入口、报告上传来源、历史报告 sheet、返回无空白、X年龄原理和问答输入栏。
- 截图证据在 `X_new/implementation_audit/ios_xage_goal_final_recheck_20260707/`。本轮修复尚未上传 TestFlight，等待用户确认后再递增 build 并发布。本记录不包含测试账号、密码、Apple 账号、签名凭据或 token。

## 2026-07-07 iOS XAGE 真实用户上传与 Apple 健康趋势复测

- 使用真实生产用户数据通道复测当前 iOS XAGE：手机号登录表单对用户提供的密码返回“手机号或密码错误”，生产库确认该手机号对应 active 用户存在；后续未修改账号密码，改用服务端为该用户签发的一次性调试 token 进入真实用户数据页。
- 真实触发 Apple 健康只读授权流程，系统权限页可打开并允许读取；iOS Simulator HealthKit 无真实样本，App 正确显示“暂无可同步样本”而不是 `Not Found`。由于当前 Debug/Simulator 签名不允许 App 写入 HealthKit，缺失样本改用生产 `/api/health-data/indicators/device-sync` 生成 14 项 `apple_health` 来源指标。
- 发现并修复真实数据合并 bug：服务端已有 Apple 健康 HRV、睡眠、步数、血压等趋势点时，XAGE 数据页仍显示默认 `无/待同步`。根因是数据页只请求 watched 指标趋势，固定 Apple 健康卡不在 watched 中；同时一次请求超过后端 `/indicators/trend` 的 10 指标限制会导致整批 400。已将默认 Apple 健康关键指标加入趋势请求，并按 10 个一批请求后合并结果，且正确 URL 编码 `+` 等字符。
- 真实上传测试：相册选择实际 JPG 体检报告后 App 上传成功并显示“AI 正在后台识别”；同一实际 PDF 通过生产上传接口写入 `source_type=pdf`、进入 pending 识别队列。历史报告 sheet 可看到新 PDF 与新图片记录，单份 PDF 详情可打开并显示识别中状态。
- 验证：`git diff --check` 通过；`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test` 70 tests 0 failures；生产日志确认趋势批量请求修复后均为 200，图片/PDF 上传接口均为 200；iPhone 17 Pro Simulator 逐项验证数据页 Apple 健康来源卡、指标详情、报告相册上传、历史报告列表、PDF 单份详情。
- 截图证据在 `X_new/implementation_audit/ios_real_user_test_20260707/`。该修复已随 TestFlight `1.0(13)` 上传。本记录不包含用户密码、JWT、SSH、API key、Apple 账号或任何 token。

## 2026-07-07 iOS TestFlight 1.0(13) 上传完成

- 按用户确认发布 iOS TestFlight，工程 `CURRENT_PROJECT_VERSION` 从 `12` 递增到 `13`，`MARKETING_VERSION` 继续保持 `1.0`。
- 本包包含 `1.0(12)` 之后的全部待发布修复：报告历史与单份 AI 汇总、用药管理入口、报告上传等待态与识别完成通知、问答等待进度提示、Apple 健康睡眠无样本提示，以及真实用户复测后修复的 Apple 健康默认趋势合并。
- 发布前验证：`xcodebuild -project Xjie/Xjie.xcodeproj -scheme Xjie -destination 'platform=iOS Simulator,name=iPhone 17 Pro' test` 70 tests 0 failures；`git diff --check` 通过。
- Release archive `Xjie/build/Xjie-TestFlight-1.0-13.xcarchive` 生成成功；归档 Info.plist 确认 `CFBundleDisplayName=小捷`、版本 `1.0`、build `13`、bundle id `com.xjie.app`、HealthKit 读写说明和外部 PDF/图片打开支持存在；codesign entitlements 确认 `com.apple.developer.healthkit=true`。
- Release 二进制检查确认不包含 `UI 验证入口`、`ui-validation-token`、`xjie.debug.uiValidationLogin`、`XJIE_DEBUG_ACCESS_TOKEN`、测试手机号、明文密码或 JWT 字符串。
- `xcodebuild -exportArchive` 使用 `Xjie/build/ExportOptions.plist` 上传，返回 `Upload succeeded` 和 `EXPORT SUCCEEDED`；App Store Connect 已开始 processing，TestFlight 可见性仍需等待 Apple 处理完成。
- 本记录不包含 Apple 账号、密码、API key、签名证书、provisioning profile 内容、用户密码或任何 token。

## 2026-07-09 iOS TestFlight 1.0(14) 上传完成

- 按用户要求发布 iOS TestFlight，工程 `CURRENT_PROJECT_VERSION` 从 `13` 递增到 `14`，`MARKETING_VERSION` 继续保持 `1.0`。
- 本包包含 `1.0(13)` 之后的 XAGE 修复和成熟化：健康问答上下文语义层、数据源确认回复去内部字段、服务器 XAGE 化、XAGE 液态玻璃用药管理、数据卡片管理入口收敛和数据卡片偏好持久化。
- 发布前验证：`git diff --check` 通过；build settings 确认 `MARKETING_VERSION=1.0`、`CURRENT_PROJECT_VERSION=14`、bundle id `com.xjie.app`、自动签名和 team id `52BRF299Y7`；iPhone 17 Pro Simulator 单元测试 70 tests 0 failures。
- Release archive `Xjie/build/Xjie-TestFlight-1.0-14.xcarchive` 生成成功；归档 Info.plist 确认 `CFBundleDisplayName=小捷`、版本 `1.0`、build `14`、bundle id `com.xjie.app`、HealthKit 读写说明存在；codesign entitlements 确认 `com.apple.developer.healthkit=true`。
- Release 二进制检查确认不包含 `UI 验证入口`、`ui-validation-token`、`xjie.debug.uiValidationLogin`、测试手机号、测试密码或 JWT 字符串。
- `xcodebuild -exportArchive` 使用 `Xjie/build/ExportOptions.plist` 上传，返回 `Uploaded Xjie`、`Upload succeeded` 和 `EXPORT SUCCEEDED`；App Store Connect 已开始 processing，TestFlight 可见性仍需等待 Apple 处理完成。
- 本记录不包含 Apple 账号、密码、API key、签名证书、provisioning profile 内容、用户密码或任何 token。

## 2026-07-07 iOS XAGE LLM 上下文结构、快返和 Simulator 交互复测

- 针对问答显得不聪明、同一 session 重复强调、已同步 Apple 健康仍追问设备等问题，后端新增 `message_structure`：包含 `active_subject`、`intent`、`data_source_memory`、`health_fact_index`、`session_memory`、`response_plan`。聊天接口在保存用户消息前按当前消息和历史构建结构化上下文。
- OpenAI prompt 改为严格服从 `allowed_context` / `blocked_context`：本人问题才注入本人健康数据；妻子/家人/他人病例不会混入当前用户尿酸、血糖、TIR、报告或 Apple 健康数据。已同步 Apple 健康时，明确禁止再问“是否戴 Apple Watch / 是否同步 Apple 健康 / 把 HRV 截图发给我”。
- 问候、数据源确认、妻子 NT 主体纠错新增后端 fast path，直接返回 `message-structure-fast-path`，避免走完整 RAG/LLM 链路；文献检索改为仅在 `response_plan.needs_literature` 时执行，减少简单消息响应时间。
- iOS 问答等待卡按用户消息类型切换文案：问候、Apple 健康同步、妻子/NT、报告/病史和普通深度分析分别显示不同进度，不再对简单问题展示“检索文献”。
- 生产后端已同步 `context_builder.py`、`chat.py`、`openai_provider.py`、`omics.py` 和对应单测到服务器源码与 `xjie-api` 容器，容器内 `py_compile` 通过，`pytest tests/unit/test_chat_message_structure.py tests/unit/test_context_builder.py -q` 为 4 passed；重启 `xjie-api` 后外部 `/healthz` 返回 `{"ok":true}`，并已用同步源码重建 `xjie-backend` 镜像。
- 自动化验证：本地后端结构测试 4 passed，后端 unit 15 passed，iOS iPhone 17 Pro Simulator `xcodebuild test` 70 tests 0 failures，`git diff --check` 通过。
- Simulator 交互验证：iPhone 17 Pro Simulator 使用 Debug UI 验证入口逐项点击登录页、数据页、资料菜单、报告/日常/就医/画像详情、日常同步按钮、排序态、底部完成排序、添加指标候选表、候选表上滑、候选指标添加、压力原理、问答 `+` 菜单和 PDF/图片系统选择器。截图保存在 `X_new/implementation_audit/ios_llm_context_stress_20260707/sim/`。
- 限制：Debug UI 验证 session 不能作为真实线上登录态，发送问答会被生产接口返回“未登录”；本轮已验证 UI/按钮链路和后端生产部署，真实 LLM S01-S12 响应仍需有效线上用户登录态继续测。本记录不包含用户密码、SSH、API key、JWT、Apple 账号或任何 token。

## 2026-07-07 iOS XAGE 高强度上下文 Simulator UI 自动化

- 按用户最新要求停止继续尝试真机，改为先统一使用 iPhone 17 Pro Simulator 验证。
- 新增 `XjieUITests` target，并把它接入 `Xjie` scheme；新增 `XAgeHighIntensityContextUITests` 自动化脚本，使用真实 UI 控件点击和输入覆盖 XAGE 高强度按钮链路。
- UI 脚本覆盖：Debug UI 验证入口、资料菜单 `报告 / 日常 / 就医 / 画像` 四详情页、排序态 `置顶 / 删除` 和底部 `完成排序`、添加指标候选/管理表、问答 `+` 菜单、拍照/PDF/图片/相册/新对话入口、5 类代表上下文 prompt（问候、Apple 健康、妻子 NT、HRV、病史摘要）、X年龄 inline `i` 原理说明。
- 为稳定 UI 测试新增仅 Debug 生效的启动开关：`XJIE_UI_TEST_RESET_AUTH` 清理测试登录态，`XJIE_DISABLE_APP_UPDATE_CHECK` 禁用更新弹窗，`XJIE_DISABLE_PUSH_PERMISSION` 禁用通知权限弹窗；Release 不受影响。
- 问答输入框新增 accessibility identifier `xage.chat.input`，便于 UI 自动化用真实输入框输入 prompt。
- 验证：高强度 UI 脚本在 iPhone 17 Pro Simulator 单独运行通过，`1 passed, 0 failed`；现有 iOS 单元测试单独运行通过，`70 passed, 0 failed`；`git diff --check` 通过。xcresult 路径记录在 `X_new/implementation_audit/ios_llm_context_stress_20260707/verification_report.md`。本记录不包含测试账号、密码、JWT、Apple 账号或任何 token。

## 2026-07-08 iOS XAGE S01-S12 上下文结构补强与 Simulator 回归

- 按用户最新要求继续只使用 iPhone 17 Pro Simulator，不再尝试真机。本轮把高强度 UI 自动化 prompt 从 5 类代表消息扩展为 S01-S12 全量场景，仍然通过真实输入框和发送按钮执行，不绕过 UI。
- 后端 `message_structure` 新增报告识别状态记忆和同指标多来源冲突记忆：`report_status` 可让“报告分析好了吗”直接走状态快返；`metric_conflicts` 会记录 48 小时内 manual / Apple 健康等来源的明显差异，回答血压波动时必须按来源和时间解释。
- 聊天 fast path 新增 `report_status_query`，报告 pending/done/failed 类问题不再进入完整 RAG/LLM；风险意图识别补充 `风险 / 影响 / 后果`，尿酸风险问题会保留本人健康上下文并允许证据检索。
- OpenAI 健康问题识别补充 `HRV / 心率变异 / NT / 颈项透明层`，减少专业健康问题被当成普通聊天的风险。
- 后端专项单测扩展到 11 个结构场景，覆盖 Apple 健康和 CGM 已连接不反问、妻子/母亲主体隔离、旧血压时效、多来源血压冲突、报告 pending 快返和尿酸风险证据路径。
- 生产后端已同步服务器源码与 `xjie-api` 容器，容器内 `py_compile` 通过，`pytest tests/unit/test_chat_message_structure.py tests/unit/test_context_builder.py -q` 为 12 passed；重启后容器内、公网 IP 和 `www.jianjieaitech.com` 的 `/healthz` 均返回 `{"ok":true}`，并已提交 `xjie-backend:latest` 镜像。
- 验证：本地后端 unit 23 passed；iPhone 17 Pro Simulator UI 自动化 1 passed、0 failed，xcresult 为 `/tmp/xjie-derived-ui-context-sim-s12/Logs/Test/Test-Xjie-2026.07.08_00-07-22-+0800.xcresult`；iOS 单元测试 70 passed、0 failed，xcresult 为 `/tmp/xjie-derived-unit-context-sim-s12/Logs/Test/Test-Xjie-2026.07.08_00-11-15-+0800.xcresult`；`git diff --check` 通过。
- 记录已更新到 `X_new/implementation_audit/ios_llm_context_stress_20260707/`。真实线上账号的 LLM 最终自然语言质量仍需有效登录态继续人工复核；本记录不包含用户密码、JWT、SSH、API key、Apple 账号或任何 token。

## 2026-07-08 iOS XAGE 成熟健康 NLU 与手动 Simulator 场景验证

- 按用户要求不再按个例零散修补，新增后端 `health_nlu` 语义层，把用户健康问题统一解析为医学概念、主体、意图、安全等级、数据需求、质量门控和宏观类别。概念覆盖心血管/血压/HRV、血糖代谢、肾脏尿酸、肝脂代谢、炎症、孕期生殖、睡眠恢复、体重活动、内分泌营养、报告/设备、用药安全和急症症状。
- `message_structure` 和 OpenAI prompt 接入 `health_nlu`：本人问题可使用本人健康事实和已同步设备数据；妻子、母亲等家属/他人问题会清空本人事实、指标、报告、冲突记忆和历史 assistant 结论，避免同一 session 中把本人血糖/TIR/尿酸套用到家属。
- 多来源指标冲突新增 deterministic fast path：例如手动血压和 Apple 健康血压差异较大时，先返回来源、测量时间、数值和差异，再给复测建议，不让 LLM 泛化成普通血压科普。
- 急症 fast path 扩充胸痛、喘不上气、冒冷汗、晕厥、卒中、失血、自伤等触发词，并同步返回短摘要，便于 iOS 气泡直接显示“检测到紧急症状，请立即就医”。
- 手动 iPhone 17 Pro Simulator 验证 8 类代表场景：Apple 健康同步记忆、HRV 使用已同步上下文、妻子 NT 主体边界、母亲血糖主体隔离、血压多来源冲突、报告状态、药物安全和急症边界。测试中发现并修复两类结构性问题：母亲血糖问题曾被本人血糖/TIR 污染；血压变化问题曾未先展示来源/时间冲突。
- 验证：本地 `py_compile` 通过；后端专项 `test_health_nlu.py` + `test_chat_message_structure.py` 为 40 passed；后端完整 unit 为 52 passed；iPhone 17 Pro Simulator Debug build 通过；`git diff --check` 通过。生产 `xjie-api` 已同步源码和容器，容器内专项 40 passed，公网 IP 与域名 `/healthz` 均返回 ok，并已提交 `xjie-backend:latest` 镜像。
- 记录与截图在 `implementation_audit/ios_health_nlu_mature_dialogue_20260708/`。本记录不包含测试账号、密码、JWT、SSH、API key、Apple 账号或任何 token。

## 2026-07-10 iOS XAGE 稳健交互路由、特殊人群边界与全链路复核

- 后端新增统一对话路由层，急症、确定性高风险数值、证据不足澄清、状态快答和 LLM 分析共用同一同步/SSE 执行管线；路由、进度、回答和质量标志以结构化字段返回 iOS。
- 新增数据库幂等租约和 Alembic `0020_chat_request_receipts`，网络重试、并发请求及租约接管只允许一个执行者保存回答；同步接口改为直接读取数据库租约列，避免 SQLAlchemy identity map 缓存旧所有权。
- NLU/上下文按主体、来源、时效、当前概念和最新明确状态路由，解决 Apple 健康重复追问、本人/家属数据串用、跨主题污染、报告状态歧义和同会话重复强调。
- 高风险确定性规则补齐单项严重血压、无单位血糖、低血糖、酮症症状和孕产边界；孕期/产后六周内采用 `>=160` 收缩压或 `>=110` 舒张压阈值，同主体“确认未怀孕”可覆盖旧孕期状态。
- 儿童严重低血糖不再固定套用成人 15 克；已知儿童按既定个体方案并明确幼儿通常更少，年龄未知的“孩子”分别说明未成年和成年路径，成年本人仍保留 15 克/15 分钟规则。
- iOS 改用 SSE、服务器路由进度、token 绑定刷新和有限连接等待；网络失败保留可重试用户气泡，新对话阻断旧回答串入，AI 授权必须明确接受。
- 移除自签证书放行和任意 ATS；生产 API 使用系统 HTTPS 校验，Info.plist 声明不使用需出口合规文稿的自有加密。
- 人工 Simulator 测试发现中文拼音候选词发送后输入框残留原文；改为同步消费草稿、退出焦点并清理同一 IME 回写，同时保护用户的新草稿。按原步骤重测后输入框立即清空且消息只发送一次。
- 验证：后端完整 pytest `156 passed, 3 skipped`；变更范围 Ruff、compileall、迁移升级/降级/重升级、`git diff --check` 通过；iPhone 17 Pro Simulator 完整 iOS 测试 `80 unit + 2 UI`，0 failed。
- 32 个逐项人工场景和截图保存在 `implementation_audit/ios_robust_chat_routing_20260710/`，覆盖授权、数据源记忆、主体隔离、证据不足、数值歧义、急症、网络重试、会话隔离、孕产、儿童和中文 IME。
- 生产部署前发现服务器 `backend/.env` 会被旧 Dockerfile 的 `COPY . .` 烘焙进镜像；该候选镜像未上线并已删除。新增 `backend/.dockerignore`，并把 Dockerfile 改为只复制 `pyproject.toml`、Alembic、`app`、`static` 和 `tests`。安全重建镜像禁入文件计数为 0，镜像内完整单测 `156 passed`。
- 生产服务器 `/home/mayl/XJie_IOS_XAGE` 已快进到 `e663f80`，部署 `xjie-backend:xage-e663f80`；PostgreSQL Alembic 从 `0019_app_releases` 升到 `0020_chat_request_receipts (head)`，新表存在。正式容器保留原端口、restart policy 和 `host.docker.internal:host-gateway`，启动异常计数为 0，旧容器保留为回滚备份。
- 公网合成账号验证完成注册、显式 AI 授权、紧急路由、幂等重放、真实 `llm.health.standard`、响应守卫和注销；公网模型请求约 6.02 秒完成。Nginx 新增 `/api/chat/stream` 精确无缓冲路由与 `/privacy` 转发，复测 `route` 约 0.295 秒到达、`done` 约 10.424 秒到达，`/privacy` 从 404 恢复为 200。
- 生产 JWT 密钥长度仍低于 32 字符；为避免未通知地使全部用户 token 失效，本轮未轮换，已记录为维护窗口安全项。依赖未锁定和 Docker 依赖层缓存不足也作为后续运维优化保留。
- 本轮只使用 Simulator，未尝试真机，未发布 TestFlight；当前 TestFlight `1.0(14)` 不包含本次修改。本记录不包含账号密码、JWT、SSH、API key 或 Apple 凭据。

## 2026-07-11 iOS XAGE 复合健康问答完整性与证据一致性

- 针对“失眠、情绪低落、鼻炎、脊柱侧弯和缺氧是否相关”这类复合问题，新增通用 `causal_assessment`：逐项区分研究关联、可能机制、个体是否已证实和能改变判断的客观评估；普通血压/心率等因果问题不会被硬塞入鼻炎、侧弯或缺氧检查。
- Provider 对严格 JSON 的 `finish_reason`、闭合结构、残句、Markdown、深度篇幅和本轮必答概念做完整性门控；第一次失败从头重试，第二次仍失败时返回可重试状态，不再把半句话持久化为成功回答。连续追问 `delta_only` 保持简洁但仍检查残句和本轮概念覆盖。
- 响应守卫删除未经证实的缺氧因果断言，保留有条件、可能性或“不能确认”的边界；情绪危机和呼吸急症提示按等价措辞去重，避免同一安全提示出现两次。
- 文献检索按概念组过滤候选；后处理不再猜测论文换号，只保留原编号下关系主体、方向、否定/肯定和证据强度均一致的角标。summary、analysis、answer_markdown、幂等 replay 和历史回载使用同一紧凑编号契约。
- assistant 元数据保存版本化 citation 快照、`reply_to_user_message_id`、summary、answer、followups 和 response_state；后续 claim 更新不会改变旧回答证据含义，缺失旧 claim 时不会压缩数组造成错号。
- 新增显式核心证据 seed CLI 与 `backend/deploy/seed_core_evidence.sh`。预览不连接数据库或执行 embedding，`--apply` 才幂等写入并记录 manifest SHA256、PMID、embedding 模型和结果；重复 seed 保留人工 disabled 状态。
- iOS 深度问答主气泡显示完整正文，残缺短摘要回退到完整正文，正文/分析相同则不显示重复按钮；Markdown 保留行内格式。证据页按正文实际角标展示并兼容旧稀疏编号。
- iOS Citation 新增适用人群、研究类型、样本量和年份；常见研究设计转为中文用户文案，未知内部代码不再直接暴露。参考信息自然换行，不再单行省略或重复期刊。
- Auth 单测改用不读写 Keychain、忽略 Debug override 的独立 `AuthManager`，消除全量测试中 shared 登录态竞态。
- 三轮独立反例审查覆盖：漏答概念、代词式“本次不讨论它”、缺氧自相矛盾、错主体论文、正反极性、观察性证据过度因果、`结论。[1]`、`但[1]。`、稀疏编号、历史证据快照和 seed 幂等。
- 验证：后端完整 pytest `236 passed, 3 skipped`；变更范围 Ruff、compileall、seed preview、shell 语法和 `git diff --check` 通过；iPhone 17 Pro Simulator iOS 单元测试 `92 passed, 0 failed`，Debug build 通过。
- Simulator 使用本地临时 SQLite 和合成账号逐步验证完整正文、历史重载、证据编号、适用人群、中文研究类型、样本量/年份、自然换行和安全区。最终脱敏截图为 `implementation_audit/ios_compound_chat_quality_20260710/screenshots/23_final_evidence_population_layout.png`。
- 原始登录截图目录和本地 SQLite 默认忽略，仅提交人工复核且不含账号标识的最终画面。本轮未尝试真机、未发布 TestFlight；当前 `1.0(14)` 不包含本次客户端修改。本记录不包含手机号、密码、JWT、SSH、API key 或 Apple 凭据。
