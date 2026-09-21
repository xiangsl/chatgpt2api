#!/bin/sh
mkdir -p /app/data
rm -f /app/data/logs.jsonl /app/data/image-trace.log
touch /app/data/logs.jsonl /app/data/image-trace.log
exec "$@"
