# Xjie 技术架构与特性

> 版本：v1.4.0 | 更新日期：2026-04-03  
> 技术栈：SwiftUI + FastAPI + TimescaleDB + Kimi K2.5

---

## 一、整体架构

```
┌──────────────────────────────────────────────────────┐
│                    iOS App (SwiftUI)                  │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │  Views   │ │ViewModels│ │ Services │ │  Models  │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────────┘ │
│       └─────────────┴───────────┘                     │
│                     │ HTTPS / SSE                     │
├─────────────────────┼────────────────────────────────┤
│              FastAPI Backend                          │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │ Routers │ │ Services │ │Providers │ │  Models  │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       │            │            │            │        │
│  ┌────┴────┐  ┌────┴────┐ ┌────┴────┐  ┌───┴─────┐ │
│  │SQLAlchemy│  │  Redis  │ │ Kimi/   │  │TimescaleDB│
│  │  2.0    │  │   7     │ │ OpenAI  │  │(PG 16)  │ │
│  └─────────┘  └─────────┘ └─────────┘  └─────────┘ │
└──────────────────────────────────────────────────────┘
```

| 层 | 技术 | 版本 |
|----|------|------|
| 前端 | SwiftUI + Combine | iOS 15+ |
| 后端 | FastAPI + Pydantic v2 | 0.2.0 |
| ORM | SQLAlchemy 2.0 (async) | 2.0 |
| 数据库 | TimescaleDB (PostgreSQL 16) | 16 |
| 缓存 | Redis | 7 |
| LLM | Kimi K2.5 (Moonshot) / OpenAI 兼容 | — |
| 容器化 | Docker + docker-compose | — |
| CI/CD | GitHub Actions | — |
| 部署 | Aliyun ECS | 8.130.213.44 |

---

## 二、iOS 架构设计

### 2.1 MVVM 分层

```
App/               XjieApp.swift — @main 入口、auth 路由、splash 动画
Models/            7 个 Codable 模型文件（Auth/Chat/Glucose/Health/Meal/Settings/FeatureFlag）
ViewModels/        12 个 @MainActor ViewModel 文件
Views/             13 个模块目录 + Shared 共用组件 + Components 基础组件
Services/          6 个服务（API/Auth/Environment/FeatureFlag/Push/Protocol）
Utils/             10 个工具类
Repositories/      1 个 Repository（HealthDataRepository）
Resources/         i18n 本地化字符串（zh-Hans / en）
```

### 2.2 依赖注入

- `APIServiceProtocol` 协议抽象网络层
- 所有 ViewModel 接收 `api: APIServiceProtocol` 参数
- 测试通过 `MockAPIService` 注入

### 2.3 响应式数据流

- `@Published` 属性驱动 UI 更新
- `@StateObject` / `@EnvironmentObject` 管理 ViewModel 生命周期
- `Task` + `async/await` 处理异步操作
- `guard !Task.isCancelled` 防止页面离开后更新 UI

### 2.4 iPad 自适应

- `@Environment(\.horizontalSizeClass)` 判断设备
- iPhone → `TabView`（底部标签栏）
- iPad → `NavigationSplitView`（侧边栏导航）

---

## 三、后端架构设计

### 3.1 分层结构

```
routers/           API 路由层（auth/chat/health_data/health_reports/admin/glucose/meals/omics/push）
services/          业务逻辑层（health_summary_service/feature_service/push_service）
providers/         LLM 接口层（openai_provider/base — 抽象接口）
models/            ORM 模型层（18+ 表）
schemas/           Pydantic v2 请求/响应 Schema
core/              配置中心（config.py — Settings + .env）
db/                数据库连接 + Alembic 迁移
workers/           后台任务
utils/             工具函数
```

### 3.2 LLM Provider 抽象

```python
class BaseLLMProvider:
    async def generate_text(query, context, skill_prompt) -> ChatLLMResult
    async def stream_text(query, context, skill_prompt) -> AsyncGenerator
    async def generate_vision(image_data, prompt) -> str
```

- `OpenAIProvider` 实现，兼容 Kimi / OpenAI / 其他 OpenAI 接口兼容模型
- 模型名集中配置：`settings.OPENAI_MODEL_TEXT` / `settings.OPENAI_MODEL_VISION`
- Kimi K2.5 特殊处理：`llm_temperature_kwargs()` 智能省略不支持的参数
- 流式输出自动过滤 `<think>...</think>` 标签

### 3.3 数据库设计

| 表 | 用途 | 关键字段 |
|----|------|---------|
| user_account | 用户账户 | phone, password_hash, is_admin |
| user_profiles | 用户画像 | sex, age, height_cm, weight_kg, liver_risk_level |
| glucose | 血糖时序数据 | timestamp, glucose_value, source (TimescaleDB 超表) |
| meals | 膳食记录 | food_items, estimated_calories, image_url, ai_analysis |
| health_documents | 体检/病历 | doc_type, csv_data, abnormal_flags, ai_brief, ai_summary |
| conversations | 对话会话 | thread_id |
| chat_messages | 消息 | role, content, summary, analysis, profile_extracted |
| omics_data | 多组学 | data_type, ai_interpretation, risk_level |
| feature_flags | 功能开关 | key, enabled, rollout_pct |
| skills | AI 技能 | priority, trigger_hint, prompt_template |
| llm_token_audit | Token 审计 | model, prompt_tokens, completion_tokens, feature |
| consent | 用户授权 | feature, granted |
| device_tokens | 推送 Token | token, device_name |
| summary_tasks | 摘要任务 | status, stage, token_used |
| indicator_knowledge | 指标知识库 | indicator_name, description, reference_range |

---

## 四、安全体系

### 4.1 认证与授权

| 措施 | 实现 |
|------|------|
| JWT 双 Token | Access 30min + Refresh 7d |
| Token 安全存储 | iOS Keychain（非 UserDefaults） |
| 并发刷新去重 | `refreshTask: Task<Void, Error>?` 排队机制 |
| 管理员守卫 | `require_admin` 依赖注入保护所有 admin 端点 |
| AI 授权同意 | `Consent` 模型，403 自动触发授权并重试 |
| 强制解包清零 | 全项目 `!` 替换为 `guard let` / `if let` |

### 4.2 网络安全

| 措施 | 实现 |
|------|------|
| URL 安全构建 | `URLBuilder` 枚举 + `URLComponents` / `URLQueryItem` |
| CORS 配置 | 仅允许指定来源 |
| 输入验证 | Pydantic v2 Schema 强类型校验 |
| Token 审计 | 每次 LLM 调用记录 prompt/completion tokens + 功能分类 |

### 4.3 隐私合规

| 措施 | 实现 |
|------|------|
| PrivacyInfo.xcprivacy | 声明健康数据 + 相册访问 + 文件 API 使用 |
| i18n 国际化 | 150+ 键值对（zh-Hans / en） |

---

## 五、性能优化

### 5.1 渲染性能

| 优化 | 详情 |
|------|------|
| DateFormatter 缓存 | 4 个 Formatter 顶层 `private let` 单例，`Utils.parseISO()` 统一入口 |
| 图表数据预计算 | `chartData: [(Date, Double)]` 在 fetch 后一次性解析，Canvas draw 内零日期解析 |
| 请求取消 | `Task` 引用 + `cancel()`，页面消失后不更新 UI |
| ChatMessage.id | 存储属性（非计算属性），避免 SwiftUI 无限重渲染 |

### 5.2 网络性能

| 优化 | 详情 |
|------|------|
| 分页加载 | 20 条/页 + offset + `loadMore()` |
| 自动重试 | URLError / 5xx 最多 2 次，指数退避 1s → 2s |
| 超时分级 | 普通请求 15s / 文件上传 60s / LLM 调用 90s |
| 离线缓存 | 文件级 Codable 持久化，网络恢复后自动刷新 |
| 网络监测 | `NWPathMonitor` 实时检测，断网时展示缓存 + Banner |

### 5.3 缓存策略

| 缓存层 | 实现 | TTL |
|--------|------|-----|
| 图片内存缓存 | `NSCache`（100 张 / 50 MB） | 会话内 |
| 图片磁盘缓存 | `cachesDirectory` 文件存储 | 3 天 |
| Feature Flags | iOS 本地缓存 | 5 分钟 |
| Feature Flags | 后端内存缓存 | 60 秒 |
| 离线数据 | `cachesDirectory/offline_cache/` | 无限（手动清理） |

### 5.4 后端性能

| 优化 | 详情 |
|------|------|
| AI 摘要懒加载 | 历史文档首次访问时生成，后续查询直接返回 |
| 异步摘要生成 | `threading.Thread` 后台执行健康研究报告 |
| 流式输出 | SSE 事件流避免长时间等待 |
| 功能开关缓存 | 60 秒内存缓存避免频繁 DB 查询 |

---

## 六、测试体系

### 6.1 单元测试

| 测试文件 | 用例数 | 覆盖 |
|---------|--------|------|
| UtilsTests | 22 | formatDate / formatTime / toFixed / glucoseColor / URLBuilder / MIMEType |
| LoginViewModelTests | 8 | 输入验证 × 3 + 登录成功 × 2 + 网络错误 + subjects 加载 × 2 |
| ChatViewModelTests | 6 | 发消息 / 空消息 / 错误 / 新对话 / 历史加载 |
| ChatMessageTests | 4 | BUG-01 回归：id decode / 生成 / 稳定性 |
| HomeViewModelTests | 3 | fetchData 成功 / 失败 / loading |
| GlucoseViewModelTests | 3 | fetchRange / error / 窗口切换 |
| **合计** | **46** | **P0-P6 任务 39/39 ✅** |

### 6.2 测试基础设施

- `MockAPIService`：完整实现 `APIServiceProtocol`，支持注入成功/失败响应
- 所有 ViewModel 支持依赖注入 → 可独立测试
- GitHub Actions CI：macOS 15 runner + DerivedData 缓存

---

## 七、代码质量

### 7.1 代码复用

| 共用组件 | 使用场景 |
|---------|---------|
| `CSVTableView` | ExamReportViews + MedicalRecordViews |
| `DocumentTagView` | 4 种标签组件（来源/状态 × 列表/详情） |
| `MetricItemView` | HomeView + GlucoseView 指标卡片 |
| `EmptyStateView` | 所有列表页空状态 |
| `ErrorStateView` | 自动识别网络/认证/服务器错误类型 |
| `CachedAsyncImage` | 全部图片展示（三层缓存） |
| `SplashView` | 启动画面（渐变 + Logo 动画） |

### 7.2 常量管理

- `ChartConstants`：血糖图表绘制参数
- `APIConstants`：requestTimeout / uploadTimeout / llmTimeout / pageSize

### 7.3 无障碍

- 30+ 硬编码 emoji 替换为 SF Symbols
- 所有交互元素自动获得 VoiceOver 支持
- 弃用 API 全部替换（`UIDocumentPickerViewController` → `UTType`）

---

## 八、设计系统

### 8.1 品牌配色

| Token | 用途 | 值 |
|-------|------|-----|
| `appPrimary` | 主色深蓝 | #1565C0 |
| `appAccent` | 辅色青绿 | #00C9A7 |
| `appGradientStart` | 渐变起点 | #00C9A7 |
| `appGradientEnd` | 渐变终点 | #1565C0 |
| `appDanger` | 异常红 | #ef4444 |
| `appSuccess` | 成功绿 | #22c55e |
| `appWarning` | 警告黄 | #f59e0b |

### 8.2 深浅模式

| Token | 映射 |
|-------|------|
| `appText` | `Color(.label)` — 自动适配 |
| `appBackground` | `Color(.systemBackground)` |
| `appCardBg` | `Color(.secondarySystemBackground)` |
| `appMuted` | `Color(.secondaryLabel)` |

- `CardStyle` 修饰器：亮色有阴影，暗色自动移除

---

## 九、LLM 集成

### 9.1 提供商支持

| 提供商 | 模型 | 状态 |
|--------|------|------|
| Kimi (Moonshot) | kimi-k2.5（多模态 + 思考模式） | 生产主力 |
| OpenAI | gpt-4 / gpt-4-vision | 备选支持 |
| Gemini | — | 已移除 |

### 9.2 Kimi K2.5 适配

| 特性 | 处理方式 |
|------|---------|
| 温度参数 | `llm_temperature_kwargs()` — kimi-k2.5 自动省略 temperature/top_p/n 等参数 |
| 思考标签 | 流式输出自动过滤 `<think>...</think>` |
| 多模态 | 图片编码 base64 传入，支持膳食识别 + 报告 OCR |
| Token 审计 | 每次调用记录 prompt/completion tokens、模型、功能分类 |

### 9.3 Prompt 工程

| 系统 | 策略 |
|------|------|
| AI 对话 | 身份设定 + 数据感知消息构建 + 技能注入 |
| 文档摘要 | JSON 格式输出 `{"brief":"≤10字","summary":"详细"}` |
| 健康报告 | 6 阶段分步生成，上下文逐步传递 |
| 用户画像 | 从对话提取 profile_extracted，仅更新为空的字段 |

---

## 十、部署与运维

### 10.1 Docker 部署

```yaml
services:
  api:        xjie-backend    (FastAPI, port 8000)
  db:         timescaledb     (PostgreSQL 16, port 35432)
  redis:      redis:7         (port 6379)
```

### 10.2 部署流程

```bash
git pull origin main
docker build --network=host -t xjie-backend ./backend
docker stop xjie-api && docker rm xjie-api
docker run -d --name xjie-api --env-file ~/XJie_IOS/backend/.env \
  --network=host --restart unless-stopped xjie-backend
```

### 10.3 数据库迁移

- Alembic 管理迁移版本
- `0001` 初始化核心表 → `0009` Feature Flags + Skills 表
- 增量 ALTER TABLE 添加 ai_brief / ai_summary 等列

### 10.4 日志与监控

| 组件 | 实现 |
|------|------|
| iOS 结构化日志 | `os.Logger`（network / auth / data / ui 分类） |
| 崩溃上报 | `CrashReporter` 协议（可接入 Crashlytics / Sentry） |
| Token 审计 | `llm_token_audit` 表，Token 仪表板可视化 |
| 健康检查 | `GET /healthz` 端点 |

### 10.5 环境配置

- `Environment.swift`：从 Info.plist 读取 `API_BASE_URL`，DEBUG 时 fallback 到 localhost
- `.env` 文件：`LLM_PROVIDER` / `OPENAI_MODEL_TEXT` / `OPENAI_MODEL_VISION` / `DATABASE_URL` 等

---

## 十一、项目规模

| 指标 | 数值 |
|------|------|
| iOS Swift 源文件 | 52 |
| 后端 Python 源文件 | 30+ |
| 单元测试 | 46 |
| API 端点 | 70+ |
| 数据库表 | 18+ |
| 共用 UI 组件 | 7 |
| ViewModel | 12 |
| Alembic 迁移 | 9+ |
