#!/bin/bash
# 在控制机上执行：按 hosts.txt 逐台远程执行命令（工作目录为目标文件夹）
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOSTS_FILE="hosts.txt"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
    cat <<'EOF'
用法: ./exe-shell.sh [远程命令]

按 hosts.txt 逐台 SSH 到目标机器，在「目标文件夹」下执行命令。

默认命令: echo '' > data/logs.json

示例:
  ./exe-shell.sh
  ./exe-shell.sh "sudo echo '' > data/logs.jsonl"
  ./exe-shell.sh "rm -f data/logs.json"

hosts.txt 格式（一行一台，字段以 | 分隔）:
  主机|用户名|密码|目标文件夹

依赖: sshpass, ssh
EOF
}

check_deps() {
    local missing=()
    for cmd in sshpass ssh; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if ((${#missing[@]} > 0)); then
        log_error "缺少依赖: ${missing[*]}"
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

run_one() {
    local host="$1" user="$2" password="$3" target_dir="$4" remote_cmd="$5"
    local conn_opts=(
        -o StrictHostKeyChecking=no
        -o UserKnownHostsFile=/dev/null
        -o LogLevel=ERROR
        -o ConnectTimeout=15
        -o ServerAliveInterval=30
        -o ServerAliveCountMax=120
    )
    local remote="${user}@${host}"

    log_info "========== ${host} (${target_dir}) =========="
    log_info "${host}: 执行: ${remote_cmd}"

    if ! sshpass -p "$password" ssh -n "${conn_opts[@]}" "$remote" \
        "cd '${target_dir}' && ${remote_cmd}"; then
        log_error "${host}: 命令执行失败"
        return 1
    fi

    log_info "========== 成功: ${host} (${target_dir}) =========="
    echo
    return 0
}

main() {
    if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        usage
        exit 0
    fi

    local remote_cmd="${*:-echo '' > data/logs.json}"

    check_deps

    if [[ ! -f "$HOSTS_FILE" ]]; then
        log_error "缺少文件: ${HOSTS_FILE}"
        usage
        exit 1
    fi

    log_info "远程命令: ${remote_cmd}"

    local total=0 ok=0 fail=0
    local host user password target_dir

    while IFS= read -r line <&3 || [[ -n "$line" ]]; do
        parse_line "$line" || continue
        total=$((total + 1))
        if run_one "$host" "$user" "$password" "$target_dir" "$remote_cmd"; then
            ok=$((ok + 1))
        else
            fail=$((fail + 1))
        fi
    done 3< "$HOSTS_FILE"

    echo
    log_info "执行完成: 共 ${total} 台, 成功 ${ok} 台, 失败 ${fail} 台"
    [[ "$fail" -eq 0 ]]
}

main "$@"
