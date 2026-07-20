# XJie iOS 轻量回归与发布制度

生效日期：2026-07-20

## 一、目标

仓库默认采用轻量门禁，优先提供几分钟内可得到的反馈。完整 XCTest、完整后端、真实 PostgreSQL 集成、精确测试清单和重复 Archive 不再自动绑定到每一次开发、PR、CI 与发布操作。

原有完整检查没有删除，统一保留为 `strict` 模式。在账号、HealthKit、AI 安全、数据库迁移、签名或高风险发布中，可由开发者主动启用。

轻量门禁通过只表示输出中列出的检查通过，不表示所有业务功能、设备、系统权限和线上依赖已经验证。

## 二、默认阶段

### `fast`

命令：

```sh
/usr/bin/python3 -I tools/run_regression_gate.py fast
```

检查 tracked/untracked 文件的空白错误、关键 JSON 可解析性以及门禁 Python/Shell 配置语法。不启动 Simulator，不运行 iOS Unit/UI，不构建设备 Archive，也不运行 backend 全量测试。

### `impacted`

命令：

```sh
/usr/bin/python3 -I tools/run_regression_gate.py impacted
```

包含 `fast` 的全部检查，并增加：

- backend 与 tools Python 源码编译检查；
- iOS generic Simulator Debug 编译；
- 工作树在检查期间未发生漂移。

它不自动运行 iOS Unit、完整 UI、小屏 UI、backend full、PG16 集成或 device Archive。

### CI

默认 CI 包含三个轻量 job：

- policy：JSON、Python、Shell、YAML 和差异空白检查；
- backend：Python 源码编译检查；
- iOS：generic Simulator Debug 编译。

最终仍汇总为 `quality-gate`。设置仓库变量 `XJIE_STRICT_GATES=1` 后，工作流恢复执行保留的完整 policy、backend 和 iOS 检查。

### Internal TestFlight 与 Release

默认候选门禁复用 `impacted` 的轻量检查，并绑定当前提交与工作树。它不再次运行完整 Unit/UI/backend/PG 测试，也不为了门禁额外生成一份重复无签名 Archive。

实际 TestFlight 归档或上传仍必须使用：

```sh
scripts/release_testflight.sh --archive-only
scripts/release_testflight.sh --upload
```

签名包/IPA 的身份、profile、entitlement、敏感内容、哈希和上传回执检查继续保留。这些属于制品与凭据安全，不因测试门禁瘦身而关闭。

## 三、Strict 模式

以下命令进入保留的完整实现：

```sh
/usr/bin/python3 -I tools/run_regression_gate.py fast --strict
/usr/bin/python3 -I tools/run_regression_gate.py impacted --strict
/usr/bin/python3 -I tools/run_regression_gate.py internal-testflight --strict
/usr/bin/python3 -I tools/run_regression_gate.py release --strict
```

assert 与 qualify 命令同样支持 `--strict`。Hooks 使用 `XJIE_STRICT_GATES=1` 恢复不可变候选静态合同检查；CI 使用同名 repository variable 恢复完整 job。

Strict 模式继续使用 `quality/regression_contracts.json`、`quality/expected_xctests.json`、`quality/expected_python_tests.json` 和相关验证器。默认轻量模式不声称满足这些精确清单。

## 四、开发要求

- 行为修改仍应写一个与改动直接相关、具有真实断言的回归测试，但不要求默认门禁运行仓库全部测试。
- `quality/change_impact.json` 应如实记录影响范围、验证计划和未覆盖风险。
- 不允许用 `|| true`、空 catch 或吞掉退出码的方式伪造轻量检查成功。
- 不使用 `--no-verify`；默认 Hook 已足够轻量。
- 提交前至少运行 `fast`；准备 PR 时运行 `impacted`。

## 五、默认门禁没有证明的内容

默认轻量结果不证明：

- 181 项 iOS Unit、6 项完整 UI、2 项小屏 UI 或其精确清单已执行；
- 331 项 backend 与 80 项 tools 清单已执行；
- HealthKit、Apple Watch、通知、第三方输入法或 VoiceOver 真机行为正确；
- AI 内容、引用、安全与主体隔离经过真实端到端验证；
- PostgreSQL migration、生产部署和回滚经过集成验证；
- TestFlight 上传后的 Apple processing 和实际安装体验合格。

需要上述结论时，应运行对应 focused test、strict 门禁或完成人工/真实设备验收，并只描述实际取得的证据。
