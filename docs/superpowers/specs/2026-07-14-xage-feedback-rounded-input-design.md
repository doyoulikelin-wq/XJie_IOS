# XAGE 问题反馈多行输入框圆角调整设计

日期：2026-07-14

## 目标

解决问题反馈多行输入框端部过度圆润的问题。实际 APP 页面与 Xcode Canvas 预览使用同一个共享背景组件，确保预览调试结果与生产页面一致。

## 问题原因

当前问题反馈页和样式预览中的 `TextEditor` 都使用 `XAgeCapsuleFill()` 作为背景。`Capsule` 会根据控件高度自动生成接近高度一半的圆角；当 `TextEditor` 最小高度为 180pt 时，两端会呈现接近半圆的形状，因此看起来像一个放大的胶囊，而不是常见的多行输入框。

## 已选方案

新增共享组件 `XAgeRoundedFieldBackground`，使用连续圆角矩形代替胶囊形状。组件提供可配置的 `cornerRadius`，默认值为 `18pt`。

组件保留现有 `XAgeCapsuleFill` 的视觉参数：

- 白色填充透明度 `0.58`。
- `ultraThinMaterial` 材质。
- 白色描边透明度 `0.88`、线宽 `1pt`。
- 浅蓝色 `7ACAF5` 阴影，透明度 `0.12`、半径 `14pt`、纵向偏移 `7pt`。

唯一的生产视觉变化是将背景形状从 `Capsule` 改为 `RoundedRectangle(cornerRadius: 18, style: .continuous)`。

## 修改范围

### 共享样式文件

在 `XAgeStyleComponents.swift` 的通用生产组件区域增加 `XAgeRoundedFieldBackground`。该组件与 `XAgeCapsuleFill` 并存：

- `XAgeCapsuleFill` 继续服务于单行输入、小按钮和快捷气泡。
- `XAgeRoundedFieldBackground` 专门服务于高度较大的多行输入区域。

### 实际问题反馈页

将 `XAgeMainView.swift` 中 `XAgeProblemFeedbackView.feedbackEditor` 的背景从 `XAgeCapsuleFill()` 替换为 `XAgeRoundedFieldBackground()`。

以下行为保持不变：

- `TextEditor` 最小高度 `180pt`。
- 内边距 `10pt`。
- 字数统计与 2000 字限制。
- 提交、错误提示和后端接口。
- accessibility identifier。

### Canvas 预览

将 `XAgeStyleComponentsPreview.feedbackEditorSection` 中的背景同步替换为 `XAgeRoundedFieldBackground()`，确保预览与实际页面引用同一生产组件。

## 不包含

- 不调整单行输入框圆角。
- 不调整用药快捷气泡、按钮或其他胶囊组件。
- 不改变反馈输入框高度、内边距、字体、颜色或业务状态。
- 不修改反馈提交接口。
- 不新增第三方依赖。

## 测试与验证

- 先增加共享圆角背景的编译契约测试，验证默认圆角为 `18pt`；测试应在组件实现前失败。
- 实现组件后运行该测试，确认由红转绿。
- 运行 Debug 模拟器构建，确认 `#Preview` 可编译且没有 SwiftUI 类型检查超时。
- 运行问题反馈入口 UI 测试，确认页面仍可进入、输入框仍存在、邮箱和提交按钮仍展示。
- 执行 `git diff --check`。
- 审计未提交差异，继续保留用户已有的更多菜单和“剂量/次”改动。

## 成功标准

- 实际问题反馈页与 Canvas 预览中的多行输入框均为 `18pt` 连续圆角矩形。
- 两处使用同一个共享生产组件，不维护样式副本。
- 单行输入、快捷气泡和按钮视觉不受影响。
- Debug 构建及问题反馈 UI 回归通过。
