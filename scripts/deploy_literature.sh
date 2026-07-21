#!/bin/bash -p
# 文献证据库/生产 API 部署入口。
#
# 下列是 root 预装 launcher 传入的内部参数，不是操作员命令：
#   --doctor
#   EXPECTED_SHA [deploy]
#   EXPECTED_SHA ingest --confirm-ingest
# 操作员只能调用 /usr/local/sbin/xjie-production-launch；本文件必须是受监督的内部子进程。

set -euo pipefail
umask 077
readonly PATH="/usr/sbin:/usr/bin:/sbin:/bin"
readonly LC_ALL="C"
readonly HOME="/nonexistent"
readonly XDG_CONFIG_HOME="/nonexistent"
export PATH LC_ALL HOME XDG_CONFIG_HOME
for unsafe_startup_name in TAR_OPTIONS GREP_OPTIONS POSIXLY_CORRECT BASH_COMPAT; do
  if [[ -n "${!unsafe_startup_name+x}" ]]; then
    echo "[fail] 生产部署必须由 clean-environment launcher 启动；拒绝 ${unsafe_startup_name}" >&2
    exit 1
  fi
done
unset TAR_OPTIONS GREP_OPTIONS POSIXLY_CORRECT BASH_COMPAT
unset CDPATH ENV BASH_ENV PYTHONPATH PYTHONHOME PYTHONSTARTUP
while IFS= read -r inherited_name; do
  if [[ "$inherited_name" == BASH_FUNC_* \
    || "$inherited_name" == SHELLOPTS || "$inherited_name" == BASHOPTS ]]; then
    echo "[fail] clean launcher 不得继承 Bash 函数/选项环境: ${inherited_name}" >&2
    exit 1
  fi
  if [[ "$inherited_name" == GIT_* || "$inherited_name" == DOCKER_* \
    || "$inherited_name" == LD_* || "$inherited_name" == DYLD_* ]]; then
    unset "$inherited_name"
  fi
done < <(compgen -e)
unset SSH_ASKPASS SSH_ASKPASS_REQUIRE
unset BUILDKIT_HOST BUILDX_CONFIG
unset http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY no_proxy
unset SSL_CERT_FILE SSL_CERT_DIR REQUESTS_CA_BUNDLE CURL_CA_BUNDLE
unset OPENSSL_CONF SSLKEYLOGFILE PYTHONHTTPSVERIFY
readonly GIT_CONFIG_GLOBAL="/dev/null"
readonly GIT_CONFIG_NOSYSTEM="1"
readonly GIT_TERMINAL_PROMPT="0"
readonly GIT_NO_REPLACE_OBJECTS="1"
readonly GIT_ATTR_NOSYSTEM="1"
export GIT_CONFIG_GLOBAL GIT_CONFIG_NOSYSTEM GIT_TERMINAL_PROMPT \
  GIT_NO_REPLACE_OBJECTS GIT_ATTR_NOSYSTEM
readonly DOCKER_HOST="unix:///var/run/docker.sock"
export DOCKER_HOST

readonly OFFICIAL_ORIGIN_HTTPS="https://github.com/doyoulikelin-wq/XJie_IOS.git"
readonly CANONICAL_BRANCH="main"
readonly SPEC_RELATIVE="backend/deploy/production_container.json"
readonly DEPLOY_GUARD_RELATIVE="backend/deploy/production_deploy_guard.py"
readonly RELEASE_GATE_RELATIVE="tools/run_regression_gate.py"
readonly TEST_INVENTORY_RELATIVE="quality/expected_python_tests.json"
readonly DEPLOY_ENTRYPOINT_RELATIVE="scripts/deploy_literature.sh"
readonly DEPLOY_LAUNCHER_RELATIVE="scripts/launch_production_deploy.py"
readonly DEPLOY_INSTALLER_RELATIVE="scripts/install_production_deploy_bundle.py"
readonly TRUSTED_LAUNCHER="/usr/local/sbin/xjie-production-launch"
readonly TRUSTED_ENTRYPOINT="/usr/local/sbin/xjie-production-deploy"
readonly TRUSTED_INSTALLER="/usr/local/sbin/xjie-production-install"
readonly TRUSTED_BUNDLE_DIR="/usr/local/libexec/xjie-production-deploy"
readonly TRUSTED_SPEC="${TRUSTED_BUNDLE_DIR}/production_container.json"
readonly TRUSTED_DEPLOY_GUARD="${TRUSTED_BUNDLE_DIR}/production_deploy_guard.py"
readonly TRUSTED_RELEASE_GATE="${TRUSTED_BUNDLE_DIR}/run_regression_gate.py"
readonly TRUSTED_TEST_INVENTORY="${TRUSTED_BUNDLE_DIR}/expected_python_tests.json"
readonly LAUNCH_AUTHORITY="/etc/xjie-production-deploy/launch-authority"
readonly DEPLOY_PRINCIPAL="mayl"
readonly DATABASE_PROBE_EXTRA_HOST="host.docker.internal:host-gateway"
readonly STATE_DIR="/home/mayl/.locks"
readonly CUTOVER_JOURNAL="${STATE_DIR}/xjie-production-cutover.json"
readonly RUNTIME_PARENT="/dev/shm"
readonly EXPECTED_SHA="${1:-}"
readonly ACTION="${2:-deploy}"
readonly ACTION_CONFIRMATION="${3:-}"

runtime_dir=""
runtime_base=""
source_root=""
spec_path="$TRUSTED_SPEC"
deploy_guard="$TRUSTED_DEPLOY_GUARD"
env_snapshot=""
database_probe_env_snapshot=""
database_migration_env_snapshot=""
container_name=""
image_repository=""
secret_env_file=""
database_probe_image=""
database_probe_image_id=""
container_health_url=""
public_health_url=""
candidate_container=""
candidate_container_id=""
cutover_candidate_name=""
ephemeral_container=""
ephemeral_container_id=""
ephemeral_image_id=""
ephemeral_role=""
reference_server=""
reference_server_id=""
reference_server_image_id=""
reference_server_role=""
reference_socket_dir=""
reference_password=""
restore_volume_name=""
restore_volume_image_id=""
restore_volume_owned=0
backup_container=""
old_container_id=""
old_image_id=""
image_id=""
new_container_id=""
old_container_stopped=0
deployment_committed=0
deployment_run_id=""
trusted_bundle_sha256=""
expand_journal=""
expand_approval_plan=""
expand_migration_plan=""
expand_backup_path=""
expand_evidence_path=""
expand_rehearsal_password=""
lifecycle_args=()
supervised_service_names=()
supervised_service_ids=()
supervised_service_roles=()

step() { echo -e "\n\033[1;36m==>\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ok]\033[0m $*"; }
fail() { echo -e "\033[1;31m[fail]\033[0m $*" >&2; exit 1; }

acquire_or_validate_deploy_lock() {
  [[ "${XJIE_DEPLOY_LOCK_SUPERVISED:-}" == "1" ]] \
    || fail "deploy/ingest 必须处于 root lock supervisor 的受控进程组"
  unset XJIE_DEPLOY_LOCK_SUPERVISED
}

broker_request() {
  local request=$1
  [[ "${XJIE_DEPLOY_BROKER_FD:-}" == "8" \
    && "${XJIE_DEPLOY_LEGACY_LOCK_FD:-}" == "10" ]] \
    || fail "deploy/ingest 缺少 root validation broker"
  /usr/bin/python3 -I - "$request" "$PPID" <<'PY'
import socket
import struct
import sys

request, expected_supervisor = sys.argv[1:]
broker = socket.fromfd(8, socket.AF_UNIX, socket.SOCK_SEQPACKET)
try:
    peer_pid, peer_uid, peer_gid = struct.unpack(
        "3i", broker.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
    )
    if (
        peer_pid != int(expected_supervisor)
        or peer_pid <= 1
        or peer_uid != 0
        or peer_gid != 0
    ):
        raise SystemExit("validation broker peer is not the root supervisor")
    payload = request.encode("ascii") + b"\0"
    if len(payload) > 256 or broker.send(payload) != len(payload):
        raise SystemExit("cannot send validation broker request")
    response = broker.recv(1025)
finally:
    broker.close()
if (
    len(response) > 1024
    or not response.endswith(b"\0")
    or b"\0" in response[:-1]
):
    raise SystemExit("validation broker response framing is invalid")
try:
    response_text = response[:-1].decode("ascii")
except UnicodeDecodeError:
    raise SystemExit("validation broker response is not ASCII")
if not response_text.startswith("OK "):
    raise SystemExit("root validation broker rejected the request")
print(response_text.removeprefix("OK "))
PY
}

validate_clean_launcher_authority() {
  [[ "${XJIE_DEPLOY_LAUNCHER_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] \
    || fail "deploy/ingest 必须由 root clean-environment launcher 启动"
  broker_request PING >/dev/null
}

git() {
  /usr/bin/git \
    -c core.hooksPath=/dev/null \
    -c core.fsmonitor=false \
    -c core.untrackedCache=false \
    -c protocol.file.allow=never \
    -c http.sslVerify=true \
    -c http.sslCAInfo=/etc/ssl/certs/ca-certificates.crt \
    -c http.proxy= \
    "$@"
}

assert_root_controlled_directory() {
  local path=$1
  local metadata owner group mode
  [[ -d "$path" && ! -L "$path" ]] || fail "受信目录缺失或是符号链接: ${path}"
  metadata=$(stat -c '%u:%g:%a' "$path") || fail "无法读取受信目录身份: ${path}"
  IFS=: read -r owner group mode <<<"$metadata"
  [[ "$owner" == "0" && "$group" == "0" ]] \
    || fail "受信目录必须由 root:root 持有: ${path}"
  (( (8#$mode & 8#022) == 0 )) || fail "受信目录不能由 group/other 写入: ${path}"
}

assert_root_owned_file() {
  local path=$1
  local expected_mode=$2
  local metadata owner group mode links kind
  [[ -f "$path" && ! -L "$path" ]] || fail "受信文件缺失或不是普通文件: ${path}"
  metadata=$(stat -c '%u:%g:%a:%h:%F' "$path") || fail "无法读取受信文件身份: ${path}"
  IFS=: read -r owner group mode links kind <<<"$metadata"
  [[ "$owner" == "0" && "$group" == "0" && "$mode" == "$expected_mode" \
    && "$links" == "1" && "$kind" == "regular file" ]] \
    || fail "受信文件 owner/mode/link/type 不正确: ${path}"
}

assert_trusted_bundle() {
  local invoked_path
  invoked_path=$(readlink -f -- "$0") || fail "无法解析生产部署入口"
  [[ "$invoked_path" == "$TRUSTED_ENTRYPOINT" ]] \
    || fail "只能运行 root 预装入口 ${TRUSTED_ENTRYPOINT}"
  for directory in / /usr /usr/local /usr/local/sbin /usr/local/libexec \
    "$TRUSTED_BUNDLE_DIR" /etc /etc/xjie-production-deploy; do
    assert_root_controlled_directory "$directory"
  done
  assert_root_owned_file "$TRUSTED_LAUNCHER" 555
  assert_root_owned_file "$TRUSTED_ENTRYPOINT" 555
  assert_root_owned_file "$TRUSTED_SPEC" 444
  assert_root_owned_file "$TRUSTED_DEPLOY_GUARD" 444
  assert_root_owned_file "$TRUSTED_RELEASE_GATE" 444
  assert_root_owned_file "$TRUSTED_TEST_INVENTORY" 444
  assert_root_owned_file "$TRUSTED_INSTALLER" 555
  assert_root_owned_file "$LAUNCH_AUTHORITY" 400
}

compute_trusted_bundle_sha256() {
  /usr/bin/python3 -I - \
    "$TRUSTED_LAUNCHER" "$TRUSTED_ENTRYPOINT" "$TRUSTED_SPEC" \
    "$TRUSTED_DEPLOY_GUARD" "$TRUSTED_RELEASE_GATE" \
    "$TRUSTED_TEST_INVENTORY" "$TRUSTED_INSTALLER" <<'PY'
import hashlib
import os
import stat
import sys

digest = hashlib.sha256()
for path in sys.argv[1:]:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_mode,
            metadata.st_uid,
            metadata.st_gid,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or metadata.st_nlink != 1
            or metadata.st_size > 16 * 1024 * 1024
        ):
            raise SystemExit("trusted bundle file identity changed")
        encoded_path = path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(metadata.st_size.to_bytes(8, "big"))
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        observed = os.fstat(descriptor)
        observed_identity = (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_uid,
            observed.st_gid,
            observed.st_nlink,
            observed.st_size,
            observed.st_mtime_ns,
            observed.st_ctime_ns,
        )
        if observed_identity != identity:
            raise SystemExit("trusted bundle file changed while hashing")
    finally:
        os.close(descriptor)
print(digest.hexdigest())
PY
}

compute_trusted_launcher_sha256() {
  /usr/bin/python3 -I - "$TRUSTED_LAUNCHER" <<'PY'
import hashlib
import os
import stat
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
try:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != 0
        or before.st_gid != 0
        or stat.S_IMODE(before.st_mode) != 0o555
        or before.st_nlink != 1
    ):
        raise SystemExit("trusted launcher identity is invalid")
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    after = os.fstat(descriptor)
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
        value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns,
    )
    if identity(before) != identity(after) or total != before.st_size:
        raise SystemExit("trusted launcher changed while hashing")
finally:
    os.close(descriptor)
print(digest.hexdigest())
PY
}

container_exists() {
  docker container inspect "$1" >/dev/null 2>&1
}

assert_exact_stopped_one_shot() {
  local expected_id=$1
  local expected_image=$2
  local label=$3
  local metadata observed_id observed_image running exit_code
  metadata=$(docker container inspect \
    --format '{{.Id}}|{{.Image}}|{{.State.Running}}|{{.State.ExitCode}}' \
    "$expected_id") || fail "无法读取 ${label} one-shot 容器状态"
  IFS='|' read -r observed_id observed_image running exit_code <<<"$metadata"
  [[ "$observed_id" == "$expected_id" \
    && "$observed_image" == "$expected_image" \
    && "$running" == "false" \
    && "$exit_code" == "0" ]] \
    || fail "${label} one-shot 容器未以 exact ID/image 正常停止"
}

container_internal_health() {
  local name=$1
  docker exec "$name" python -I -c \
    "import json,urllib.request; r=urllib.request.urlopen('${container_health_url}',timeout=3); p=json.loads(r.read()); raise SystemExit(0 if r.status == 200 and p == {'ok': True} else 1)" \
    >/dev/null 2>&1
}

public_health() {
  /usr/bin/python3 -I - "$public_health_url" <<'PY' >/dev/null 2>&1
import json
import ssl
import sys
import urllib.request

context = ssl.create_default_context()
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    urllib.request.HTTPSHandler(context=context),
)
with opener.open(sys.argv[1], timeout=3) as response:
    payload = json.loads(response.read().decode("utf-8"))
if response.status != 200 or payload != {"ok": True}:
    raise SystemExit(1)
PY
}

verify_running_revision() {
  local expected=$1
  local image revision container_revision
  image=$(docker container inspect --format '{{.Image}}' "$container_name")
  revision=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image")
  container_revision=$(docker container inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$container_name")
  [[ "$revision" == "$expected" && "$container_revision" == "$expected" ]] \
    || fail "运行容器没有绑定 EXPECTED_SHA=${expected}"
}

run_confirmed_ingest() {
  local name="${container_name}-deploy-${deployment_run_id}-literature-ingest"
  local args_path="${runtime_dir}/literature-ingest-args.bin"
  local -a command_args
  step "抓取种子文献（约 500 条，预计 30-60 分钟）"
  echo "    已收到独立 --confirm-ingest；任务在可按 immutable ID 回收的 one-shot 容器中执行。"
  /usr/bin/python3 -I "$deploy_guard" create-args \
    --spec "$spec_path" \
    --name "$name" \
    --image "$old_image_id" \
    --image-ref "$image_ref" \
    --env-file "$env_snapshot" \
    --env-source "$secret_env_file" \
    --expected-sha "$EXPECTED_SHA" \
    --run-id "$deployment_run_id" \
    --role literature-ingest \
    --output "$args_path" \
    -- python -I -m app.workers.literature_ingest \
      --seed app/workers/literature_seeds.json
  mapfile -d '' -t command_args <"$args_path"
  ephemeral_container="$name"
  docker "${command_args[@]}" >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="literature-ingest"
  [[ "$ephemeral_image_id" == "$old_image_id" ]] \
    || fail "文献导入 one-shot 容器没有绑定当前生产 image ID"
  /usr/bin/timeout --signal=TERM --kill-after=10s 3600s \
    docker container start --attach "$ephemeral_container_id"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" "文献导入"
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  ok "种子抓取完成"
}

recover_interrupted_cutover() {
  [[ -e "$CUTOVER_JOURNAL" || -L "$CUTOVER_JOURNAL" ]] || return 0
  local journal_output="${runtime_dir}/cutover-journal.bin"
  local recovery_plan="${runtime_dir}/recovery-plan.bin"
  local official_inspect="${runtime_dir}/recovery-official.json"
  local backup_inspect="${runtime_dir}/recovery-backup.json"
  local candidate_inspect="${runtime_dir}/recovery-candidate.json"
  local -a journal_values recovery_arguments=() recovery_actions=() current_actions=()
  local journal_state journal_sha journal_bundle journal_container journal_backup journal_candidate
  local journal_old_container_id journal_candidate_container_id
  local journal_old_image_id journal_candidate_image_id
  local action observed_id observed_image ready=0 attempt action_index compare_index

  /usr/bin/python3 -I "$deploy_guard" read-journal \
    --journal "$CUTOVER_JOURNAL" \
    --output "$journal_output"
  mapfile -d '' -t journal_values <"$journal_output"
  [[ "${#journal_values[@]}" -eq 10 ]] \
    || fail "cutover journal 字段数不正确"
  journal_state=${journal_values[0]}
  journal_sha=${journal_values[1]}
  journal_bundle=${journal_values[2]}
  journal_container=${journal_values[3]}
  journal_backup=${journal_values[4]}
  journal_candidate=${journal_values[5]}
  journal_old_container_id=${journal_values[6]}
  journal_candidate_container_id=${journal_values[7]}
  journal_old_image_id=${journal_values[8]}
  journal_candidate_image_id=${journal_values[9]}
  [[ "$journal_bundle" == "$trusted_bundle_sha256" ]] \
    || fail "活动 journal 由另一受信 bundle 写入；恢复精确旧 bundle 后再继续"
  [[ "$journal_container" == "$container_name" ]] \
    || fail "cutover journal 容器名与生产规范不一致"

  step "恢复中断的 cutover（state=${journal_state}, sha=${journal_sha}）"
  if container_exists "$journal_container"; then
    docker container inspect "$journal_container" >"$official_inspect"
    recovery_arguments+=(--official "$official_inspect")
  fi
  if container_exists "$journal_backup"; then
    docker container inspect "$journal_backup" >"$backup_inspect"
    recovery_arguments+=(--backup "$backup_inspect")
  fi
  if container_exists "$journal_candidate"; then
    docker container inspect "$journal_candidate" >"$candidate_inspect"
    recovery_arguments+=(--named-candidate "$candidate_inspect")
  fi
  /usr/bin/python3 -I "$deploy_guard" plan-recovery \
    --journal "$CUTOVER_JOURNAL" \
    "${recovery_arguments[@]}" \
    --output "$recovery_plan"
  mapfile -d '' -t recovery_actions <"$recovery_plan"
  [[ "${#recovery_actions[@]}" -ge 1 ]] || fail "恢复计划不能为空"
  rm -f -- "$official_inspect" "$backup_inspect" "$candidate_inspect" \
    "$journal_output" "$recovery_plan"

  for ((action_index = 0; action_index < ${#recovery_actions[@]}; action_index += 1)); do
    action=${recovery_actions[$action_index]}
    recovery_arguments=()
    current_actions=()
    rm -f -- "$official_inspect" "$backup_inspect" "$candidate_inspect" \
      "$recovery_plan"
    if container_exists "$journal_container"; then
      docker container inspect "$journal_container" >"$official_inspect"
      recovery_arguments+=(--official "$official_inspect")
    fi
    if container_exists "$journal_backup"; then
      docker container inspect "$journal_backup" >"$backup_inspect"
      recovery_arguments+=(--backup "$backup_inspect")
    fi
    if container_exists "$journal_candidate"; then
      docker container inspect "$journal_candidate" >"$candidate_inspect"
      recovery_arguments+=(--named-candidate "$candidate_inspect")
    fi
    /usr/bin/python3 -I "$deploy_guard" plan-recovery \
      --journal "$CUTOVER_JOURNAL" \
      "${recovery_arguments[@]}" \
      --output "$recovery_plan"
    mapfile -d '' -t current_actions <"$recovery_plan"
    if [[ "$action" == "verify_official_old" \
      && "${#current_actions[@]}" -eq 2 \
      && "${current_actions[0]}" == "verify_named_candidate_quarantined" \
      && "${current_actions[1]}" == "verify_official_old" ]]; then
      : # The preceding verification is non-mutating and therefore remains planned.
    else
      [[ "${#current_actions[@]}" -eq "$(( ${#recovery_actions[@]} - action_index ))" ]] \
        || fail "恢复动作前完整计划长度发生变化"
      for ((compare_index = 0; compare_index < ${#current_actions[@]}; compare_index += 1)); do
        [[ "${current_actions[$compare_index]}" == "${recovery_actions[$((action_index + compare_index))]}" ]] \
          || fail "恢复动作前容器拓扑或剩余计划发生变化"
      done
    fi
    rm -f -- "$official_inspect" "$backup_inspect" "$candidate_inspect" \
      "$recovery_plan"
    case "$action" in
      stop_official_candidate)
        observed_id=$(docker container inspect --format '{{.Id}}' "$journal_container")
        observed_image=$(docker container inspect --format '{{.Image}}' "$journal_container")
        [[ "$observed_id" == "$journal_candidate_container_id" \
          && "$observed_image" == "$journal_candidate_image_id" ]] \
          || fail "停止前正式候选容器身份已变化"
        docker container stop --time 10 "$journal_candidate_container_id" >/dev/null
        ;;
      quarantine_official_candidate)
        container_exists "$journal_candidate" \
          && fail "隔离正式候选前原候选名称已被占用"
        observed_id=$(docker container inspect --format '{{.Id}}' "$journal_container")
        observed_image=$(docker container inspect --format '{{.Image}}' "$journal_container")
        [[ "$observed_id" == "$journal_candidate_container_id" \
          && "$observed_image" == "$journal_candidate_image_id" \
          && "$(docker container inspect --format '{{.State.Running}}' "$journal_container")" == "false" ]] \
          || fail "隔离前正式候选容器身份或状态已变化"
        docker container rename "$journal_candidate_container_id" "$journal_candidate"
        ;;
      rename_backup_to_official)
        container_exists "$journal_container" \
          && fail "恢复旧容器前正式名称仍被占用"
        observed_id=$(docker container inspect --format '{{.Id}}' "$journal_backup")
        observed_image=$(docker container inspect --format '{{.Image}}' "$journal_backup")
        [[ "$observed_id" == "$journal_old_container_id" \
          && "$observed_image" == "$journal_old_image_id" ]] \
          || fail "重命名前回滚容器身份已变化"
        docker container rename "$journal_old_container_id" "$journal_container"
        ;;
      start_official)
        observed_id=$(docker container inspect --format '{{.Id}}' "$journal_container")
        observed_image=$(docker container inspect --format '{{.Image}}' "$journal_container")
        [[ "$observed_id" == "$journal_old_container_id" \
          && "$observed_image" == "$journal_old_image_id" ]] \
          || fail "启动前旧正式容器身份已变化"
        docker container start "$journal_old_container_id" >/dev/null
        ;;
      verify_named_candidate_quarantined)
        observed_id=$(docker container inspect --format '{{.Id}}' "$journal_candidate")
        observed_image=$(docker container inspect --format '{{.Image}}' "$journal_candidate")
        [[ "$observed_id" == "$journal_candidate_container_id" \
          && "$observed_image" == "$journal_candidate_image_id" \
          && "$(docker container inspect --format '{{.State.Running}}' "$journal_candidate")" == "false" ]] \
          || fail "隔离候选容器身份或状态已变化"
        ;;
      verify_official_old)
        observed_id=$(docker container inspect --format '{{.Id}}' "$journal_container")
        observed_image=$(docker container inspect --format '{{.Image}}' "$journal_container")
        [[ "$observed_id" == "$journal_old_container_id" \
          && "$observed_image" == "$journal_old_image_id" ]] \
          || fail "恢复后的正式容器不是 journal 记录的旧实例"
        for ((attempt = 0; attempt < 30; attempt += 1)); do
          if container_internal_health "$journal_container"; then
            ready=1
            break
          fi
          sleep 1
        done
        [[ "$ready" -eq 1 ]] || fail "中断 cutover 恢复后旧容器未通过 healthz"
        ;;
      *) fail "恢复 guard 返回未知动作" ;;
    esac
  done
  observed_id=$(docker container inspect --format '{{.Id}}' "$journal_container")
  observed_image=$(docker container inspect --format '{{.Image}}' "$journal_container")
  [[ "$observed_id" == "$journal_old_container_id" \
    && "$observed_image" == "$journal_old_image_id" \
    && "$(docker container inspect --format '{{.State.Running}}' "$journal_container")" == "true" ]] \
    || fail "清除 journal 前旧正式容器身份或状态发生变化"
  if container_exists "$journal_candidate"; then
    [[ "$(docker container inspect --format '{{.Id}}' "$journal_candidate")" == "$journal_candidate_container_id" \
      && "$(docker container inspect --format '{{.Image}}' "$journal_candidate")" == "$journal_candidate_image_id" \
      && "$(docker container inspect --format '{{.State.Running}}' "$journal_candidate")" == "false" ]] \
      || fail "清除 journal 前隔离候选身份或状态发生变化"
  fi
  container_internal_health "$journal_container" \
    || fail "清除 journal 前恢复的旧正式容器健康检查失败"
  /usr/bin/python3 -I "$deploy_guard" clear-journal \
    --journal "$CUTOVER_JOURNAL"
  ok "已按持久 journal 恢复旧生产容器并清理候选"
}

emit_lifecycle_label_args() {
  local name=$1
  local image=$2
  local role=$3
  local output="${runtime_dir}/labels-${role}.bin"
  rm -f -- "$output"
  /usr/bin/python3 -I "$deploy_guard" emit-lifecycle-labels \
    --name "$name" \
    --image "$image" \
    --expected-sha "$EXPECTED_SHA" \
    --run-id "$deployment_run_id" \
    --role "$role" \
    --output "$output"
  mapfile -d '' -t lifecycle_args <"$output"
  rm -f -- "$output"
  [[ "${#lifecycle_args[@]}" -eq 18 ]] \
    || fail "部署生命周期标签参数数量不正确"
}

remove_exact_restore_volume() {
  local inspect_path attached_path observed_name
  [[ "$restore_volume_owned" -eq 1 ]] || return 0
  [[ -n "$restore_volume_name" && -n "$restore_volume_image_id" \
    && -n "$deployment_run_id" ]] || return 1
  inspect_path="${runtime_dir}/restore-volume-remove-inspect.json"
  attached_path="${runtime_dir}/restore-volume-attached-containers.txt"
  if ! docker volume inspect "$restore_volume_name" >"$inspect_path" 2>/dev/null; then
    observed_name=$(docker volume ls --quiet \
      --filter "name=^${restore_volume_name}$") || return 1
    [[ -z "$observed_name" ]] || return 1
    restore_volume_owned=0
    restore_volume_name=""
    restore_volume_image_id=""
    rm -f -- "$inspect_path" "$attached_path"
    return 0
  fi
  chmod 600 "$inspect_path" || return 1
  /usr/bin/python3 -I "$deploy_guard" \
    validate-expand-restore-volume-inspect \
    --inspect "$inspect_path" --name "$restore_volume_name" \
    --expected-sha "$EXPECTED_SHA" --run-id "$deployment_run_id" \
    --image-id "$restore_volume_image_id" || return 1
  docker container ls --all --quiet --no-trunc \
    --filter "volume=${restore_volume_name}" >"$attached_path" || return 1
  [[ ! -s "$attached_path" ]] || return 1
  docker volume rm "$restore_volume_name" >/dev/null || return 1
  if docker volume inspect "$restore_volume_name" >/dev/null 2>&1; then
    return 1
  fi
  observed_name=$(docker volume ls --quiet \
    --filter "name=^${restore_volume_name}$") || return 1
  [[ -z "$observed_name" ]] || return 1
  rm -f -- "$inspect_path" "$attached_path"
  restore_volume_owned=0
  restore_volume_name=""
  restore_volume_image_id=""
}

cleanup_managed_restore_volumes() {
  local names_path inspect_path plan_path relist_path recheck_path replan_path
  local record_index field_index volume_name attached_path observed_name found
  local official_id
  local -a names=() relisted=() plan=() replan=()
  names_path="${runtime_dir}/managed-restore-volume-names.txt"
  inspect_path="${runtime_dir}/managed-restore-volume-inspects.json"
  plan_path="${runtime_dir}/managed-restore-volume-plan.bin"
  relist_path="${runtime_dir}/managed-restore-volume-relisted.txt"
  recheck_path="${runtime_dir}/managed-restore-volume-recheck.json"
  replan_path="${runtime_dir}/managed-restore-volume-replan.bin"
  attached_path="${runtime_dir}/managed-restore-volume-attached.txt"
  official_id=$(docker container inspect --format '{{.Id}}' "$container_name")
  [[ "$official_id" =~ ^[0-9a-f]{64}$ \
    && "$(docker container inspect --format '{{.State.Running}}' "$official_id")" \
      == "true" ]] \
    || fail "restore volume 清理前正式容器身份不安全"

  docker volume ls --quiet \
    --filter "label=com.jianjieaitech.xjie.deploy.scope=production-api" \
    --filter "label=com.jianjieaitech.xjie.deploy.role=schema-restore-volume" \
    >"$names_path"
  mapfile -t names <"$names_path"
  if [[ "${#names[@]}" -eq 0 ]]; then
    rm -f -- "$names_path"
    return 0
  fi
  docker volume inspect "${names[@]}" >"$inspect_path"
  chmod 600 "$inspect_path"
  /usr/bin/python3 -I "$deploy_guard" \
    plan-expand-restore-volume-cleanup \
    --inspects "$inspect_path" --output "$plan_path"
  mapfile -d '' -t plan <"$plan_path"
  [[ "${#plan[@]}" -eq "$((1 + 6 * ${#names[@]}))" \
    && "${plan[0]}" == "restore-volume-cleanup-v1" ]] \
    || fail "受管 restore volume 清理计划不完整"

  docker volume ls --quiet \
    --filter "label=com.jianjieaitech.xjie.deploy.scope=production-api" \
    --filter "label=com.jianjieaitech.xjie.deploy.role=schema-restore-volume" \
    >"$relist_path"
  mapfile -t relisted <"$relist_path"
  [[ "${#relisted[@]}" -eq "${#names[@]}" ]] \
    || fail "restore volume 清理前集合数量发生变化"
  for volume_name in "${names[@]}"; do
    found=0
    for observed_name in "${relisted[@]}"; do
      [[ "$observed_name" == "$volume_name" ]] && found=1
    done
    [[ "$found" -eq 1 ]] || fail "restore volume 清理前集合身份发生变化"
  done
  docker volume inspect "${relisted[@]}" >"$recheck_path"
  chmod 600 "$recheck_path"
  /usr/bin/python3 -I "$deploy_guard" \
    plan-expand-restore-volume-cleanup \
    --inspects "$recheck_path" --output "$replan_path"
  mapfile -d '' -t replan <"$replan_path"
  [[ "${#replan[@]}" -eq "${#plan[@]}" ]] \
    || fail "restore volume 清理前计划数量发生变化"
  for ((field_index = 0; field_index < ${#plan[@]}; field_index += 1)); do
    [[ "${replan[$field_index]}" == "${plan[$field_index]}" ]] \
      || fail "restore volume 清理前身份发生变化"
  done

  for ((record_index = 1; record_index < ${#plan[@]}; record_index += 6)); do
    [[ "${plan[$record_index]}" == "remove_restore_volume" ]] \
      || fail "restore volume 清理包含未知动作"
    volume_name=${plan[$((record_index + 1))]}
    [[ "$(docker container inspect --format '{{.Id}}' "$container_name")" \
      == "$official_id" \
      && "$(docker container inspect --format '{{.State.Running}}' "$official_id")" \
      == "true" ]] \
      || fail "restore volume 删除前正式容器身份发生变化"
    container_internal_health "$container_name" \
      || fail "restore volume 删除前正式容器不健康"
    docker container ls --all --quiet --no-trunc \
      --filter "volume=${volume_name}" >"$attached_path"
    [[ ! -s "$attached_path" ]] \
      || fail "restore volume 仍挂载到容器，拒绝清理"
    if ! docker volume inspect "$volume_name" >"$recheck_path" 2>/dev/null; then
      observed_name=$(docker volume ls --quiet \
        --filter "name=^${volume_name}$") \
        || fail "无法区分已收敛 restore volume 与 Docker daemon 故障"
      [[ -z "$observed_name" ]] \
        || fail "restore volume 仍存在但无法 inspect"
      continue
    fi
    chmod 600 "$recheck_path"
    /usr/bin/python3 -I "$deploy_guard" \
      plan-expand-restore-volume-cleanup \
      --inspects "$recheck_path" --output "$replan_path"
    mapfile -d '' -t replan <"$replan_path"
    [[ "${#replan[@]}" -eq 7 \
      && "${replan[0]}" == "${plan[0]}" ]] \
      || fail "restore volume 删除前不再是唯一受管对象"
    for ((field_index = 0; field_index < 6; field_index += 1)); do
      [[ "${replan[$((field_index + 1))]}" \
        == "${plan[$((record_index + field_index))]}" ]] \
        || fail "restore volume 删除前 exact identity 变化"
    done
    docker volume rm "$volume_name" >/dev/null
    if docker volume inspect "$volume_name" >/dev/null 2>&1; then
      fail "restore volume 删除后仍存在"
    fi
    observed_name=$(docker volume ls --quiet \
      --filter "name=^${volume_name}$")
    [[ -z "$observed_name" ]] || fail "restore volume 删除后仍被列出"
  done
  rm -f -- "$names_path" "$inspect_path" "$plan_path" "$relist_path" \
    "$recheck_path" "$replan_path" "$attached_path"
}

cleanup_prejournal_orphans() {
  local list_path="${runtime_dir}/managed-container-ids.txt"
  local inspect_path="${runtime_dir}/managed-container-inspects.json"
  local plan_path="${runtime_dir}/managed-container-plan.bin"
  local relist_path="${runtime_dir}/managed-container-relisted-ids.txt"
  local recheck_path="${runtime_dir}/managed-container-rechecks.json"
  local replan_path="${runtime_dir}/managed-container-replan.bin"
  local official_id official_image observed_id observed_image observed_name remaining_id
  local record_index field_index container_id
  local original_id relisted_id original_found
  local -a managed_ids=() relisted_ids=() planned_ids=() plan=() replan=()

  [[ ! -e "$CUTOVER_JOURNAL" && ! -L "$CUTOVER_JOURNAL" ]] \
    || fail "journal 尚未恢复并清除，禁止进入 pre-journal 孤儿回收"
  container_exists "$container_name" || fail "正式容器 ${container_name} 不存在"
  [[ "$(docker container inspect --format '{{.State.Running}}' "$container_name")" == "true" ]] \
    || fail "孤儿回收前正式容器未运行"
  official_id=$(docker container inspect --format '{{.Id}}' "$container_name")
  official_image=$(docker container inspect --format '{{.Image}}' "$container_name")
  container_internal_health "$container_name" || fail "孤儿回收前正式容器健康检查失败"

  docker container ls --all --quiet --no-trunc \
    --filter "label=com.jianjieaitech.xjie.deploy.scope=production-api" \
    >"$list_path"
  mapfile -t managed_ids <"$list_path"
  rm -f -- "$list_path"
  if [[ "${#managed_ids[@]}" -gt 0 ]]; then
    docker container inspect "${managed_ids[@]}" >"$inspect_path"
  else
    printf '[]\n' >"$inspect_path"
  fi
  chmod 600 "$inspect_path"
  /usr/bin/python3 -I "$deploy_guard" plan-orphan-cleanup \
    --inspects "$inspect_path" \
    --output "$plan_path"
  mapfile -d '' -t plan <"$plan_path"
  rm -f -- "$inspect_path" "$plan_path"
  [[ "${#plan[@]}" -ge 1 && "${plan[0]}" == "orphan-cleanup-v1" ]] \
    || fail "孤儿回收计划版本不正确"
  [[ "$(( (${#plan[@]} - 1) % 7 ))" -eq 0 ]] \
    || fail "孤儿回收计划字段数不正确"

  for ((record_index = 1; record_index < ${#plan[@]}; record_index += 7)); do
    [[ "${plan[$record_index]}" == "remove_orphan" ]] \
      || fail "孤儿回收计划包含未知动作"
    planned_ids+=("${plan[$((record_index + 1))]}")
  done

  # Finish the second, whole-batch validation before the first destructive call.
  # A disappearing/changed later object therefore cannot produce a partial cleanup.
  if [[ "${#planned_ids[@]}" -gt 0 ]]; then
    docker container ls --all --quiet --no-trunc \
      --filter "label=com.jianjieaitech.xjie.deploy.scope=production-api" \
      >"$relist_path"
    mapfile -t relisted_ids <"$relist_path"
    rm -f -- "$relist_path"
    [[ "${#relisted_ids[@]}" -eq "${#managed_ids[@]}" ]] \
      || fail "孤儿删除前受管容器集合数量发生变化"
    for original_id in "${managed_ids[@]}"; do
      original_found=0
      for relisted_id in "${relisted_ids[@]}"; do
        if [[ "$relisted_id" == "$original_id" ]]; then
          original_found=1
          break
        fi
      done
      [[ "$original_found" -eq 1 ]] \
        || fail "孤儿删除前受管容器集合身份发生变化"
    done
    docker container inspect "${managed_ids[@]}" >"$recheck_path"
    chmod 600 "$recheck_path"
    /usr/bin/python3 -I "$deploy_guard" plan-orphan-cleanup \
      --inspects "$recheck_path" \
      --output "$replan_path"
    mapfile -d '' -t replan <"$replan_path"
    rm -f -- "$recheck_path" "$replan_path"
    [[ "${#replan[@]}" -eq "${#plan[@]}" ]] \
      || fail "孤儿删除前全批重新核验记录数变化"
    for ((field_index = 0; field_index < ${#plan[@]}; field_index += 1)); do
      [[ "${replan[$field_index]}" == "${plan[$field_index]}" ]] \
        || fail "孤儿删除前全批身份或顺序发生变化"
    done
  fi

  for ((record_index = 1; record_index < ${#plan[@]}; record_index += 7)); do
    container_id=${plan[$((record_index + 1))]}
    if ! docker container inspect "$container_id" >/dev/null 2>&1; then
      remaining_id=$(docker container ls --all --quiet --no-trunc --filter "id=${container_id}") \
        || fail "无法区分已收敛孤儿与 Docker daemon 故障"
      [[ -z "$remaining_id" ]] || fail "孤儿仍存在但无法按完整 ID inspect"
      # Docker --rm may have converged an isolated one-shot after the full validation.
      continue
    fi
    docker container inspect "$container_id" >"$recheck_path"
    chmod 600 "$recheck_path"
    /usr/bin/python3 -I "$deploy_guard" plan-orphan-cleanup \
      --inspects "$recheck_path" \
      --output "$replan_path"
    mapfile -d '' -t replan <"$replan_path"
    rm -f -- "$recheck_path" "$replan_path"
    [[ "${#replan[@]}" -eq 8 && "${replan[0]}" == "${plan[0]}" ]] \
      || fail "孤儿删除阶段不再产生唯一可删除记录"
    for ((field_index = 0; field_index < 7; field_index += 1)); do
      [[ "${replan[$((field_index + 1))]}" == "${plan[$((record_index + field_index))]}" ]] \
        || fail "孤儿删除阶段 role/revision/run/topology 发生变化"
    done
    observed_id=$(docker container inspect --format '{{.Id}}' "$container_id")
    observed_image=$(docker container inspect --format '{{.Image}}' "$container_id")
    observed_name=$(docker container inspect --format '{{.Name}}' "$container_id")
    [[ "$observed_id" == "$container_id" \
      && "$observed_image" == "${plan[$((record_index + 3))]}" \
      && "$observed_name" != "/${container_name}" ]] \
      || fail "孤儿删除阶段容器 ID/image/name 发生变化"
    [[ "$(docker container inspect --format '{{.Id}}' "$container_name")" == "$official_id" ]] \
      || fail "孤儿删除阶段正式容器身份发生变化"
    docker container rm --force --volumes "$container_id" >/dev/null
  done

  [[ "$(docker container inspect --format '{{.Id}}' "$container_name")" == "$official_id" \
    && "$(docker container inspect --format '{{.Image}}' "$container_name")" == "$official_image" \
    && "$(docker container inspect --format '{{.State.Running}}' "$container_name")" == "true" ]] \
    || fail "孤儿回收期间正式容器身份或运行状态发生变化"
  container_internal_health "$container_name" || fail "孤儿回收后正式容器健康检查失败"
  cleanup_managed_restore_volumes
  container_internal_health "$container_name" \
    || fail "restore volume 孤儿回收后正式容器健康检查失败"
  ok "pre-journal 部署孤儿已完成全量身份核验与安全回收"
}

assert_current_rollback_identity() {
  container_exists "$old_container_id" || fail "当前回滚容器已消失"
  [[ "$(docker container inspect --format '{{.Id}}' "$old_container_id")" == "$old_container_id" \
    && "$(docker container inspect --format '{{.Image}}' "$old_container_id")" == "$old_image_id" \
    && "$(docker container inspect --format '{{.Name}}' "$old_container_id")" == "/${backup_container}" \
    && "$(docker container inspect --format '{{.State.Running}}' "$old_container_id")" == "false" ]] \
    || fail "当前回滚容器 ID/image/name/state 发生变化"
}

cleanup_expired_backups() {
  local list_path="${runtime_dir}/backup-retention-container-ids.txt"
  local inspect_path="${runtime_dir}/backup-retention-inspects.json"
  local plan_path="${runtime_dir}/backup-retention-plan.bin"
  local recheck_path="${runtime_dir}/backup-retention-rechecks.json"
  local replan_path="${runtime_dir}/backup-retention-replan.bin"
  local retained_scope observed_id observed_image observed_name expected_id
  local record_index field_index container_id found expected_replan_length
  local -a managed_ids=() relisted_ids=() remaining_ids=() plan=() replan=()

  [[ "$deployment_committed" -eq 1 ]] \
    || fail "只有已提交且 journal 已清除的部署才能执行备份保留"
  [[ ! -e "$CUTOVER_JOURNAL" && ! -L "$CUTOVER_JOURNAL" ]] \
    || fail "journal 仍存在，禁止清理历史备份"
  assert_candidate_runtime_identity
  container_internal_health "$container_name" \
    || fail "备份保留前新正式容器健康检查失败"
  assert_current_rollback_identity

  retained_scope=$(docker container inspect --format \
    '{{ index .Config.Labels "com.jianjieaitech.xjie.deploy.scope" }}' \
    "$old_container_id")
  if [[ -z "$retained_scope" ]]; then
    echo "[warn] 当前回滚容器是首次迁移的 legacy 容器；本次保留全部历史备份，需人工确认后再清理。" >&2
    return 0
  fi
  [[ "$retained_scope" == "production-api" ]] \
    || fail "当前回滚容器 lifecycle scope 非法"

  docker container ls --all --quiet --no-trunc \
    --filter "label=com.jianjieaitech.xjie.deploy.scope=production-api" \
    >"$list_path"
  mapfile -t managed_ids <"$list_path"
  rm -f -- "$list_path"
  [[ "${#managed_ids[@]}" -ge 2 ]] \
    || fail "备份保留无法同时识别新正式容器与当前回滚"
  docker container inspect "${managed_ids[@]}" >"$inspect_path"
  chmod 600 "$inspect_path"
  /usr/bin/python3 -I "$deploy_guard" plan-backup-retention \
    --inspects "$inspect_path" \
    --retained-backup-id "$old_container_id" \
    --output "$plan_path"
  mapfile -d '' -t plan <"$plan_path"
  rm -f -- "$inspect_path" "$plan_path"
  [[ "${#plan[@]}" -ge 1 && "${plan[0]}" == "backup-retention-v1" ]] \
    || fail "备份保留计划版本不正确"
  [[ "$(( (${#plan[@]} - 1) % 7 ))" -eq 0 ]] \
    || fail "备份保留计划字段数不正确"
  for ((record_index = 1; record_index < ${#plan[@]}; record_index += 7)); do
    [[ "${plan[$record_index]}" == "remove_expired_backup" ]] \
      || fail "备份保留计划包含未知动作"
    [[ "${plan[$((record_index + 1))]}" != "$old_container_id" \
      && "${plan[$((record_index + 1))]}" != "$new_container_id" ]] \
      || fail "备份保留计划试图删除正式容器或当前回滚"
  done

  for ((record_index = 1; record_index < ${#plan[@]}; record_index += 7)); do
    container_id=${plan[$((record_index + 1))]}
    assert_candidate_runtime_identity
    container_internal_health "$container_name" \
      || fail "历史备份删除阶段新正式容器健康检查失败"
    assert_current_rollback_identity

    # Re-list and validate the entire remaining lifecycle scope before every
    # non-transactional delete. A new/replaced managed container aborts cleanup.
    docker container ls --all --quiet --no-trunc \
      --filter "label=com.jianjieaitech.xjie.deploy.scope=production-api" \
      >"$list_path"
    mapfile -t relisted_ids <"$list_path"
    rm -f -- "$list_path"
    [[ "${#relisted_ids[@]}" -eq "${#managed_ids[@]}" ]] \
      || fail "历史备份删除前受管容器全集发生变化"
    for expected_id in "${managed_ids[@]}"; do
      found=0
      for observed_id in "${relisted_ids[@]}"; do
        if [[ "$observed_id" == "$expected_id" ]]; then
          found=1
          break
        fi
      done
      [[ "$found" -eq 1 ]] || fail "历史备份删除前受管容器 ID 集合发生变化"
    done

    docker container inspect "${relisted_ids[@]}" >"$recheck_path"
    chmod 600 "$recheck_path"
    /usr/bin/python3 -I "$deploy_guard" plan-backup-retention \
      --inspects "$recheck_path" \
      --retained-backup-id "$old_container_id" \
      --output "$replan_path"
    mapfile -d '' -t replan <"$replan_path"
    rm -f -- "$recheck_path" "$replan_path"
    expected_replan_length=$((1 + ${#plan[@]} - record_index))
    [[ "${#replan[@]}" -eq "$expected_replan_length" \
      && "${replan[0]}" == "${plan[0]}" ]] \
      || fail "历史备份删除阶段剩余计划记录数发生变化"
    for ((field_index = 1; field_index < ${#replan[@]}; field_index += 1)); do
      [[ "${replan[$field_index]}" == "${plan[$((record_index + field_index - 1))]}" ]] \
        || fail "历史备份删除阶段 role/revision/run/topology 发生变化"
    done
    observed_id=$(docker container inspect --format '{{.Id}}' "$container_id")
    observed_image=$(docker container inspect --format '{{.Image}}' "$container_id")
    observed_name=$(docker container inspect --format '{{.Name}}' "$container_id")
    [[ "$observed_id" == "$container_id" \
      && "$observed_image" == "${plan[$((record_index + 3))]}" \
      && "$observed_name" != "/${container_name}" \
      && "$observed_name" != "/${backup_container}" \
      && "$(docker container inspect --format '{{.State.Running}}' "$container_id")" == "false" ]] \
      || fail "历史备份删除阶段容器 ID/image/name/state 发生变化"
    docker container rm "$container_id" >/dev/null
    remaining_ids=()
    for expected_id in "${managed_ids[@]}"; do
      [[ "$expected_id" == "$container_id" ]] || remaining_ids+=("$expected_id")
    done
    managed_ids=("${remaining_ids[@]}")
  done

  assert_candidate_runtime_identity
  container_internal_health "$container_name" \
    || fail "备份保留后新正式容器健康检查失败"
  assert_current_rollback_identity
  ok "已保留本次回滚容器，并清理更早的受管备份"
}

remove_exact_prejournal_container() {
  local name=$1
  local expected_id=$2
  local expected_image=$3
  local expected_role=$4
  local inspect_path="${runtime_dir}/exit-${name}-inspect.json"
  local plan_path="${runtime_dir}/exit-${name}-plan.bin"
  local recheck_path="${runtime_dir}/exit-${name}-recheck.json"
  local replan_path="${runtime_dir}/exit-${name}-replan.bin"
  local observed_id observed_image observed_name
  local field_index
  local -a plan=() replan=()

  container_exists "$name" || return 0
  [[ "$expected_id" =~ ^[0-9a-f]{64}$ \
    && "$expected_image" =~ ^sha256:[0-9a-f]{64}$ \
    && -n "$deployment_run_id" && -n "$expected_role" ]] || return 1
  docker container inspect "$name" >"$inspect_path" || return 1
  chmod 600 "$inspect_path" || return 1
  /usr/bin/python3 -I "$deploy_guard" plan-orphan-cleanup \
    --inspects "$inspect_path" \
    --output "$plan_path" || return 1
  mapfile -d '' -t plan <"$plan_path"
  rm -f -- "$inspect_path" "$plan_path"
  [[ "${#plan[@]}" -eq 8 \
    && "${plan[0]}" == "orphan-cleanup-v1" \
    && "${plan[1]}" == "remove_orphan" \
    && "${plan[2]}" == "$expected_id" \
    && "${plan[3]}" == "$name" \
    && "${plan[4]}" == "$expected_image" \
    && "${plan[5]}" == "$expected_role" \
    && "${plan[6]}" == "$EXPECTED_SHA" \
    && "${plan[7]%%:*}" == "$deployment_run_id" ]] || return 1
  docker container inspect "$expected_id" >"$recheck_path" || return 1
  chmod 600 "$recheck_path" || return 1
  /usr/bin/python3 -I "$deploy_guard" plan-orphan-cleanup \
    --inspects "$recheck_path" \
    --output "$replan_path" || return 1
  mapfile -d '' -t replan <"$replan_path"
  rm -f -- "$recheck_path" "$replan_path"
  [[ "${#replan[@]}" -eq "${#plan[@]}" ]] || return 1
  for ((field_index = 0; field_index < ${#plan[@]}; field_index += 1)); do
    [[ "${replan[$field_index]}" == "${plan[$field_index]}" ]] || return 1
  done
  observed_id=$(docker container inspect --format '{{.Id}}' "$expected_id") || return 1
  observed_image=$(docker container inspect --format '{{.Image}}' "$expected_id") || return 1
  observed_name=$(docker container inspect --format '{{.Name}}' "$expected_id") || return 1
  [[ "$observed_id" == "$expected_id" \
    && "$observed_image" == "$expected_image" \
    && "$observed_name" == "/${name}" \
    && "$name" != "$container_name" \
    && "$name" != "$backup_container" ]] || return 1
  docker container rm --force --volumes "$expected_id" >/dev/null || return 1
  ! container_exists "$expected_id"
}

cleanup() {
  local original_status=$?
  local cleanup_failed=0
  local service_index
  trap - EXIT
  trap '' HUP INT QUIT TERM
  set +e
  exec 8>&-

  if [[ "$deployment_committed" -ne 1 \
    && -n "$runtime_dir" && -n "$trusted_bundle_sha256" \
    && ( -e "$CUTOVER_JOURNAL" || -L "$CUTOVER_JOURNAL" ) ]]; then
    echo "Deployment did not complete; invoking the journal-bound recovery planner." >&2
    ( set -e; recover_interrupted_cutover )
    recovery_status=$?
    [[ "$recovery_status" -eq 0 ]] || cleanup_failed=1
  elif [[ "$deployment_committed" -ne 1 ]]; then
    if [[ "$old_container_stopped" -eq 1 ]]; then
      echo "Deployment stopped production but its journal is missing; refusing name-based recovery." >&2
      cleanup_failed=1
    fi
    if [[ -n "$ephemeral_container" ]]; then
      remove_exact_prejournal_container \
        "$ephemeral_container" "$ephemeral_container_id" \
        "$ephemeral_image_id" "$ephemeral_role" || cleanup_failed=1
    fi
    if [[ -n "$reference_server" \
      && "$reference_server" != "$ephemeral_container" ]]; then
      remove_exact_prejournal_container \
        "$reference_server" "$reference_server_id" \
        "$reference_server_image_id" "$reference_server_role" \
        || cleanup_failed=1
    fi
    if [[ "$restore_volume_owned" -eq 1 ]]; then
      remove_exact_restore_volume || cleanup_failed=1
    fi
    if [[ -n "$candidate_container" \
      && "$candidate_container" != "$ephemeral_container" ]]; then
      remove_exact_prejournal_container \
        "$candidate_container" "$candidate_container_id" \
        "$image_id" candidate || cleanup_failed=1
    fi
  fi
  if [[ "$deployment_committed" -ne 1 ]]; then
    for ((service_index = 0; \
      service_index < ${#supervised_service_ids[@]}; \
      service_index += 1)); do
      remove_exact_prejournal_container \
        "${supervised_service_names[$service_index]}" \
        "${supervised_service_ids[$service_index]}" \
        "$image_id" \
        "${supervised_service_roles[$service_index]}" \
        || cleanup_failed=1
    done
  fi
  if [[ -n "$runtime_dir" && -d "$runtime_dir" ]]; then
    rm -rf -- "$runtime_dir" || cleanup_failed=1
  fi

  if [[ "$cleanup_failed" -ne 0 ]]; then
    echo "Deployment cleanup/rollback was incomplete; manual recovery is required." >&2
    original_status=1
  fi
  exit "$original_status"
}
trap cleanup EXIT

terminate_deploy_process_group() {
  local signal_name=$1
  local exit_status=$2
  trap '' "$signal_name"
  kill -s "$signal_name" -- "-$$" 2>/dev/null || true
  exit "$exit_status"
}
trap 'terminate_deploy_process_group HUP 129' HUP
trap 'terminate_deploy_process_group INT 130' INT
trap 'terminate_deploy_process_group QUIT 131' QUIT
trap 'terminate_deploy_process_group TERM 143' TERM

if (( BASH_VERSINFO[0] < 4 )); then
  fail "部署脚本要求 Bash 4+（生产 Linux）；Bash 3.2 不受支持"
fi
for command in readlink stat /usr/bin/python3; do
  command -v "$command" >/dev/null 2>&1 || fail "缺少受信入口依赖: ${command}"
done
if [[ "$EXPECTED_SHA" == "--doctor" ]]; then
  [[ "$#" -eq 1 ]] || fail "--doctor 不接受其他参数"
  assert_trusted_bundle
  trusted_bundle_sha256=$(compute_trusted_bundle_sha256)
  [[ "$trusted_bundle_sha256" =~ ^[0-9a-f]{64}$ ]] \
    || fail "无法绑定 root 受信 bundle 摘要"
  /usr/bin/python3 -I "$deploy_guard" validate-spec --spec "$spec_path"
  ok "root 受信 bundle 身份、摘要和生产规范有效: ${trusted_bundle_sha256}"
  exit 0
fi
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] \
  || fail "用法: $0 EXPECTED_SHA [deploy]，或 ingest --confirm-ingest，或 expand-deploy --confirm-expand-migration"
case "$ACTION" in
  deploy)
    [[ "$#" -le 2 ]] || fail "deploy 不接受额外参数"
    ;;
  ingest)
    [[ "$#" -eq 3 && "$ACTION_CONFIRMATION" == "--confirm-ingest" ]] \
      || fail "ingest 必须显式提供 --confirm-ingest，且不能与 deploy 合并执行"
    ;;
  expand-deploy)
    [[ "$#" -eq 3 \
      && "$ACTION_CONFIRMATION" == "--confirm-expand-migration" ]] \
      || fail "expand-deploy 必须显式提供 --confirm-expand-migration"
    ;;
  *) fail "用法: $0 EXPECTED_SHA [deploy]，或 ingest --confirm-ingest，或 expand-deploy --confirm-expand-migration" ;;
esac

deploy_principal_uid=$(/usr/bin/id -u "$DEPLOY_PRINCIPAL") \
  || fail "生产部署 principal 不存在: ${DEPLOY_PRINCIPAL}"
[[ "$EUID" -eq "$deploy_principal_uid" ]] \
  || fail "deploy/ingest 必须由 clean launcher 固定切换为 ${DEPLOY_PRINCIPAL} 执行"
validate_clean_launcher_authority

command -v docker >/dev/null 2>&1 || fail "缺少离线恢复依赖: docker"

acquire_or_validate_deploy_lock "$@"
ok "已取得生产部署互斥锁"

[[ ! -L "$STATE_DIR" ]] || fail "部署持久状态目录不能是符号链接"
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
[[ -d "$STATE_DIR" && ! -L "$STATE_DIR" \
  && "$(stat -c '%u' "$STATE_DIR")" == "$EUID" \
  && "$(stat -c '%a' "$STATE_DIR")" == "700" ]] \
  || fail "部署持久状态目录身份不正确"

# The installer must use the same lock. The authoritative bundle identity is
# therefore established only after this deployment owns that lock.
assert_trusted_bundle
trusted_bundle_sha256=$(compute_trusted_bundle_sha256)
[[ "$trusted_bundle_sha256" =~ ^[0-9a-f]{64}$ ]] \
  || fail "无法在部署锁内绑定 root 受信 bundle 摘要"
[[ "$(compute_trusted_launcher_sha256)" == "$XJIE_DEPLOY_LAUNCHER_SHA256" ]] \
  || fail "取得部署锁前 clean launcher 已被替换"
unset XJIE_DEPLOY_LAUNCHER_SHA256

[[ -d "$RUNTIME_PARENT" && ! -L "$RUNTIME_PARENT" ]] \
  || fail "部署运行目录必须是本机 tmpfs 目录"
[[ "$(stat -f -c '%T' "$RUNTIME_PARENT")" == "tmpfs" ]] \
  || fail "部署运行目录不是 tmpfs，禁止把生产环境快照写入持久磁盘"
runtime_base="${RUNTIME_PARENT}/xjie-deploy-${EUID}"
[[ ! -L "$runtime_base" ]] || fail "部署私有 tmpfs 目录不能是符号链接"
mkdir -p "$runtime_base"
chmod 700 "$runtime_base"
[[ "$(stat -c '%u' "$runtime_base")" == "$EUID" \
  && "$(stat -c '%a' "$runtime_base")" == "700" ]] \
  || fail "部署私有 tmpfs 目录身份不正确"
runtime_dir="${runtime_base}/runtime"
if [[ -e "$runtime_dir" || -L "$runtime_dir" ]]; then
  rm -rf --one-file-system -- "$runtime_dir"
fi
mkdir "$runtime_dir"
chmod 700 "$runtime_dir"
cd "$runtime_dir"

/usr/bin/python3 -I "$deploy_guard" validate-spec --spec "$spec_path"
trusted_spec_output="${runtime_dir}/trusted-spec.bin"
/usr/bin/python3 -I "$deploy_guard" emit-spec \
  --spec "$spec_path" \
  --output "$trusted_spec_output"
mapfile -d '' -t production_spec_values <"$trusted_spec_output"
[[ "${#production_spec_values[@]}" -eq 6 ]] \
  || fail "受信生产容器规范导出字段数不正确"
container_name=${production_spec_values[0]}
image_repository=${production_spec_values[1]}
secret_env_file=${production_spec_values[2]}
database_probe_image=${production_spec_values[3]}
container_health_url=${production_spec_values[4]}
public_health_url=${production_spec_values[5]}

# Recovery deliberately uses only the root-owned bundle and precedes network access:
# a GitHub/network/new-candidate failure must not keep an interrupted cutover down.
if [[ -e "$CUTOVER_JOURNAL" || -L "$CUTOVER_JOURNAL" ]]; then
  recover_interrupted_cutover
fi

for command in cmp git grep tar timeout; do
  command -v "$command" >/dev/null 2>&1 || fail "缺少候选资格/构建依赖: ${command}"
done

step "同步并绑定官方 main 精确提交"
official_git_dir="${runtime_dir}/official.git"
git init --bare --quiet --template=/dev/null "$official_git_dir"
chmod -R go-rwx "$official_git_dir"
[[ -d "$official_git_dir" && ! -L "$official_git_dir" \
  && "$(stat -c '%u' "$official_git_dir")" == "$EUID" \
  && "$(( 8#$(stat -c '%a' "$official_git_dir") & 8#077 ))" -eq 0 ]] \
  || fail "隔离 bare object store 身份不安全"
git --git-dir="$official_git_dir" fetch --no-tags --no-write-fetch-head \
  "$OFFICIAL_ORIGIN_HTTPS" \
  "refs/heads/${CANONICAL_BRANCH}:refs/heads/${CANONICAL_BRANCH}"
REMOTE_MAIN=$(git --git-dir="$official_git_dir" rev-parse "refs/heads/${CANONICAL_BRANCH}")
[[ "$REMOTE_MAIN" == "$EXPECTED_SHA" ]] \
  || fail "origin/main 已不是调用方指定的 EXPECTED_SHA；重新走部署审批"
git --git-dir="$official_git_dir" fsck --strict --no-dangling "$EXPECTED_SHA" \
  >/dev/null
qualification_root="${runtime_dir}/qualification"
mkdir -p \
  "${qualification_root}/backend/deploy" \
  "${qualification_root}/tools" \
  "${qualification_root}/scripts" \
  "${qualification_root}/quality"
for relative_path in \
  "$SPEC_RELATIVE" "$DEPLOY_GUARD_RELATIVE" "$RELEASE_GATE_RELATIVE" \
  "$TEST_INVENTORY_RELATIVE" "$DEPLOY_ENTRYPOINT_RELATIVE" \
  "$DEPLOY_LAUNCHER_RELATIVE" "$DEPLOY_INSTALLER_RELATIVE" \
  "quality/regression_contracts.json"; do
  [[ "$(git --git-dir="$official_git_dir" cat-file -t "${EXPECTED_SHA}:${relative_path}")" == "blob" ]] \
    || fail "EXPECTED_SHA 缺少普通资格文件: ${relative_path}"
  git --git-dir="$official_git_dir" cat-file blob "${EXPECTED_SHA}:${relative_path}" \
    >"${qualification_root}/${relative_path}"
done
chmod -R a-w "$qualification_root"
qualification_spec="${qualification_root}/${SPEC_RELATIVE}"
qualification_deploy_guard="${qualification_root}/${DEPLOY_GUARD_RELATIVE}"
qualification_release_gate="${qualification_root}/${RELEASE_GATE_RELATIVE}"
qualification_test_inventory="${qualification_root}/${TEST_INVENTORY_RELATIVE}"
qualification_entrypoint="${qualification_root}/${DEPLOY_ENTRYPOINT_RELATIVE}"
qualification_launcher="${qualification_root}/${DEPLOY_LAUNCHER_RELATIVE}"
qualification_installer="${qualification_root}/${DEPLOY_INSTALLER_RELATIVE}"

step "执行候选代码前证明 exact-SHA bundle 与 root 预装受信副本逐字节一致"
cmp -s -- "$qualification_spec" "$TRUSTED_SPEC" \
  || fail "候选生产容器规范与 root 预装副本不同；先走独立 bundle 安装审批"
cmp -s -- "$qualification_deploy_guard" "$TRUSTED_DEPLOY_GUARD" \
  || fail "候选部署 guard 与 root 预装副本不同；先走独立 bundle 安装审批"
cmp -s -- "$qualification_release_gate" "$TRUSTED_RELEASE_GATE" \
  || fail "候选 release gate 与 root 预装副本不同；先走独立 bundle 安装审批"
cmp -s -- "$qualification_test_inventory" "$TRUSTED_TEST_INVENTORY" \
  || fail "候选测试清单与 root 预装副本不同；先走独立 bundle 安装审批"
cmp -s -- "$qualification_entrypoint" "$TRUSTED_ENTRYPOINT" \
  || fail "候选部署入口与 root 预装副本不同；先走独立 bundle 安装审批"
cmp -s -- "$qualification_launcher" "$TRUSTED_LAUNCHER" \
  || fail "候选 clean launcher 与 root 预装副本不同；先走独立 bundle 安装审批"
cmp -s -- "$qualification_installer" "$TRUSTED_INSTALLER" \
  || fail "候选 bundle installer 与 root 预装副本不同；先走独立 bundle 安装审批"

verify_official_candidate() {
  assert_trusted_bundle
  [[ "$(compute_trusted_bundle_sha256)" == "$trusted_bundle_sha256" ]] \
    || fail "root 受信 bundle 在部署过程中发生变化"
  cmp -s -- "$qualification_release_gate" "$TRUSTED_RELEASE_GATE" \
    || fail "官方资格复核前 release gate 不再匹配受信副本"
  broker_request "VERIFY ${EXPECTED_SHA}"
}

step "验证 merged PR、官方 main 精确 tip/CI 与 main/XAGE 双分支保护"
verify_official_candidate

if [[ "$ACTION" == "ingest" ]]; then
  container_exists "$container_name" || fail "容器 ${container_name} 不存在"
  [[ "$(docker container inspect --format '{{.State.Running}}' "$container_name")" == "true" ]] \
    || fail "ingest 前生产容器未运行"
  verify_running_revision "$EXPECTED_SHA"
  container_internal_health "$container_name" || fail "ingest 前容器健康检查失败"
  step "文献导入前回收已验证的 pre-journal 部署孤儿"
  cleanup_prejournal_orphans
  old_container_id=$(docker container inspect --format '{{.Id}}' "$container_name")
  old_image_id=$(docker container inspect --format '{{.Image}}' "$container_name")
  image_ref="${image_repository}:main-${EXPECTED_SHA}"
  env_snapshot="${runtime_dir}/production.env"
  /usr/bin/python3 -I "$deploy_guard" snapshot-env \
    --spec "$spec_path" \
    --source "$secret_env_file" \
    --output "$env_snapshot"
  deployment_run_id=$(/usr/bin/python3 -I -c 'import secrets; print(secrets.token_hex(16))')
  [[ "$deployment_run_id" =~ ^[0-9a-f]{32}$ ]] \
    || fail "无法生成文献导入生命周期 run ID"
  run_confirmed_ingest
  rm -f -- "$env_snapshot"
  env_snapshot=""
  [[ "$(docker container inspect --format '{{.Id}}' "$container_name")" == "$old_container_id" ]] \
    || fail "文献导入期间生产容器身份发生变化"
  container_internal_health "$container_name" || fail "文献导入后容器健康检查失败"
  step "完成"
  echo "  - exact main SHA: ${EXPECTED_SHA}"
  echo "  - 导入日志已由 one-shot 容器 attach 输出；失败会按 immutable ID 强制回收"
  exit 0
fi

step "官方资格通过后从隔离 bare object store 归档 exact main"
HEAD_SHA=$(git --git-dir="$official_git_dir" rev-parse "refs/heads/${CANONICAL_BRANCH}")
[[ "$HEAD_SHA" == "$EXPECTED_SHA" ]] || fail "隔离 object store 不等于 EXPECTED_SHA"
source_root="${runtime_dir}/source"
mkdir "$source_root"
tree_manifest="${runtime_dir}/exact-main-tree.bin"
git --git-dir="$official_git_dir" ls-tree -rz --full-tree "$EXPECTED_SHA" \
  >"$tree_manifest"
chmod 600 "$tree_manifest"
git --git-dir="$official_git_dir" archive --format=tar "$EXPECTED_SHA" \
  | tar -xf - -C "$source_root"
[[ "$(git --git-dir="$official_git_dir" rev-parse "${EXPECTED_SHA}^{tree}")" \
  == "$(git --git-dir="$official_git_dir" rev-parse "refs/heads/${CANONICAL_BRANCH}^{tree}")" ]] \
  || fail "EXPECTED_SHA tree 与隔离 official main 不一致"
/usr/bin/python3 -I "$deploy_guard" validate-source-snapshot \
  --manifest "$tree_manifest" \
  --source-root "$source_root"
rm -f -- "$tree_manifest"
chmod -R a-w "$source_root"
candidate_spec_path="${source_root}/${SPEC_RELATIVE}"
candidate_deploy_guard="${source_root}/${DEPLOY_GUARD_RELATIVE}"
candidate_release_gate="${source_root}/${RELEASE_GATE_RELATIVE}"
candidate_test_inventory="${source_root}/${TEST_INVENTORY_RELATIVE}"
candidate_entrypoint="${source_root}/${DEPLOY_ENTRYPOINT_RELATIVE}"
candidate_launcher="${source_root}/${DEPLOY_LAUNCHER_RELATIVE}"
candidate_installer="${source_root}/${DEPLOY_INSTALLER_RELATIVE}"
for candidate_file in \
  "$candidate_spec_path" "$candidate_deploy_guard" \
  "$candidate_release_gate" "$candidate_test_inventory" \
  "$candidate_entrypoint" "$candidate_launcher" "$candidate_installer"; do
  [[ -f "$candidate_file" && ! -L "$candidate_file" \
    && "$(stat -c '%h:%F' "$candidate_file")" == "1:regular file" ]] \
    || fail "归档后的候选 bundle 文件缺失或身份不安全: ${candidate_file}"
done
cmp -s -- "$candidate_spec_path" "$TRUSTED_SPEC" \
  && cmp -s -- "$candidate_deploy_guard" "$TRUSTED_DEPLOY_GUARD" \
  && cmp -s -- "$candidate_release_gate" "$TRUSTED_RELEASE_GATE" \
  && cmp -s -- "$candidate_test_inventory" "$TRUSTED_TEST_INVENTORY" \
  && cmp -s -- "$candidate_entrypoint" "$TRUSTED_ENTRYPOINT" \
  && cmp -s -- "$candidate_launcher" "$TRUSTED_LAUNCHER" \
  && cmp -s -- "$candidate_installer" "$TRUSTED_INSTALLER" \
  || fail "归档后的候选 bundle 不再匹配 root 受信副本"
ok "官方 main 与只读源码快照已绑定 ${EXPECTED_SHA}"

step "官方资格通过后回收已验证的 pre-journal 部署孤儿"
cleanup_prejournal_orphans

step "创建 owner-only 不可变生产环境快照"
env_snapshot="${runtime_dir}/production.env"
/usr/bin/python3 -I "$deploy_guard" snapshot-env \
  --spec "$spec_path" \
  --source "$secret_env_file" \
  --output "$env_snapshot"
database_probe_env_snapshot="${runtime_dir}/database-probe.env"
deployment_run_id=$(/usr/bin/python3 -I -c 'import secrets; print(secrets.token_hex(16))')
[[ "$deployment_run_id" =~ ^[0-9a-f]{32}$ ]] \
  || fail "无法生成部署生命周期 run ID"

container_exists "$container_name" || fail "容器 ${container_name} 不存在"
[[ "$(docker container inspect --format '{{.State.Running}}' "$container_name")" == "true" ]] \
  || fail "容器 ${container_name} 未运行"
old_container_id=$(docker container inspect --format '{{.Id}}' "$container_name")
old_image_id=$(docker container inspect --format '{{.Image}}' "$container_name")

run_migration_command() {
  local name=$1
  local role=$2
  local output=$3
  shift 3
  local args_path="${runtime_dir}/${name}-args.bin"
  local -a command_args
  /usr/bin/python3 -I "$deploy_guard" create-args \
    --spec "$spec_path" \
    --name "$name" \
    --image "$image_id" \
    --image-ref "$image_ref" \
    --env-file "$env_snapshot" \
    --env-source "$secret_env_file" \
    --expected-sha "$EXPECTED_SHA" \
    --run-id "$deployment_run_id" \
    --role "$role" \
    --output "$args_path" \
    -- "$@"
  mapfile -d '' -t command_args <"$args_path"
  ephemeral_container="$name"
  docker "${command_args[@]}" >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="$role"
  [[ "$ephemeral_image_id" == "$image_id" ]] \
    || fail "one-shot 容器未绑定候选 image ID: ${name}"
  docker container start --attach "$ephemeral_container_id" >"$output"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" "$role"
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
}

create_supervised_service_candidates() {
  local role name args_path observed_id observed_image observed_running
  local -a role_command create_args
  for role in celery-worker celery-beat; do
    name="${container_name}-deploy-${deployment_run_id}-${role}"
    args_path="${runtime_dir}/${role}-args.bin"
    container_exists "$name" && fail "受监管服务容器名已存在: ${name}"
    if [[ "$role" == "celery-worker" ]]; then
      role_command=(
        python -I -m celery --app app.workers.celery_app:celery_app
        worker --loglevel=INFO --concurrency=2
        '--hostname=xjie-worker@%h' --without-gossip --without-mingle
      )
    else
      role_command=(
        python -I -m celery --app app.workers.celery_app:celery_app
        beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
        --pidfile=/tmp/celerybeat.pid
      )
    fi
    /usr/bin/python3 -I "$deploy_guard" create-args \
      --spec "$spec_path" \
      --name "$name" \
      --image "$image_id" \
      --image-ref "$image_ref" \
      --env-file "$env_snapshot" \
      --env-source "$secret_env_file" \
      --expected-sha "$EXPECTED_SHA" \
      --run-id "$deployment_run_id" \
      --role "$role" \
      --output "$args_path" \
      -- "${role_command[@]}"
    mapfile -d '' -t create_args <"$args_path"
    docker "${create_args[@]}" >/dev/null
    observed_id=$(docker container inspect --format '{{.Id}}' "$name")
    observed_image=$(docker container inspect --format '{{.Image}}' "$name")
    observed_running=$(docker container inspect --format '{{.State.Running}}' "$name")
    [[ "$observed_id" =~ ^[0-9a-f]{64}$ \
      && "$observed_image" == "$image_id" \
      && "$observed_running" == "false" ]] \
      || fail "受监管 ${role} 候选未绑定 exact image 或意外运行"
    supervised_service_names+=("$name")
    supervised_service_ids+=("$observed_id")
    supervised_service_roles+=("$role")
  done
  [[ "${#supervised_service_ids[@]}" -eq 2 ]] \
    || fail "受监管 worker/beat 候选集合不完整"
}

start_and_verify_supervised_services() {
  local index role container_id running worker_id worker_hostname
  local log_path
  for ((index = 0; index < ${#supervised_service_ids[@]}; index += 1)); do
    container_id=${supervised_service_ids[$index]}
    docker container start "$container_id" >/dev/null
  done
  sleep 5
  for ((index = 0; index < ${#supervised_service_ids[@]}; index += 1)); do
    role=${supervised_service_roles[$index]}
    container_id=${supervised_service_ids[$index]}
    running=$(docker container inspect --format '{{.State.Running}}' "$container_id")
    [[ "$running" == "true" \
      && "$(docker container inspect --format '{{.Image}}' "$container_id")" == "$image_id" ]] \
      || fail "受监管 ${role} 未保持运行或 image 身份变化"
    log_path="${runtime_dir}/${role}.log"
    docker logs "$container_id" >"$log_path" 2>&1
    if LC_ALL=C grep -Eiq \
      'Traceback|CRITICAL|segmentation fault|Killed process|Unable to load celery application' \
      "$log_path"; then
      fail "受监管 ${role} 启动日志出现致命错误"
    fi
    if [[ "$role" == "celery-worker" ]]; then
      worker_id=$container_id
    else
      docker exec "$container_id" python -I -c \
        "import os; raise SystemExit(0 if os.path.isfile('/tmp/celerybeat.pid') else 1)" \
        >/dev/null 2>&1 \
        || fail "受监管 celery-beat 未创建运行时 pid 证明"
    fi
  done
  [[ -n "${worker_id:-}" ]] || fail "受监管 celery-worker 身份缺失"
  worker_hostname="xjie-worker@${worker_id:0:12}"
  docker exec "$worker_id" python -I -m celery \
    --app app.workers.celery_app:celery_app inspect ping \
    --destination "$worker_hostname" --timeout=5 >/dev/null \
    || fail "受监管 celery-worker 未对 exact hostname 响应"
}

prepare_database_probe_image() {
  local probe_image_metadata probe_os probe_arch probe_repo_digest
  if [[ -n "$database_probe_image_id" ]]; then
    [[ "$(docker image inspect --format '{{.Id}}' "$database_probe_image")" \
      == "$database_probe_image_id" ]] \
      || fail "受信 PostgreSQL image ID 在部署期间发生变化"
    return 0
  fi
  docker image pull --platform linux/amd64 "$database_probe_image" >/dev/null
  probe_image_metadata=$(docker image inspect \
    --format '{{.Id}}|{{.Os}}|{{.Architecture}}' "$database_probe_image") \
    || fail "无法读取受信 PostgreSQL image 身份"
  IFS='|' read -r database_probe_image_id probe_os probe_arch \
    <<<"$probe_image_metadata"
  probe_repo_digest="postgres@${database_probe_image##*@}"
  [[ "$database_probe_image_id" =~ ^sha256:[0-9a-f]{64}$ \
    && "$probe_os" == "linux" && "$probe_arch" == "amd64" ]] \
    || fail "受信 PostgreSQL image 没有绑定 linux/amd64 immutable image ID"
  docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' \
    "$database_probe_image" | grep -F -x -- "$probe_repo_digest" >/dev/null \
    || fail "受信 PostgreSQL image RepoDigest 与规范不一致"
}

run_database_schema_probe() {
  local name=$1
  local probe=$2
  local output=$3
  local probe_env=$4
  local maximum_output_bytes=${5:-65536}
  local file_blocks=128
  if [[ "$maximum_output_bytes" -gt 65536 ]]; then
    file_blocks=32768
  fi
  prepare_database_probe_image
  ephemeral_container="$name"
  emit_lifecycle_label_args "$name" "$database_probe_image_id" database-schema
  docker container create \
    --platform linux/amd64 \
    --name "$name" \
    --env-file "$probe_env" \
    --interactive \
    --user 70:70 \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --restart no \
    --memory 256m \
    --memory-swap 256m \
    --pids-limit 128 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777 \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=16m,uid=70,gid=70,mode=0700 \
    --add-host "$DATABASE_PROBE_EXTRA_HOST" \
    "${lifecycle_args[@]}" \
    --entrypoint /usr/local/bin/psql \
    "$database_probe_image_id" \
    --no-psqlrc --quiet --tuples-only --no-align \
    --set ON_ERROR_STOP=1 >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="database-schema"
  [[ "$ephemeral_image_id" == "$database_probe_image_id" ]] \
    || fail "数据库结构探针未绑定 digest-pinned PostgreSQL 客户端 image ID"
  (
    ulimit -f "$file_blocks"
    /usr/bin/timeout --signal=TERM --kill-after=10s 120s \
      docker container start --attach --interactive "$ephemeral_container_id"
  ) <"$probe" >"$output"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" "生产数据库只读结构探针"
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  [[ -f "$output" && ! -L "$output" \
    && "$(stat -c '%s' "$output")" -le "$maximum_output_bytes" ]] \
    || fail "生产数据库只读结构探针输出超出上限或身份非法"
  chmod 600 "$output"
}

assert_reference_server_identity() {
  local metadata observed_id observed_image running restart_count
  [[ -n "$reference_server" && -n "$reference_server_id" \
    && -n "$reference_server_image_id" ]] \
    || fail "参考数据库身份尚未建立"
  metadata=$(docker container inspect \
    --format '{{.Id}}|{{.Image}}|{{.State.Running}}|{{.RestartCount}}' \
    "$reference_server_id") \
    || fail "无法读取参考数据库 immutable identity"
  IFS='|' read -r observed_id observed_image running restart_count <<<"$metadata"
  [[ "$observed_id" == "$reference_server_id" \
    && "$observed_image" == "$reference_server_image_id" \
    && "$running" == "true" && "$restart_count" == "0" \
    && "$(docker container inspect --format '{{.Name}}' "$reference_server_id")" \
      == "/${reference_server}" ]] \
    || fail "参考数据库容器身份、运行状态或 restart count 发生变化"
}

assert_restore_volume_identity() {
  local inspect_path="${runtime_dir}/restore-volume-current-inspect.json"
  [[ "$restore_volume_owned" -eq 1 \
    && -n "$restore_volume_name" \
    && -n "$restore_volume_image_id" ]] \
    || fail "restore volume 身份尚未建立"
  docker volume inspect "$restore_volume_name" >"$inspect_path"
  chmod 600 "$inspect_path"
  /usr/bin/python3 -I "$deploy_guard" \
    validate-expand-restore-volume-inspect \
    --inspect "$inspect_path" --name "$restore_volume_name" \
    --expected-sha "$EXPECTED_SHA" --run-id "$deployment_run_id" \
    --image-id "$restore_volume_image_id"
}

create_restore_volume() {
  local observed created inspect_path
  prepare_database_probe_image
  restore_volume_name="${container_name}-deploy-${deployment_run_id}-schema-restore-volume"
  restore_volume_image_id="$database_probe_image_id"
  inspect_path="${runtime_dir}/restore-volume-create-inspect.json"
  if docker volume inspect "$restore_volume_name" >/dev/null 2>&1; then
    fail "本次 execution ID 的 restore volume 已存在，拒绝复用"
  fi
  observed=$(docker volume ls --quiet \
    --filter "name=^${restore_volume_name}$")
  [[ -z "$observed" ]] \
    || fail "本次 execution ID 的 restore volume 名称已被未知对象占用"
  emit_lifecycle_label_args \
    "$restore_volume_name" "$restore_volume_image_id" schema-restore-volume
  created=$(docker volume create --driver local \
    "${lifecycle_args[@]}" "$restore_volume_name")
  [[ "$created" == "$restore_volume_name" ]] \
    || fail "Docker 未返回 exact restore volume 名称"
  docker volume inspect "$restore_volume_name" >"$inspect_path"
  chmod 600 "$inspect_path"
  /usr/bin/python3 -I "$deploy_guard" \
    validate-expand-restore-volume-inspect \
    --inspect "$inspect_path" --name "$restore_volume_name" \
    --expected-sha "$EXPECTED_SHA" --run-id "$deployment_run_id" \
    --image-id "$restore_volume_image_id"
  restore_volume_owned=1
}

run_restore_volume_capacity_probe() {
  local name=$1
  local output=$2
  local stderr_path="${runtime_dir}/restore-volume-capacity.stderr"
  prepare_database_probe_image
  assert_restore_volume_identity
  : >"$output"
  : >"$stderr_path"
  chmod 600 "$output" "$stderr_path"
  emit_lifecycle_label_args \
    "$name" "$database_probe_image_id" schema-restore-capacity
  ephemeral_container="$name"
  ephemeral_container_id=$(docker container create \
    --platform linux/amd64 --name "$name" \
    --network none --log-driver none --user 70:70 --read-only \
    --cap-drop ALL --security-opt no-new-privileges --restart no \
    --memory 256m --memory-swap 256m --pids-limit 64 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --env LC_ALL=C \
    --mount "type=volume,src=${restore_volume_name},dst=/var/lib/postgresql/data,readonly,volume-nocopy" \
    "${lifecycle_args[@]}" \
    --entrypoint /bin/stat "$database_probe_image_id" \
    -f -c '%a %S' /var/lib/postgresql/data)
  [[ "$ephemeral_container_id" =~ ^[0-9a-f]{64}$ ]] \
    || fail "restore volume 容量探针 container ID 非法"
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="schema-restore-capacity"
  [[ "$ephemeral_image_id" == "$database_probe_image_id" ]] \
    || fail "restore volume 容量探针未绑定 digest-pinned PostgreSQL image"
  docker container start --attach "$ephemeral_container_id" \
    >"$output" 2>"$stderr_path"
  [[ ! -s "$stderr_path" ]] || fail "restore volume 容量探针产生 stderr"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" schema-restore-capacity
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  [[ -f "$output" && ! -L "$output" \
    && "$(stat -c '%s' "$output")" -le 4096 ]] \
    || fail "restore volume 容量探针输出非法"
  rm -f -- "$stderr_path"
  assert_restore_volume_identity
}

initialize_restore_volume() {
  local name=$1
  local stderr_path="${runtime_dir}/restore-volume-init.stderr"
  prepare_database_probe_image
  assert_restore_volume_identity
  : >"$stderr_path"
  chmod 600 "$stderr_path"
  emit_lifecycle_label_args \
    "$name" "$database_probe_image_id" schema-restore-volume-init
  ephemeral_container="$name"
  ephemeral_container_id=$(docker container create \
    --platform linux/amd64 --name "$name" \
    --network none --log-driver none --user 0:0 --read-only \
    --cap-drop ALL --cap-add CHOWN \
    --security-opt no-new-privileges --restart no \
    --memory 128m --memory-swap 128m --pids-limit 32 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --mount "type=volume,src=${restore_volume_name},dst=/var/lib/postgresql/data,volume-nocopy" \
    "${lifecycle_args[@]}" \
    --entrypoint /bin/sh "$database_probe_image_id" \
    -ceu 'chmod 0700 /var/lib/postgresql/data && chown 70:70 /var/lib/postgresql/data' \
    )
  [[ "$ephemeral_container_id" =~ ^[0-9a-f]{64}$ ]] \
    || fail "restore volume 初始化器 container ID 非法"
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="schema-restore-volume-init"
  [[ "$ephemeral_image_id" == "$database_probe_image_id" ]] \
    || fail "restore volume 初始化器未绑定 digest-pinned PostgreSQL image"
  docker container start --attach "$ephemeral_container_id" \
    >/dev/null 2>"$stderr_path"
  [[ ! -s "$stderr_path" ]] || fail "restore volume 初始化器产生 stderr"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" schema-restore-volume-init
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  rm -f -- "$stderr_path"
  assert_restore_volume_identity
}

start_reference_database() {
  local name=$1
  local storage=${2:-tmpfs}
  local ready=0 attempt memory_limit role
  local -a data_storage_args=()
  prepare_database_probe_image
  reference_server="$name"
  reference_server_image_id="$database_probe_image_id"
  if [[ "$storage" == "restore-volume" ]]; then
    assert_restore_volume_identity
    role="schema-restore-server"
    memory_limit="1024m"
    data_storage_args=(
      --mount "type=volume,src=${restore_volume_name},dst=/var/lib/postgresql/data,volume-nocopy"
    )
  elif [[ "$storage" == "tmpfs" ]]; then
    role="schema-reference-server"
    memory_limit="512m"
    data_storage_args=(
      --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=256m,uid=70,gid=70,mode=0700
    )
  else
    fail "未知的隔离 PostgreSQL storage mode"
  fi
  reference_server_role="$role"
  reference_socket_dir="${runtime_dir}/reference-pg-socket"
  reference_password=$(/usr/bin/python3 -I -c \
    'import secrets; print(secrets.token_hex(32))')
  [[ "$reference_password" =~ ^[0-9a-f]{64}$ ]] \
    || fail "无法生成隔离参考数据库凭据"
  [[ ! -e "$reference_socket_dir" && ! -L "$reference_socket_dir" ]] \
    || fail "参考数据库 socket 目录已存在"
  mkdir "$reference_socket_dir"
  chmod 777 "$reference_socket_dir"
  [[ -d "$reference_socket_dir" && ! -L "$reference_socket_dir" \
    && "$(stat -c '%u:%a' "$reference_socket_dir")" == "${EUID}:777" ]] \
    || fail "参考数据库 socket 目录身份不安全"

  emit_lifecycle_label_args \
    "$name" "$reference_server_image_id" "$reference_server_role"
  reference_server_id=$(docker container create \
    --platform linux/amd64 \
    --name "$name" \
    --network none \
    --log-driver none \
    --user 70:70 \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --restart no \
    --stop-timeout 20 \
    --memory "$memory_limit" \
    --memory-swap "$memory_limit" \
    --pids-limit 256 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777 \
    "${data_storage_args[@]}" \
    --mount "type=bind,src=${reference_socket_dir},dst=/var/run/postgresql" \
    --env "POSTGRES_USER=xjie_reference" \
    --env "POSTGRES_PASSWORD=${reference_password}" \
    --env "POSTGRES_DB=xjie_reference" \
    --env "POSTGRES_INITDB_ARGS=--auth-local=scram-sha-256 --auth-host=scram-sha-256" \
    --env "PGDATA=/var/lib/postgresql/data/pgdata" \
    "${lifecycle_args[@]}" \
    "$reference_server_image_id" \
    postgres -c listen_addresses= \
      -c unix_socket_directories=/var/run/postgresql)
  [[ "$reference_server_id" =~ ^[0-9a-f]{64}$ \
    && "$(docker container inspect --format '{{.Image}}' "$reference_server_id")" \
      == "$reference_server_image_id" ]] \
    || fail "参考数据库未绑定 digest-pinned PostgreSQL image"
  docker container start "$reference_server_id" >/dev/null

  # initdb 会短暂启动再关闭一个临时 server；两次成功查询之间留出窗口，
  # 避免把那个临时 server 误认为 PID 1 的最终实例。
  for ((attempt = 0; attempt < 120; attempt += 1)); do
    if docker container inspect --format '{{.State.Running}}' \
      "$reference_server_id" 2>/dev/null | grep -F -x true >/dev/null \
      && docker exec --env "PGPASSWORD=${reference_password}" \
        "$reference_server_id" /usr/local/bin/psql \
        --no-psqlrc --quiet --tuples-only --no-align \
        --host /var/run/postgresql --username xjie_reference \
        --dbname xjie_reference --command 'SELECT 1' 2>/dev/null \
          | grep -F -x 1 >/dev/null; then
      ready=1
      break
    fi
    sleep 0.25
  done
  [[ "$ready" -eq 1 ]] || fail "隔离参考数据库初始化超时"
  sleep 1
  assert_reference_server_identity
  [[ "$(docker exec --env "PGPASSWORD=${reference_password}" \
    "$reference_server_id" /usr/local/bin/psql \
    --no-psqlrc --quiet --tuples-only --no-align \
    --host /var/run/postgresql --username xjie_reference \
    --dbname xjie_reference --command 'SELECT 1')" == "1" ]] \
    || fail "隔离参考数据库未稳定进入最终只监听 Unix socket 的实例"
  if [[ "$storage" == "restore-volume" ]]; then
    assert_restore_volume_identity
  fi
}

run_reference_schema_materializer() {
  local name=$1
  local materializer=$2
  local candidate_manifest=$3
  local materializer_image=${4:-$image_id}
  local result_validator=${5:-validate-reference-materializer-result}
  local reference_uri materializer_result materializer_stderr
  local materializer_status=0 stderr_size=0
  materializer_result="${runtime_dir}/reference-schema-materializer-result.json"
  materializer_stderr="${runtime_dir}/reference-schema-materializer.stderr"
  : >"$materializer_result"
  : >"$materializer_stderr"
  chmod 600 "$materializer_result" "$materializer_stderr"
  reference_uri="postgresql+psycopg://xjie_reference:${reference_password}@/xjie_reference?host=/var/run/postgresql"
  assert_reference_server_identity
  ephemeral_container="$name"
  emit_lifecycle_label_args \
    "$name" "$materializer_image" schema-reference-materializer
  docker container create \
    --name "$name" \
    --network none \
    --log-driver none \
    --user 65534:65534 \
    --interactive \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --restart no \
    --memory 512m \
    --memory-swap 512m \
    --pids-limit 256 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777 \
    --mount "type=bind,src=${reference_socket_dir},dst=/var/run/postgresql,readonly" \
    --env "XJIE_REFERENCE_DATABASE_URL=${reference_uri}" \
    "${lifecycle_args[@]}" \
    --entrypoint python \
    "$materializer_image" -I - >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="schema-reference-materializer"
  [[ "$ephemeral_image_id" == "$materializer_image" ]] \
    || fail "参考结构 materializer 未绑定指定 image ID"
  if (
    ulimit -f 128
    /usr/bin/timeout --signal=TERM --kill-after=10s 120s \
      docker container start --attach --interactive "$ephemeral_container_id"
  ) <"$materializer" >"$materializer_result" 2>"$materializer_stderr"; then
    materializer_status=0
  else
    materializer_status=$?
  fi
  chmod 600 "$materializer_result" "$materializer_stderr"
  [[ "$(stat -c '%u:%a:%h:%F' "$materializer_result")" \
      == "${EUID}:600:1:regular file" \
    && "$(stat -c '%u:%a:%h:%F' "$materializer_stderr")" \
      == "${EUID}:600:1:regular file" \
    && "$(stat -c '%s' "$materializer_result")" -le 65536 \
    && "$(stat -c '%s' "$materializer_stderr")" -le 65536 ]] \
    || {
      rm -f -- "$materializer_result" "$materializer_stderr"
      fail "参考结构 materializer 输出身份非法或超出 64KiB"
    }
  stderr_size=$(stat -c '%s' "$materializer_stderr")
  if [[ "$materializer_status" -ne 0 || "$stderr_size" -ne 0 ]]; then
    if [[ "$stderr_size" -ne 0 ]]; then
      echo "[fail] 参考结构 materializer stderr 尾部（最多 4096 bytes）:" >&2
      /usr/bin/tail -c 4096 -- "$materializer_stderr" >&2 || true
    fi
    rm -f -- "$materializer_result" "$materializer_stderr"
    fail "参考结构 materializer 退出异常或产生 stderr"
  fi
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" "参考结构 materializer"
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  if ! /usr/bin/python3 -I "$deploy_guard" \
    "$result_validator" \
    --candidate-manifest "$candidate_manifest" \
    --result "$materializer_result"; then
    rm -f -- "$materializer_result" "$materializer_stderr"
    fail "参考结构 materializer 结果未通过候选 manifest 绑定校验"
  fi
  rm -f -- "$materializer_result" "$materializer_stderr"
  assert_reference_server_identity
}

run_reference_catalog_probe() {
  local name=$1
  local probe=$2
  local output=$3
  assert_reference_server_identity
  ephemeral_container="$name"
  emit_lifecycle_label_args \
    "$name" "$database_probe_image_id" schema-reference-catalog
  docker container create \
    --platform linux/amd64 \
    --name "$name" \
    --network none \
    --log-driver none \
    --user 70:70 \
    --interactive \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --restart no \
    --memory 256m \
    --memory-swap 256m \
    --pids-limit 128 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777 \
    --tmpfs /var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=16m,uid=70,gid=70,mode=0700 \
    --mount "type=bind,src=${reference_socket_dir},dst=/var/run/postgresql,readonly" \
    --env "PGHOST=/var/run/postgresql" \
    --env "PGPORT=5432" \
    --env "PGUSER=xjie_reference" \
    --env "PGPASSWORD=${reference_password}" \
    --env "PGDATABASE=xjie_reference" \
    --env "PGOPTIONS=-c default_transaction_read_only=on" \
    --env "XJIE_EXPECTED_DATABASE=xjie_reference" \
    "${lifecycle_args[@]}" \
    --entrypoint /usr/local/bin/psql \
    "$database_probe_image_id" \
    --no-psqlrc --quiet --tuples-only --no-align \
    --set ON_ERROR_STOP=1 >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="schema-reference-catalog"
  [[ "$ephemeral_image_id" == "$database_probe_image_id" ]] \
    || fail "参考 catalog reader 未绑定 digest-pinned PostgreSQL image ID"
  (
    ulimit -f 32768
    /usr/bin/timeout --signal=TERM --kill-after=10s 120s \
      docker container start --attach --interactive "$ephemeral_container_id"
  ) <"$probe" >"$output"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" "参考 catalog reader"
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  [[ -f "$output" && ! -L "$output" \
    && "$(stat -c '%s' "$output")" -le 16777216 ]] \
    || fail "参考 catalog 输出超出 16MiB 或身份非法"
  chmod 600 "$output"
  assert_reference_server_identity
}

stop_reference_database() {
  local metadata observed_id observed_image running exit_code
  assert_reference_server_identity
  docker container stop --time 20 "$reference_server_id" >/dev/null
  metadata=$(docker container inspect \
    --format '{{.Id}}|{{.Image}}|{{.State.Running}}|{{.State.ExitCode}}' \
    "$reference_server_id") \
    || fail "无法读取已停止参考数据库的 immutable identity"
  IFS='|' read -r observed_id observed_image running exit_code <<<"$metadata"
  [[ "$observed_id" == "$reference_server_id" \
    && "$observed_image" == "$reference_server_image_id" \
    && "$running" == "false" && "$exit_code" == "0" ]] \
    || fail "参考数据库没有以 exact ID/image 正常停止"
  docker container rm --volumes "$reference_server_id" >/dev/null
  reference_server=""
  reference_server_id=""
  reference_server_image_id=""
  reference_server_role=""
  rm -rf -- "$reference_socket_dir"
  reference_socket_dir=""
  reference_password=""
}

run_schema_manifest_probe() {
  local name=$1
  local probe_image=$2
  local role=$3
  local probe=$4
  local output=$5
  ephemeral_container="$name"
  emit_lifecycle_label_args "$name" "$probe_image" "$role"
  docker container create \
    --name "$name" \
    --interactive \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    "${lifecycle_args[@]}" \
    --entrypoint python \
    "$probe_image" -I - >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="$role"
  [[ "$ephemeral_image_id" == "$probe_image" ]] \
    || fail "${role} schema 探针未绑定 immutable image ID"
  docker container start --attach --interactive "$ephemeral_container_id" \
    <"$probe" >"$output"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" "$role"
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
}

assert_candidate_runtime_identity() {
  [[ "$(docker container inspect --format '{{.Id}}' "$container_name")" == "$new_container_id" ]] \
    || fail "候选运行容器 ID 发生变化"
  [[ "$(docker container inspect --format '{{.State.Running}}' "$container_name")" == "true" ]] \
    || fail "候选运行容器未保持 running"
  [[ "$(docker container inspect --format '{{.RestartCount}}' "$container_name")" == "0" ]] \
    || fail "候选运行容器发生重启"
  [[ "$(docker container inspect --format '{{.Image}}' "$container_name")" == "$image_id" ]] \
    || fail "候选运行容器 image ID 发生变化"
  verify_running_revision "$EXPECTED_SHA"
}

write_cutover_journal() {
  local state=$1
  assert_trusted_bundle
  [[ "$(compute_trusted_bundle_sha256)" == "$trusted_bundle_sha256" ]] \
    || fail "写 journal 前 root 受信 bundle 发生变化"
  /usr/bin/python3 -I "$deploy_guard" write-journal \
    --journal "$CUTOVER_JOURNAL" \
    --state "$state" \
    --expected-sha "$EXPECTED_SHA" \
    --trusted-bundle-sha256 "$trusted_bundle_sha256" \
    --container-name "$container_name" \
    --backup-name "$backup_container" \
    --candidate-name "$cutover_candidate_name" \
    --old-container-id "$old_container_id" \
    --candidate-container-id "$candidate_container_id" \
    --old-image-id "$old_image_id" \
    --candidate-image-id "$image_id"
}

prepare_expand_rehearsal_role() {
  local super_env=$1
  local role_env=$2
  expand_rehearsal_password=$(/usr/bin/python3 -I -c \
    'import secrets; print(secrets.token_hex(32))')
  [[ "$expand_rehearsal_password" =~ ^[0-9a-f]{64}$ ]] \
    || fail "无法生成隔离迁移角色凭据"
  assert_reference_server_identity
  docker exec --interactive \
    --env "PGPASSWORD=${reference_password}" \
    "$reference_server_id" /usr/local/bin/psql \
    --no-psqlrc --quiet --set ON_ERROR_STOP=1 \
    --set "rehearsal_password=${expand_rehearsal_password}" \
    --host /var/run/postgresql --username xjie_reference \
    --dbname xjie_reference <<'SQL'
CREATE ROLE xjie_migration_rehearsal LOGIN PASSWORD :'rehearsal_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER DATABASE xjie_reference OWNER TO xjie_migration_rehearsal;
ALTER SCHEMA public OWNER TO xjie_migration_rehearsal;
GRANT ALL ON SCHEMA public TO xjie_migration_rehearsal;
SQL
  printf '%s\n' \
    'PGHOST=/var/run/postgresql' \
    'PGPORT=5432' \
    'PGUSER=xjie_reference' \
    "PGPASSWORD=${reference_password}" \
    'PGDATABASE=xjie_reference' >"$super_env"
  printf '%s\n' \
    'PGHOST=/var/run/postgresql' \
    'PGPORT=5432' \
    'PGUSER=xjie_migration_rehearsal' \
    "PGPASSWORD=${expand_rehearsal_password}" \
    'PGDATABASE=xjie_reference' >"$role_env"
  chmod 600 "$super_env" "$role_env"
}

run_expand_backup() {
  local name=$1
  local backup=$2
  local stderr_path="${runtime_dir}/schema-backup.stderr"
  local status=0
  prepare_database_probe_image
  [[ ! -e "$backup" && ! -L "$backup" ]] \
    || fail "未验证 schema 备份路径已存在"
  : >"$stderr_path"
  chmod 600 "$stderr_path"
  emit_lifecycle_label_args "$name" "$database_probe_image_id" schema-backup
  ephemeral_container="$name"
  docker container create \
    --platform linux/amd64 \
    --name "$name" \
    --env-file "$database_migration_env_snapshot" \
    --user 70:70 \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --restart no \
    --memory 512m --memory-swap 512m --pids-limit 128 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --add-host "$DATABASE_PROBE_EXTRA_HOST" \
    "${lifecycle_args[@]}" \
    --entrypoint /usr/local/bin/pg_dump \
    "$database_probe_image_id" \
    --format=custom --compress=gzip:9 --no-owner --no-privileges \
    --serializable-deferrable >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="schema-backup"
  [[ "$ephemeral_image_id" == "$database_probe_image_id" ]] \
    || fail "schema 备份未绑定 digest-pinned PostgreSQL image"
  if (
    set -o noclobber
    exec 9>"$backup"
    /usr/bin/timeout --signal=TERM --kill-after=30s 900s \
      docker container start --attach "$ephemeral_container_id" \
      >&9 2>"$stderr_path"
  ); then
    status=0
  else
    status=$?
  fi
  chmod 600 "$backup" "$stderr_path" 2>/dev/null || true
  [[ "$status" -eq 0 && ! -s "$stderr_path" ]] \
    || fail "生产 schema pg_dump 失败或产生 stderr"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" schema-backup
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  rm -f -- "$stderr_path"
}

run_expand_database_size_probe() {
  local name=$1
  local output=$2
  local probe="${runtime_dir}/production-database-size.sql"
  printf '%s\n' \
    '\\set ON_ERROR_STOP on' \
    'SELECT pg_catalog.pg_database_size(current_database());' >"$probe"
  chmod 600 "$probe"
  run_database_schema_probe \
    "$name" "$probe" "$output" "$database_probe_env_snapshot" 4096
  rm -f -- "$probe"
}

run_expand_backup_toc() {
  local name=$1
  local backup=$2
  local toc=$3
  local stderr_path="${runtime_dir}/schema-backup-toc.stderr"
  local status=0
  prepare_database_probe_image
  : >"$toc"
  : >"$stderr_path"
  chmod 600 "$toc" "$stderr_path"
  emit_lifecycle_label_args \
    "$name" "$database_probe_image_id" schema-backup-toc
  ephemeral_container="$name"
  docker container create \
    --platform linux/amd64 \
    --name "$name" \
    --network none --log-driver none \
    --interactive --user 70:70 --read-only \
    --cap-drop ALL --security-opt no-new-privileges --restart no \
    --memory 256m --memory-swap 256m --pids-limit 128 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    "${lifecycle_args[@]}" \
    --entrypoint /usr/local/bin/pg_restore \
    "$database_probe_image_id" --list >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="schema-backup-toc"
  if /usr/bin/timeout --signal=TERM --kill-after=10s 120s \
    docker container start --attach --interactive "$ephemeral_container_id" \
    <"$backup" >"$toc" 2>"$stderr_path"; then
    status=0
  else
    status=$?
  fi
  chmod 600 "$toc" "$stderr_path"
  [[ "$status" -eq 0 && ! -s "$stderr_path" ]] \
    || fail "pg_restore --list 未能完整读取 schema 备份"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" schema-backup-toc
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  rm -f -- "$stderr_path"
}

run_expand_restore() {
  local name=$1
  local backup=$2
  local super_env=$3
  local stderr_path="${runtime_dir}/schema-restore.stderr"
  local status=0
  assert_reference_server_identity
  : >"$stderr_path"
  chmod 600 "$stderr_path"
  emit_lifecycle_label_args "$name" "$database_probe_image_id" schema-restore
  ephemeral_container="$name"
  docker container create \
    --platform linux/amd64 \
    --name "$name" \
    --network none --log-driver none \
    --env-file "$super_env" \
    --interactive --user 70:70 --read-only \
    --cap-drop ALL --security-opt no-new-privileges --restart no \
    --memory 512m --memory-swap 512m --pids-limit 128 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    --mount "type=bind,src=${reference_socket_dir},dst=/var/run/postgresql,readonly" \
    "${lifecycle_args[@]}" \
    --entrypoint /usr/local/bin/pg_restore \
    "$database_probe_image_id" \
    --exit-on-error --no-owner --no-privileges \
    --role=xjie_migration_rehearsal --dbname=xjie_reference >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="schema-restore"
  if /usr/bin/timeout --signal=TERM --kill-after=30s 900s \
    docker container start --attach --interactive "$ephemeral_container_id" \
    <"$backup" >/dev/null 2>"$stderr_path"; then
    status=0
  else
    status=$?
  fi
  chmod 600 "$stderr_path"
  [[ "$status" -eq 0 && ! -s "$stderr_path" ]] \
    || fail "隔离 PG16 pg_restore 失败或产生 stderr"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" schema-restore
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  rm -f -- "$stderr_path"
  assert_reference_server_identity
}

run_expand_python_probe() {
  local name=$1
  local role=$2
  local probe_image=$3
  local probe=$4
  local result=$5
  local probe_env=$6
  local connection_mode=$7
  local stderr_path="${runtime_dir}/${role}.stderr"
  local status=0
  local -a connection_args=()
  if [[ "$connection_mode" == "isolated" ]]; then
    connection_args=(
      --network none --log-driver none
      --mount "type=bind,src=${reference_socket_dir},dst=/var/run/postgresql,readonly"
    )
  elif [[ "$connection_mode" == "production" ]]; then
    connection_args=(--add-host "$DATABASE_PROBE_EXTRA_HOST")
  else
    fail "未知 expand Python probe 连接模式"
  fi
  : >"$result"
  : >"$stderr_path"
  chmod 600 "$result" "$stderr_path"
  emit_lifecycle_label_args "$name" "$probe_image" "$role"
  ephemeral_container="$name"
  docker container create \
    --name "$name" \
    "${connection_args[@]}" \
    --env-file "$probe_env" \
    --interactive --user 65534:65534 --read-only \
    --cap-drop ALL --security-opt no-new-privileges --restart no \
    --memory 512m --memory-swap 512m --pids-limit 128 \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
    "${lifecycle_args[@]}" \
    --entrypoint python "$probe_image" -I - >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$name")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$name")
  ephemeral_role="$role"
  [[ "$ephemeral_image_id" == "$probe_image" ]] \
    || fail "${role} 未绑定指定 immutable image"
  if /usr/bin/timeout --signal=TERM --kill-after=30s 900s \
    docker container start --attach --interactive "$ephemeral_container_id" \
    <"$probe" >"$result" 2>"$stderr_path"; then
    status=0
  else
    status=$?
  fi
  chmod 600 "$result" "$stderr_path"
  [[ "$status" -eq 0 && ! -s "$stderr_path" \
    && "$(stat -c '%s' "$result")" -le 65536 ]] \
    || fail "${role} 失败、产生 stderr 或输出超限"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" "$role"
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  rm -f -- "$stderr_path"
}

if [[ "$ACTION" == "deploy" || "$ACTION" == "expand-deploy" ]]; then
  step "构建 EXPECTED_SHA 候选镜像"
  image_ref="${image_repository}:main-${EXPECTED_SHA}"
  image_id_path="${runtime_dir}/candidate-image-id"
  docker build \
    --pull \
    --platform linux/amd64 \
    --label "org.opencontainers.image.revision=${EXPECTED_SHA}" \
    --iidfile "$image_id_path" \
    --tag "$image_ref" \
    "$source_root/backend"
  image_id=$(<"$image_id_path")
  image_metadata=$(docker image inspect \
    --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}|{{.Os}}|{{.Architecture}}' \
    "$image_id")
  IFS='|' read -r image_revision image_os image_architecture <<<"$image_metadata"
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ \
    && "$image_revision" == "$EXPECTED_SHA" \
    && "$image_os" == "linux" && "$image_architecture" == "amd64" ]] \
    || fail "候选镜像 ID/revision/platform 无法绑定 EXPECTED_SHA"
  [[ "$(docker image inspect --format '{{.Id}}' "$image_ref")" == "$image_id" ]] \
    || fail "候选 tag 没有绑定 --iidfile 捕获的 image ID"

  step "在候选镜像内执行版本控制的 backend 精确清单门禁"
  test_container="${container_name}-deploy-${deployment_run_id}-backend-test"
  ephemeral_container="$test_container"
  emit_lifecycle_label_args "$test_container" "$image_id" backend-test
  docker container create \
    --name "$test_container" \
    --network none \
    "${lifecycle_args[@]}" \
    --entrypoint python \
    "$image_id" \
    -I -m pytest tests -q --junitxml=/tmp/xjie-backend-full.xml >/dev/null
  ephemeral_container_id=$(docker container inspect --format '{{.Id}}' "$test_container")
  ephemeral_image_id=$(docker container inspect --format '{{.Image}}' "$test_container")
  ephemeral_role="backend-test"
  [[ "$ephemeral_image_id" == "$image_id" ]] \
    || fail "backend test 容器未绑定候选 image ID"
  docker container start --attach "$ephemeral_container_id"
  assert_exact_stopped_one_shot \
    "$ephemeral_container_id" "$ephemeral_image_id" "候选 backend tests"
  docker container cp "$ephemeral_container_id:/tmp/xjie-backend-full.xml" \
    "$runtime_dir/backend-full.xml"
  docker container rm --volumes "$ephemeral_container_id" >/dev/null
  ephemeral_container=""
  ephemeral_container_id=""
  ephemeral_image_id=""
  ephemeral_role=""
  [[ -f "$runtime_dir/backend-full.xml" && ! -L "$runtime_dir/backend-full.xml" ]] \
    || fail "候选 backend JUnit 不是本机普通文件"
  chmod 600 "$runtime_dir/backend-full.xml"
  assert_trusted_bundle
  [[ "$(compute_trusted_bundle_sha256)" == "$trusted_bundle_sha256" ]] \
    || fail "校验 backend JUnit 前 root 受信 bundle 发生变化"
  broker_request JUNIT

  step "扫描候选镜像全部历史 layer、Config.Env 与禁入秘密材料"
  image_scan_inspect="${runtime_dir}/candidate-image-scan.json"
  image_scan_archive="${runtime_dir}/candidate-image-save.tar"
  docker image inspect "$image_id" >"$image_scan_inspect"
  docker image save --output "$image_scan_archive" "$image_id"
  chmod 600 "$image_scan_inspect" "$image_scan_archive"
  /usr/bin/python3 -I "$deploy_guard" scan-image \
    --image-inspect "$image_scan_inspect" \
    --image-archive "$image_scan_archive" \
    --env-file "$env_snapshot" \
    --expected-image-id "$image_id"
  rm -f -- "$image_scan_inspect" "$image_scan_archive"

  step "证明运行镜像与候选镜像没有 migration/model schema delta"
  migration_probe="${runtime_dir}/migration-manifest-probe.py"
  old_migration_manifest="${runtime_dir}/old-migration-manifest.json"
  candidate_migration_manifest="${runtime_dir}/candidate-migration-manifest.json"
  /usr/bin/python3 -I "$deploy_guard" emit-migration-probe \
    --output "$migration_probe"
  old_schema_container="${container_name}-deploy-${deployment_run_id}-schema-old"
  run_schema_manifest_probe \
    "$old_schema_container" "$old_image_id" schema-old \
    "$migration_probe" "$old_migration_manifest"
  candidate_schema_container="${container_name}-deploy-${deployment_run_id}-schema-candidate"
  run_schema_manifest_probe \
    "$candidate_schema_container" "$image_id" schema-candidate \
    "$migration_probe" "$candidate_migration_manifest"
  chmod 600 "$old_migration_manifest" "$candidate_migration_manifest"

  timestamp=$(date -u +%Y%m%d%H%M%S)
  candidate_container="${container_name}-deploy-${deployment_run_id}-candidate"
  backup_container="${container_name}-backup-main-${EXPECTED_SHA:0:12}-${timestamp}"
  container_exists "$candidate_container" && fail "候选容器名已存在"
  container_exists "$backup_container" && fail "回滚容器名已存在"

  candidate_args_path="$runtime_dir/candidate-args.bin"
  /usr/bin/python3 -I "$deploy_guard" create-args \
    --spec "$spec_path" \
    --name "$candidate_container" \
    --image "$image_id" \
    --image-ref "$image_ref" \
    --env-file "$env_snapshot" \
    --env-source "$secret_env_file" \
    --expected-sha "$EXPECTED_SHA" \
    --run-id "$deployment_run_id" \
    --role candidate \
    --output "$candidate_args_path"
  mapfile -d '' -t candidate_args <"$candidate_args_path"
  docker "${candidate_args[@]}" >/dev/null
  candidate_container_id=$(docker container inspect --format '{{.Id}}' "$candidate_container")
  [[ "$(docker container inspect --format '{{.Image}}' "$candidate_container")" == "$image_id" ]] \
    || fail "候选容器创建后未绑定候选 image ID"

  step "验证声明式候选不会继承旧镜像默认值"
  docker container inspect "$container_name" >"$runtime_dir/old-container.json"
  docker image inspect "$old_image_id" >"$runtime_dir/old-image.json"
  docker container inspect "$candidate_container" >"$runtime_dir/candidate-container.json"
  docker image inspect "$image_id" >"$runtime_dir/candidate-image.json"
  chmod 600 "$runtime_dir"/*.json
  /usr/bin/python3 -I "$deploy_guard" validate-inspects \
    --spec "$spec_path" \
    --old-container "$runtime_dir/old-container.json" \
    --old-image "$runtime_dir/old-image.json" \
    --candidate-container "$runtime_dir/candidate-container.json" \
    --candidate-image "$runtime_dir/candidate-image.json" \
    --env-file "$env_snapshot" \
    --expected-sha "$EXPECTED_SHA"
  rm -f -- "$runtime_dir/old-container.json" "$runtime_dir/old-image.json" \
    "$runtime_dir/candidate-container.json" "$runtime_dir/candidate-image.json"
  [[ "$(docker container inspect --format '{{.Id}}' "$container_name")" == "$old_container_id" ]] \
    || fail "生产容器在部署锁内被替换"
  [[ "$(docker container inspect --format '{{.Id}}' "$candidate_container")" == "$candidate_container_id" ]] \
    || fail "候选容器在声明式核验后被替换"

  step "数据库只读核对前重新验证官方候选资格"
  verify_official_candidate
  step "只读获取候选 Alembic heads 与生产数据库当前 revision"
  run_migration_command \
    "${container_name}-deploy-${deployment_run_id}-alembic-heads" \
    alembic-heads \
    "$runtime_dir/alembic-heads.txt" \
    alembic heads --verbose
  run_migration_command \
    "${container_name}-deploy-${deployment_run_id}-alembic-current" \
    alembic-current \
    "$runtime_dir/alembic-current.txt" \
    alembic current --verbose
  if [[ "$ACTION" == "deploy" ]]; then
    step "验证生产数据库已处于候选 Alembic heads（普通 deploy 禁止 DDL）"
    /usr/bin/python3 -I "$deploy_guard" validate-no-migration-delta \
      --old-manifest "$old_migration_manifest" \
      --candidate-manifest "$candidate_migration_manifest" \
      --heads "$runtime_dir/alembic-heads.txt" \
      --current "$runtime_dir/alembic-current.txt"
    step "在断网临时 PostgreSQL 中物化候选模型的参考数据库结构"
    reference_schema_materializer="${runtime_dir}/reference-schema-materializer.py"
    reference_catalog_probe="${runtime_dir}/reference-catalog-probe.sql"
    reference_catalog="${runtime_dir}/reference-schema-catalog.json"
    /usr/bin/python3 -I "$deploy_guard" emit-reference-schema-materializer \
      --candidate-manifest "$candidate_migration_manifest" \
      --output "$reference_schema_materializer"
    /usr/bin/python3 -I "$deploy_guard" emit-reference-catalog-probe \
      --candidate-manifest "$candidate_migration_manifest" \
      --output "$reference_catalog_probe"
    start_reference_database \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-server"
    run_reference_schema_materializer \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-materializer" \
      "$reference_schema_materializer" \
      "$candidate_migration_manifest"
    run_reference_catalog_probe \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-catalog" \
      "$reference_catalog_probe" \
      "$reference_catalog"
    stop_reference_database
    rm -f -- "$reference_schema_materializer" "$reference_catalog_probe"

    step "只向 digest-pinned psql 提供生产凭据并核对参考 catalog"
    /usr/bin/python3 -I "$deploy_guard" snapshot-database-probe-env \
      --spec "$spec_path" \
      --source "$secret_env_file" \
      --application-env "$env_snapshot" \
      --output "$database_probe_env_snapshot"
    database_schema_probe="${runtime_dir}/database-schema-probe.py"
    database_schema_result="${runtime_dir}/database-schema-result.json"
    /usr/bin/python3 -I "$deploy_guard" emit-database-schema-probe \
      --candidate-manifest "$candidate_migration_manifest" \
      --reference-catalog "$reference_catalog" \
      --output "$database_schema_probe"
    run_database_schema_probe \
      "${container_name}-deploy-${deployment_run_id}-database-schema" \
      "$database_schema_probe" \
      "$database_schema_result" \
      "$database_probe_env_snapshot"
    /usr/bin/python3 -I "$deploy_guard" validate-database-schema \
      --candidate-manifest "$candidate_migration_manifest" \
      --reference-catalog "$reference_catalog" \
      --database-catalog "$database_schema_result"
    rm -f -- "$migration_probe" "$old_migration_manifest" \
      "$candidate_migration_manifest" "$runtime_dir/alembic-heads.txt" \
      "$runtime_dir/alembic-current.txt" "$database_schema_probe" \
      "$database_schema_result" "$database_probe_env_snapshot" \
      "$reference_catalog"
    database_probe_env_snapshot=""
  else
    step "验证 exact old history 与唯一线性 additive migration chain"
    expand_migration_source="${runtime_dir}/expand-migrations.json"
    expand_migration_plan="${runtime_dir}/expand-migration-plan.json"
    /usr/bin/python3 -I "$deploy_guard" extract-expand-migration-source \
      --old-manifest "$old_migration_manifest" \
      --candidate-manifest "$candidate_migration_manifest" \
      --source-root "$source_root" \
      --output "$expand_migration_source"
    /usr/bin/python3 -I "$deploy_guard" validate-expand-migration \
      --old-manifest "$old_migration_manifest" \
      --candidate-manifest "$candidate_migration_manifest" \
      --migration-source "$expand_migration_source" \
      --output "$expand_migration_plan"
    expand_plan_values_path="${runtime_dir}/expand-plan-values.bin"
    /usr/bin/python3 -I "$deploy_guard" read-expand-migration-plan \
      --plan "$expand_migration_plan" \
      --output "$expand_plan_values_path"
    mapfile -d '' -t expand_plan_values <"$expand_plan_values_path"
    [[ "${#expand_plan_values[@]}" -eq 2 ]] \
      || fail "expand migration plan 导出字段数不正确"
    expand_old_head=${expand_plan_values[0]}
    expand_candidate_head=${expand_plan_values[1]}

    step "分别由 old/candidate immutable image 物化独立参考 catalog"
    old_reference_materializer="${runtime_dir}/old-reference-materializer.py"
    old_reference_probe="${runtime_dir}/old-reference-catalog.sql"
    old_reference_catalog="${runtime_dir}/old-reference-catalog.json"
    candidate_reference_materializer="${runtime_dir}/candidate-reference-materializer.py"
    candidate_reference_probe="${runtime_dir}/candidate-reference-catalog.sql"
    candidate_reference_catalog="${runtime_dir}/candidate-reference-catalog.json"
    /usr/bin/python3 -I "$deploy_guard" emit-reference-schema-materializer \
      --candidate-manifest "$old_migration_manifest" \
      --output "$old_reference_materializer"
    /usr/bin/python3 -I "$deploy_guard" emit-reference-catalog-probe \
      --candidate-manifest "$old_migration_manifest" \
      --output "$old_reference_probe"
    start_reference_database \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-server"
    run_reference_schema_materializer \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-materializer" \
      "$old_reference_materializer" "$old_migration_manifest" \
      "$old_image_id" validate-expand-reference-materializer-result
    run_reference_catalog_probe \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-catalog" \
      "$old_reference_probe" "$old_reference_catalog"
    stop_reference_database
    /usr/bin/python3 -I "$deploy_guard" emit-reference-schema-materializer \
      --candidate-manifest "$candidate_migration_manifest" \
      --output "$candidate_reference_materializer"
    /usr/bin/python3 -I "$deploy_guard" emit-reference-catalog-probe \
      --candidate-manifest "$candidate_migration_manifest" \
      --output "$candidate_reference_probe"
    start_reference_database \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-server"
    run_reference_schema_materializer \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-materializer" \
      "$candidate_reference_materializer" "$candidate_migration_manifest" \
      "$image_id" validate-expand-reference-materializer-result
    run_reference_catalog_probe \
      "${container_name}-deploy-${deployment_run_id}-schema-reference-catalog" \
      "$candidate_reference_probe" "$candidate_reference_catalog"
    stop_reference_database
    /usr/bin/python3 -I "$deploy_guard" validate-expand-catalog-transition \
      --old-manifest "$old_migration_manifest" \
      --candidate-manifest "$candidate_migration_manifest" \
      --old-catalog "$old_reference_catalog" \
      --migrated-catalog "$candidate_reference_catalog" \
      --candidate-reference-catalog "$candidate_reference_catalog" \
      --plan "$expand_migration_plan"

    step "以独立只读角色证明生产当前 head/catalog 是完全 old 或完全 candidate"
    /usr/bin/python3 -I "$deploy_guard" snapshot-database-probe-env \
      --spec "$spec_path" --source "$secret_env_file" \
      --application-env "$env_snapshot" \
      --output "$database_probe_env_snapshot"
    observed_head_path="${runtime_dir}/observed-head.bin"
    /usr/bin/python3 -I "$deploy_guard" validate-expand-observed-head \
      --plan "$expand_migration_plan" \
      --input "$runtime_dir/alembic-current.txt" \
      --output "$observed_head_path"
    mapfile -d '' -t observed_head_values <"$observed_head_path"
    [[ "${#observed_head_values[@]}" -eq 1 ]] \
      || fail "生产数据库 observed head 导出不唯一"
    observed_head=${observed_head_values[0]}
    if [[ "$observed_head" == "$expand_old_head" ]]; then
      observed_manifest="$old_migration_manifest"
      observed_reference_catalog="$old_reference_catalog"
      observed_catalog_probe="$old_reference_probe"
    elif [[ "$observed_head" == "$expand_candidate_head" ]]; then
      observed_manifest="$candidate_migration_manifest"
      observed_reference_catalog="$candidate_reference_catalog"
      observed_catalog_probe="$candidate_reference_probe"
    else
      fail "生产数据库 head 不属于批准的 expand 两态"
    fi
    observed_schema_probe="${runtime_dir}/observed-schema-probe.sql"
    observed_schema_result="${runtime_dir}/observed-schema-result.json"
    observed_production_catalog="${runtime_dir}/observed-production-catalog.json"
    /usr/bin/python3 -I "$deploy_guard" emit-database-schema-probe \
      --candidate-manifest "$observed_manifest" \
      --reference-catalog "$observed_reference_catalog" \
      --output "$observed_schema_probe"
    run_database_schema_probe \
      "${container_name}-deploy-${deployment_run_id}-database-schema" \
      "$observed_schema_probe" "$observed_schema_result" \
      "$database_probe_env_snapshot"
    /usr/bin/python3 -I "$deploy_guard" validate-database-schema \
      --candidate-manifest "$observed_manifest" \
      --reference-catalog "$observed_reference_catalog" \
      --database-catalog "$observed_schema_result"
    run_database_schema_probe \
      "${container_name}-deploy-${deployment_run_id}-database-schema" \
      "$observed_catalog_probe" "$observed_production_catalog" \
      "$database_probe_env_snapshot" 16777216

    step "生成 owner-only 审批计划并请求 root 独立 SHA-256 审批"
    expand_approval_plan="${STATE_DIR}/xjie-production-expand-plan-${EXPECTED_SHA}.json"
    if [[ -e "$expand_approval_plan" || -L "$expand_approval_plan" ]]; then
      candidate_approval_plan="${runtime_dir}/candidate-expand-approval-plan.json"
      /usr/bin/python3 -I "$deploy_guard" emit-expand-approval-plan \
        --expected-main-sha "$EXPECTED_SHA" \
        --trusted-bundle-sha256 "$trusted_bundle_sha256" \
        --old-manifest "$old_migration_manifest" \
        --candidate-manifest "$candidate_migration_manifest" \
        --old-catalog "$old_reference_catalog" \
        --candidate-catalog "$candidate_reference_catalog" \
        --plan "$expand_migration_plan" --output "$candidate_approval_plan"
      /usr/bin/python3 -I "$deploy_guard" validate-expand-approval-plan \
        --approval-plan "$expand_approval_plan" \
        --plan "$expand_migration_plan"
      cmp -s -- "$candidate_approval_plan" "$expand_approval_plan" \
        || fail "持久 expand 审批计划与本次 exact inputs 不同"
    else
      /usr/bin/python3 -I "$deploy_guard" emit-expand-approval-plan \
        --expected-main-sha "$EXPECTED_SHA" \
        --trusted-bundle-sha256 "$trusted_bundle_sha256" \
        --old-manifest "$old_migration_manifest" \
        --candidate-manifest "$candidate_migration_manifest" \
        --old-catalog "$old_reference_catalog" \
        --candidate-catalog "$candidate_reference_catalog" \
        --plan "$expand_migration_plan" --output "$expand_approval_plan"
    fi
    broker_request "MIGRATION ${EXPECTED_SHA}" >/dev/null

    step "审批通过后才提取独立 migration role 的最小 PG identity"
    database_migration_env_snapshot="${runtime_dir}/database-migration.env"
    /usr/bin/python3 -I "$deploy_guard" snapshot-database-migration-env \
      --spec "$spec_path" --source "$secret_env_file" \
      --application-env "$env_snapshot" \
      --output "$database_migration_env_snapshot"
    expand_journal="${STATE_DIR}/xjie-production-expand-journal-${EXPECTED_SHA}.json"
    expand_backup_path="${STATE_DIR}/xjie-production-schema-backup-${EXPECTED_SHA}.dump"
    expand_evidence_path="${STATE_DIR}/xjie-production-expand-evidence-${EXPECTED_SHA}.json"
    if [[ -e "$expand_journal" || -L "$expand_journal" ]]; then
      /usr/bin/python3 -I "$deploy_guard" validate-expand-journal-binding \
        --journal "$expand_journal" --approval-plan "$expand_approval_plan" \
        --plan "$expand_migration_plan" --backup-path "$expand_backup_path" \
        --old-image-id "$old_image_id" --candidate-image-id "$image_id"
    else
      [[ "$observed_head" == "$expand_old_head" ]] \
        || fail "无 journal 时生产数据库不得预先处于 candidate head"
      /usr/bin/python3 -I "$deploy_guard" start-expand-journal \
        --journal "$expand_journal" --approval-plan "$expand_approval_plan" \
        --plan "$expand_migration_plan" --backup-path "$expand_backup_path" \
        --old-image-id "$old_image_id" --candidate-image-id "$image_id"
    fi
    expand_journal_values_path="${runtime_dir}/expand-journal-values.bin"
    /usr/bin/python3 -I "$deploy_guard" read-expand-journal \
      --journal "$expand_journal" --output "$expand_journal_values_path"
    mapfile -d '' -t expand_journal_values <"$expand_journal_values_path"
    [[ "${#expand_journal_values[@]}" -eq 5 ]] \
      || fail "expand journal 导出字段数不正确"
    expand_journal_state=${expand_journal_values[0]}
    expand_recovery_path="${runtime_dir}/expand-recovery.bin"
    /usr/bin/python3 -I "$deploy_guard" plan-expand-recovery-catalog \
      --journal "$expand_journal" --observed-head "$observed_head" \
      --observed-manifest "$observed_manifest" \
      --observed-catalog "$observed_production_catalog" \
      --output "$expand_recovery_path"
    mapfile -d '' -t expand_recovery_values <"$expand_recovery_path"
    [[ "${#expand_recovery_values[@]}" -eq 1 ]] \
      || fail "expand recovery 计划不唯一"
    expand_action=${expand_recovery_values[0]}

    expand_runner="${runtime_dir}/expand-transaction-runner.py"
    expand_transaction_result="${runtime_dir}/expand-production-result.json"
    rehearsal_result="${runtime_dir}/expand-rehearsal-result.json"
    old_compat_result="${runtime_dir}/expand-old-app-compat.json"
    /usr/bin/python3 -I "$deploy_guard" emit-expand-transaction-runner \
      --plan "$expand_migration_plan" --output "$expand_runner"

    if [[ "$expand_action" == "resume_backup" ]]; then
      step "创建 production pg_dump custom 备份并验证完整 TOC"
      /usr/bin/python3 -I "$deploy_guard" reset-unverified-expand-backup \
        --journal "$expand_journal"
      run_expand_backup \
        "${container_name}-deploy-${deployment_run_id}-schema-backup" \
        "$expand_backup_path"
      expand_backup_toc="${runtime_dir}/expand-backup.toc"
      expand_backup_attestation="${runtime_dir}/expand-backup-attestation.json"
      run_expand_backup_toc \
        "${container_name}-deploy-${deployment_run_id}-schema-backup-toc" \
        "$expand_backup_path" "$expand_backup_toc"
      /usr/bin/python3 -I "$deploy_guard" attest-expand-backup \
        --backup "$expand_backup_path" --toc "$expand_backup_toc" \
        --output "$expand_backup_attestation"
      /usr/bin/python3 -I "$deploy_guard" advance-expand-journal \
        --journal "$expand_journal" --state backup_verified \
        --backup-attestation "$expand_backup_attestation"
      expand_action="resume_restore_rehearsal"
    fi

    if [[ "$expand_action" == "resume_restore_rehearsal" ]]; then
      step "在隔离 PG16 恢复真实备份、执行同一事务 runner、核对 catalog 与旧应用 CRUD"
      rehearsal_backup_toc="${runtime_dir}/rehearsal-backup.toc"
      rehearsal_backup_attestation="${runtime_dir}/rehearsal-backup-attestation.json"
      rehearsal_super_env="${runtime_dir}/rehearsal-super.env"
      rehearsal_role_env="${runtime_dir}/rehearsal-role.env"
      rehearsal_catalog="${runtime_dir}/expand-rehearsal-catalog.json"
      old_compat_probe="${runtime_dir}/expand-old-app-compat.py"
      production_database_size="${runtime_dir}/production-database-size.txt"
      restore_volume_capacity="${runtime_dir}/restore-volume-capacity.txt"
      restore_volume_inspect="${runtime_dir}/restore-volume-inspect.json"
      restore_volume_attestation="${runtime_dir}/restore-volume-attestation.json"
      run_expand_backup_toc \
        "${container_name}-deploy-${deployment_run_id}-schema-backup-toc" \
        "$expand_backup_path" "$rehearsal_backup_toc"
      /usr/bin/python3 -I "$deploy_guard" attest-expand-backup \
        --backup "$expand_backup_path" --toc "$rehearsal_backup_toc" \
        --output "$rehearsal_backup_attestation"
      /usr/bin/python3 -I "$deploy_guard" validate-expand-backup-binding \
        --journal "$expand_journal" \
        --backup-attestation "$rehearsal_backup_attestation"
      run_expand_database_size_probe \
        "${container_name}-deploy-${deployment_run_id}-database-schema" \
        "$production_database_size"
      create_restore_volume
      run_restore_volume_capacity_probe \
        "${container_name}-deploy-${deployment_run_id}-schema-restore-capacity" \
        "$restore_volume_capacity"
      docker volume inspect "$restore_volume_name" >"$restore_volume_inspect"
      chmod 600 "$restore_volume_inspect"
      /usr/bin/python3 -I "$deploy_guard" attest-expand-restore-volume \
        --inspect "$restore_volume_inspect" \
        --database-size "$production_database_size" \
        --capacity "$restore_volume_capacity" \
        --backup-attestation "$rehearsal_backup_attestation" \
        --expected-sha "$EXPECTED_SHA" --run-id "$deployment_run_id" \
        --image-id "$database_probe_image_id" \
        --output "$restore_volume_attestation"
      initialize_restore_volume \
        "${container_name}-deploy-${deployment_run_id}-schema-restore-volume-init"
      start_reference_database \
        "${container_name}-deploy-${deployment_run_id}-schema-restore-server" \
        restore-volume
      prepare_expand_rehearsal_role "$rehearsal_super_env" "$rehearsal_role_env"
      run_expand_restore \
        "${container_name}-deploy-${deployment_run_id}-schema-restore" \
        "$expand_backup_path" "$rehearsal_super_env"
      run_expand_python_probe \
        "${container_name}-deploy-${deployment_run_id}-schema-migration-rehearsal" \
        schema-migration-rehearsal "$image_id" "$expand_runner" \
        "$rehearsal_result" "$rehearsal_role_env" isolated
      /usr/bin/python3 -I "$deploy_guard" validate-expand-transaction-result \
        --plan "$expand_migration_plan" --result "$rehearsal_result"
      run_reference_catalog_probe \
        "${container_name}-deploy-${deployment_run_id}-schema-reference-catalog" \
        "$candidate_reference_probe" "$rehearsal_catalog"
      /usr/bin/python3 -I "$deploy_guard" validate-expand-catalog-transition \
        --old-manifest "$old_migration_manifest" \
        --candidate-manifest "$candidate_migration_manifest" \
        --old-catalog "$old_reference_catalog" \
        --migrated-catalog "$rehearsal_catalog" \
        --candidate-reference-catalog "$candidate_reference_catalog" \
        --plan "$expand_migration_plan"
      /usr/bin/python3 -I "$deploy_guard" emit-expand-old-app-compat-probe \
        --old-manifest "$old_migration_manifest" \
        --plan "$expand_migration_plan" --output "$old_compat_probe"
      run_expand_python_probe \
        "${container_name}-deploy-${deployment_run_id}-schema-old-compat" \
        schema-old-compat "$old_image_id" "$old_compat_probe" \
        "$old_compat_result" "$rehearsal_role_env" isolated
      /usr/bin/python3 -I "$deploy_guard" validate-expand-old-app-compat-result \
        --old-manifest "$old_migration_manifest" \
        --plan "$expand_migration_plan" --result "$old_compat_result"
      stop_reference_database
      remove_exact_restore_volume \
        || fail "隔离 restore volume 未能按 exact identity 清理"
      rm -f -- "$rehearsal_super_env" "$rehearsal_role_env"
      expand_rehearsal_password=""
      /usr/bin/python3 -I "$deploy_guard" advance-expand-journal \
        --journal "$expand_journal" --state restore_verified \
        --restore-volume-attestation "$restore_volume_attestation"
      expand_action="start_transaction"
    fi

    if [[ ! -e "$rehearsal_result" && ! -L "$rehearsal_result" ]]; then
      /usr/bin/python3 -I "$deploy_guard" emit-expected-expand-transaction-result \
        --plan "$expand_migration_plan" --output "$rehearsal_result"
    fi
    if [[ ! -e "$old_compat_result" && ! -L "$old_compat_result" ]]; then
      /usr/bin/python3 -I "$deploy_guard" \
        emit-expected-expand-old-app-compat-result \
        --old-manifest "$old_migration_manifest" \
        --plan "$expand_migration_plan" --output "$old_compat_result"
    fi

    if [[ "$expand_action" == "start_transaction" \
      || "$expand_action" == "retry_transaction" ]]; then
      step "最终资格复核后以 migration role 执行唯一生产事务"
      if [[ "$expand_action" == "start_transaction" ]]; then
        /usr/bin/python3 -I "$deploy_guard" advance-expand-journal \
          --journal "$expand_journal" --state production_transaction_started
      fi
      verify_official_candidate
      container_internal_health "$container_name" \
        || fail "生产 expand 事务前旧应用不健康"
      run_expand_python_probe \
        "${container_name}-deploy-${deployment_run_id}-schema-migration-production" \
        schema-migration-production "$image_id" "$expand_runner" \
        "$expand_transaction_result" "$database_migration_env_snapshot" production
      /usr/bin/python3 -I "$deploy_guard" validate-expand-transaction-result \
        --plan "$expand_migration_plan" --result "$expand_transaction_result"
      expand_action="resume_post_transaction_attestation"
    elif [[ "$expand_action" == "resume_post_transaction_attestation" \
      || "$expand_action" == "resume_cutover" \
      || "$expand_action" == "complete" ]]; then
      /usr/bin/python3 -I "$deploy_guard" emit-expected-expand-transaction-result \
        --plan "$expand_migration_plan" --output "$expand_transaction_result"
    else
      fail "expand recovery 返回未知动作: ${expand_action}"
    fi

    if [[ "$expand_action" == "resume_post_transaction_attestation" ]]; then
      step "事务后以只读角色精确证明 candidate head/catalog 且旧应用仍健康"
      post_production_catalog="${runtime_dir}/post-production-catalog.json"
      run_database_schema_probe \
        "${container_name}-deploy-${deployment_run_id}-database-schema" \
        "$candidate_reference_probe" "$post_production_catalog" \
        "$database_probe_env_snapshot" 16777216
      /usr/bin/python3 -I "$deploy_guard" validate-expand-catalog-transition \
        --old-manifest "$old_migration_manifest" \
        --candidate-manifest "$candidate_migration_manifest" \
        --old-catalog "$old_reference_catalog" \
        --migrated-catalog "$post_production_catalog" \
        --candidate-reference-catalog "$candidate_reference_catalog" \
        --plan "$expand_migration_plan"
      container_internal_health "$container_name" \
        || fail "扩展 schema 提交后旧生产应用不健康"
      /usr/bin/python3 -I "$deploy_guard" advance-expand-journal \
        --journal "$expand_journal" --state production_schema_attested
      expand_action="resume_cutover"
    else
      post_production_catalog="$observed_production_catalog"
    fi
    [[ "$expand_action" == "resume_cutover" || "$expand_action" == "complete" ]] \
      || fail "expand schema gate 未到达可切换状态"
    rm -f -- "$database_migration_env_snapshot"
    database_migration_env_snapshot=""

    expand_cutover_journal_values_path="${runtime_dir}/expand-journal-before-cutover.bin"
    /usr/bin/python3 -I "$deploy_guard" read-expand-journal \
      --journal "$expand_journal" --output "$expand_cutover_journal_values_path"
    mapfile -d '' -t expand_cutover_journal_values \
      <"$expand_cutover_journal_values_path"
    [[ "${#expand_cutover_journal_values[@]}" -eq 5 ]] \
      || fail "cutover 前 expand journal 导出字段数不正确"
    expand_journal_state=${expand_cutover_journal_values[0]}
    if [[ "$expand_action" == "resume_cutover" \
      && "$expand_journal_state" == "production_schema_attested" ]]; then
      step "在任何容器切换前持久记录 expand cutover 边界"
      /usr/bin/python3 -I "$deploy_guard" advance-expand-journal \
        --journal "$expand_journal" --state cutover_started
      expand_journal_state="cutover_started"
    elif [[ "$expand_action" == "resume_cutover" \
      && "$expand_journal_state" == "cutover_started" ]]; then
      :
    elif [[ "$expand_action" == "complete" \
      && "$expand_journal_state" == "completed" ]]; then
      :
    else
      fail "expand journal 与 cutover 恢复动作不一致"
    fi
  fi
  [[ "$(docker container inspect --format '{{.Id}}' "$container_name")" == "$old_container_id" ]] \
    || fail "数据库只读核对期间生产容器身份发生变化"
  [[ "$(docker container inspect --format '{{.State.Running}}' "$container_name")" == "true" ]] \
    || fail "数据库只读核对期间旧生产容器停止"

  container_internal_health "$container_name" \
    || fail "schema gate 后旧生产容器健康检查失败"
  [[ "$(docker container inspect --format '{{.Id}}' "$candidate_container")" == "$candidate_container_id" ]] \
    || fail "候选容器在切换前被替换"
  [[ "$(docker container inspect --format '{{.Image}}' "$candidate_container")" == "$image_id" ]] \
    || fail "候选容器在切换前换绑 image"

  step "创建受监管的通用 Celery worker/beat 候选（切换前保持停止）"
  create_supervised_service_candidates
  rm -f -- "$env_snapshot"
  env_snapshot=""

  step "切换前再次验证官方候选资格"
  verify_official_candidate
  step "切换到候选镜像"
  cutover_candidate_name=$candidate_container
  write_cutover_journal prepared
  old_container_stopped=1
  docker container stop --time 30 "$old_container_id" >/dev/null
  write_cutover_journal old_stopped
  docker container rename "$old_container_id" "$backup_container"
  write_cutover_journal old_renamed
  docker container rename "$candidate_container_id" "$container_name"
  write_cutover_journal candidate_renamed
  candidate_container=""
  cutover_started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  docker container start "$candidate_container_id" >/dev/null
  write_cutover_journal candidate_started
  new_container_id=$(docker container inspect --format '{{.Id}}' "$container_name")
  [[ "$new_container_id" == "$candidate_container_id" ]] \
    || fail "切换后的容器不是已验证候选"
  assert_candidate_runtime_identity

  step "等待容器内与公网首次就绪"
  backend_ready=0
  for ((attempt = 0; attempt < 30; attempt += 1)); do
    assert_candidate_runtime_identity
    if container_internal_health "$container_name"; then
      backend_ready=1
      break
    fi
    sleep 1
  done
  [[ "$backend_ready" -eq 1 ]] || fail "30 秒内容器健康检查未通过"
  public_ready=0
  for ((attempt = 0; attempt < 30; attempt += 1)); do
    assert_candidate_runtime_identity
    if public_health; then
      public_ready=1
      break
    fi
    sleep 1
  done
  [[ "$public_ready" -eq 1 ]] || fail "30 秒内公网健康检查未通过"

  step "执行 30 秒连续稳定窗口与致命日志检查"
  stability_started=$(date +%s)
  consecutive_checks=0
  stability_verified=0
  for ((attempt = 0; attempt < 10; attempt += 1)); do
    assert_candidate_runtime_identity
    container_internal_health "$container_name" \
      || fail "稳定窗口内容器健康检查失败"
    public_health || fail "稳定窗口内公网健康检查失败"
    consecutive_checks=$((consecutive_checks + 1))
    elapsed=$(( $(date +%s) - stability_started ))
    if [[ "$elapsed" -ge 30 && "$consecutive_checks" -ge 6 ]]; then
      stability_verified=1
      break
    fi
    sleep 5
  done
  [[ "$stability_verified" -eq 1 ]] \
    || fail "候选容器没有完成 30 秒连续稳定窗口"
  docker logs --since "$cutover_started_at" "$container_name" \
    >"$runtime_dir/candidate.log" 2>&1
  if LC_ALL=C grep -Eiq \
    'Traceback|CRITICAL|Application startup failed|segmentation fault|Killed process' \
    "$runtime_dir/candidate.log"; then
    fail "候选容器稳定窗口出现致命日志"
  fi
  assert_candidate_runtime_identity

  step "启动并验证受监管的通用 Celery worker/beat"
  start_and_verify_supervised_services
  assert_candidate_runtime_identity

  step "提交部署前最后回读官方候选资格"
  verify_official_candidate
  assert_candidate_runtime_identity

  if [[ "$ACTION" == "expand-deploy" ]]; then
    step "绑定备份、事务、candidate catalog 与稳定切换的 exact evidence"
    final_backup_toc="${runtime_dir}/final-backup.toc"
    final_backup_attestation="${runtime_dir}/final-backup-attestation.json"
    run_expand_backup_toc \
      "${container_name}-deploy-${deployment_run_id}-schema-backup-toc" \
      "$expand_backup_path" "$final_backup_toc"
    /usr/bin/python3 -I "$deploy_guard" attest-expand-backup \
      --backup "$expand_backup_path" --toc "$final_backup_toc" \
      --output "$final_backup_attestation"
    /usr/bin/python3 -I "$deploy_guard" validate-expand-backup-binding \
      --journal "$expand_journal" \
      --backup-attestation "$final_backup_attestation"
    if [[ -e "$expand_evidence_path" || -L "$expand_evidence_path" ]]; then
      /usr/bin/python3 -I "$deploy_guard" validate-expand-evidence \
        --journal "$expand_journal" --plan "$expand_migration_plan" \
        --old-manifest "$old_migration_manifest" \
        --rehearsal-transaction-result "$rehearsal_result" \
        --old-app-compat-result "$old_compat_result" \
        --transaction-result "$expand_transaction_result" \
        --candidate-manifest "$candidate_migration_manifest" \
        --post-catalog "$post_production_catalog" \
        --evidence "$expand_evidence_path"
    else
      /usr/bin/python3 -I "$deploy_guard" write-expand-evidence \
        --journal "$expand_journal" --plan "$expand_migration_plan" \
        --old-manifest "$old_migration_manifest" \
        --rehearsal-transaction-result "$rehearsal_result" \
        --old-app-compat-result "$old_compat_result" \
        --transaction-result "$expand_transaction_result" \
        --candidate-manifest "$candidate_migration_manifest" \
        --post-catalog "$post_production_catalog" \
        --output "$expand_evidence_path"
    fi
    /usr/bin/python3 -I "$deploy_guard" advance-expand-journal \
      --journal "$expand_journal" --state completed
    expand_journal_state="completed"
  fi

  /usr/bin/python3 -I "$deploy_guard" clear-journal \
    --journal "$CUTOVER_JOURNAL"
  deployment_committed=1
  step "提交后保留当前 worker/beat，并回收旧版本受管服务"
  cleanup_prejournal_orphans
  step "提交完成后保留当前回滚，并清理更早的受管备份"
  cleanup_expired_backups
  ok "生产容器已绑定 ${EXPECTED_SHA}；回滚容器: ${backup_container}"
fi

step "完成"
echo "  - exact main SHA: ${EXPECTED_SHA}"
echo "  - 失败时排查: docker logs ${container_name} --tail 200"
