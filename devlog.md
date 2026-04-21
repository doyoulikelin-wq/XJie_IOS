# Xjie iOS 开发日志 (DevLog)

> 项目：Xjie iOS App (SwiftUI)  
> 起始日期：2026-03-24  
> 当前状态：v1.6.0 已上传 TestFlight (build 2)

---

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
