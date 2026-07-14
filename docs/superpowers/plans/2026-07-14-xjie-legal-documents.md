# XJie Legal Documents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the abbreviated XJie privacy policy and add a complete local SwiftUI service agreement, while preserving the current legal-page UI and More Menu return behavior.

**Architecture:** Move the existing legal-document models, shared header, privacy page, and permission page into a focused `XAgeLegalDocumentViews.swift` file. Keep presentation state in `XAgeMoreMenu`, add one service-agreement full-screen route, and represent the two documents as immutable section arrays rendered by one shared card component.

**Tech Stack:** Swift 5, SwiftUI, XCTest/XCUITest, Python `unittest`, Xcode project OpenStep PBX, repository regression guard.

## Global Constraints

- Work directly on the current `XAGE` branch; do not create or switch to a worktree.
- Preserve the three user-owned untracked paths and never stage them.
- Use “合肥简捷爱科技有限公司” as the operator and personal-information processor, “简捷爱科技” as the short name, and `jianjieaitech@163.com` as the only policy contact email.
- Publication/effective/version date is `2026年7月14日`.
- Both documents are local SwiftUI content; do not add a web view, remote CMS, acceptance backend, new permission, SDK, dependency, build-number change, signing, export, or TestFlight operation.
- Do not promise unverified server location, exact retention days, third-party vendor identity, cross-border status, or security absolutes.
- The service agreement must describe current AI identification through “AI 健康问答” and “助手小捷”; do not claim unimplemented exported-file watermarks or metadata labels.
- Keep existing accessibility identifiers for privacy and permissions; add exactly `xage.service.agreement.page` for the service agreement.
- Keep XCTest inventories at Unit `158`, full UI `9`, small UI `2`, and union `167` by extending the existing legal UI test instead of adding a new XCTest method.
- Add one Python policy test, changing the tools inventory from `74` to `75`; tools permit zero skips.
- Do not weaken `quality/regression_contracts.json` architecture limits or the pinned Xcode `26.3` / build `17C529` identity.
- A lawyer familiar with Chinese personal-information, medical-health, consumer, and generative-AI rules must review the final production copy before release.

## File Map

- Create `Xjie/Xjie/Views/Home/XAgeLegalDocumentViews.swift`: all legal-document models, shared UI, full privacy copy, full service-agreement copy, and existing permission page.
- Modify `Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift`: retain only More Menu/business views; add the service route and remove the moved legal declarations.
- Modify `Xjie/Xjie.xcodeproj/project.pbxproj`: add one file reference/build file and register it in Home/Sources.
- Modify `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`: extend the existing legal navigation loop with the service agreement.
- Modify `tools/tests/test_release_policy.py`: add a focused source-level invariant for company/contact, chapter counts, medical/AI boundaries, and forbidden copied brands.
- Modify `quality/expected_python_tests.json`: register the new tools test ID.
- Modify `AGENTS.md` and `docs/quality/REGRESSION_POLICY.md`: update the exact tools count from 74 to 75.
- Modify `quality/change_impact.json`: declare this legal-copy/navigation/source-layout change before production edits.
- Modify `development_records.json`: append the completed change record with honest red/green and toolchain evidence.
- Create `implementation_audit/ios_xage_legal_documents_20260714/verification_report.md`: durable verification report.

---

### Task 1: Register impact and establish the two RED tests

**Files:**
- Modify: `quality/change_impact.json`
- Modify: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift:207-224`
- Modify: `tools/tests/test_release_policy.py`

**Interfaces:**
- Consumes: existing `XAgeUITestCase`, `xage.more`, `xage.account.<title>` menu identifiers, and existing legal-page identifiers.
- Produces: a UI expectation for `xage.account.服务协议 → xage.service.agreement.page` and a source invariant named `test_xage_legal_documents_are_complete_and_product_specific`.

- [ ] **Step 1: Run the pre-edit guards and record the baseline**

Run:

```bash
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --working
```

Expected: both pass for the current tree. If either fails, preserve the full output under `implementation_audit/ios_xage_legal_documents_20260714/` before changing source.

- [ ] **Step 2: Replace `quality/change_impact.json` with this change’s real scope**

Use these exact top-level values and preserve the existing schema shape:

```json
{
  "schema_version": 1,
  "change_id": "2026-07-14-ios-xage-legal-documents",
  "change_type": "feature",
  "summary": "为 XJie 新增完整本地 SwiftUI 服务协议，扩充隐私政策，并把法律文档页面从更多菜单业务文件拆分到独立文件。",
  "root_cause": "现有隐私政策仅有八个概述章节，未逐项覆盖账号、Apple 健康、报告上传、AI 对话、敏感健康信息、委托处理、未成年人和完整权利渠道；项目也没有服务协议入口，无法向用户集中说明账号规则、AI 标识、医疗边界、用户内容许可和争议解决。",
  "risk_hypothesis": "若直接复制第三方协议会引入支付宝、医保、挂号和关联公司等不存在的业务；若只新增长文本而不拆文件，会继续扩大更多菜单职责；若服务协议返回调用更多菜单 onClose，会重现子页面返回直接关闭更多菜单的问题；若测试或 PBX 清单遗漏，页面可能不在目标中或导航回归无法被发现。"
}
```

Set `impacted_domains` to:

```json
[
  "ios_account_client",
  "ios_chat_client",
  "ios_health_client",
  "ios_project_release",
  "ios_ui_interaction",
  "quality_process_gate",
  "test_suite_integrity"
]
```

Set `regression_contracts` to:

```json
[
  "UX-NAV-001",
  "UX-ACCESSIBILITY-001",
  "TEST-DETERMINISM-001",
  "TEST-SUITE-INTEGRITY-001",
  "RELEASE-GATE-001",
  "PROCESS-GATE-001"
]
```

List the two modified tests, the full legal/permission sibling scan, PBX source scan, exact content prohibitions, manual VoiceOver/dynamic-height review, lawyer-review risk, and the pinned-Xcode local limitation in the remaining fields.

- [ ] **Step 3: Extend the existing UI test before production code**

Replace the page expectation array in `testMoreMenuLegalPagesReturnToMenu()` with:

```swift
for (entryIdentifier, pageIdentifier) in [
    ("xage.account.服务协议", "xage.service.agreement.page"),
    ("xage.account.隐私政策", "xage.privacy.policy.page"),
    ("xage.account.权限申请与使用情况说明", "xage.permissions.usage.page")
] {
    let entry = app.buttons[entryIdentifier]
    scrollIntoViewOnActiveScreen(entry, direction: .up, maxSwipes: 8)
    entry.tap()
    XCTAssertTrue(app.descendants(matching: .any)[pageIdentifier].waitForExistence(timeout: 5))

    app.buttons["返回"].tap()
    XCTAssertTrue(app.buttons[entryIdentifier].waitForExistence(timeout: 5))
}
```

- [ ] **Step 4: Add the focused source invariant before the new file exists**

Add this method to `ReleasePolicyTests` in `tools/tests/test_release_policy.py`:

```python
def test_xage_legal_documents_are_complete_and_product_specific(self):
    legal_path = (
        REPO_ROOT / "Xjie" / "Xjie" / "Views" / "Home" / "XAgeLegalDocumentViews.swift"
    )
    self.assertTrue(legal_path.is_file(), "focused XAGE legal document source is missing")
    source = legal_path.read_text(encoding="utf-8")

    self.assertEqual(len(re.findall(r'id:\s*"privacy-[a-z-]+"', source)), 11)
    self.assertEqual(len(re.findall(r'id:\s*"service-[a-z-]+"', source)), 15)
    self.assertGreaterEqual(source.count("合肥简捷爱科技有限公司"), 2)
    self.assertGreaterEqual(source.count("jianjieaitech@163.com"), 2)
    self.assertNotIn("support@xjie-health.com", source)

    for required in (
        "xage.service.agreement.page",
        "AI 健康问答",
        "助手小捷",
        "不构成医疗诊断",
        "立即联系当地急救机构",
        "用药管理和快捷说明只用于记录",
        "不得删除、篡改、隐匿或伪造",
        "当前版本不向 Apple 健康写入数据",
    ):
        self.assertIn(required, source)

    for forbidden in (
        "蚂蚁阿福",
        "支付宝",
        "医保",
        "预约挂号",
        "在线问诊",
    ):
        self.assertNotIn(forbidden, source)
```

- [ ] **Step 5: Run both focused tests and verify RED for the intended missing feature**

Run the source invariant:

```bash
/usr/bin/python3 -I tools/tests/test_release_policy.py \
  ReleasePolicyTests.test_xage_legal_documents_are_complete_and_product_specific
```

Expected: one assertion failure with `focused XAGE legal document source is missing`; no import or syntax error.

Run the focused UI method into a new result bundle:

```bash
rm -rf /tmp/xjie-legal-red.xcresult /tmp/xjie-legal-red-derived
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/xjie-legal-red-derived \
  -resultBundlePath /tmp/xjie-legal-red.xcresult \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuLegalPagesReturnToMenu
```

Expected: the app compiles and the test fails because `xage.account.服务协议` does not exist. Save the relevant failure excerpt under the audit directory. Do not commit the red tree.

---

### Task 2: Build the focused legal-document SwiftUI file and More Menu route

**Files:**
- Create: `Xjie/Xjie/Views/Home/XAgeLegalDocumentViews.swift`
- Modify: `Xjie/Xjie/Views/Home/XAgeMoreMenuViews.swift:1-250,520-850`
- Modify: `Xjie/Xjie.xcodeproj/project.pbxproj`
- Test: `Xjie/XjieUITests/XAgeHighIntensityContextUITests.swift`
- Test: `tools/tests/test_release_policy.py`

**Interfaces:**
- Consumes: `XAgeLiquidBackground`, `XAgeGlassCardBackground`, `XAgeCapsuleFill`, `Color(hex:)`, and a closure `onClose: () -> Void`.
- Produces: `XAgeServiceAgreementView`, `XAgePrivacyPolicyView`, and `XAgePermissionUsageView`, each initialized as `init(onClose: @escaping () -> Void)` by memberwise Swift initialization.

- [ ] **Step 1: Move the existing shared legal declarations into the new file**

Create `XAgeLegalDocumentViews.swift` with `import SwiftUI`. Move the existing block from `XAgeLegalSection` through the end of `XAgePermissionUsageView` without changing the permission copy or permission page identifier.

Use these access levels:

```swift
private struct XAgeLegalSection: Identifiable {
    let id: String
    let title: String
    let paragraphs: [String]
    let bullets: [String]
}

private struct XAgePermissionDescription: Identifiable {
    let id: String
    let icon: String
    let title: String
    let applicationMoment: String
    let purpose: String
    let denialImpact: String
}

```

Keep `XAgeLocalDocumentHeader` and `XAgeLegalSectionCard` private. Declare `XAgePrivacyPolicyView`, `XAgeServiceAgreementView`, and `XAgePermissionUsageView` without `private` because `XAgeMoreMenuViews.swift` constructs them. Retain the complete existing header and permission bodies during the move, then replace the privacy body and add the service body with the complete code in the following steps.

The common section renderer must be shared rather than duplicated:

```swift
private struct XAgeLegalSectionCard: View {
    let section: XAgeLegalSection

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(section.title)
                .font(.system(size: 17, weight: .bold))
                .foregroundStyle(Color(hex: "173F64"))
            ForEach(section.paragraphs, id: \.self) { paragraph in
                Text(paragraph)
                    .font(.system(size: 14))
                    .foregroundStyle(Color(hex: "496A83"))
                    .lineSpacing(4)
            }
            ForEach(section.bullets, id: \.self) { bullet in
                HStack(alignment: .top, spacing: 8) {
                    Text("•").foregroundStyle(Color(hex: "238AD6"))
                    Text(bullet)
                        .font(.system(size: 14))
                        .foregroundStyle(Color(hex: "496A83"))
                        .lineSpacing(4)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}
```

- [ ] **Step 2: Replace the privacy policy with the complete 11-section source**

Use the complete arrays below exactly so the copy cannot drift from product behavior:

```swift
private static let sections = [
    XAgeLegalSection(
        id: "privacy-scope",
        title: "一、政策适用范围与处理者信息",
        paragraphs: [
            "本政策适用于由合肥简捷爱科技有限公司（简称“简捷爱科技”）运营的 XJie（小捷）iOS App 及相关服务。",
            "如您提供的是他人的个人信息，请确保已取得合法、充分的授权，并已向相关人员说明处理目的、范围和方式。"
        ],
        bullets: []
    ),
    XAgeLegalSection(
        id: "privacy-collection",
        title: "二、我们如何收集个人信息",
        paragraphs: ["我们遵循合法、正当、必要和诚信原则，按您实际使用的功能处理最少必要信息。"],
        bullets: [
            "账号信息：手机号码、登录凭证及账号安全操作所需信息。",
            "健康敏感信息：个人资料、病史、医疗记录、用药记录、手动指标、Apple 健康数据、体检报告、病例和聊天中的健康描述。",
            "报告与媒体：您主动选择的文档、照片、文件名称、类型及报告识别结果。",
            "语音输入：您主动启用麦克风和语音识别时处理的音频及转换文字。",
            "运行与安全：建立网络连接、排查故障、保护账号和接口所需的必要错误与安全日志。",
            "问题反馈：您主动填写的反馈内容和自愿提供的联系方式。"
        ]
    ),
    XAgeLegalSection(
        id: "privacy-permissions",
        title: "三、我们如何调用设备权限",
        paragraphs: ["相机、相册、麦克风、语音识别和 Apple 健康权限不会默认开启，只在您使用对应功能时由系统请求。您可以在 iOS 设置中撤回授权，拒绝仅影响对应功能。"],
        bullets: ["当前版本不向 Apple 健康写入数据；HealthKit 未授权项目不会被读取。"]
    ),
    XAgeLegalSection(
        id: "privacy-use",
        title: "四、我们如何使用个人信息",
        paragraphs: ["我们使用必要信息提供账号、健康档案、趋势展示、用药管理、报告识别、AI 健康问答、安全保障、故障排查和用户支持。"],
        bullets: ["我们不出售您的个人信息，不将健康资料或对话用于广告定向，也不将其用于训练通用 AI 模型。"]
    ),
    XAgeLegalSection(
        id: "privacy-technologies",
        title: "五、Cookie、SDK 与类似技术",
        paragraphs: ["XJie iOS App 当前不以 Cookie 进行网页广告追踪。相机、相册、语音识别和 HealthKit 等能力由 Apple 系统框架提供，并受系统授权控制。"],
        bullets: ["未来新增独立处理个人信息的第三方 SDK 时，我们会在上线前更新说明并履行必要的告知和授权程序。"]
    ),
    XAgeLegalSection(
        id: "privacy-storage",
        title: "六、信息存储期限、地点与安全措施",
        paragraphs: ["我们仅在实现服务、保障安全和履行法定义务所需的最短合理期限内保存信息，并采取 HTTPS/TLS、访问控制、最小权限和日志审计等合理措施。"],
        bullets: ["如未来涉及个人信息跨境提供，我们会依法另行告知接收方、目的、方式、信息类型和权利渠道，并履行必要程序。"]
    ),
    XAgeLegalSection(
        id: "privacy-disclosure",
        title: "七、委托处理、共享、转让与公开披露",
        paragraphs: ["为提供云存储、报告识别、AI 推理或基础运维确有必要时，我们可能委托受约束的服务提供者处理最少必要信息，并要求其仅按约定目的处理。"],
        bullets: ["除依法无需同意的情形外，共享、转让或公开披露会依法告知并取得必要同意。"]
    ),
    XAgeLegalSection(
        id: "privacy-ai",
        title: "八、AI 健康问答与健康数据处理",
        paragraphs: ["AI 健康问答可能处理您的健康敏感信息，仅用于响应您的请求、整理报告和提供健康信息参考。AI 输出可能错误、遗漏或过时，不构成医疗诊断、处方、治疗或急救服务。"],
        bullets: ["请勿输入无权提供的他人隐私、账号密码或与问题无关的敏感信息；重要结论应结合原始报告并咨询专业医生。"]
    ),
    XAgeLegalSection(
        id: "privacy-rights",
        title: "九、您如何行使个人信息权利",
        paragraphs: ["您可以查看或修改可编辑资料、管理系统权限，并通过“更多 → 账号与安全 → 注销账号”提交注销。"],
        bullets: ["您也可以通过联系邮箱请求访问、复制、更正、补充、删除或解释处理规则；撤回同意不影响撤回前已完成处理的效力。"]
    ),
    XAgeLegalSection(
        id: "privacy-minors",
        title: "十、未成年人信息保护",
        paragraphs: ["未成年人应在监护人指导和同意下使用本服务。不满十四周岁儿童的信息属于敏感个人信息，监护人应谨慎决定是否使用健康信息和 AI 问答功能。"],
        bullets: ["监护人可以通过联系邮箱提出查询、更正或删除请求。"]
    ),
    XAgeLegalSection(
        id: "privacy-contact",
        title: "十一、政策更新与联系我们",
        paragraphs: [
            "处理目的、范围、共享对象、权利渠道或安全风险发生重大变化时，我们会更新政策并通过 App 页面、弹窗或其他合理方式通知。",
            "个人信息处理者：合肥简捷爱科技有限公司",
            "联系邮箱：jianjieaitech@163.com"
        ],
        bullets: ["您也可以通过“更多 → 问题反馈”提交产品问题或建议。"]
    )
]
```

The privacy introduction card must show both dates and the processor:

```swift
Text("发布日期：2026年7月14日")
Text("生效日期：2026年7月14日")
Text("个人信息处理者：合肥简捷爱科技有限公司")
Text("医疗健康信息属于敏感个人信息，请重点阅读相关处理目的、必要性、影响和您的控制方式。")
```

- [ ] **Step 3: Add the complete 15-section service agreement source**

Use the complete arrays below exactly:

```swift
private static let sections = [
    XAgeLegalSection(id: "service-definitions", title: "一、定义", paragraphs: ["XJie（小捷）是由合肥简捷爱科技有限公司运营的健康数据管理与 AI 健康信息服务。本服务包括账号、健康档案、Apple 健康同步、报告和病例资料、用药管理、AI 健康问答及相关辅助功能。"], bullets: ["“输入”指您提交给 AI 健康问答的内容；“输出”指系统根据输入生成的内容；“用户内容”包括您填写、上传或同步的文字、健康数据、图片和文档。"]),
    XAgeLegalSection(id: "service-account", title: "二、账号注册、使用与安全", paragraphs: ["您应使用本人合法、有效的手机号码注册，妥善保管登录凭证，并对账号下的操作负责。"], bullets: ["账号仅供本人使用，不得出租、出借、转让或用于违法活动。发现异常时请及时修改密码或联系简捷爱科技；注销操作以 App 内不可逆提示为准。"]),
    XAgeLegalSection(id: "service-license", title: "三、服务内容与使用许可", paragraphs: ["部分功能依赖登录、网络、系统权限或您主动提供的数据。简捷爱科技授予您个人、有限、可撤销、不可转让、非独占和非商业的使用许可。"], bullets: ["未经书面许可，不得反向工程、绕过安全措施、批量抓取、转售或向第三方提供服务接口。"]),
    XAgeLegalSection(id: "service-ai", title: "四、AI 健康问答及生成内容标识", paragraphs: ["AI 健康问答依托生成式人工智能处理输入并产生输出。当前界面通过“AI 健康问答”“助手小捷”及助手身份样式提示 AI 生成属性。"], bullets: ["对外复制、发布或传播 AI 输出前，您应核验真实性、合法性和适用性并主动声明 AI 生成属性；不得删除、篡改、隐匿或伪造依法提供的生成内容标识。"]),
    XAgeLegalSection(id: "service-medical", title: "五、医疗健康服务特别说明", paragraphs: ["简捷爱科技和 XJie 不是医疗机构。AI 输出、健康评分、趋势和报告解读仅供健康管理参考，不构成医疗诊断、处方、治疗方案或急救服务。"], bullets: ["用药管理和快捷说明只用于记录，不构成用药建议；请遵医嘱并核对药品说明书。出现胸痛、呼吸困难、意识障碍、严重过敏、自伤风险等紧急情况时，请立即联系当地急救机构或前往医疗机构。"]),
    XAgeLegalSection(id: "service-conduct", title: "六、用户行为规范", paragraphs: ["您不得利用本服务从事违法活动、侵害他人权益、传播虚假医疗信息、攻击系统、盗取账号、非法处理他人个人信息或危害未成年人的行为。"], bullets: ["不得将未经核实的 AI 输出冒充医生意见、权威结论或简捷爱科技的承诺。"]),
    XAgeLegalSection(id: "service-user-content", title: "七、用户上传内容及授权", paragraphs: ["您保留合法上传内容的权利，并保证有权提供相关内容。为提供存储、展示、同步、报告识别和 AI 解读，您授予简捷爱科技在服务目的和必要期限内处理该内容的有限许可。"], bullets: ["该许可不是公开传播、商业出售或训练通用 AI 模型的授权。"]),
    XAgeLegalSection(id: "service-third-party", title: "八、第三方服务", paragraphs: ["Apple 健康、相机、相册和语音识别等能力由 Apple 系统框架提供。云基础设施、报告识别或 AI 推理服务提供者可能作为受托处理方参与最少必要处理。"], bullets: ["第三方独立提供的页面或服务适用其自身规则，XJie 会在合理范围内提示服务边界。"]),
    XAgeLegalSection(id: "service-obligations", title: "九、简捷爱科技的权利与义务", paragraphs: ["简捷爱科技将在合理范围内维护服务运行和安全、保护个人信息、响应合法请求，并可对违法、侵权、攻击或严重违约行为采取必要措施。"], bullets: ["我们不承诺服务永久、无错误或完全不中断；重大变化会通过合理方式通知。"]),
    XAgeLegalSection(id: "service-ip", title: "十、知识产权", paragraphs: ["App、界面、代码、图形、商标和运营文档的相关权利归简捷爱科技或合法权利人所有。"], bullets: ["AI 输出可能与其他输出相似或包含不受独占保护的内容；您使用或传播输出时应自行核查第三方知识产权风险。"]),
    XAgeLegalSection(id: "service-privacy", title: "十一、隐私与数据保护", paragraphs: ["个人信息处理遵循《XJie（小捷）隐私政策》。就个人信息处理存在不一致时，以对个人信息权益说明更具体的隐私政策为准。"], bullets: []),
    XAgeLegalSection(id: "service-disclaimer", title: "十二、权利声明及责任限制", paragraphs: ["AI 输出可能不准确、不完整、存在偏差或过时；网络、系统、设备、权限、第三方服务、维护或不可抗力也可能造成中断。"], bullets: ["在法律允许范围内，各方按照过错、因果关系和实际损失承担责任，本协议不排除依法不得排除的责任或消费者基本权利。"]),
    XAgeLegalSection(id: "service-termination", title: "十三、违约处理、服务变更与终止", paragraphs: ["对违法、侵权、攻击或严重违约行为，我们可以根据性质、影响和风险采取警告、限制功能、暂停账号、删除违法内容或终止服务，并保留联系和申诉渠道。"], bullets: ["您可以停止使用并通过 App 申请注销；终止后的数据处理和法定留存按隐私政策执行。"]),
    XAgeLegalSection(id: "service-minors", title: "十四、未成年人保护", paragraphs: ["未成年人须在监护人指导和同意下使用。监护人应管理账号、健康资料上传和 AI 问答；不满十四周岁儿童使用涉及敏感健康信息的功能前，应取得监护人同意。"], bullets: []),
    XAgeLegalSection(id: "service-law", title: "十五、法律适用、争议解决及其他", paragraphs: ["本协议适用中华人民共和国大陆地区法律。争议应先友好协商；协商不成，可依法向简捷爱科技住所地有管辖权的人民法院提起诉讼。"], bullets: ["个别条款无效不影响其他条款效力；协议发生重大更新时会通过 App 页面、弹窗或其他合理方式通知。联系邮箱：jianjieaitech@163.com。"])
]
```

Use this page composition:

```swift
struct XAgeServiceAgreementView: View {
    let onClose: () -> Void

    var body: some View {
        ZStack {
            XAgeLiquidBackground().ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    XAgeLocalDocumentHeader(title: "服务协议", onClose: onClose)
                    introductionCard
                    ForEach(Self.sections) { section in
                        XAgeLegalSectionCard(section: section)
                    }
                }
                .padding(24)
            }
            .scrollIndicators(.hidden)
            .accessibilityIdentifier("xage.service.agreement.page")
        }
    }

    private var introductionCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("版本日期：2026年7月14日")
            Text("运营主体：合肥简捷爱科技有限公司")
            Text("请重点阅读账号、AI 与医疗边界、用户内容许可、责任限制、服务终止和争议解决条款。注册、登录或实际使用本服务，表示您已阅读并同意本协议；如不同意，请停止使用。")
        }
        .font(.system(size: 14))
        .foregroundStyle(Color(hex: "496A83"))
        .lineSpacing(4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(18)
        .background(XAgeGlassCardBackground(cornerRadius: 24))
    }
}
```

- [ ] **Step 4: Wire the More Menu route without closing the parent**

Add beside the other legal states:

```swift
@State private var showServiceAgreement = false
```

Insert before the privacy row:

```swift
XAgeAccountMenuRow(
    icon: "doc.text.fill",
    title: "服务协议",
    subtitle: "了解服务规则、AI 使用边界与双方权利义务"
) {
    showServiceAgreement = true
}
```

Insert before the privacy cover:

```swift
.fullScreenCover(isPresented: $showServiceAgreement) {
    XAgeServiceAgreementView(onClose: { showServiceAgreement = false })
}
```

Do not call `onClose()` from this cover or the legal page’s back button.

- [ ] **Step 5: Add the new file to the Xcode project**

Use the next local IDs:

```pbxproj
A90005 /* XAgeLegalDocumentViews.swift in Sources */ = {isa = PBXBuildFile; fileRef = B90005 /* XAgeLegalDocumentViews.swift */; };
B90005 /* XAgeLegalDocumentViews.swift */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = XAgeLegalDocumentViews.swift; sourceTree = "<group>"; };
```

Add `B90005` to the Home group immediately after `B90004 /* XAgeMoreMenuViews.swift */`, and add `A90005` to the main App target Sources phase immediately after `A90004`.

- [ ] **Step 6: Run focused static and compile checks**

Run:

```bash
/usr/bin/python3 -I tools/tests/test_release_policy.py \
  ReleasePolicyTests.test_xage_legal_documents_are_complete_and_product_specific
xcodebuild build \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath /tmp/xjie-legal-build-derived
```

Expected: focused test `OK`; build ends with `** BUILD SUCCEEDED **`. If compiler visibility fails, expose only the cross-file legal page type or existing shared style actually named by the error.

- [ ] **Step 7: Run the focused UI test and verify GREEN**

Run:

```bash
rm -rf /tmp/xjie-legal-green.xcresult /tmp/xjie-legal-green-derived
xcodebuild test \
  -project Xjie/Xjie.xcodeproj \
  -scheme Xjie \
  -configuration Debug \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -derivedDataPath /tmp/xjie-legal-green-derived \
  -resultBundlePath /tmp/xjie-legal-green.xcresult \
  -only-testing:XjieUITests/XAgeHighIntensityContextUITests/testMoreMenuLegalPagesReturnToMenu
/usr/bin/python3 -I tools/validate_xcresult.py \
  --path /tmp/xjie-legal-green.xcresult \
  --minimum-tests 1 \
  --required-test XjieUITests.XAgeHighIntensityContextUITests/testMoreMenuLegalPagesReturnToMenu
```

Expected: exactly the focused legal UI method passes; every launch audit reports intercepted requests and zero unhandled requests.

---

### Task 3: Register the new tools test and close all quality gates

**Files:**
- Modify: `quality/expected_python_tests.json`
- Modify: `AGENTS.md`
- Modify: `docs/quality/REGRESSION_POLICY.md`
- Modify: `quality/change_impact.json`
- Modify: `development_records.json`
- Create: `implementation_audit/ios_xage_legal_documents_20260714/verification_report.md`

**Interfaces:**
- Consumes: green source/UI results from Task 2.
- Produces: exact tools inventory `75`, latest matching development record, complete verification report, and a commit eligible for push/PR CI.

- [ ] **Step 1: Register the exact Python test ID**

Insert this ID into the sorted `tools` array in `quality/expected_python_tests.json`:

```json
"test_release_policy.ReleasePolicyTests.test_xage_legal_documents_are_complete_and_product_specific"
```

Keep every existing ID. The exact tools count becomes 75.

- [ ] **Step 2: Update the two normative count statements**

Change only the tools count statements:

```text
AGENTS.md: tools `75` IDs
docs/quality/REGRESSION_POLICY.md: tools 75 的运行时 ID 清单
```

Do not change backend `264`, Unit `158`, full UI `9`, small UI `2`, or union `167`.

- [ ] **Step 3: Run manifest and guard checks**

Run:

```bash
/usr/bin/python3 -I tools/python_test_gate.py tools
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --working
```

Expected: `tools passed; executed=75 skipped=0`; both regression guard commands pass. Any required failure must be saved, explained, and fixed without weakening the contract.

- [ ] **Step 4: Run the full iOS exact profiles**

Run fresh Unit/full UI/small UI commands using the exact templates in `tools/run_regression_gate.py`, then validate:

```bash
/usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-quality-unit.xcresult --expected-profile ios_unit
/usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-quality-ui.xcresult --expected-profile ios_ui_full
/usr/bin/python3 -I tools/validate_xcresult.py --path /tmp/xjie-quality-ui-small.xcresult --expected-profile ios_ui_small --required-device-model 'iPhone SE (3rd generation)'
```

Expected: Unit 158/158, full UI 9/9, small UI 2/2, zero failed/skipped/extra/missing IDs.

- [ ] **Step 5: Run the impacted aggregate and preserve environment blockers honestly**

Run:

```bash
/usr/bin/python3 -I tools/run_regression_gate.py impacted
```

Expected on a compliant machine: tools 75, impacted iOS/backend commands, unsigned generic-device Release archive, bundle verifier, and diff check pass.

If this host still only has Xcode 26.6 or lacks `backend/.venv`, preserve the exact fail-closed output in the audit directory. Do not change `PINNED_XCODE_VERSION`, SDK expectations, command registry, or interpreter trust checks. The Draft PR must remain blocked until exact-SHA CI provides the pinned Xcode 26.3 evidence.

- [ ] **Step 6: Write the durable verification and development records**

The verification report must include:

```markdown
# XJie legal documents verification

## Scope
- Complete 11-section privacy policy.
- Complete 15-section service agreement.
- Shared local SwiftUI legal-document UI and parent-preserving return route.

## Required RED evidence
- Focused source test failed because the legal file was missing.
- Focused UI test failed because the service-agreement entry was missing.

## Passing evidence
- Focused source invariant result.
- Focused UI xcresult.
- Tools 75/75.
- Unit 158/158, full UI 9/9, small UI 2/2.
- PBX/architecture guard and Release-shape result, or the exact local toolchain blocker.

## Remaining review
- Final legal copy requires professional lawyer review before release.
- Simulator automation does not replace VoiceOver, large-text, real-device HealthKit, or real service-provider review.
```

Append a latest `development_records.json` record with ID `2026-07-14-ios-xage-legal-documents`, matching the change-impact domains/contracts/tests/files and using only evidence actually observed.

- [ ] **Step 7: Perform final staged-candidate verification and commit**

Stage only intended paths, excluding:

```text
Xjie/Xjie.xcodeproj/project.xcworkspace/
docs/superpowers/plans/2026-07-13-xage-key-logic-comments.md
docs/superpowers/specs/2026-07-13-xage-key-logic-comments-design.md
```

Run:

```bash
git diff --cached --check
/usr/bin/python3 -I tools/regression_guard.py validate
/usr/bin/python3 -I tools/regression_guard.py check --working
git commit -m "feat(ios-xage): add complete legal documents"
```

Expected: normal commit succeeds without `--no-verify`. Confirm the new commit contains all intended files and the three user-owned paths remain untracked.

- [ ] **Step 8: Push and update the existing Draft PR**

Run:

```bash
git push origin XAGE
gh pr view 8 --repo doyoulikelin-wq/XJie_IOS --json url,isDraft,headRefOid,statusCheckRollup
```

Expected: `origin/XAGE` and PR #8 point to the exact new commit. Do not claim CI green if the run is waiting for fork approval, is attached to another SHA, or has not completed successfully.

---

## Plan Self-Review

- Spec coverage: all 11 privacy chapters, all 15 service chapters, exact company/contact/date, current AI label boundary, medical/emergency/medication disclaimers, navigation, file split, PBX, accessibility, tests, records, and non-goals are assigned to concrete steps.
- Completeness scan: every implementation step contains concrete code, paths, commands, and expected outcomes.
- Type consistency: all three pages consume `onClose: () -> Void`; only the page types cross files; section and permission models remain private; the More Menu uses the exact produced `XAgeServiceAgreementView` type.
- Inventory consistency: XCTest method names are unchanged at 158/9/2/167; the one new Python method is explicitly registered and changes tools from 74 to 75 everywhere.
