# XAGE 防回归开发与发布制度

生效日期：2026-07-13
适用范围：iOS XAGE、仓库内生产后端、数据库迁移、CI 与 TestFlight 发布

## 零、为什么修好后还会再犯

过去不少修改只处理当前可见症状，没有把“以后都必须成立”的规则放进共享实现和机器门禁；聊天或文档里的提醒不会让编译器、测试和发布脚本自动拒绝旧错误。与此同时，`XAgeMainView` 跨域耦合、UI 测试依赖公网/系统时序、CI 曾漏跑 XAGE 或只看命令退出码，都会让一次局部修改重新打开旧入口。以后不再把“这次改对了”当完成，唯一闭环是根因、同类扫描、永久契约、命名回归、真实执行结果和证据全部同时成立。

## 一、唯一完成定义

修复完成不是“当前页面看起来好了”，而是：

> 根因确认 + 同类入口扫描 + 永久约束 + 命名回归测试 + 受影响/全量门禁通过 + 证据落档。

任一必需项未执行、失败、被跳过或没有证据时，不得说“已完成”，不得提交发布记录，更不得上传 TestFlight。

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

机器可读契约位于 `quality/regression_contracts.json`。它同时校验契约测试锚点、影响域、XAGE 架构上限和发布命令。

当前关键契约包括：

- `UX-NAV-001`：页面和 sheet 的关闭语义一致。
- `UX-KEYBOARD-001`：点击、下拉、菜单、切页和离开均正确释放焦点；输入框 1–5 行；中文输入不回写。
- `UX-ACCESSIBILITY-001`：真实命中区至少 44pt，父子可访问语义不冲突。
- `UX-FORM-001`：干净/脏表单、提交锁和危险操作确认一致。
- `DATA-CARD-001`：数据卡片选择和顺序按账号持久化，同步不恢复已移出卡片。
- `CHAT-SESSION-001`：幂等重试和迟到回答隔离。
- `AI-SUBJECT-001`：本人和家属主体绝不串用数据。
- `AI-SAFETY-001`：急症/确定性风险优先，不给危险或绝对保证。
- `AI-EVIDENCE-001`：正文、引用、重放和历史快照一致。
- `HEALTH-REGISTRY-001`：目录、读取、上传和趋势共用稳定 registry。
- `HEALTH-ACCOUNT-001`：健康同步账号隔离、来源幂等、手工数据保护。
- `TEST-DETERMINISM-001`：CI UI 测试不得依赖公网、生产账号或真实模型时序；外部交互使用仅 Debug 且显式启用的确定性传输。
- `TEST-SUITE-INTEGRITY-001`：精确运行清单、参数化 case 和 skip 状态只能显式增强；删除、改名、缩减或明显弱化测试必须失败。
- `PROCESS-GATE-001`：行为修改必须伴随影响清单和有意义的测试变更。

新增一种历史错误时，必须新增或扩展相应契约；不能只在聊天或 devlog 中写一句提醒。

## 五、XAgeMainView 临时保守规则

`XAgeMainView.swift` 当前超过一万行，跨越多个业务域。拆分完成前：

- 任意修改保守触发 UI/交互、AI 客户端、Health 客户端和账号相关回归。
- 文件总行数、struct/enum、sheet、full-screen cover、alert、固定延时 presentation 和静默 API 失败数量不得超过 2026-07-13 基线。
- 不得重新引入旧 `HomeView`、`ChatView`、`SettingsView` 或 `MedicationListView` 路由。
- 新职责必须拆到 Data、Chat、XAge、Settings 或 Shared 的聚焦文件中；不能继续堆入巨型文件。

这是一条“停止恶化”门禁，不等于拆分已经完成。

## 六、验证矩阵

每次至少运行：新增回归测试、影响域既有测试、同类相邻路径。UI/交互还要按本次影响覆盖：

- 空、加载、成功、失败、重试、长内容和重启恢复；
- 点空白、明显纵向下拉、提交、切页、返回、打开菜单/附件/历史时的键盘和焦点；
- 单行到最大行数、中文输入法；第三方输入法不能实测时记录真机风险；
- 页面、sheet、干净/脏表单、忙碌态和二次进入；
- 横滑/纵滑方向冲突和首尾边界；
- 44pt 命中、VoiceOver 语义、大字号、小屏和安全区；
- 前后截图或可重复几何/快照断言。

AI 修改必须跑主体隔离、急症/特殊人群、数据证据、引用、幂等、历史回载和内部字段防泄漏。Health 修改必须跑 registry、权限/无样本/部分成功/失败状态、账号切换、迟到回调、来源身份、手工数据保护和迁移。

## 七、对现有测试结论的边界

`XAgeHighIntensityContextUITests` 的全部测试只能继承 `XAgeUITestCase`，通过同一个 application factory 启动，并显式启用仅 Debug 可用的 `XJIE_UI_TEST_STUB_NETWORK`。共享基类独占 app 的创建、启动、重启与终止；源码范围内 `XCUIApplication` 类型/构造和 `.launch` / `.terminate` 的 token 数量是精确契约，`.init`、上下文构造、方法引用、嵌套 helper 或基类外 lifecycle 调用都失败。每次 launch 都由 teardown 自动读取运行时审计 `xjie.uiTest.networkAudit`，断言至少拦截过一个请求且 `unhandled=0`，因此不能靠把一次审计调用集中到少数测试来伪造覆盖。账号主体、功能开关、对话历史、用药、本人资料和家庭接口返回确定性 fixture；受控 `APIService` 传输中的未知请求无论 URL scheme 都会进入 fail-closed stub，不能用非 HTTP(S) scheme 绕过。审计计数在响应交付前同步发布，测试代码不得靠关闭网络错误弹窗继续执行。测试模式同时关闭所有通知中心入口、HealthKit 和不受控的 `NWPathMonitor`。

其中 12 个 prompt 另外显式启用 `XJIE_UI_TEST_STUB_CHAT`。每一条都断言键盘关闭、输入框清空、原始用户消息出现、对应助手回显出现且没有错误弹窗。因此它能证明客户端输入、发送和消息呈现壳层，但不能证明真实服务端返回了正确 AI 回答。

以后：

- UI 壳层结论可以引用该测试；
- AI 内容、安全、主体、引用或路由结论必须引用确定性 Swift/Python 测试，或引用真正断言最终助手回答的受控端到端评测；
- 不得再把“输入过 12 个问题”描述为“验证了 12 个 AI 回答”。
- 公网 SSE 延迟、断网、重连和超时属于独立网络集成测试，不得重新塞回每次 CI UI 门禁制造不确定性。
- 生产代码只能在 `APIService.trustedSession` 保留唯一一个由 `makeSessionConfiguration()` 创建的 `URLSession`；APIService 内请求只能显式使用 `self.trustedSession`，外部只能显式使用 `APIService.shared.trustedSession`，UI 测试自身禁止发请求。门禁先移除 Swift 注释/普通字符串但保留可执行插值，再统一反引号标识符，精确约束 `APIService` / `trustedSession` token、构造和请求调用；第二构造/别名、推断会话、上下文 `.shared`、简单或 tuple/pattern shadow、字符串插值/raw 插值/bare regex/转义标识符绕过，`Data`/`NSData`/`String(contentsOf:)`、`AsyncImage`、WebKit、Network/CFNetwork/POSIX API 及函数别名都会被阻断。本地 URL 文件读取只能使用先检查 `url.isFileURL` 的 `LocalFileDataLoader`。这是对受控源码入口的 fail-closed 约束，不是 OS 级防火墙；新增动态调用或新的底层网络框架时，必须先扩展门禁和负例，不能只用 `intercepted>0` 声称整个进程绝无外联。
- `NWPathMonitor`、`HKHealthStore` 和 `UNUserNotificationCenter.current` 也使用全源精确 token/构造身份，只允许分别出现在 `NetworkMonitor`、可注入的 `AppleHealthSyncViewModel` 和 `PushNotificationManager` 的 UI-safe factory。直接 `.init`、上下文 `.init`、构造器/`current` 方法引用或复制第二个 owner 均失败；因此测试模式的 no-op 不是靠每个调用点自觉，而是由唯一系统入口和 token 数共同约束。
- `xcodebuild test` 返回 0 不代表执行过正确测试。Unit、完整 UI、小屏 UI 和 CI 都必须生成 `.xcresult`，由 `tools/validate_xcresult.py` 对照受版本控制的精确清单校验：Unit 恰好 149 项、完整 UI 恰好 5 项、Unit/完整 UI 并集恰好 154 项，小屏专项恰好执行那 2 个已登记用例；任何缺失、额外、重复、改名、skip、fail 或 expected-failure 都失败。小屏结果还必须证明设备模型是 iPhone SE（第 3 代）。
- Python 同样使用运行时精确清单，而不是最低数量：backend full 恰好 264 个 ID，tools 恰好 74 个 ID。tools 不允许 skip；backend 只允许下文列出的 3 个固定 integration placeholder，因此通过结论必须写成 `261 passed + 3 skipped`。

## 八、执行命令

```bash
cd /Users/linlin/Desktop/X/XJie_IOS

# 契约、锚点和架构上限
/usr/bin/python3 -I tools/regression_guard.py validate

# 提交前检查当前修改
/usr/bin/python3 -I tools/regression_guard.py check --working

# 按 change_impact.json 运行受影响门禁
/usr/bin/python3 -I tools/run_regression_gate.py impacted

# 发布候选：PR 合并、官方分支精确 SHA 的 push CI 变绿后，先复制模板并填写全部 passed 证据
mkdir -p .quality
cp quality/release_signoffs.example.json .quality/release_signoffs.json
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git rev-parse 'HEAD:quality/regression_contracts.json'
shasum -a 256 <脱敏截图或录屏文件>

# 签核文件完成后，用受信且隔离的 Apple/Xcode Python 运行完整发布门禁
/usr/bin/python3 -I tools/run_regression_gate.py release

# archive/export 前再次确认结果仍属于当前 HEAD
/usr/bin/python3 -I tools/run_regression_gate.py assert-release

# 唯一允许的归档/上传入口
scripts/release_testflight.sh --archive-only
scripts/release_testflight.sh --upload
```

本地 `.githooks/pre-commit` 和 `.githooks/pre-push` 会执行静态门禁，并覆盖新增、修改、删除、复制以及重命名前后的路径；working-tree 差异还必须同时检查 tracked 和 untracked 普通文件的空白错误。仓库根、三个 source root、`.xcodeproj/project.pbxproj`、共享 scheme 以及这些固定输入的每一层祖先都必须是实际目录/普通文件；source root 下所有 Swift、Info.plist、entitlements、privacy、asset 和 localization 文件也逐项 `lstat`，任何 ancestor/directory/file symlink 都 fail closed。未改内容的测试复制/重命名、只有测试函数声明、skip 或恒真断言都不算有效测试变更。CI、hooks、guard、xcresult validator、发布脚本、签核模板、发布制度和契约注册表本身属于 `quality_process_gate` 行为域，削弱它们同样必须更新影响清单和工具回归测试。提交差异检查对 merge commit 使用 first-parent diff，不能再用空的 `git show --format=` 假绿。push 阶段不要求尚不可能存在的发布证据；候选 SHA 通过 PR 合并且远端 push CI 变绿后，`release`/`assert-release` 才生成并强制校验发布证据。禁止 `--no-verify`。

Git 调用 hook 时可能导出相对 `GIT_INDEX_FILE` 等 repository-local 环境；hook 只能在创建 immutable candidate 前保留真实 index，随后必须清除 `git rev-parse --local-env-vars` 的全部变量，再进行 linked-worktree add/remove 和候选树验证，并由 tools 测试真实执行这一环境形态。

## 九、CI 与发布

GitHub Actions 必须无路径过滤地监听 `XAGE` 和 `main` 的 push/pull request，覆盖 iOS、backend、quality、gate 工具、完整 iOS UI 套件、固定 iPhone SE（第 3 代）的双用例小屏套件和 Release device archive；不得用 `workflow_dispatch` 绕开多提交比较，也不得使用 `|| true` 或把必需命令放进后续仍可成功的 `&&` 链来吞掉失败。policy 工具套件会真实执行生产发布脚本和 `/bin/zsh`，所以该 job 的唯一 runner 必须固定为 `macos-15`，不能再以 Linux 只做静态替身；其中 tools/guard 三个 Python 入口必须固定 `/usr/bin/python3 -I`，不能继承镜像 PATH 中会漂移的 Homebrew Python。backend 与最终汇总可以继续使用 Ubuntu。iOS 必须严格匹配 Unit 149、完整 UI 5、小屏 2、Unit/完整 UI 并集 154 的受控清单；Python 必须严格匹配 backend 264 和 tools 74 的运行时 ID 清单。清单变化必须显式修改契约和负向测试，不能用新的最低数掩盖删除、改名、参数化收缩或零执行。最终 `quality-gate` 只有在 policy、backend 和 iOS 全部验证都成功时才通过。文档、脚本或工作流单独修改也必须产生同名检查，避免 required check 缺席。

Xcode 工程边界不能靠 `project.pbxproj` 的 comment、section 名或文件名字符串判断。门禁先清除 OpenStep comment、把 quoted value 换成不可伪造 token，要求关键 dictionary key 恰好出现一次，并解析 `objects` 中每个顶层对象的 `isa`（不依赖字段顺序），阻断 duplicate-key last-value、isa-last 和隐藏 Aggregate/Shell target。三个 `PBXNativeTarget`、PBXProject targets、container proxy、target dependency、配置列表、build phases/rules/dependencies、phase 类型和 Sources 的 build-file → fileRef → group ancestry 都必须精确；磁盘 Swift 集合必须与三个 Sources phase 精确相等，framework phases 必须为空，Swift package product/reference/object、额外 Sources/shell/aggregate phase/target、重复/换绑 target/fileRef 均失败。八个 Debug/Release `XCBuildConfiguration`、四个按序 configuration lists 及 Release default、PBXProject/target config-list 绑定都固定；共享 `Xjie.xcscheme` 的 Build/Test/Launch/Profile/Archive graph 也必须精确且不允许 pre/post action、环境变量、参数或 test plan。

Release 编译设置分两层验证。静态 PBX 层禁止 source inclusion/exclusion、base xcconfig、compiler/linker injection、bridging header、Swift include、library/framework search path，以及 Release 下的 debug/testability/architecture/C/C++ flag 覆盖；归档前再把真实 `xcodebuild -showBuildSettings -json` 管道交给同一 verifier，精确验证 Release、iphoneos/arm64、SDK、wholemodule、dSYM、Info.plist、entitlements、bundle/version/build，并拒绝有效值中的 `OTHER_LDFLAGS`、bridging/include/compiler 覆盖。有效 header/library/framework search paths 只能是本次 `TARGET_BUILD_DIR` 及其 `include`，防止静态文本正确但继承/命令行结果被改写。

所有可能影响 iOS 的源码、工程、配置、测试支持、质量门禁或发布链变化，都必须创建全新的无签名 `generic/platform=iOS` Release archive，并对其中的 device `.app` 运行 `tools/verify_release_bundle.py`。Simulator Release build 不能替代这一项，因为 `targetEnvironment(simulator)` 或 SDK 条件编译可能产生不同二进制。verifier 必须确认合法 bundle、Info.plist、主可执行文件为可执行的普通非符号链接文件，并只接受 thin little-endian 64-bit arm64 `MH_EXECUTE` 与 iOS device platform 2（或旧 iPhoneOS load command）；ASCII、FAT、x86_64、dylib、Simulator、截断/畸形 Mach-O、UI 自动化、Debug 开关、测试传输标记和敏感运行时文件全部 fail closed。

仓库管理员必须在首次精确 SHA 的 CI 成功后，将 GitHub Actions app `15368` 产生的 `quality-gate` 设为 `XAGE` 和 `main` 的 required check，开启 strict、管理员执行和“必须通过 PR”，PR bypass users/teams/apps 必须为空，并禁止 force-push 和删除分支。当前仓库只有 owner、没有独立 reviewer，所以 approval count 固定为 0；这只能降低误操作概率，不能阻止 owner 在同一 PR 中同时削弱 workflow、gate、测试或常量并自行合并。增加真实协作者后必须升级为 1 个批准并要求最后一次 push 由他人批准，质量/发布路径还应由独立 CODEOWNERS、required workflow/ruleset 或受保护发布环境控制。此后使用 feature branch → PR → merge，不再把“直接 push 受保护目标分支”写成正常流程。`release` 与 `assert-release` 均须实时查询固定官方仓库：官方分支 tip 等于当前 `HEAD`、该 SHA 关联一个已合并到目标分支且 `merge_commit_sha == HEAD` 的 PR、`ci.yml` 的 push run 已完成成功、对应 `quality-gate` check 由固定 GitHub Actions app 产生且链接到该 run、两个受保护分支设置均符合要求。可变本地 `origin`、仅有本地 JSON、手动触发或其他 SHA 的绿灯无效。

归档前先要求候选工程唯一的 `CURRENT_PROJECT_VERSION` 严格大于 `release_gate.latest_uploaded_build`。当前登记的最新已上传 build 是 `17`，所以 build 17 本身不可再次签核或发布，下一候选至少为 build `18`。只在新候选可安装后，才把 `quality/release_signoffs.example.json` 复制为被忽略的 `.quality/release_signoffs.json`，填写当前 `HEAD`、`HEAD^{tree}`、`HEAD:quality/regression_contracts.json` blob、带时区完成时间，以及以下五项 `passed` 证据：真实 iPhone HealthKit、Apple Watch/后台同步、第三方中文输入法、大字号/VoiceOver、受控 AI 最终回答。每项必须把 `app_version` / `app_build` 精确填写为该候选工程唯一的 `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION`，并有真实测试人、带时区测试时间、设备/系统/build 或受控环境、至少两条可复现步骤与观察；脱敏截图、录屏或记录必须是 `.quality/evidence/` 下的本地普通文件，并填写该路径及真实 SHA-256。URL、符号链接、缺失文件、错误/旧版本构建、摘要不一致、`QA`、`xx`、纯数字引用和模板文字均无效。路径和 SHA-256 只能证明本地文件字节存在且未变化，不能认证测试者身份，也不能证明步骤真实执行；发布者自填五项签核不构成独立证据，必须由可核验的真实测试人/QA 提供并接受复核。`release` 只允许 `/usr/bin/python3 -I` 的隔离 Apple/Xcode 解释器，并将完整签核摘要、候选版本/构建、官方 tip、merged PR、远端 check、两分支保护、SE 3 身份、backend 原生解释器/依赖摘要/外层 JUnit、受信 Xcode `26.3`（build `17C529`）和本地命令绑定到 schema `5` evidence；`assert-release` 和发布脚本会实时再次核验，缺项、过期、换 SHA、换 build、换 runtime/toolchain、删除或修改证据均阻断归档。

跟踪发布脚本的两种模式都会用 `destination=export` 本地导出恰好一个 IPA。该顺序没有“诊断”例外：build 未严格大于已上传值、`release`/`assert-release` 未通过时，禁止签名 archive 和 `xcodebuild -exportArchive`；普通回归门禁所需的无签名 generic-device archive 是唯一的发布前 archive 例外。`--upload` 的认证元数据完整性在 repository/environment/release lock 与 cleanup EXIT trap 建立之后、固定 Xcode 身份和 `assert-release` 之前先 fail closed；这只是无外部副作用的格式/互斥 preflight，不会读取密码、不触发签名/归档/上传，也不能绕过后续任一发布门禁，失败时必须由 trap 清理锁。解包前先要求字节 0 是 local header、全包只有一个位于 EOF 的无 comment EOCD，central directory 与 EOCD 连续；随后把每一个 local header/name/extra/CRC/压缩尺寸/数据区与其 central entry 一一绑定并要求从 byte 0 到 central directory 没有 gap、overlap 或未引用数据。local/central extra 分别只允许 pinned Xcode/ditto 的对应旧 Unix 形态，时间必须一致；flag `0x08` 时还必须解析并精确比对带签名的 16-byte data descriptor，其他差异全部失败。然后遍历整个 IPA，而不是只扫描 `Payload/*.app`：拒绝空/绝对/穿越路径、反斜杠、重复路径、Unicode NFC + 大小写归一化冲突、链接/特殊项、加密项、异常单项/总展开量和异常压缩比，并对所有普通成员检查 `.env`、`.pem`、`.key`、`.p8`、`.p12`、`.pfx`、`.sqlite`、`.db` 等敏感文件名、跨读取块 PEM、DER/PKCS#8、OpenSSH、private JWK 和 SQLite header；超过有界二进制读取的 JSON/DER 声明和纯空白前缀按无法证明安全而失败。随后再安全解包并校验实际 distribution `.app` 的版本/构建、生产 API、arm64 iOS device Mach-O、codesign 的实际叶证书确实属于 profile `DeveloperCertificates`、HealthKit/background-delivery、team/application identifier、`get-task-allow=false`、`beta-reports-active=true` 和 App Store distribution profile；provision profile 只有在 CMS 证明恰有一个 Apple trusted signer 后才允许解码。最后绑定 IPA SHA-256 与 distribution CDHash。`--archive-only` 在这里停止，不上传；`--upload` 只允许 pinned Xcode 的 `altool` 上传同一个 owner-only、单 hard-link、read-only snapshot，并在调用前重新比对 path/device/inode/link count/mode/size/hash，缩小验证后替换的 TOCTOU 窗口。上传认证只能选一组完整元数据：`XJIE_ASC_API_KEY_ID` + `XJIE_ASC_API_ISSUER_ID`，或 `XJIE_ASC_USERNAME` + `XJIE_ASC_PASSWORD_KEYCHAIN_ITEM`；这里只记录变量名，不得把值写入代码、文档、memory、日志或聊天。上传 build `N` 成功后，必须通过后续受保护 PR 将 `latest_uploaded_build` 推进到 `N`，不得复用旧 build。

## 十、自动门禁的边界与当前状态

- `TEST-SUITE-INTEGRITY-001` 可以精确约束测试 ID、参数化 case、skip 和明显的断言删除/恒真替换，但静态规则无法证明任意改写后的断言仍有同等语义强度。独立 reviewer 缺失期间，这是明确的信任边界，不能声称测试体系“无法被自行削弱”。
- backend full 的 264 个运行时 ID 中，以下 3 项仍是固定 placeholder skip，原因均为 `requires dockerized postgres + redis stack`：`tests.integration.test_api_chat_mock::test_chat_mock_placeholder`、`tests.integration.test_api_glucose_import::test_glucose_import_flow_placeholder`、`tests.integration.test_api_meals_flow::test_meals_photo_flow_placeholder`。因此这轮门禁证明的是 261 个通过加 3 个受控缺口，不证明聊天 mock、血糖导入和膳食照片的真实 PostgreSQL/Redis 集成链已经覆盖。
- backend gate 会绑定 `.venv` 原生解释器、隔离 probe、`pyvenv.cfg` 和全部 site-packages 字节，并在外层删除旧 XML 后复核精确 JUnit；它消除假脚本、旧 XML 和依赖漂移造成的意外假绿，但不能宣称抵御同一 UID 主动进程在检查间竞争替换并恢复系统文件。Homebrew Python 的 framework/stdlib/dylib 也不是仓库内可复现制品。
- 最终 ZIP parser 已根据一次 build 17 的 Xcode 26.3 直接 export 字节修正 local/central extra 与 signed descriptor 解析，但该 export 违反候选顺序，不能作为合规 release 证据；合规兼容证据只能来自未来 build >=18 在 `release` 与 `assert-release` 全部通过后由跟踪脚本生成的候选。
- 截至 2026-07-14，提交 `e8a0fd5` 的本地 working-tree `impacted` 曾完整通过，但 PR #4 的 exact-SHA policy 在 Ubuntu runner 因没有 `/bin/zsh` 正确失败；backend 同 SHA 已通过。现已将 policy 固定为 `macos-15` 并加入精确 runner 回归断言，因此旧提交的本地和远端结果自动失效，当前修改树必须从头重跑并以新 SHA 的 PR/push 检查为准，不能提前写成最终全绿。
- GitHub `XAGE` / `main` 保护规则尚未安装或回读。`main` 当前比 `XAGE` 落后 69 commits，且仍是旧的 fail-open CI/无兼容 `quality-gate`；不能为了勾选“已保护”而静默同步或把它写成完成。安全顺序是 feature PR → `XAGE` 合并 → exact merged-SHA push CI 绿 → 安装并回读 `XAGE` 保护；`main` 需要另行明确同步/引导决策、兼容 CI 变绿后才能安装并回读保护。在两分支都真实符合契约前 release 保持 blocked。
- 最新已上传 TestFlight 仍是 `1.0(17)`。本轮没有递增 build、没有上传，但曾错误绕过发布脚本，对仍为 build 17 的当前树直接执行一次签名 archive 与 `xcodebuild -exportArchive`；这是流程违规，不是合规验证或发布证据，生成物已删除且绝不可复用/上传。`latest_uploaded_build=17` 已让当前工程 build 17 在 release/dry-run/assert-release 中 fail closed；下一候选至少 build 18，并且五项真人/受控签核必须全部重新绑定新候选的 exact HEAD、版本和 build。条件全部满足前不得 archive/upload。

## 十一、证据格式

每次解决问题都在 `memory/resolved_issues.md` 使用统一模板，并在 `development_records.json` 记录：

- 最小复现和根因；
- 永久不变量/契约 ID；
- 同类入口扫描范围；
- 新增或增强的测试名和路径；
- 执行命令、通过数量和证据；
- 未验证项、真机限制和剩余风险。

只写“已修复、测试通过”不再算有效记录。
