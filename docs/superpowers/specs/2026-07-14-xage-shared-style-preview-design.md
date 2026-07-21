# XAGE 共享样式与 Canvas 预览设计

日期：2026-07-14

## 目标

建立一个可被生产页面与 Xcode Canvas 同时使用的 XAGE 样式文件。开发者在预览中调整共享组件参数后，实际 APP 页面同步采用这些参数，不再维护预览副本与生产副本两套实现。

## 范围

### 包含

- 页面液态渐变背景。
- 玻璃圆角卡片背景。
- 胶囊按钮与输入背景。
- 渐变主操作按钮。
- 单行玻璃输入框。
- 问题反馈多行输入框示例。
- 剂量、频次和使用说明快捷气泡示例。
- 用药页面专用背景、卡片和胶囊样式对照。
- 一个不依赖网络、登录状态或后端数据的 `#Preview` 样式陈列页。

### 不包含

- 不重新设计现有视觉参数。
- 不改变问题反馈和用药管理的业务逻辑。
- 不把指标卡、评分卡等业务组件全部搬进样式文件。
- 不新增第三方 UI 依赖。
- 不让 Canvas 发起网络请求。

## 方案选择

采用单文件共享方案：创建 `XAgeStyleComponents.swift`，同时容纳生产样式原语和 Canvas 样式陈列页。`XAgeMainView` 与 `XAgeMedicationManagementView` 直接引用该文件中的组件，预览也使用相同类型。

没有采用“生产组件与预览分成两个文件”的方案，因为本次目标是让开发者在一个文件中集中调试。也不采用预览副本方案，因为副本中的修改不会自动作用到 APP，容易造成参数漂移。

## 文件结构

`XAgeStyleComponents.swift` 按以下顺序组织：

1. 通用 XAGE 样式组件。
2. 用药页面专用样式组件。
3. 预览专用的小型示例布局与本地状态。
4. `#Preview` 声明。

用户已确认 `XAgeCapsuleFill.swift` 仅为临时测试文件，可以删除。实施时不复用该文件内容，而是删除文件及其工程引用，并正式创建 `XAgeStyleComponents.swift`。工程文件最终只保留新文件所需的最小文件引用和 Sources 构建阶段条目。

## 通用生产组件

### XAgeLiquidBackground

保留当前页面渐变、光斑、模糊和高光参数，作为 XAGE 页面统一底层背景。

### XAgeGlassCardBackground

保留可配置 `cornerRadius`，用于信息卡、输入区和内容容器。预览同时展示多个常用圆角值，方便比较。

### XAgeCapsuleFill

保留当前白色透明度、材质、描边和生产阴影参数。临时实验文件中的黑色阴影不迁移到共享生产组件；预览中提供独立的阴影对照示例，不改变生产默认值。

### XAgeGradientActionLabel

保留标题、图标、渐变、胶囊裁切和阴影逻辑，用于提交反馈、家庭邀请等主操作按钮。

### XAgeGlassTextField

将焦点字段类型从固定的 `XAgeFamilyField` 泛型化为 `Field: Hashable`。组件仍接收文本绑定、键盘类型、文本内容类型、大小写策略和焦点绑定。`XAgeFamilyField` 保留在家庭功能附近，生产调用行为不变；预览使用自己的本地焦点枚举。

## 用药专用样式组件

以下组件保留原名称与视觉参数，但移动到共享样式文件：

- `XAgeMedicationLiquidBackground`
- `XAgeMedicationGlassCard`
- `XAgeMedicationCapsuleFill`
- `XAgeMedicationPrimaryActionLabel`

用药快捷气泡继续使用 `XAgeMedicationCapsuleFill`，避免样式抽取意外改变现有界面。

`XAgeMedicationFlowLayout` 仍留在用药页面，因为它是布局算法而非颜色、材质或基础视觉原语。预览陈列页使用同类的简单自适应布局来展示气泡，不搬迁业务编辑组件。

## Canvas 样式陈列页

预览页面使用 `ScrollView` 和本地 `@State`，展示：

- 完整 XAGE 液态背景。
- 两种常用圆角的玻璃卡片。
- 胶囊按钮与生产/黑色阴影对照。
- 渐变主按钮。
- 单行玻璃输入框。
- 与问题反馈页一致的多行 `TextEditor`。
- 剂量、频次和使用说明快捷气泡。
- 通用 XAGE 样式与用药专用样式的并列对照。

预览不初始化 ViewModel，不读取环境对象，不执行 `.task`，不访问服务端。

## 生产页面迁移

迁移顺序：

1. 在共享文件中建立组件并保持当前生产参数。
2. 让 `XAgeMainView` 与 `XAgeMedicationManagementView` 编译使用共享组件。
3. 从原文件删除对应的私有重复定义。
4. 将 `XAgeGlassTextField` 调整为泛型焦点字段并验证全部现有调用点。
5. 删除临时 `XAgeCapsuleFill.swift` 及其工程引用，确保每个类型只有一个生产定义。

问题反馈页的 `TextEditor` 继续使用共享 `XAgeCapsuleFill`。业务状态、字数限制、提交接口与错误处理均不改变。

## 工程文件处理

当前 `project.pbxproj` 包含 Xcode 添加文件时产生的大量无关排序差异。实施时只保留：

- `XAgeStyleComponents.swift` 文件引用。
- Home 分组中的文件条目。
- APP target Sources 阶段中的构建条目。

临时 `XAgeCapsuleFill.swift` 的文件引用与 Sources 条目全部移除。

其他排序、PatientHistory 条目重排和与本功能无关的工程结构变化不纳入本次提交。用户的其他未提交业务代码改动继续保留。

## 验证

- 迁移前运行 Debug 构建，记录现有基线；若当前手动文件导致重复定义或工程错误，记录为已知基线并在迁移中消除。
- 迁移后运行 Debug 模拟器构建。
- 确认 `XAgeStyleComponents.swift` 的 `#Preview` 可独立编译，不触发网络和环境对象崩溃。
- 运行用药快捷输入 UI 测试。
- 运行问题反馈入口 UI 测试。
- 执行 `git diff --check`。
- 审计暂存差异，确保工程文件只包含新共享样式文件的必要引用。

## 成功标准

- Canvas 可以在一个文件内查看并调试确认范围内的所有样式。
- 修改共享组件参数时，生产调用方自动使用同一实现。
- APP Debug 构建成功且没有重复类型或 SwiftUI 类型检查超时。
- 用药快捷输入和问题反馈原有交互测试继续通过。
- 无关手动改动和未跟踪文件未被覆盖或提交。
