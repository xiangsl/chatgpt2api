#!/bin/bash
# 在目标机器上执行：解压 zip 包
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

TARGET_DIR="${1:?用法: update.sh <目标文件夹>}"

ZIP_FILE="${TARGET_DIR}/chatgpt2api.zip"

if [[ ! -f "$ZIP_FILE" ]]; then
    echo "[ERROR] 压缩包不存在: $ZIP_FILE" >&2
    exit 1
fi

if [[ ! -d "$TARGET_DIR" ]]; then
    echo "[ERROR] 目标文件夹不存在: $TARGET_DIR" >&2
    exit 1
fi

if ! command -v unzip &>/dev/null; then
    echo "[ERROR] 缺少依赖: unzip（Ubuntu/Debian: apt install unzip）" >&2
    exit 1
fi

echo "[INFO] 压缩包: ${ZIP_FILE} ($(du -h "$ZIP_FILE" | cut -f1))"
echo "[INFO] 解压到 ${TARGET_DIR} ..."
cd "$TARGET_DIR"
unzip -o "$ZIP_FILE"

echo "[INFO] 解压完成"
