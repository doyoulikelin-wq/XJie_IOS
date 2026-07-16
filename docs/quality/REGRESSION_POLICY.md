# XJie iOS 防回归开发与发布制度

生效日期：2026-07-13
适用范围：iOS XAGE 产品、仓库内生产后端、数据库迁移、CI 与 TestFlight 发布；代码交付分支统一为 `main`

## 零、为什么修好后还会再犯

过去不少修改只处理当前可见症状，没有把“以后都必须成立”的规则放进共享实现和机器门禁；聊天或文档里的提醒不会让编译器、测试和发布脚本自动拒绝旧错误。与此同时，`XAgeMainView` 跨域耦合、UI 测试依赖公网/系统时序、CI 曾漏跑 XAGE 或只看命令退出码，都会让一次局部修改重新打开旧入口。以后不再把“这次改对了”当完成，唯一闭环是根因、同类扫描、永久契约、命名回归、真实执行结果和证据全部同时成立。

## 一、唯一完成定义

修复完成不是“当前页面看起来好了”，而是：

> 根因确认 + 同类入口扫描 + 永久约束 + 命名回归测试 + 受影响/全量门禁通过 + 证据落档。

任一当前阶段的必需项未执行、失败、被跳过或没有证据时，不得说该阶段“已完成”。完整自动化、官方 `main`、唯一签名包和敏感内容扫描全部通过后，可以先上传仅限内部测试的 TestFlight 候选；五项真机/受控签核未基于该 TestFlight 安装包全部通过前，不得称为最终合格、正式发布或对外推广。

同一代码出现一次红、一次绿，说明存在未受控时序或环境边界，不说明第一次可以作废。失败证据必须保留；在完成可解释复现、根因、同类扫描、永久约束和新提交的完整门禁前，“重跑变绿”仍按失败处理。

### 门禁按阶段执行，不在编辑循环重复全量工作

- `fast` 是日常开发反馈：先执行静态契约和 tracked/untracked 空白检查，让廉价失败早于 backend/Xcode；随后运行真实 change impact 选出的 Unit、focused backend 或 backend full，并在末尾再次检查空白和工作树漂移。它主动排除完整 UI、小屏 UI 和设备 Archive。命令为 `/usr/bin/python3 -I tools/run_regression_gate.py fast`，输出固定标明 `NOT RELEASE EVIDENCE`。
- `impacted` 是实现稳定后、提交 PR 前运行一次的受影响候选门禁。它可以包含完整 UI、小屏和无签名设备 Archive，但不应在每一轮小改动后重复执行。若 backend full 已被选中，它覆盖 AI/Health focused 子集，runner 必须删除重复执行。
- `internal-testflight` / `assert-internal-testflight` 只负责冻结后的 main exact-SHA 内部 TestFlight 上传候选：保留全量精确测试、必要的 PG16 集成结果、设备 Archive、同一 IPA 签名与敏感内容校验，生成独立 schema `1` evidence，不接收 `manual_signoffs`，也不表示最终合格。Apple 接受上传后由 `qualify-testflight` 校验 TestFlight 来源、回执绑定的五项 `post_upload_signoffs`。既有 `release` / `assert-release` 仍是独立 schema `5` 最终门禁，仍须 `manual_signoffs`；任何 internal evidence 都不能冒充或转换成 final evidence。

`fast` 和 `impacted` 都不能生成、替代或冒充发布 evidence。Git hooks 只检查不可变 snapshot 的静态契约；`regression_guard.py check` 已包含 registry validation，禁止再串一个重复的 standalone `validate`。因此日常修改可以快速反馈，而发布安全边界没有下放或删除。

## 二、修改前

1. 明确授权范围：iOS XAGE 线程只改 iOS；共享 API/schema 必须保持另一端兼容，不能借防回归擅自扩范围。
2. 搜索 `memory/resolved_issues.md`、`memory/known_risks.md`、UI memory、`quality/regression_contracts.json`、相关代码与测试。
3. 先复现问题，写出最小步骤、实际结果和期望结果。
4. 区分“表面症状”和“真实根因”。没有根因时先诊断，不以坐标、延时、单个 if 或单页特判冒充修复。
5. 更新 `quality/change_impact.json`：影响域、同类入口、契约 ID、回归测试、人工矩阵和剩余风险必须完整。

## 三、编码规则

- 先增加能在旧行为上失败的测试，再修生产代码；若只能扩展现有测试，必须增加能识别本次回归的断言或真实交互。
- 同一规则优先进入共享组件、单一 presentation route、状态机、API/schema 约束或统一测试辅助层。
- 不允许只修用户指出的那个入口；必须搜索同类 sheet、表单、键盘、返回、账号、数据源和 AI 路由。
- 无法自动化时必须停下说明原因，取得用户明确批准后才能使用人工例外；人工例外必须有可重复脚本、截图/录屏和未覆盖风险。
- 不允许用 `try?`、空 catch、`|| true`、把失败命令放进会继续成功的 `&&` 链、测试内吞错误、关闭错误弹窗等方式把失败变成成功。

## 四、永久契约

机器可读契约位于 `quality/regression_contracts.json`。它同时校验契约测试锚点、影响域、XAGE 架构上限和发布命令。每一个 `behavior_domain` 都必须声明顺序固定的 `required_contract_ids`，并与 guard 内代码侧固定映射精确相等；行为域的 required contracts 与每个 contract 的 `domains` 必须双向精确一致，禁止把新域临时挂到无关旧契约、额外挂域或留下未归属契约。每个 contract 的完整规范化定义（ID、domains、不变量和有序测试锚点）还必须匹配代码侧固定 SHA-256，禁止保留 ID 却把不变量换短、锚点泛化或在契约之间互换证据。整个规范化 registry 也必须匹配固定摘要，锁住 behavior domain 的 source/test/meaningful/command 映射、conservative overrides、architecture limits、commands 和 release gate，不能在契约身份不变时从旁路缩减分类或执行。`change_impact.json` 必须包含全部 primary affected domains 的所有 required contracts，任意缺失都失败。新增或正当修改行为域/契约/映射必须同时显式更新注册表、代码侧固定映射/摘要和既有命名负向回归，不能等到某个跨多提交 PR 才偶然发现缺口。

- `BRANCH-CANONICAL-001`：`main` 是唯一开发基线、PR 目标、CI push/PR 目标、部署来源和发布候选；官方默认分支必须为 `main`。`XAGE` 仅保留为历史可追溯分支，继续严格保护并启用 `lock_branch=true`、`allow_fork_syncing=false`，不能再接收 PR、push、部署或发布。候选相关门禁只能绑定 main；保护回读必须同时证明 main 未锁定、XAGE 已锁定。

生产部署禁止直接运行仓库脚本或操作员直接调用内部 deployer，只允许从 root 预装的 `/usr/local/sbin/xjie-production-launch` 启动；`/usr/local/sbin/xjie-production-deploy` 是它降权且受看门狗管理的内部子进程。七文件事务 bundle 按固定顺序包含 launcher、deployer、container spec、deploy guard、release gate、expected Python inventory 和最后替换的 installer；三个 `/usr/local/sbin` 文件必须是 `root:root 0555` 的单链接普通文件，四个 `/usr/local/libexec/xjie-production-deploy` 文件必须是 `root:root 0444`，所有父目录由 root 控制且不可由 group/other 写。候选 exact-SHA 中的七个源文件必须逐字节等于该独立安装 bundle；bundle 变更只能在生产健康、无活动 journal、已取得全局锁时由 root 另行批准并原子安装，不能由它正在批准的候选自更新。Launcher 只通过匿名 stdin pipe 接收一个 NUL 结尾 GitHub token，它不得进入 argv、环境、文件或日志；内部 deployer 使用 `/bin/bash -p` 阻断 `BASH_ENV`/继承函数，固定 PATH、本机 Docker socket、HTTPS 官方 origin 与系统 Git，清除 Git exec/config/object/SSH/proxy 重定向。它先用已安装 release gate 回读 official main tip、merged PR、exact push `quality-gate` 及 main/XAGE 两套实时保护；在这些资格全部成立以前，仓库 Python 不得执行，生产 env 不得打开，orphan 不得删除。通过后才激活并 `git archive EXPECTED_SHA`、整批回收 orphan、快照 owner-only env 和构建镜像。运行目录固定为 owner-only `/dev/shm` tmpfs；`docker build --iidfile` 捕获的 immutable image ID 是后续测试、扫描、只读数据库核对和切换的唯一镜像身份，tag 只供定位。完整安装与演练步骤见 `docs/operations/PRODUCTION_DEPLOYMENT.md`。

所有候选、backend test、Alembic 检查、数据库结构检查和 old/candidate schema probe 容器必须在创建时原子携带 schema/scope/branch/revision/run-id/role/original-name/image-id/phase 九项生命周期标签。在线资格通过后，cleanup 先对 scope 内全部对象做一次完整 inspect/plan，再按所有计划 full ID 一次性做第二批 inspect/plan；两批的名称、container/image ID、revision、run/role、完整命令、环境类别、stdin、network/port、mount、restart、capability、security option、readonly/tmpfs 等投影及摘要必须完全一致，任何对象异常都发生在首次删除之前。运行中的 official 是唯一保护对象；上次成功产生的 stopped backup 只保留一个发布周期并由下一次合格部署清理，one-shot 冒用 official/backup 名称直接失败。Docker 没有跨多个容器的删除事务，因此随后阶段按不可复用 full ID 幂等删除，已由 `--rm` 收敛的对象视为完成，异常必须报告可能的部分进度，文档不得再声称删除本身具备事务原子性。

生产容器的非秘密配置只有 `backend/deploy/production_container.json` 一个真相源；helper 与独立字面量测试固定容器名、镜像仓库、env 路径、`127.0.0.1:8000:8000` loopback 端口、extra host、restart policy 和内外健康 URL。候选必须保留新镜像的 Cmd/Entrypoint/User/WorkingDir/Env 默认值，完整 HostConfig、网络拓扑与 runtime-only Config 不得静默丢失；旧 `0.0.0.0` 端口只允许单向收紧到 loopback。`docker image save` 的 owner-only 归档必须绑定候选 image ID，并流式扫描全部历史 layer，包括后续层已经删除的字节；路径穿越、危险 link/special member、重复/超限成员、私钥/SQLite 结构、生产秘密值以及 image `Config.Env` 与 runtime-only key 重名都失败，公开 CA PEM 不因扩展名被误报。

自动部署当前只允许 **no-delta**：同一只读、无网络 probe 分别在运行 image 与候选 image 中导入全部 `app.models`、规范化 53 张 SQLAlchemy model 表/列/约束/索引，并按字节 SHA-256 验证唯一线性 Alembic 历史；两份 manifest 必须完全相同，生产 `alembic current` 必须精确等于候选唯一 `head`。随后候选 image 必须在 PostgreSQL `readonly` 事务中只通过 SQLAlchemy Inspector 反射生产库，精确核对候选模型的全部表、列、PostgreSQL 编译类型、可空性和主键，回滚事务后只输出与候选 manifest 绑定的摘要；缺表、缺/多列、类型、nullable、主键或摘要差异均阻断切流。应用启动禁止 `create_all` 和手写 schema DDL，部署脚本也禁止 `alembic upgrade`。任何历史 migration 改写、新 revision 或仅改 model 未写 migration 的变化都先阻断自动部署；第一笔真实 schema delta 前必须建立可重建的受信 PostgreSQL baseline、expand/contract 分类、受影响旧写路径 CRUD probe、备份/恢复和 migration-specific evidence，不能用普通容器 rollback 冒充数据库回滚。

构建前、数据库只读核对前、切流前和 30 秒稳定窗口后都要重新回读远端候选资格。stop/rename/start 每一步写入 owner-only、fsync 的 schema-2 持久 cutover journal，并绑定写入它的完整 trusted-bundle SHA-256；bundle 不匹配时必须恢复精确旧 bundle，不能猜版本兼容。普通异常由 EXIT trap 回滚；SIGKILL/主机掉电后的下一次运行只使用 root bundle，把官方名、backup 名和 candidate 名的完整 inspect 交给纯 recovery planner，一次性验证全部 ID/image/running 拓扑。离线恢复不得 `rm`：若候选占据正式名，只能先停止并改回确定的 quarantine 名，再恢复旧 backup；具名候选保持 stopped，待 GitHub 在线资格重新成立后才由 orphan cleanup 删除。不存在精确旧实例或 backup 损坏时计划必须为空，禁止先删后猜。新容器只有在 ID/image/revision 不变、`RestartCount=0`、容器内与公网健康连续通过、无致命启动日志且最终远端回读仍通过后，才清除 journal 并提交。

当前关键契约包括：

- `UX-NAV-001`：页面和 sheet 的关闭语义一致。
- `UX-KEYBOARD-001`：点击、下拉、菜单、切页和离开均正确释放焦点；聊天输入框保持 1–5 行，Return 只插入换行且不发送、不收键盘，纸飞机是唯一的草稿发送动作；中文输入不回写旧草稿。
- `UX-CHAT-QUIESCENCE-001`：连续消息首次溢出时不得排队/叠加自动滚动动画，XAGE 与旧聊天都必须保留唯一且顺序固定的底部 anchor，并只通过同步禁动画的 `ChatAutoScroll` 定位；发送必须先同步捕获不可变草稿、失焦并显式关闭键盘，之后才能启动异步任务，快捷问题、重试、同意后续、报告上传后续和全部相邻发送入口也不得直接或通过别名绕过。thinking 与 upload 必须共用 `ChatProgressIndicator`，只有明确的 Debug UI automation 使用静态图标，普通 Debug/Release 使用正常 `ProgressView`；除这一视觉状态外，Release 与 UI automation 的 anchor、消息/Markdown consumer、辅助功能树、发送 wiring、生命周期和终态不得分叉。视觉不变的普通文本只能暴露纯文本辅助功能树，当前 inline renderer 支持的 Markdown 必须保留原视觉格式和去标记阅读顺序，且每个链接仍须暴露真实可激活、可命中的 `Link`；最终唯一收口到 idle、无 thinking、精确消息数、latest assistant 和 focus false。既有 policy test 必须实际构造并拒绝当前 80 个对抗变异，锁定 anchor、全部发送入口、真实 consumer、完整根消费者、条件编译块、共享 UI 等待/网络审计、完整终态、换行编辑与 Link 动作。
- `UX-ACCESSIBILITY-001`：真实命中区至少 44pt，父子可访问语义不冲突。
- `UX-FORM-001`：干净/脏表单、提交锁和危险操作确认一致。
- `DATA-CARD-001`：数据卡片选择和顺序按账号持久化，同步不恢复已移出卡片。
- `CHAT-SESSION-001`：幂等重试和迟到回答隔离。
- `AI-SUBJECT-001`：本人和家属主体绝不串用数据。
- `AI-SAFETY-001`：急症/确定性风险优先，不给危险或绝对保证。
- `AI-EVIDENCE-001`：正文、引用、重放和历史快照一致。
- `HEALTH-REGISTRY-001`：目录、读取、上传和趋势共用稳定 registry。
- `HEALTH-ACCOUNT-001`：健康同步账号隔离、来源幂等、手工数据保护。
- `BACKEND-CORE-001`：后端生产逻辑、依赖、容器、部署和迁移变更必须运行精确 backend full、guard 与 diff；AI/Health 聚焦子集不能替代完整门禁，空库/遗留库迁移和账号生命周期不得退化。
- `TEST-DETERMINISM-001`：CI UI 测试不得依赖公网、生产账号或真实模型时序；外部交互使用仅 Debug 且显式启用的确定性传输。
- `TEST-SUITE-INTEGRITY-001`：精确运行清单、参数化 case 和 skip 状态只能显式增强；删除、改名、缩减或明显弱化测试必须失败。
- `PROCESS-GATE-001`：行为修改必须伴随影响清单和有意义的测试变更。

新增一种历史错误时，必须新增或扩展相应契约；不能只在聊天或 devlog 中写一句提醒。

## 五、XAGE Swift 源文件架构规则

`XAgeMainView.swift` 的 10,305 行单体已按职责拆成七个受管文件：`XAgeContracts`、`XAgeMainView`、`XAgeDataDashboard`、`XAgeConversation`、`XAgeHealthspan`、`XAgeSettings` 和 `XAgeComponents`。`quality/swift_source_manifest.json` 是这个源文件集合、顺序、角色、影响域与上限的唯一真相源：

- Home 目录下的物理 `XAge*.swift` 全集必须与 manifest 精确相等，顺序不得漂移，且每项必须在 app target 的 PBX Sources phase 中恰好编译一次。
- 每个角色都有独立 logical-line cap；七文件的非 import/非空行聚合上限固定为 9,521，不能靠横向新建文件绕过单文件预算。
- struct/enum、sheet、full-screen cover、alert、固定延时 presentation、静默 API 失败与旧路由禁入都按整个 manifest 聚合校验，不再绑定某一文件。
- 新职责优先放入已有对应角色；确需增加角色时，必须同时审查 manifest、影响域、PBX 编译归属、聚合预算与负向变异测试，不得只在工程中加文件。
- 拆分不得改变 UI、交互、算法、网络协议或构建号；聊天静态策略必须按 manifest 顺序重建等价源码，并保留原有 UI/键盘/辅助功能回归。

`XAgeDataDashboard.swift` 仍是七个角色中最大的文件；它受 7,000 logical-line cap 约束，后续应在业务边界明确时继续细分，但不能为追求行数而破坏共享状态与交互一致性。

## 六、验证矩阵

编辑循环至少运行新增/修改的回归测试和 `fast`；实现稳定后再运行影响域候选门禁和同类相邻路径。UI/交互候选还要按本次影响覆盖：

- 空、加载、成功、失败、重试、长内容和重启恢复；
- 点空白、明显纵向下拉、纸飞机发送、切页、返回、打开菜单/附件/历史时的键盘和焦点；
- 单行到最大行数、Return 换行且不发送、完整多行草稿发送、中文输入法；第三方输入法不能实测时记录真机风险；
- 页面、sheet、干净/脏表单、忙碌态和二次进入；
- 横滑/纵滑方向冲突和首尾边界；
- 44pt 命中、VoiceOver 语义、大字号、小屏和安全区；
- 前后截图或可重复几何/快照断言。

AI 修改必须跑主体隔离、急症/特殊人群、数据证据、引用、幂等、历史回载和内部字段防泄漏。Health 修改必须跑 registry、权限/无样本/部分成功/失败状态、账号切换、迟到回调、来源身份、手工数据保护和迁移。

## 七、对现有测试结论的边界

`XAgeHighIntensityContextUITests` 的全部测试只能继承 `XAgeUITestCase`，通过同一个 application factory 启动，并显式启用仅 Debug 可用的 `XJIE_UI_TEST_STUB_NETWORK`。共享基类独占 app 的创建、启动、重启与终止；源码范围内 `XCUIApplication` 类型/构造和 `.launch` / `.terminate` 的 token 数量是精确契约，`.init`、上下文构造、方法引用、嵌套 helper 或基类外 lifecycle 调用都失败。每次 launch 都由 teardown 自动读取运行时审计 `xjie.uiTest.networkAudit`，断言至少拦截过一个请求且 `unhandled=0`，因此不能靠把一次审计调用集中到少数测试来伪造覆盖。账号主体、功能开关、对话历史、用药、本人资料和家庭接口返回确定性 fixture；受控 `APIService` 传输中的未知请求无论 URL scheme 都会进入 fail-closed stub，不能用非 HTTP(S) scheme 绕过。审计计数在响应交付前同步发布，测试代码不得靠关闭网络错误弹窗继续执行。测试模式同时关闭所有通知中心入口、HealthKit 和不受控的 `NWPathMonitor`。

其中 12 个 prompt 另外显式启用 `XJIE_UI_TEST_STUB_CHAT`。每一条都断言键盘关闭、输入框清空、原始用户消息出现、对应助手回显出现且没有错误弹窗。因此它能证明客户端输入、发送和消息呈现壳层，但不能证明真实服务端返回了正确 AI 回答。

该流程还必须保留同一会话的连续增长，不得拆成每条一个新会话来规避溢出；每轮先校验 App 自己暴露的 `phase/messages/latest/focused` 终态，再查询键盘和正文。iPhone SE 小屏用例必须真实发送现有长问题，覆盖单轮即溢出的边界。自动底部定位只能经 `ChatAutoScroll` 的显式 `SwiftUI` 禁动画 transaction。Markdown 候选必须是系统 inline parser 语义的保守超集，再用实际字符/属性判断视觉语义：`A * B * C`、inline 模式下不变的列表等仍走 `Text(verbatim:)`，粗体、单行/跨行强调、删除线、行内代码、转义、实体、链接以及 CR/CRLF/NUL 规范化保留原视觉效果；无链接富文本以一个解析后去标记 `Text` 替换辅助功能树，含链接富文本按真实链接边界分段并使用 `Link(destination:)` + `.isLink` 保留角色与激活动作。工具门禁固定全仓库 SwiftUI/UIKit 滚动 API、`UIScrollView`/`ScrollPosition`/`ScrollViewProxy`/`ChatAutoScroll`、transaction 和 `onChange` 标识符清单，精确锁定状态监听、helper、发送同步退键盘、生命周期真实值与 wiring、自动化静态进度、键盘安装器和 Markdown replacement/link tree；负向变异必须证明输入栏之后、相邻结构体、专用 overload、同名函数劫持、新 bridge、独立文件、硬编码状态、删除 dismiss、恢复测试动画、`accessibilityChildren` 重复树或移除 link action 都会失败。确定性 UI 必须发送真实 Markdown 链接并查询 SwiftUI `Link` 在 XCTest 中暴露的可命中 action control（当前平台类型为 `Button`）；这证明模拟器 AX 中存在可操作入口，不冒充真机 VoiceOver rotor/朗读/双击签核。禁止靠保留一个未使用的正确 helper、增加 timeout、关闭 XCTest idle 或只重跑来掩盖 AX 快照故障。

以后：

- UI 壳层结论可以引用该测试；
- AI 内容、安全、主体、引用或路由结论必须引用确定性 Swift/Python 测试，或引用真正断言最终助手回答的受控端到端评测；
- 不得再把“输入过 12 个问题”描述为“验证了 12 个 AI 回答”。
- 公网 SSE 延迟、断网、重连和超时属于独立网络集成测试，不得重新塞回每次 CI UI 门禁制造不确定性。
- 生产代码只能在 `APIService.trustedSession` 保留唯一一个由 `makeSessionConfiguration()` 创建的 `URLSession`；APIService 内请求只能显式使用 `self.trustedSession`，外部只能显式使用 `APIService.shared.trustedSession`，UI 测试自身禁止发请求。门禁先移除 Swift 注释/普通字符串但保留可执行插值，再统一反引号标识符，精确约束 `APIService` / `trustedSession` token、构造和请求调用；第二构造/别名、推断会话、上下文 `.shared`、简单或 tuple/pattern shadow、字符串插值/raw 插值/bare regex/转义标识符绕过，`Data`/`NSData`/`String(contentsOf:)`、`AsyncImage`、WebKit、Network/CFNetwork/POSIX API 及函数别名都会被阻断。本地 URL 文件读取只能使用先检查 `url.isFileURL` 的 `LocalFileDataLoader`。这是对受控源码入口的 fail-closed 约束，不是 OS 级防火墙；新增动态调用或新的底层网络框架时，必须先扩展门禁和负例，不能只用 `intercepted>0` 声称整个进程绝无外联。
- `NWPathMonitor`、`HKHealthStore` 和 `UNUserNotificationCenter.current` 也使用全源精确 token/构造身份，只允许分别出现在 `NetworkMonitor`、可注入的 `AppleHealthSyncViewModel` 和 `PushNotificationManager` 的 UI-safe factory。直接 `.init`、上下文 `.init`、构造器/`current` 方法引用或复制第二个 owner 均失败；因此测试模式的 no-op 不是靠每个调用点自觉，而是由唯一系统入口和 token 数共同约束。
- `xcodebuild test` 返回 0 不代表执行过正确测试。Unit、完整 UI、小屏 UI 和 CI 都必须生成 `.xcresult`，由 `tools/validate_xcresult.py` 对照受版本控制的精确清单校验：Unit 恰好 181 项、完整 UI 恰好 6 项、Unit/完整 UI 并集恰好 187 项，小屏专项恰好执行那 2 个已登记用例；任何缺失、额外、重复、改名、skip、fail 或 expected-failure 都失败。小屏结果还必须证明设备模型是 iPhone SE（第 3 代）。
- Python 同样使用运行时精确清单，而不是最低数量：backend full 恰好 331 个 ID，tools 恰好 80 个 ID。tools 不允许 skip；backend 只允许下文列出的 3 个固定 integration placeholder，因此通过结论必须写成 `328 passed + 3 skipped`。

## 八、执行命令

```bash
cd /Users/linlin/Desktop/X/XJie_IOS

# 契约、锚点和架构上限
/usr/bin/python3 -I tools/regression_guard.py validate

# 提交前检查当前修改
/usr/bin/python3 -I tools/regression_guard.py check --working

# 按 change_impact.json 运行受影响门禁
/usr/bin/python3 -I tools/run_regression_gate.py impacted

# 内部 TestFlight 候选：PR 合并且官方 main 精确 SHA 的 push CI 变绿后，
# 用受信且隔离的 Apple/Xcode Python 运行独立上传前门禁
/usr/bin/python3 -I tools/run_regression_gate.py internal-testflight

# archive/export 前再次确认结果仍属于当前 HEAD
/usr/bin/python3 -I tools/run_regression_gate.py assert-internal-testflight

# 唯一允许的归档/上传入口；脚本会在 archive 前、archive 验证后、distribution IPA 后
# 共三次调用 assert-internal-testflight
scripts/release_testflight.sh --archive-only
scripts/release_testflight.sh --upload

# future 上传成功回执：.quality/internal_testflight_upload_receipts/<version>-<build>.json
# 每次网络上传前会保留 attempt tombstone：
# .quality/internal_testflight_upload_attempts/<version>-<build>.json
# Apple 接受上传后：从 TestFlight 安装同一 build 并收集五项签核
mkdir -p .quality/evidence
cp quality/testflight_signoffs.example.json .quality/testflight_signoffs.json
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git rev-parse 'HEAD:quality/regression_contracts.json'
shasum -a 256 <脱敏截图或录屏文件>
/usr/bin/python3 -I tools/run_regression_gate.py qualify-testflight
# 资格结果：.quality/testflight_qualifications/<version>-<build>.json

# 独立的 schema 5 最终发布门禁仍需 registry manual_signoffs；这不是同一 build 在
# qualify-testflight 后自动执行的下一步，也不得使用 internal evidence 替代
cp quality/release_signoffs.example.json .quality/release_signoffs.json
/usr/bin/python3 -I tools/run_regression_gate.py release
/usr/bin/python3 -I tools/run_regression_gate.py assert-release
```

本地 `.githooks/pre-commit` 和 `.githooks/pre-push` 会执行静态门禁，并覆盖新增、修改、删除、复制以及重命名前后的路径；working-tree 差异还必须同时检查 tracked 和 untracked 普通文件的空白错误。仓库根、三个 source root、`.xcodeproj/project.pbxproj`、共享 scheme 以及这些固定输入的每一层祖先都必须是实际目录/普通文件；source root 下所有 Swift、Info.plist、entitlements、privacy、asset 和 localization 文件也逐项 `lstat`，任何 ancestor/directory/file symlink 都 fail closed。未改内容的测试复制/重命名、只有测试函数声明、skip 或恒真断言都不算有效测试变更。CI、hooks、guard、xcresult validator、发布脚本、签核模板、发布制度和契约注册表本身属于 `quality_process_gate` 行为域，削弱它们同样必须更新影响清单和工具回归测试。提交差异检查对 merge commit 使用 first-parent diff，不能再用空的 `git show --format=` 假绿。push 阶段不要求尚不可能存在的上传回执或 TestFlight 真机证据；候选 SHA 通过 PR 合并且远端 push CI 变绿后，`internal-testflight`/`assert-internal-testflight` 只生成并校验 schema `1` 上传 evidence。`release`/`assert-release` 的 schema `5` final evidence 仍须完整 `manual_signoffs`，两条 evidence 链禁止混用。禁止 `--no-verify`。

Git 调用 hook 时可能导出相对 `GIT_INDEX_FILE` 等 repository-local 环境；hook 只能在创建 immutable candidate 前保留真实 index，随后必须清除 `git rev-parse --local-env-vars` 的全部变量，再进行 linked-worktree add/remove 和候选树验证，并由 tools 测试真实执行这一环境形态。

## 九、CI 与发布

GitHub Actions 必须无路径过滤地只监听 `main` 的 push/pull request，覆盖 iOS、backend、quality、gate 工具、完整 iOS UI 套件、固定 iPhone SE（第 3 代）的双用例小屏套件和 Release device archive；不得监听或接受 `XAGE`，也不得用 `workflow_dispatch` 绕开多提交比较。不得使用 `|| true` 或把必需命令放进后续仍可成功的 `&&` 链来吞掉失败。policy 工具套件会真实执行生产发布脚本和 `/bin/zsh`，所以该 job 的唯一 runner 必须固定为 `macos-15`，不能再以 Linux 只做静态替身；其中 tools/guard Python 入口必须固定 `/usr/bin/python3 -I`，不能继承镜像 PATH 中会漂移的 Homebrew Python。backend 与最终汇总可以继续使用 Ubuntu。iOS 必须严格匹配 Unit 181、完整 UI 6、小屏 2、Unit/完整 UI 并集 187 的受控清单；Python 必须严格匹配 backend 331 和 tools 80 的运行时 ID 清单。清单变化必须显式修改当前基线和负向测试，不能用新的最低数掩盖删除、改名、参数化收缩或零执行。最终 `quality-gate` 只有在 policy、backend 和 iOS 全部验证都成功时才通过。文档、脚本或工作流单独修改也必须产生同名检查，避免 required check 缺席。

Xcode 工程边界不能靠 `project.pbxproj` 的 comment、section 名或文件名字符串判断。门禁先清除 OpenStep comment、把 quoted value 换成不可伪造 token，要求关键 dictionary key 恰好出现一次，并解析 `objects` 中每个顶层对象的 `isa`（不依赖字段顺序），阻断 duplicate-key last-value、isa-last 和隐藏 Aggregate/Shell target。三个 `PBXNativeTarget`、PBXProject targets、container proxy、target dependency、配置列表、build phases/rules/dependencies、phase 类型和 Sources 的 build-file → fileRef → group ancestry 都必须精确；磁盘 Swift 集合必须与三个 Sources phase 精确相等，framework phases 必须为空，Swift package product/reference/object、额外 Sources/shell/aggregate phase/target、重复/换绑 target/fileRef 均失败。八个 Debug/Release `XCBuildConfiguration`、四个按序 configuration lists 及 Release default、PBXProject/target config-list 绑定都固定；共享 `Xjie.xcscheme` 的 Build/Test/Launch/Profile/Archive graph 也必须精确且不允许 pre/post action、环境变量、参数或 test plan。

Release 编译设置分两层验证。静态 PBX 层禁止 source inclusion/exclusion、base xcconfig、compiler/linker injection、bridging header、Swift include、library/framework search path，以及 Release 下的 debug/testability/architecture/C/C++ flag 覆盖；归档前再把真实 `xcodebuild -showBuildSettings -json` 管道交给同一 verifier，精确验证 Release、iphoneos/arm64、SDK、wholemodule、dSYM、Info.plist、entitlements、bundle/version/build，并拒绝有效值中的 `OTHER_LDFLAGS`、bridging/include/compiler 覆盖。有效 header/library/framework search paths 只能是本次 `TARGET_BUILD_DIR` 及其 `include`，防止静态文本正确但继承/命令行结果被改写。

稳定的 iOS PR 候选以及每个发布候选都必须创建一次全新的无签名 `generic/platform=iOS` Release archive，并对其中的 device `.app` 运行 `tools/verify_release_bundle.py`；普通编辑循环不再 Archive。Simulator Release build 不能替代候选归档，因为 `targetEnvironment(simulator)` 或 SDK 条件编译可能产生不同二进制。verifier 必须确认合法 bundle、Info.plist、主可执行文件为可执行的普通非符号链接文件，并只接受 thin little-endian 64-bit arm64 `MH_EXECUTE` 与 iOS device platform 2（或旧 iPhoneOS load command）；ASCII、FAT、x86_64、dylib、Simulator、截断/畸形 Mach-O、UI 自动化、Debug 开关、测试传输标记和敏感运行时文件全部 fail closed。

仓库管理员必须将 GitHub Actions app `15368` 产生的 `quality-gate` 设为 `main` 和历史 `XAGE` 的 required check，开启 strict、管理员执行和“必须通过 PR”，PR bypass users/teams/apps 必须为空，并禁止 force-push 和删除分支。角色必须不同：官方 `default_branch=main`，main `lock_branch=false`；XAGE `lock_branch=true` 且 `allow_fork_syncing=false`。CI 不监听 XAGE 只是纵深防御，不能替代远端只读锁。当前仓库只有 owner、没有独立 reviewer，所以 approval count 固定为 0；这只能降低误操作概率，不能阻止 owner 在同一 PR 中同时削弱 workflow、gate、测试或常量并自行合并。增加真实协作者后必须升级为 1 个批准并要求最后一次 push 由他人批准，质量/发布路径还应由独立 CODEOWNERS、required workflow/ruleset 或受保护发布环境控制。此后只能使用 main-based feature branch → PR to main → merge；XAGE 不再接收任何交付。`release` 与 `assert-release` 均须实时查询固定官方仓库：官方默认分支和候选分支都为 main，main tip 等于当前 `HEAD`，该 SHA 关联一个已合并到 main 且 `merge_commit_sha == HEAD` 的 PR，`ci.yml` 的 main push run 已完成成功，对应 `quality-gate` check 由固定 GitHub Actions app 产生且链接到该 run，并且 main/XAGE 的不同锁定状态均符合要求。可变本地 `origin`、仅有本地 JSON、XAGE 运行、手动触发或其他 SHA 的绿灯无效。

`internal-testflight` 与 `assert-internal-testflight` 对上传候选执行相同的官方 main、merged PR、exact-SHA push check 和双分支保护核验；`qualify-testflight` 则同时核验 tracked pending candidate 的原始 candidate HEAD/PR/CI 以及当前 qualification HEAD/official main，不允许用 registry 后续提交替换被上传的候选身份。

内部 TestFlight 上传前先要求候选工程唯一的 `CURRENT_PROJECT_VERSION` 严格大于 `release_gate.latest_uploaded_build`，并要求不存在尚未处理的 `pending_internal_candidate`。当前 `latest_uploaded_build=18`，且 build 18 仍是 `uploaded_pending_qualification`，所以 build 18 不可再次归档/上传，build 19 虽是下一可能号码，也必须等 build 18 成功资格完成或通过受保护 registry 变更明确拒绝/退休后才能开始上传。第一阶段使用 `/usr/bin/python3 -I tools/run_regression_gate.py internal-testflight`，把候选版本/构建、官方 tip、merged PR、远端 check、两分支保护、SE 3 身份、backend 原生解释器/依赖摘要/外层 JUnit、受信 Xcode `26.3`（build `17C529`）和本地全量命令写入 `.quality/internal_testflight_gate.json`。该文件固定 schema `1`、phase `internal_testflight_upload`，不得包含 `manual_signoffs`、`external_promotion_allowed` 或任何 final claim。

`scripts/release_testflight.sh` 的两种模式都会用 `destination=export` 本地导出恰好一个 IPA，并固定三次调用 `assert-internal-testflight`：签名 archive 前、archive 与 app 验证后、实际 distribution IPA 完成全部验证后。该顺序没有“诊断”例外：build 不合格、存在 pending candidate、`internal-testflight`/`assert-internal-testflight` 未通过时，禁止签名 archive 和 `xcodebuild -exportArchive`；稳定 PR 候选所需的无签名 generic-device archive 是唯一的上传前 archive 例外。`--upload` 的认证元数据完整性在 repository/environment/release lock 与 cleanup EXIT trap 建立后先 fail closed；解包前继续逐字节绑定 ZIP local/central entry、EOCD、data descriptor、路径/类型/展开量，并扫描全包敏感文件名及 PEM/DER/PKCS#8/OpenSSH/private JWK/SQLite。安全解包后校验 distribution `.app` 的版本/构建、生产 API、arm64 iOS device Mach-O、实际签名叶证书/profile、HealthKit entitlements、IPA SHA-256 和 distribution CDHash。Snapshot 完成后会把 owner-only parent 锁成 `0500`，记录 parent 的 realpath/device/inode/nlink/mode/owner 和 IPA 的 realpath/device/inode/nlink/mode/size/hash，并在 uploader 前后复核；这能关闭正常流程或意外写入造成的路径替换，但不声称隔离能够主动 chmod、ptrace 或控制发布进程的恶意同 UID publisher。`--upload` 只把该 bounded-trust snapshot path 交给 pinned Xcode `altool`；网络调用前会先原子创建 `.quality/internal_testflight_upload_attempts/<version>-<build>.json`，该 attempt tombstone 在成功、失败或 timeout 后都保留，同一 publisher 机器禁止用同一 build 重试。Pinned Xcode 会把固定 `Running altool at path ...` banner 写到 stderr，因此 stdout JSON 与 stderr 必须分别写入两个 owner-only `0600` 临时文件：只能解析并哈希 stdout，禁止用 `2>&1` 合并，失败诊断不得回显原始输出，EXIT trap 必须删除两者。只有 stdout JSON 的 `product-errors` 恰好为空数组、`success-message` 为非空字符串、`errors` 未报告错误，且同一 IPA 最后一次身份复核通过后，才原子创建 `.quality/internal_testflight_upload_receipts/<version>-<build>.json`，写入 schema `1` receipt、exact HEAD/tree/version/build、IPA SHA-256、distribution CDHash 和相关无秘密摘要。该本地 tombstone 无法跨机器协调；Apple build 唯一性和单一授权 publisher 是仍需执行的跨机器边界。认证变量名仍仅允许既有两组，凭据值不得写入代码、文档、memory、日志或聊天。

成功上传 build `N` 后，必须通过受保护 PR 把 `latest_uploaded_build` 推进到 `N`，并把上传回执的必要身份记录为 `pending_internal_candidate`；该 pending 未成功资格完成或明确拒绝/退休前，`internal-testflight` 会阻断下一包。候选只允许面向受控内部测试员，未完成第二阶段前不得添加外部测试组、公开推广，或使用“最终合格”“正式发布”“生产可用”等表述。

第二阶段必须由测试者从 TestFlight 安装 tracked pending receipt 对应的同一 build，再按 `quality/testflight_signoffs.example.json` 填写 `.quality/testflight_signoffs.json`。顶层必须绑定 exact candidate `HEAD`/tree/registry blob、`pending_candidate_sha256`、`upload_receipt_identifier`、`installation_source=TestFlight` 和完成时间；五项 `post_upload_signoffs` 的每一项都必须为 `passed`，绑定相同 app version/build，并逐项重复同一个 `pending_candidate_sha256`、`upload_receipt_identifier` 和 `installation_source=TestFlight`。future verified upload 的 identifier 为 `altool-result-sha256:<upload_result_sha256>`，历史 build 18 为 `xcode-distribution:<distribution_identifier>`。每项还须写真实测试人、严格晚于 `uploaded_at` 的带时区 `tested_at`、环境、至少两条步骤/观察，以及 `.quality/evidence/` 下脱敏普通文件的真实 SHA-256。随后运行 `/usr/bin/python3 -I tools/run_regression_gate.py qualify-testflight`；它重新核对 pending receipt、候选 exact-SHA PR/CI/分支保护和五项签核，成功后原子写 `.quality/testflight_qualifications/<version>-<build>.json`。只有该文件明确记录 `external_promotion_allowed=true` 才允许 external promotion；这要求 future `verified_local_ipa_altool` receipt 具有有效 IPA SHA-256 与 distribution CDHash。任一项失败都必须保留证据，明确拒绝/退休 pending build，经新 main-based PR 修复并递增 build，从第一阶段重来，禁止修补、重签或重用失败 build。

既有 `/usr/bin/python3 -I tools/run_regression_gate.py release` 与 `assert-release` 不属于内部 TestFlight 上传链。最终签核必须单独从 `quality/release_signoffs.example.json` 生成 `.quality/release_signoffs.json`；这两个命令继续只接受 `.quality/release_gate.json` 的 schema `5` final evidence，并实时要求 registry `manual_signoffs`。schema `1` `.quality/internal_testflight_gate.json`、上传 receipt、`.quality/testflight_signoffs.json` 或 `.quality/testflight_qualifications/<version>-<build>.json` 都不得转换、复用或描述为 schema `5` 最终发布证据。

## 十、自动门禁的边界与当前状态

- `TEST-SUITE-INTEGRITY-001` 可以精确约束测试 ID、参数化 case、skip 和明显的断言删除/恒真替换，但静态规则无法证明任意改写后的断言仍有同等语义强度。独立 reviewer 缺失期间，这是明确的信任边界，不能声称测试体系“无法被自行削弱”。
- backend full 的 331 个运行时 ID 中，以下 3 项仍是固定 placeholder skip，原因均为 `requires dockerized postgres + redis stack`：`tests.integration.test_api_chat_mock::test_chat_mock_placeholder`、`tests.integration.test_api_glucose_import::test_glucose_import_flow_placeholder`、`tests.integration.test_api_meals_flow::test_meals_photo_flow_placeholder`。因此这轮门禁证明的是 328 个通过加 3 个受控缺口，不证明聊天 mock、血糖导入和膳食照片的真实 PostgreSQL/Redis 集成链已经覆盖。
- backend gate 会绑定 `.venv` 原生解释器、隔离 probe、`pyvenv.cfg` 和全部 site-packages 字节，并在外层删除旧 XML 后复核精确 JUnit；它消除假脚本、旧 XML 和依赖漂移造成的意外假绿，但不能宣称抵御同一 UID 主动进程在检查间竞争替换并恢复系统文件。Homebrew Python 的 framework/stdlib/dylib 也不是仓库内可复现制品。
- 最终 ZIP parser 已根据一次 build 17 的 Xcode 26.3 直接 export 字节修正 local/central extra 与 signed descriptor 解析，但该 export 违反候选顺序，不能作为合规 release 证据；下一份严格同 IPA 兼容证据只能来自 build >=19 在 `internal-testflight` 与 `assert-internal-testflight` 全部通过后由跟踪脚本生成并上传的候选。
- 截至 2026-07-14，提交 `e8a0fd5` 的本地 working-tree `impacted` 曾完整通过，但 PR #4 的 exact-SHA policy 在 Ubuntu runner 因没有 `/bin/zsh` 正确失败；backend 同 SHA 已通过。现已将 policy 固定为 `macos-15` 并加入精确 runner 回归断言，因此旧提交的本地和远端结果自动失效，当前修改树必须从头重跑并以新 SHA 的 PR/push 检查为准，不能提前写成最终全绿。
- 2026-07-14 已完成独立 bootstrap：XAGE 最终 tip `035a35ffc57cc5399d87743e809fc7cff01f7fd0` 经 PR #6 合并为 main `143686532eeb7a6468b15d53c67667ec9924dd84`，两者 tree 一致；XAGE push、PR #6 与 main push 的 exact-SHA `quality-gate` 均成功。官方默认分支现为 main；main 严格保护且 `lock_branch=false`，XAGE 保持严格保护并 `lock_branch=true`、`allow_fork_syncing=false`。后续任何制度或实现变更都只能经 main-based feature branch 的 exact-SHA PR CI 合入 main，并以合并后 main push 的独立 `quality-gate` 作最终远程证明；XAGE 不再接收任何交付。
- 最新已上传 TestFlight 是 `1.0(18)`，因此 `latest_uploaded_build=18`。它是历史 direct Xcode `destination=upload` + managed remote signing 的 `pending_internal_candidate`：Apple distribution identifier、app/build、证书与 archive/upload log 摘要已记录，但没有可恢复的本地 distribution IPA，故 `ipa_sha256` / `distribution_cdhash` 永久为 `null`，receipt identifier 固定为 `xcode-distribution:<distribution_identifier>`，`external_promotion_allowed` 永久为 `false`。build 18 只能作为带该 provenance limitation 的内部候选接受 `qualify-testflight` 检验；即使内部资格通过也不能 external promotion，更不能冒充未来严格同 IPA 上传证据。在其资格完成或通过受保护 registry 变更明确拒绝/退休前，禁止上传 build 19 或任何下一包。

## 十一、证据格式

每次解决问题都在 `memory/resolved_issues.md` 使用统一模板，并在 `development_records.json` 记录：

- 最小复现和根因；
- 永久不变量/契约 ID；
- 同类入口扫描范围；
- 新增或增强的测试名和路径；
- 执行命令、通过数量和证据；
- 未验证项、真机限制和剩余风险。

只写“已修复、测试通过”不再算有效记录。
