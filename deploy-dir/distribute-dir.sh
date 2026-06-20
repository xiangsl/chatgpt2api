#!/bin/bash
# 在控制机上执行：将本地目录内容批量分发到各目标机器
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOSTS_FILE="hosts.txt"
SOURCE_DIR="test"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

SSH_OPTS=(
    -o StrictHostKeyChecking=no
    -o UserKnownHostsFile=/dev/null
    -o LogLevel=ERROR
    -o ConnectTimeout=15
    -o ServerAliveInterval=30
    -o ServerAliveCountMax=120
)

log_info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
    cat <<'EOF'
用法: ./distribute-dir.sh -s source_dir [-f hosts.txt]

控制机 deploy-dir 目录下需包含:
  distribute-dir.sh      本脚本
  hosts.txt              主机列表（默认）

说明:
  仅支持目录分发，不支持单个文件。
  会将 source_dir 下的所有子目录和文件同步到远程目标目录
  （不包含 source_dir 目录本身，内容直接落入目标目录）。

选项:
  -s <source_dir>        指定本地源目录（必填）
  -f <file>              指定主机列表文件（默认 hosts.txt）

hosts 文件格式（一行一台，字段以 | 分隔）:
  主机|用户名|密码|目标文件夹

示例:
  192.168.1.100|root|your_password|/opt/chatgpt2api
  10.0.0.5|admin|secret123|/home/admin/chatgpt2api

  ./distribute-dir.sh -s /path/to/source_dir
  ./distribute-dir.sh -s ../data -f hosts.txt

依赖: sshpass, ssh, rsync（优先）或 scp
  Ubuntu/Debian: apt install sshpass openssh-client rsync
  CentOS/RHEL:   yum install sshpass openssh-clients rsync
EOF
}

check_deps() {
    local missing=()
    for cmd in sshpass ssh; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    if ! command -v rsync &>/dev/null && ! command -v scp &>/dev/null; then
        missing+=("rsync 或 scp")
    fi
    if ((${#missing[@]} > 0)); then
        log_error "缺少依赖: ${missing[*]}"
        usage
        exit 1
    fi
}

resolve_source_dir() {
    local candidate="$SOURCE_DIR"

    if [[ -f "$candidate" ]]; then
        log_error "不支持单个文件，请指定目录: $candidate"
        usage
        exit 1
    fi
    if [[ -f "$SCRIPT_DIR/$candidate" ]]; then
        log_error "不支持单个文件，请指定目录: $candidate"
        usage
        exit 1
    fi

    if [[ -d "$candidate" ]]; then
        SOURCE_DIR="$(cd "$candidate" && pwd)"
        return 0
    fi
    if [[ -d "$SCRIPT_DIR/$candidate" ]]; then
        SOURCE_DIR="$(cd "$SCRIPT_DIR/$candidate" && pwd)"
        return 0
    fi

    log_error "源目录不存在: $candidate"
    usage
    exit 1
}

check_inputs() {
    local missing=()
    [[ -f "$HOSTS_FILE" ]] || missing+=("$HOSTS_FILE")
    if [[ -z "$SOURCE_DIR" ]]; then
        log_error "缺少参数: -s source_dir"
        usage
        exit 1
    fi
    resolve_source_dir
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

sync_source_dir() {
    local remote="$1" password="$2" target_dir="$3"
    local -a rsync_ssh=(-e "ssh ${SSH_OPTS[*]}")

    if command -v rsync &>/dev/null; then
        sshpass -p "$password" rsync -azr "${rsync_ssh[@]}" \
            "$SOURCE_DIR/" \
            "${remote}:${target_dir}/" </dev/null
        return $?
    fi

    sshpass -p "$password" scp -r "${SSH_OPTS[@]}" \
        "$SOURCE_DIR/." \
        "${remote}:${target_dir}/" </dev/null
}

distribute_one() {
    local host="$1" user="$2" password="$3" target_dir="$4"
    local remote="${user}@${host}"
    local dir_size start elapsed

    log_info "========== 开始分发: ${host} (${target_dir}) =========="

    log_info "${host}: 检查远程目标目录 ${target_dir} ..."
    if ! sshpass -p "$password" ssh -n "${SSH_OPTS[@]}" "$remote" "test -d '${target_dir}'"; then
        log_error "${host}: 远程目标目录不存在: ${target_dir}"
        return 1
    fi

    dir_size="$(du -sh "$SOURCE_DIR" | cut -f1)"
    log_info "${host}: 同步目录 ${SOURCE_DIR}/ 下全部内容（约 ${dir_size}），大目录可能需几分钟 ..."
    start=$(date +%s)
    if ! sync_source_dir "$remote" "$password" "$target_dir"; then
        log_error "${host}: 目录同步失败"
        return 1
    fi
    elapsed=$(( $(date +%s) - start ))
    log_info "${host}: 同步完成，耗时 ${elapsed}s"

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
            -s)
                shift
                SOURCE_DIR="${1:?缺少 -s 参数值}"
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
    check_inputs

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
