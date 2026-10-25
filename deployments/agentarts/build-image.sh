#!/usr/bin/env sh
set -eu
# Run from the root of the clean source bundle. IMAGE must be supplied, never guessed.
: "${IMAGE:?请设置实际镜像名，例如 embedded-engineer-agent:0.1.0}"
docker info >/dev/null
docker buildx build --platform linux/arm64 --load --provenance=false -f deployments/agentarts/Dockerfile -t "$IMAGE" .
ARCH=$(docker image inspect "$IMAGE" --format '{{.Architecture}}')
[ "$ARCH" = arm64 ] || { echo '镜像不是arm64，停止导出'; exit 1; }
docker save --output embedded-engineer-agent-arm64.tar "$IMAGE"
echo '已生成 embedded-engineer-agent-arm64.tar；这是可上传SWR的镜像包，源码ZIP不是镜像。'
