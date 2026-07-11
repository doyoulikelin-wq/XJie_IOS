# iOS Apple 健康同步故障修复与发布审计

日期：2026-07-11  
范围：iOS XAGE、生产后端、TestFlight `1.0(16)`；Android 未修改。

## 结论

“Apple 健康同步使用不了”不是单点权限故障，而是一条前后端故障链：客户端展示了 54 项指标，但原读取引擎只实际查询 14 项；查询错误被 `try?` 吞掉，拒绝读取、查询失败和确实无数据无法区分；多个同步入口没有统一刷新服务端；账号切换时本地同步状态和卡片偏好未按账号隔离；工程也没有后台传递 entitlement 与 ObserverQuery。服务端同时缺少可靠样本身份、分类值和本地日期契约，可能把“全部跳过”误报为成功，并可能覆盖手工数据。

本次将 54 项目录统一为单一注册表：51 项有真实 HealthKit 读取实现，3 项明确标记为不支持，分别是睡眠评分、`glucose` 复合卡（原生血糖指标另有真实读取）和症状复合卡。前后端同步、账号隔离、幂等、后台观察、迁移和用户可见状态均已闭环。

## 查明的主要原因

1. 指标目录与读取引擎分裂：界面 54 项、引擎 14 项，未映射项目永远不会读取。
2. HealthKit 查询使用 `try?`，读取拒绝、类型不可用、查询失败与无样本都被压成空数组。
3. 同步入口逻辑不一致，部分入口上传后不刷新服务端趋势；服务端恢复指标还被截断为前 8 项。
4. 全局 UserDefaults 同步标记与卡片布局没有账号作用域，token 切换期间的重试也可能串到新账号。
5. 没有 `com.apple.developer.healthkit.background-delivery`，也没有按账号启停的 HealthKit Observer。
6. 服务端按同日指标做兼容覆盖，缺少 `source_metric/source_id`，旧 build 15 时间戳身份升级到 UUID 时有重复风险；手工记录与设备记录也没有足够隔离。
7. 分类记录被当成连续数值，来源本地日期与时区偏移丢失；全部拒绝仍可能被 200/跳过表现成成功。

## 已完成修改

- 以 `AppleHealthStore.metricRegistry` 统一目录、HealthKit 类型、读取策略、值类型、展示名与后台频率。
- 覆盖活动、身体测量、心脏/呼吸、睡眠、营养、血糖/胰岛素、声音/环境和生理记录；按指标使用今日、36 小时、14 天、365 天或全历史窗口。
- 每个查询返回可诊断结果，不再吞错；同步状态区分已同步、已是最新、部分成功和拒绝，并保留服务端 422 的逐项原因。
- 所有显式同步入口走同一流程：配置账号、读取、上传、刷新服务端完整指标目录。
- JWT `sub` 仅以 SHA-256 摘要形成本地账号作用域；同步标记、Observer enrollment、卡片布局和服务端快照均按账号隔离。账号切换或注销会停止旧账号任务，重试前后都会再次校验账号。
- 增加后台 HealthKit entitlement 与按账号启停的 Observer 协调器，处理并发手动/后台同步、dirty rerun、停止回调和 finish-window 竞态。
- 上传契约增加 `value_kind`、`display_value`、`source_local_date`、`timezone_offset_minutes`、`source_metric` 和 `source_id`。
- 服务端增加来源样本唯一索引、精确幂等、并发 savepoint、旧 build 15 时间戳身份到 UUID 的原子接管、设备与手工记录隔离，以及明确的 inserted/updated/unchanged/rejected 计数。
- 分类值只以标签参与用户趋势与健康上下文；原始数值仅用于审计，不再作为连续数值进入范围、冲突或 LLM 推断。
- 修正 Health 隐私说明：当前版本只读、不向 Apple 健康写入；明确数据范围、前后台同步和当前登录账号。

## 验证结果

- iPhone 17 Pro Simulator、iOS 26.3.1 全量 Xcode 测试：`144 passed, 0 failed`，其中 142 项单元测试、2 项完整 UI 流程。
- HealthKit/API 定向测试：49 项通过；两轮独立反例审查均未发现剩余 P0/P1。
- 后端完整测试：`261 passed, 3 skipped`；本次变更 Python 文件 Ruff、compileall、`git diff --check` 均通过。
- PostgreSQL 16：Alembic `0021 → 0020 → 0021` 往返通过，最终 `alembic check` 无缺失操作。
- 注册表与目录 ID：54/54 唯一且完全匹配，51 项支持、3 项明确不支持。
- Computer Use 人工检查确认数据页、Apple 健康同步卡和数据卡片管理布局正常；脱敏画面见 [01-health-data-screen.jpg](screenshots/01-health-data-screen.jpg)。

## 生产部署与公网回归

- 实现提交：`38df6ee`；生产镜像：`xjie-backend:xage-38df6ee`。
- 生产 PostgreSQL 从 `0020_chat_request_receipts` 升级到 `0021_device_indicator_identity`。
- 新容器 `restart_count=0`；本机与公网 `/healthz` 均为 200，未授权设备同步为 401；新增列、索引和约束无缺失。
- 两个一次性合成账号完成：首次插入、第二次 unchanged、来源本地日期、分类标签、旧 build 15 时间戳 ID 到 UUID 单行接管、全部拒绝结构化 422，以及账号 A/B 隔离。两个账号均通过公开注销接口清理。
- 第一次回归脚本曾复用唯一 `username` 导致第二个合成账号注册 500；第一个账号已清理。修正为独立用户名后全链路通过，之后日志错误计数为 0；该异常属于测试数据冲突，不是 Health 同步实现故障。

## TestFlight

- 版本：`1.0(16)`；发布准备提交：`e1b8000`。
- Archive：`Xjie/build/Xjie-TestFlight-1.0-16.xcarchive`，`ARCHIVE SUCCEEDED`。
- 归档确认：显示名“小捷”、bundle id `com.xjie.app`、生产 HTTPS、准确的 Health 说明、HealthKit 与 background-delivery entitlement。
- Release 可执行文件的 Debug/UI 测试标记、旧 localhost HTTP、私钥形态和敏感文件扫描均为 0；签名验证通过。
- 本机 App Store profile 同时包含 HealthKit 与 background-delivery，有效期至 2027-04-09。
- 2026-07-11 23:28（Asia/Shanghai）上传返回 `Uploaded Xjie`、`Upload succeeded`、`EXPORT SUCCEEDED`；App Store Connect 已开始 processing。

## 真机限制

Simulator 无法证明真实用户对每个 HealthKit 类型的读取授权，也不能证明 iOS 在锁屏、系统调度或冷启动条件下的后台唤醒时机。Apple 为保护隐私，也不会向应用可靠披露用户是否拒绝了读取权限，因此客户端只能将“无数据”和可观察到的查询错误做诚实区分，不能伪造“已授权读取”的结论。`1.0(16)` 处理完成后仍需用真实 iPhone/Apple Watch 做一次授权、前台同步和后台更新验收。

本报告不包含手机号、密码、JWT、SSH、API key、Apple 账号或签名材料。
