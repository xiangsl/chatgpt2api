#!/bin/bash
# 在控制机上执行：将 chatgpt2api.zip 批量分发到各目标机器
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ZIP_FILE="chatgpt2api.zip"
UPDATE_SCRIPT="update.sh"
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
用法: ./distribute-zip.sh [-f hosts.txt]

控制机 deploy-file 目录下需包含:
  distribute-zip.sh      本脚本
  update.sh              目标机器解压脚本
  chatgpt2api.zip        待分发压缩包
  hosts.txt              主机列表（默认）

选项:
  -f <file>              指定主机列表文件（默认 hosts.txt）

hosts 文件格式（一行一台，字段以 | 分隔）:
  主机|用户名|密码|目标文件夹

示例:
  192.168.1.100|root|your_password|/opt/chatgpt2api
  10.0.0.5|admin|secret123|/home/admin/chatgpt2api

  ./distribute-zip.sh
  ./distribute-zip.sh -f hosts.txt

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
    [[ -f "$HOSTS_FILE" ]] || missing+=("$HOSTS_FILE")
    [[ -f "$ZIP_FILE" ]] || missing+=("$ZIP_FILE")
    [[ -f "$UPDATE_SCRIPT" ]] || missing+=("$UPDATE_SCRIPT")
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

distribute_one() {
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
    local zip_size start elapsed

    log_info "========== 开始分发: ${host} (${target_dir}) =========="

    log_info "${host}: 检查远程目标目录 ${target_dir} ..."
    if ! sshpass -p "$password" ssh -n "${conn_opts[@]}" "$remote" "test -d '${target_dir}'"; then
        log_error "${host}: 远程目标目录不存在: ${target_dir}"
        return 1
    fi

    zip_size="$(du -h "$ZIP_FILE" | cut -f1)"
    log_info "${host}: 上传 ${UPDATE_SCRIPT}、${ZIP_FILE}（约 ${zip_size}），大文件可能需几分钟 ..."
    start=$(date +%s)
    if ! sshpass -p "$password" scp "${conn_opts[@]}" \
        "$UPDATE_SCRIPT" "$ZIP_FILE" \
        "${remote}:${target_dir}/" </dev/null; then
        log_error "${host}: 文件复制失败"
        return 1
    fi
    elapsed=$(( $(date +%s) - start ))
    log_info "${host}: 上传完成，耗时 ${elapsed}s"

    log_info "${host}: 执行解压脚本 ..."
    if ! sshpass -p "$password" ssh -n -tt "${conn_opts[@]}" "$remote" \
        "chmod +x '${target_dir}/${UPDATE_SCRIPT}' && bash '${target_dir}/${UPDATE_SCRIPT}' '${target_dir}'"; then
        log_error "${host}: 解压脚本执行失败"
        return 1
    fi

    log_info "========== 分发成功: ${host} =========="
    echo
    return 0
}

main() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                usage
                exit 0
                ;;
            -f)
                shift
                HOSTS_FILE="${1:?缺少 -f 参数值}"
                ;;
            *)
                log_error "未知参数: $1"
                usage
                exit 1
                ;;
        esac
        shift
    done

    check_deps
    check_files

    local total=0 ok=0 fail=0
    local host user password target_dir

    while IFS= read -r line <&3 || [[ -n "$line" ]]; do
        parse_line "$line" || continue
        total=$((total + 1))
        if distribute_one "$host" "$user" "$password" "$target_dir"; then
            ok=$((ok + 1))
        else
            fail=$((fail + 1))
        fi
    done 3< "$HOSTS_FILE"

    echo
    log_info "分发完成: 共 ${total} 台, 成功 ${ok} 台, 失败 ${fail} 台"
    [[ "$fail" -eq 0 ]]
}

main "$@"
