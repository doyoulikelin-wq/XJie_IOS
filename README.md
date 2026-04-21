# Xjie — iOS 智能代谢健康管理 App

基于 SwiftUI 的智能代谢健康管理平台，支持 CGM 血糖追踪、膳食记录（拍照 AI 识别）、AI 健康对话、代理干预系统。

## 项目结构

```
XJie_IOS/
├── Xjie/                            ← iOS App (SwiftUI)
│   ├── Xjie/
│   │   ├── XjieApp.swift            ← App 入口
│   │   ├── Views/                   ← 页面视图
│   │   ├── ViewModels/              ← 视图模型
│   │   ├── Models/                  ← 数据模型
│   │   ├── Services/                ← 网络/存储服务
│   │   └── Resources/              ← 资源文件
│   └── Xjie.xcodeproj              ← Xcode 工程
├── backend/                         ← FastAPI 后端 API
│   ├── app/routers/                 ← 路由（auth, glucose, meals, chat, agent ...）
│   ├── app/models/                  ← 数据库模型
│   ├── app/services/                ← 业务逻辑
│   ├── app/providers/               ← LLM 提供商（OpenAI/Kimi/Gemini）
│   └── app/core/                    ← 配置、安全、中间件
├── docker-compose.yml               ← 后端基础设施
└── data/                            ← 研究数据（已 gitignore）
```

## 技术栈

| 层级     | 技术                                      |
| -------- | ----------------------------------------- |
| iOS 前端 | SwiftUI + Combine + Swift 5.9             |
| 后端     | FastAPI + SQLAlchemy 2.0 + Pydantic v2    |
| 数据库   | TimescaleDB (PostgreSQL 16)               |
| 缓存     | Redis 7                                   |
| LLM      | Kimi (Moonshot) / OpenAI / Gemini         |
| 部署     | Docker + 阿里云 ECS                       |

## 快速开始

### 后端部署

```bash
# 克隆代码
git clone https://github.com/doyoulikelin-wq/XJie_IOS.git
cd XJie_IOS

# 配置环境变量
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入数据库、Redis、LLM API Key 等

# Docker 构建并启动
docker build -t xjie-backend ./backend
docker run -d --name xjie-api \
  --env-file backend/.env \
  -p 8000:8000 \
  --restart unless-stopped \
  xjie-backend
```

### iOS App

1. 用 Xcode 打开 `Xjie/Xjie.xcodeproj`
2. 在 Info.plist 中配置 `API_BASE_URL` 指向后端地址
3. 选择真机或模拟器运行
4. Bundle ID: `com.xjie.app`

### 环境变量

在 `backend/.env` 中配置：

```env
DATABASE_URL=postgresql+psycopg://user:pass@host:port/metabodash
REDIS_URL=redis://host:port/0
JWT_SECRET=your-secret-key
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.moonshot.cn/v1   # Kimi API
OPENAI_MODEL_TEXT=moonshot-v1-8k
OPENAI_MODEL_VISION=moonshot-v1-8k
```

## 核心功能

- **手机号登录**: 注册/登录，JWT 认证
- **血糖监测**: CGM 数据导入、24h/7d 曲线、TIR 统计
- **膳食记录**: 拍照上传 → AI 视觉识别热量 → 记录
- **AI 助手「小捷」**: 友好对话风格，基于血糖+膳食上下文智能分析，可展开详细分析气泡
- **用户画像自动提取**: AI 从对话中提取性别/年龄/身高/体重等信息
- **代理系统**: 每日简报、餐前模拟、血糖救援、周评
- **三级干预**: L1 温和 / L2 标准 / L3 积极

## API 端点

| 路由                         | 功能         |
| ---------------------------- | ------------ |
| POST /api/auth/signup         | 手机号注册   |
| POST /api/auth/login          | 手机号登录   |
| POST /api/auth/refresh        | Token 刷新   |
| GET  /api/dashboard/health    | 健康总览     |
| GET  /api/glucose             | 血糖数据     |
| POST /api/meals               | 膳食记录     |
| POST /api/chat                | AI 对话      |
| GET  /api/agent/today         | 每日简报     |
| POST /api/agent/premeal-sim   | 餐前模拟     |
| GET  /api/agent/rescue        | 救援检查     |

## 测试

```bash
cd backend
pytest -q
```
