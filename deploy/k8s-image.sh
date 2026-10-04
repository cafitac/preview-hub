#!/usr/bin/env bash
# homelab k8s 용 hub 이미지를 만든다 — 로컬에서 실행한다.
#   deploy/k8s-image.sh        → phub/hub:<커밋> (cafitac/homelab apps/preview-hub 의 newTag)
# 저장소를 맥스튜디오로 보내 k8s VM 의 docker 로 빌드한다 — k3s 가 같은 런타임이라 레지스트리가 필요 없다.
# ⚠️ 커밋하지 않은 변경이 있으면 멈춘다 — 태그가 커밋을 가리켜야 무엇이 떠 있는지 안다
set -euo pipefail
HOST=${HOST:-trading-macstudio}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
[ -z "$(git status --porcelain)" ] || { echo "커밋하지 않은 변경이 있다" >&2; exit 1; }
TAG=$(git rev-parse --short=12 HEAD)
rsync -az --delete --exclude .git --exclude .venv --exclude .ruff_cache --exclude __pycache__ \
  "$ROOT/" "$HOST:Project/preview-hub-build/"
ssh "$HOST" "export PATH=/opt/homebrew/bin:\$PATH; docker --context colima-k8s build -q -t phub/hub:$TAG ~/Project/preview-hub-build"
echo "phub/hub:$TAG"
