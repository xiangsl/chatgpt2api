#!/bin/bash
# 在构建机执行：将本地镜像导出为 chatgpt2api.tar
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${1:-tydic:chatgpt2api}"
OUTPUT="${SCRIPT_DIR}/chatgpt2api.tar"

echo "导出镜像 ${IMAGE} -> ${OUTPUT}"
docker save "$IMAGE" -o "$OUTPUT"
echo "完成，文件大小: $(du -h "$OUTPUT" | cut -f1)"