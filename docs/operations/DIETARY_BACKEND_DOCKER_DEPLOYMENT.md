# 膳食记录后端 Docker 部署指令

本文用于把已经合并到官方 `main` 的膳食记录后端部署到生产 Docker 环境，解决：

```text
GET /api/dietary-records/dashboard -> 404 {"detail":"Not Found"}
```

膳食功能引入了 `0025_dietary_records` 数据库迁移。若生产数据库仍停留在旧 head，必须使用仓库受控的 `expand-deploy` 流程；禁止直接执行 `docker build`、`docker run`、`docker compose up`、`alembic upgrade`，也禁止直接调用 `/usr/local/sbin/xjie-production-deploy`。受控流程会自行构建 Docker 镜像、演练迁移、备份数据库、校验新旧应用兼容性并完成容器切换。

## 一、部署前条件

开始前逐项确认：

1. 膳食代码已经通过 PR 合并到官方仓库 `doyoulikelin-wq/XJie_IOS` 的 `main`。
2. 记录合并后 `main` 的完整 40 位提交 SHA，以下统一写作 `<MAIN_SHA>`。
3. GitHub Actions 的 `quality-gate` 在 `<MAIN_SHA>` 上成功，而不是其他分支或其他提交。
4. 生产机已经安装仓库规定的七文件 root trust bundle。
5. `/home/mayl/.config/xjie/backend.env` 已由生产管理员配置，文件中包含生产数据库、Redis、JWT、对象存储和模型服务配置；不要把其内容复制到命令、日志或本文。
6. 生产数据库具备独立的应用、只读探测和迁移账号。迁移账号必须具有完成受控 expand migration 所需的权限。
7. 当前生产服务健康，且没有未处理的 bundle-install、cutover 或 expand migration journal。

当前工作树、`XAGE` 分支、未合并提交或 `origin/main` 均不能作为生产候选。

## 二、只读部署前检查

在生产 Linux 主机进入 root shell后执行：

```bash
/usr/local/sbin/xjie-production-launch --doctor

curl --fail --silent --show-error https://www.jianjieaitech.com/healthz

curl --silent --show-error \
  --output /tmp/xjie-dietary-before.body \
  --write-out 'dietary-before HTTP %{http_code}\n' \
  'https://www.jianjieaitech.com/api/dietary-records/dashboard'
```

部署前最后一条当前预计为 `404`。不要在检查命令中加入真实用户 Token。

## 三、准备候选 SHA 与 GitHub Token

将经过独立核对的合并提交填入普通 shell 变量：

```bash
EXPECTED_MAIN_SHA='<MAIN_SHA>'
test "${#EXPECTED_MAIN_SHA}" -eq 40
```

交互式读取 GitHub Token。变量不得导出，Token 不得出现在 argv、环境文件、shell 历史或日志中：

```bash
read -r -s -p 'GitHub token: ' xjie_github_token
printf '\n'
```

Token 必须能够只读验证官方仓库、PR、Actions 检查和 `main`/`XAGE` 分支保护。

## 四、生成并独立审批数据库迁移计划

首次执行受控 expand deployment：

```bash
printf '%s\0' "$xjie_github_token" \
  | /usr/local/sbin/xjie-production-launch \
      "$EXPECTED_MAIN_SHA" expand-deploy --confirm-expand-migration
unset xjie_github_token
```

当尚未安装该候选的 root migration approval 时，流程会在完成候选拉取、Docker 构建、迁移演练和计划生成后 fail closed。计划路径为：

```text
/home/mayl/.locks/xjie-production-expand-plan-<MAIN_SHA>.json
```

由独立的 root 审批人核对：

- `expected_main_sha` 等于 `<MAIN_SHA>`；
- 迁移链是从生产当前 head 线性追加到候选 head；
- 最终 head 包含 `0025_dietary_records`；
- migration、旧/新 schema catalog、operation policy 和 trust bundle 摘要均与本次候选一致；
- 演练结果、旧/新 CRUD 兼容性、备份空间和恢复方案均已审核。

审批人计算该计划文件的 SHA-256：

```bash
PLAN="/home/mayl/.locks/xjie-production-expand-plan-${EXPECTED_MAIN_SHA}.json"
test -f "$PLAN"
/usr/bin/python3 -m json.tool "$PLAN" >/dev/null
PLAN_SHA256="$(sha256sum "$PLAN" | awk '{print $1}')"
printf 'plan sha256: %s\n' "$PLAN_SHA256"
```

然后通过独立的 root provisioning 流程创建：

```text
/etc/xjie-production-deploy/schema-migration-approval.json
```

文件必须是 `root:root 0400`、普通文件、单硬链接，内容严格为：

```json
{"schema_version":1,"expected_main_sha":"<MAIN_SHA>","plan_sha256":"<PLAN_SHA256>"}
```

不要由未审核的 checkout 自动生成这个审批文件；审批文件代表独立的数据库变更授权。

## 五、执行受控 Docker 部署

审批完成后重新交互式读取 Token，并以同一个 `<MAIN_SHA>` 再次执行：

```bash
read -r -s -p 'GitHub token: ' xjie_github_token
printf '\n'

printf '%s\0' "$xjie_github_token" \
  | /usr/local/sbin/xjie-production-launch \
      "$EXPECTED_MAIN_SHA" expand-deploy --confirm-expand-migration
deploy_status=$?

unset xjie_github_token
test "$deploy_status" -eq 0
```

该入口会自动完成：

1. 校验官方 `main`、合并 PR、exact-SHA CI 和分支保护；
2. 从 exact `<MAIN_SHA>` 创建只读源码快照；
3. 构建并绑定 `xjie-backend:main-<MAIN_SHA>` Docker 镜像；
4. 执行完整后端测试和镜像/运行时身份检查；
5. 在隔离 PostgreSQL 中演练追加迁移；
6. 对生产数据库执行只读 catalog probe；
7. 创建数据库备份并在 journal 保护下执行批准的 expand migration；
8. 验证旧应用与新应用 CRUD 兼容性；
9. 启动候选容器和 Celery worker/beat，完成健康检查后原子切换；
10. 保留一个停止状态的上一版本容器作为单次发布回滚备份。

## 六、部署后验证

部署命令成功返回后执行：

```bash
/usr/local/sbin/xjie-production-launch --doctor

curl --fail --silent --show-error https://www.jianjieaitech.com/healthz

curl --silent --show-error \
  --output /tmp/xjie-dietary-after.body \
  --write-out 'dietary-after HTTP %{http_code}\n' \
  'https://www.jianjieaitech.com/api/dietary-records/dashboard'

docker inspect \
  --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
  xjie-api
```

未携带 Token 的膳食接口应从 `404` 变为认证错误（通常是 `401`），证明请求已经进入受保护路由；不要把未认证请求误判为业务成功。`docker inspect` 输出必须等于 `<MAIN_SHA>`。

最后使用专门的合成测试账号登录 App，确认：

1. 进入“快捷功能 → 饮食”不再显示服务缺失提示；
2. dashboard 能返回空状态或真实记录，而不是 404；
3. 文字输入只生成待确认草稿；
4. 明确确认后才创建正式记录；
5. 删除、复用和完成当天记录均符合预期；
6. 不使用真实患者资料进行部署验收。

## 七、失败和恢复要求

- 任一步失败都保留原始退出码和受控 journal，不要手工删除 journal、候选容器、备份容器或数据库备份。
- 不要使用 `docker rm -f xjie-api`、手工改名容器或直接执行 migration 来“继续”。
- 先运行 `/usr/local/sbin/xjie-production-launch --doctor` 获取只读诊断。
- bundle 安装事务中断时，在确认没有 deploy/ingest 进程后使用 `/usr/local/sbin/xjie-production-install --recover`；它只恢复 trust bundle，不替代数据库 cutover 恢复。
- expand/cutover journal 的恢复应再次从受控 launcher 启动，由已安装的可信实现根据 journal 决定恢复动作。
- 如果迁移或候选资格发生变化，废弃旧审批，使用新的 `<MAIN_SHA>`、新计划 SHA-256 和新的受保护 PR 重新开始。

完整安全模型参见 `docs/operations/PRODUCTION_DEPLOYMENT.md`。
