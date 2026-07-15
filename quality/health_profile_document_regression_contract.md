# 健康画像专项文档回归合同（iOS）

日期：2026-07-15
依据：`/改进/7月15日-健康画像页面修改目标.docx`

## 最小复现与根因

- 旧客户端按自由文本和局部卡片渲染画像，可能用缺单位或未确认的身高/体重猜测 BMI；目标缺少状态、开始时间和关联指标；用药摘要没有稳定真实入口；来源与历史能力边界不清楚。
- 根因是缺少共享字段目录、结构化目标模型、安全派生函数、候选动作策略及可验证路由合同，页面文案本身无法阻止同类回归。

## 永久约束

1. BMI 不是可编辑事实。只有 `user`、`clinician` 或 `verified_source` 确认，且带可信单位的身高和体重才能派生；任何缺失、裸数字、非法范围或 `automatic` 值均显示“待补充”。派生值必须展示两项来源与最新更新时间。
2. 基础资料覆盖出生日期、性别、身高、体重、血型、地区和生活方式；长期健康覆盖诊断、家族史、长期异常、风险因素、主动关注和关联计划。
3. 候选不是事实。目标候选和安全候选只能忽略，不能直接接受；安全事实的新增、修改和删除必须二次确认。
4. 健康目标只能由用户主动创建/调整，并完整保存名称、状态、开始时间和至少一个关联指标。
5. 画像页只显示服务端已确认的长期用药摘要，不展示剂量、提醒或服药动作；按钮必须真实进入用药页。
6. 来源分类、更新时间、当前版本和冲突必须如实展示；服务端未提供逐条修订明细时必须明确说明，禁止伪造历史。
7. 概览只有一个随状态变化的浏览主操作，不提供“永久保存”；X 年龄消费保持禁用。
8. 编辑器统一覆盖键盘滚动收起、未保存返回确认、多行内容、Dynamic Type、安全区和辅助功能语义。

## 覆盖矩阵

| 文档要求 | 实现入口 | 自动化合同 |
| --- | --- | --- |
| 基础资料、长期标签 | `HealthProfileFieldCatalog` | `testHealthProfileTrustUsesServerSubjectExplicitVersionedConfirmationAndIdempotentRetry` |
| 透明 BMI | `HealthProfileDerivedMetrics.bodyMassIndex` | 同上：有效值、单位缺失、未确认值、来源、时间 |
| 事实/候选、安全确认 | `HealthProfileCandidate.canReview`、`PatientHistoryViewModel` | 同上：目标/安全接受失败、幂等、安全二次确认 |
| 结构化用户目标 | `HealthProfileGoalDetails`、目标编辑器 | 同上：不完整不出站、完整对象精确编码 |
| 用药只读摘要与跳转 | `medicationSummary` | `testMetricManagerPageAndChatKeyboardLifecycle` 的画像路径 |
| 来源、版本、历史能力 | `provenance`、`HealthProfileDisplayFormatter.source` | Unit 来源分类 + UI 文案合同 |
| 单一主操作、X 年龄禁用 | `overview`、`useBoundary` | full UI 画像路径 |

## 已执行证据

- `xcodebuild test ... -only-testing:XjieTests/APIServiceTests/testHealthProfileTrustUsesServerSubjectExplicitVersionedConfirmationAndIdempotentRetry`：通过。
- `python3 tools/validate_xcresult.py --path /private/tmp/xjie-profile-doc-final3.xcresult --minimum-tests 1 --required-test XjieTests/APIServiceTests/testHealthProfileTrustUsesServerSubjectExplicitVersionedConfirmationAndIdempotentRetry --required-device-model 'iPhone 17'`：`PASSED; executed=1 expected=1`。
- `/usr/bin/python3 -I tools/regression_guard.py validate`：编辑前及画像首轮实现后均通过。

## 发布前仍需

- 最终稳定树执行 Unit 181、full UI 6、small-screen UI 2、Unit/full-UI union 187 精确清单、tools 77、backend 331（其中 328 passed + 3 固定 skipped）的完整门禁；并保存与验证 `.xcresult`。
- iPhone 真机签核第三方中文输入法、长内容、大字号、VoiceOver、安全区、未保存返回、用药跳转返回，以及真实服务端来源/冲突/修订展示。
- 当前服务端画像概览只提供当前版本和版本号，不提供逐条修订历史列表；这是已披露的产品能力限制，不得据此宣称完整历史已经可浏览。
