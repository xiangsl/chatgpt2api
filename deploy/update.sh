#!/bin/bash
# 在目标机器上执行：加载镜像并重启服务
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

TARGET_DIR="${1:?用法: update.sh <目标文件夹>}"

TAR_FILE="${TARGET_DIR}/chatgpt2api.tar"

if [[ ! -f "$TAR_FILE" ]]; then
    echo "[ERROR] 镜像文件不存在: $TAR_FILE" >&2
    exit 1
fi

if [[ ! -d "$TARGET_DIR" ]]; then
    echo "[ERROR] 目标文件夹不存在: $TARGET_DIR" >&2
    exit 1
fi

echo "[INFO] 镜像文件: ${TAR_FILE} ($(du -h "$TAR_FILE" | cut -f1))"
echo "[INFO] 加载 Docker 镜像（大镜像可能需数分钟）..."
docker load -i "$TAR_FILE"

echo "[INFO] 在 ${TARGET_DIR} 重启服务..."
cd "$TARGET_DIR"
docker compose up -d --force-recreate

echo "[INFO] 清理悬空镜像..."
docker image prune -f

echo "[INFO] 升级完成"
docker compose ps