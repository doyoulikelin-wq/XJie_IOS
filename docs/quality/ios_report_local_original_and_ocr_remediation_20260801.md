# iOS 健康报告本地原件与 OCR 停滞修复记录（2026-08-01）

## 最小复现与生产事实

1. 在 iOS 健康报告页从相册选择一张报告并完成上传。
2. 首页长期显示“识别中”；打开报告后出现包含 workflow、asset、SHA-256、候选和 Observation 的技术追踪页，而不是报告原件。
3. 生产只读核验确认截图对应 workflow `#5`、asset `#10`：上传会话、asset 元数据、seal 和 workflow 已入库；workflow 自 2026-07-31 13:11 起一直为 `recognizing/version 1`，没有 OCR claim、provider、candidate、event、Observation 或 score job。
4. 生产只有 API 进程，没有 Celery worker/beat；当前 S3 endpoint 不可解析、凭据为占位配置，服务器也无法读取 asset 字节。近期新上传因此在 PUT 阶段返回 503。
5. 对用户提供的现场文件做只读签名检查，确认它的真实容器是 HEIC/HEIF，但旧客户端上传时把扩展名和 MIME 标成了 PNG。旧质量检查与 OCR 因而按 PNG 解码失败。
6. 生产报告视觉模型配置仍是纯文本 `moonshot-v1-8k`。即使对象字节能够读取且完成 HEIC 转码，该模型也不具备图片输入能力；配置层过去没有在 API 启动或 worker claim 前拒绝这一组合。

## 根因

- seal 只创建 `recognizing` workflow，OCR 完全依赖 Celery beat 发布扫描任务和 worker 消费；生产未部署这两个角色，所以 LLM 从未被调用。
- worker 曾在 claim workflow 之前构造 provider/extractor；构造失败会绕过所有数据库写回。未被 worker 领取的 workflow 又没有持久 deadline，而 stale reconciler 只处理已有 lease 的 running 行，因此 provider 初始化失败或 worker/beat 整体缺席都会永久显示“识别中”。
- iOS 的相机、相册、文件和系统“打开方式”入口只把原件变成内存 `Data`，没有本地持久化；状态释放或 App 重启后原件不可恢复。
- 普通用户点击报告时固定打开服务器追踪页；当前“查看原件”又依赖服务器对象下载，和“原件储存在用户本地”的产品约束相反。
- Dashboard 把 `failed` 等所有非 completed 状态统一映射成“解析中”，掩盖终态失败。
- Dashboard 旧二态设计还把 `awaiting_confirmation` 与 `committing` 混入“已入库 · 解析中”，首次 history 读取失败时又同时渲染“暂无健康报告”；用户无法区分识别中、待确认、入库中、失败与真正空数据。首次严格 UI 运行因此暴露一条仍断言旧文案的过期测试，而可访问性快照证明产品已正确显示“识别完成 · 待确认”。
- OCR/确认完成后若部分评分输入不足，score job 进入 `partial_failed`，但 workflow 仍是 `completed_score_pending`，造成第二类永久处理中。
- 文件类型过去相信客户端文件名/MIME，而不检查真实魔数；因此“名为 PNG 的 HEIC”既不能被正确质量检查，也不能被旧 OCR 路径处理。
- provider 配置过去没有端点与模型能力白名单，文本模型会等到任务执行中才失败；运行时 provider 构造失败又发生在持久 claim 之前，既没有独立基础设施预算，也没有可恢复终态。

## 永久约束

1. 所有 iOS 报告入口必须先把用户选择的精确字节、文件名、MIME、页序、大小和 SHA-256 原子写入账号与 subject 隔离的 Application Support 仓库；本地持久化失败时不得发起网络上传。
2. 本地仓库必须跨 ViewModel 和 App 重启存在，读取时复核大小与 SHA-256；错误账号、缺失或损坏文件不得回退成另一用户的数据。
3. seal 后必须把 workflow ID 与本地页清单持久绑定；历史详情优先读取本地原件，离线命中时不得发网络请求。
4. Release 用户界面不得展示 workflow/asset/SHA、fact key、原始 JSON、证据字典、算法/状态/失败代码等内部追踪信息；报告详情必须明确区分上传中、识别中、待确认、确认后入库中、失败、解析完成与评分部分不可用。未知服务端值必须使用用户兜底文案，首次读取失败不得冒充“暂无健康报告”。
5. 服务器原件只作为 OCR 临时处理副本，不作为用户原件；OCR/终态后按明确策略删除字节，同时保留必要元数据、候选、确认、Observation、总结与审计链。若要求字节绝不离开设备，需另立端侧 OCR 项目，不能把远程 LLM 描述成本地处理。
6. seal 和每次可恢复重试都必须写入持久 `pending_since/deadline`，直接唤醒 OCR 并保留 beat 扫描兜底；读取与 sweep 共用 reconciler，worker/beat 缺席、对象存储错误和过期 lease 都必须在有界时间内形成可恢复终态，不能无限 `recognizing`。
7. 报告解析完成与评分可用性必须分离；评分缺输入是终态 `unavailable/partial_failed`，不能让报告继续显示处理中。
8. 生产部署必须以同一 revision 同时验证 API、worker、beat、Alembic head、Redis、对象存储和 OCR provider；任一角色缺失即部署失败。
9. 文件类型必须由真实文件签名决定。HEIC/HEIF 原件逐字节保留不变，只能另建方向已校正的 PNG 处理副本供质量检查与远程视觉 OCR；不得用转码结果覆盖本机或服务端登记的原始摘要。
10. 视觉 provider 的静态端点/模型能力必须在 API startup 失败关闭；worker 的实际 provider 构造必须发生在持久 claim 内，构造失败走独立、最多五次的基础设施预算并补回内容 attempt，最终落为可重新上传的 `report_ocr_provider_unavailable`。Kimi 专属请求参数不得发送给 OpenAI 端点。
11. 服务器临时副本只有在客户端以 workflow、账号、主体、请求版本、页数和聚合摘要提交本机绑定证明，且服务器验证完全一致后才可进入删除资格。通用上传重放不得冒充该证明；客户端生成证明前必须重新读取每页真实字节并校验摘要，不能只看文件大小或 manifest。
12. 所有向用户声明 `reupload_report` 的技术失败必须和精确同字节重传 allowlist 共用一个策略注册表；同一原件重传必须重新绑定原 workflow、重置 pending deadline 并再次唤醒 OCR，不能退化为 duplicate/sealed 死路。

## 同类入口与状态扫描

- iOS 当前三个入口：健康报告底部上传、聊天附件、系统“打开方式”；相机、相册（最多九张）和文件选择均纳入同一 intake/store 合同。
- 报告首页最新记录、三条历史、全部历史、报告解读页和旧原件查看器均纳入本地优先/账号隔离检查。
- 服务端覆盖 seal、OCR claim/retry/terminal、确认、评分 partial failure、对象清理、历史/trace、旧卡住 workflow 恢复。
- 文件边界覆盖扩展名/MIME 与真实签名不一致、HEIC/HEIF 方向处理、JPEG 直通、源摘要不变和旧任务读取时兼容转码。
- provider 边界覆盖 Moonshot/Kimi、OpenAI 官方端点、未知端点、纯文本模型、缺少密钥、startup 静态失败、claim 内实际构造失败和 Kimi 专属参数隔离。
- provider/调度边界继续覆盖 claim 内构造失败、独立 infra 重试耗尽、worker/beat 完全缺失、旧 pending 行首次补写 deadline，以及 stalled/provider/storage/retry-exhausted 四类精确同字节恢复。
- Dashboard 内容状态覆盖 loading、成功空列表、首次读取失败和已有报告刷新失败；workflow 状态覆盖 processing、awaiting、committing、completed、failed 与未知未来值。共享状态机保证失败不落入空态，`committing` 显示“确认完成 · 入库中”。
- Release 解读页扫描画像候选、评分、随访、事件和上传失败弹窗；页面只消费共享白名单展示模型，恶意 fact key、对象/数组、未知方向、`processing`、evidence、missing inputs 和 failure code 均失败关闭为用户文案。
- Android 不在本次授权范围，不修改。

## 回归与验证计划

- iOS：先写会在旧实现失败的本地原件仓库、上传前持久化、重启恢复、账号隔离、损坏检测、离线零网络、用户详情隐藏技术追踪、失败状态不冒充解析中的命名测试。
- 后端：补任务级存储/provider 配置失败、未领取持久 deadline、seal 直接唤醒并由 sweep/读取兜底、陈旧 recognizing 对账、评分 partial failure 终态、原件临时副本清理、失败恢复动作与精确重传一致性和部署同版本角色检查。
- 运行 iOS focused XCTest 并保存 `.xcresult`，运行后端 focused pytest、iOS `fast`，稳定后只运行一次 `impacted`。
- 生产只在本地实现与门禁通过后通过受控脚本部署；部署后只读核验角色、版本、迁移和健康状态，再用一份脱敏测试报告验证 upload → OCR → 待确认/完成链路。现有 workflow #5 若服务器字节已经不可读，数据库 SHA 无法还原原件，必须由用户重新选择同一原件恢复。

## 已完成实现与证据

- iOS 已新增 Application Support 原件仓库。上传和补页发网前先原子落盘，按账号 scope 与数字 subject 分区，禁用 iCloud 备份并应用文件保护；seal 后用可恢复 journal 把 workflow 绑定到本机 manifest。
- 最新报告、历史报告和报告解读页优先列出本机页；打开单页时才加载并复核大小与 SHA-256。Release 页面不再暴露 workflow、asset、SHA、候选与 Observation 技术追踪。
- 本机绑定 ACK 会逐页重读并重算摘要。同大小内容篡改回归 `testDashboardRejectsSameSizeTamperedLocalOriginalBeforeServerAcknowledgement` 已在 `/tmp/xjie-report-tamper-focused-20260801a.xcresult` 通过 `1/1`。
- 后端按文件签名识别伪装成 PNG 的 HEIC，保留源字节与源摘要，另生成方向已校正的 PNG 供质量检查/OCR；真实现场样本已在 linux/amd64、断网、只读挂载环境完成解码，前后原摘要不变。
- 报告视觉静态配置已按端点家族与模型能力在 API startup 失败关闭；worker 的实际 provider 构造在持久 claim 内执行并有界写回。使用非医疗、合成 HEIC 夹具完成一次真实 `kimi-k2.5` 结构化视觉请求，结果为 `provider_vision_smoke=ok`，该证据只证明 provider/图片输入可达，不证明真实医疗报告识别质量。
- iOS `HealthReportCompletionTests` 在 iPhone 17 Pro Simulator 最终通过 `40/40`、零失败/零跳过，证据为 `/tmp/xjie-health-report-completion-final3-20260801.xcresult`；新增 `testReportInterpretationReleaseRenderingOmitsInternalSchemaKeysAndRawCodes` 同时覆盖恶意 payload、真实页面 Release 源码投影和上传失败码白名单。旧实现红测 `/tmp/xjie-report-interpretation-release-red2-20260801.xcresult` 命中六条泄露路径，最终 focused `/tmp/xjie-report-interpretation-failure-presentation-20260801.xcresult` 为 `1/1`。
- Release Simulator arm64 构建 `/tmp/xjie-report-interpretation-release-build2-20260801.xcresult` 已 `BUILD SUCCEEDED`，证明条件编译后的实际发布分支可构建。
- 报告端到端 UI `testReportReviewRequiresFieldAndReportConfirmationThenShowsScorePending` 在当前产品树通过 `1/1`，证据为 `/tmp/xjie-report-ui-focused-final-20260801.xcresult`；它正向要求“识别完成 · 待确认”，并反向拒绝旧版“已入库 · 解析中”。第一次 strict 的唯一 UI 红灯已证实是测试断言过期，不是产品状态回退。
- 后端 `backend_health` 精确受影响集通过 `144/144`；终审新增 pending deadline、provider 有界失败与 stalled/provider 精确重传后，相邻报告测试 `73/73` 通过，最终全后端精确清单 `/tmp/xjie-backend-full-final2-20260801.xml` 为 `395/395`（392 passed、3 个固定允许的 integration skip）。
- 变更文件 Ruff、`docker compose config --quiet`、regression guard、fast gate 和 `git diff --check` 已通过；tools 精确门禁为 `83/83`、零失败/零跳过。最终 `/usr/bin/python3 -I tools/run_regression_gate.py impacted --strict` exit `0`：backend 精确 `395/395`、tools `83/83`、Unit `/tmp/xjie-quality-unit.xcresult` 精确 `237/237`、full UI `/tmp/xjie-quality-ui.xcresult` 精确 `10/10`、small UI `/tmp/xjie-quality-ui-small.xcresult` 精确 `2/2`，并通过设备 Release Archive `/tmp/xjie-quality-release.xcarchive`、bundle 和最终 diff 检查；输出 `IMPACTED REGRESSION GATE: PASSED; NOT RELEASE EVIDENCE`。

## 证据边界

- 数据库 asset/SHA 只能证明元数据已入库，不能证明对象字节可读、LLM 被调用或报告完成。
- 确定性测试证明状态、账号和失败边界，不证明真实视觉模型质量。
- 模拟器不能代替 TestFlight 真机文件选择、相册权限和后台行为核验。
- 本地实现通过和真实 provider 合成夹具通过，均不能证明当前生产已经部署 API、worker、beat、Redis、加密对象存储或正确模型；本轮未执行生产部署、Git push 或 TestFlight 发布。
