#!/bin/bash
# 在控制机上执行：按 hosts.txt 逐台部署 chatgpt2api
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TAR_FILE="chatgpt2api.tar"
UPDATE_SCRIPT="update.sh"
HOSTS_FILE="hosts.txt"
CONFIG_FILE="config.json"
COMPOSE_FILE="docker-compose.yml"
FILES_DIR="files"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
    cat <<'EOF'
用法: ./deploy.sh

控制机 deploy-batch 目录下需包含:
  deploy.sh              本脚本
  update.sh              目标机器升级脚本
  chatgpt2api.tar        Docker 镜像包
  config.json            服务配置
  docker-compose.yml     Compose 配置（CHATGPT2API_PORT 与容器名将按目标目录端口自动替换）
  hosts.txt              主机列表
  files/                 可选，该目录下的文件/子目录会一并复制到远程目标目录（不含 files 本身）

hosts.txt 格式（一行一台，字段以 | 分隔）:
  主机|用户名|密码|目标文件夹

目标文件夹末尾的数字将作为服务端口，例如:
  /root/chatgpt2api/chatgpt2api-3001  -> 端口 3001
  /root/chatgpt2api/chatgpt2api-3002  -> 端口 3002
  /root/chatgpt2api/chatgpt2api-run    -> 默认端口 3001（单机单实例）

打包镜像（在构建机执行）:
  docker save tydic:chatgpt2api -o chatgpt2api.tar

依赖: sshpass, scp, ssh
  Ubuntu/Debian: apt install sshpass openssh-client
  CentOS/RHEL:   yum install sshpass openssh-clients
EOF
}

check_deps() {
    local missing=()
    for cmd in sshpass scp ssh; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if ((${#missing[@]} > 0)); then
        log_error "缺少依赖: ${missing[*]}"
        usage
        exit 1
    fi
}

check_files() {
    local missing=()
    for f in "$TAR_FILE" "$UPDATE_SCRIPT" "$HOSTS_FILE" "$COMPOSE_FILE"; do
        [[ -f "$f" ]] || missing+=("$f")
    done
    if ((${#missing[@]} > 0)); then
        log_error "缺少文件: ${missing[*]}"
        usage
        exit 1
    fi
}

parse_line() {
    local line="$1"
    host="" user="" password="" target_dir=""

    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    line="${line//$'\r'/}"
    [[ -z "$line" || "$line" == \#* ]] && return 1

    if [[ "$line" == *"|"* ]]; then
        IFS='|' read -r host user password target_dir <<< "$line"
    else
        read -r host user password target_dir <<< "$line"
    fi

    host="${host// /}"
    target_dir="${target_dir// /}"

    if [[ -z "$host" || -z "$user" || -z "$password" || -z "$target_dir" ]]; then
        log_warn "跳过无效行: $line"
        return 1
    fi
    return 0
}

extract_port() {
    local target_dir="$1"
    local name="${target_dir##*/}"

    if [[ "$name" =~ -([0-9]+)$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return 0
    fi

    if [[ "$name" == *-run ]]; then
        echo "3001"
        return 0
    fi

    log_error "无法从目标目录提取端口（期望形如 .../chatgpt2api-3001 或 .../chatgpt2api-run）: ${target_dir}"
    return 1
}

prepare_compose() {
    local port="$1"
    local out="$2"

    sed "s/\${CHATGPT2API_PORT:-[0-9]*}/${port}/g" "$COMPOSE_FILE" > "$out"
}

deploy_one() {
    local host="$1" user="$2" password="$3" target_dir="$4"
    local conn_opts=(
        -o StrictHostKeyChecking=no
        -o UserKnownHostsFile=/dev/null
        -o LogLevel=ERROR
        -o ConnectTimeout=15
        -o ServerAliveInterval=30
        -o ServerAliveCountMax=120
    )
    local remote="${user}@${host}"
    local port tar_size start elapsed
    local -a extra_files=() fixed_files=()

    log_info "========== 开始部署: ${host} (${target_dir}) =========="

    if ! port="$(extract_port "$target_dir")"; then
        return 1
    fi
    log_info "${host}: 从目标目录解析端口 ${port}"

    log_info "${host}: 确保远程目标目录存在 ${target_dir} ..."
    if ! sshpass -p "$password" ssh -n "${conn_opts[@]}" "$remote" "mkdir -p '${target_dir}'"; then
        log_error "${host}: 创建远程目标目录失败: ${target_dir}"
        return 1
    fi

    local tmp_dir
    tmp_dir="$(mktemp -d)"
    prepare_compose "$port" "${tmp_dir}/${COMPOSE_FILE}"
    fixed_files=( "$UPDATE_SCRIPT" "$TAR_FILE" "${tmp_dir}/${COMPOSE_FILE}" )
    if [[ -f "$CONFIG_FILE" ]]; then
        fixed_files+=( "$CONFIG_FILE" )
    else
        log_warn "${host}: 未找到 ${CONFIG_FILE}，跳过上传"
    fi
    log_info "${host}: 已生成 docker-compose.yml（CHATGPT2API_PORT=${port}，容器名后缀 _${port}）"

    tar_size="$(du -h "$TAR_FILE" | cut -f1)"
    log_info "${host}: 上传固定文件（约 ${tar_size}），大文件可能需几分钟 ..."
    start=$(date +%s)
    if ! sshpass -p "$password" scp "${conn_opts[@]}" \
        "${fixed_files[@]}" \
        "${remote}:${target_dir}/" </dev/null; then
        rm -rf "$tmp_dir"
        log_error "${host}: 固定文件复制失败"
        return 1
    fi
    rm -rf "$tmp_dir"

    if [[ -d "$FILES_DIR" ]]; then
        shopt -s nullglob dotglob
        extra_files=( "$FILES_DIR"/* )
        shopt -u nullglob dotglob
        if ((${#extra_files[@]} > 0)); then
            log_info "${host}: 上传 files/ 下的 ${#extra_files[@]} 项 ..."
            if ! sshpass -p "$password" scp -r "${conn_opts[@]}" \
                "${extra_files[@]}" "${remote}:${target_dir}/" </dev/null; then
                log_error "${host}: files/ 内容复制失败"
                return 1
            fi
        else
            log_info "${host}: files/ 为空，跳过额外文件"
        fi
    else
        log_info "${host}: 未找到 files/ 目录，跳过额外文件"
    fi

    elapsed=$(( $(date +%s) - start ))
    log_info "${host}: 上传完成，耗时 ${elapsed}s"

    log_info "${host}: 执行升级脚本（docker load / compose 可能较慢）..."
    if ! sshpass -p "$password" ssh -n -tt "${conn_opts[@]}" "$remote" \
        "chmod +x '${target_dir}/${UPDATE_SCRIPT}' && bash '${target_dir}/${UPDATE_SCRIPT}' '${target_dir}'"; then
        log_error "${host}: 升级脚本执行失败"
        return 1
    fi

    log_info "========== 部署成功: ${host} (${target_dir}, 端口 ${port}) =========="
    echo
    return 0
}

main() {
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        usage
        exit 0
    fi

    check_deps
    check_files

    local total=0 ok=0 fail=0
    local host user password target_dir

    while IFS= read -r line <&3 || [[ -n "$line" ]]; do
        parse_line "$line" || continue
        total=$((total + 1))
        if deploy_one "$host" "$user" "$password" "$target_dir"; then
            ok=$((ok + 1))
        else
            fail=$((fail + 1))
        fi
    done 3< "$HOSTS_FILE"

    echo
    log_info "部署完成: 共 ${total} 台, 成功 ${ok} 台, 失败 ${fail} 台"
    [[ "$fail" -eq 0 ]]
}

main "$@"
