#!/bin/sh
set -eu
# Build and checkout inside the dedicated VM. No hub checkout on the host.
quote() { printf "'"; printf '%s' "$1" | sed "s/'/'\\\\''/g"; printf "'"; }
mode=git
archive=
if [ "${1:-}" = --source-dir ]; then
    [ "$#" -eq 2 ] || { echo 'Usage: vm-bootstrap.sh --source-dir DIR' >&2; exit 2; }
    mode=source
    source_dir=$2
    archive=$(mktemp)
    trap 'rm -f "$archive"' EXIT HUP INT TERM
    COPYFILE_DISABLE=1 tar --no-xattrs --exclude=.git --exclude=.venv \
        --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache \
        --exclude=.mypy_cache --exclude='._*' -C "$source_dir" -cf "$archive" .
    ref= repo=
else
    ref=${1:?Usage: vm-bootstrap.sh GIT_REF [GIT_URL] | --source-dir DIR}
    repo=${2:-https://github.com/cafitac/preview-hub.git}
fi
remote_path=${PHUB_REMOTE_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin}
remote_docker=${PHUB_REMOTE_DOCKER:-docker}
remote_script=$(cat <<'REMOTE'
set -eu
mode=$1 ref=$2 repo=$3 docker=$4
if ! colima status --profile preview-hub </dev/null >/dev/null 2>&1; then
    colima start --profile preview-hub --cpu 4 --memory 8 --disk 40 --activate=false </dev/null
fi
context=$(colima ssh --profile preview-hub -- mktemp -d /tmp/phub-build.XXXXXX </dev/null)
cleanup() { colima ssh --profile preview-hub -- rm -rf "$context"; }
trap cleanup EXIT HUP INT TERM
if [ "$mode" = source ]; then
    colima ssh --profile preview-hub -- mkdir -p "$context/repo" </dev/null
    colima ssh --profile preview-hub -- tar -xf - -C "$context/repo"
else
    vm_uid=$(colima ssh --profile preview-hub -- id -u </dev/null)
    vm_gid=$(colima ssh --profile preview-hub -- id -g </dev/null)
    "$docker" --context colima-preview-hub run --rm --user "$vm_uid:$vm_gid" -v "$context:/work" --entrypoint sh alpine/git -ec '
        git clone "$1" /work/repo
        cd /work/repo
        git fetch origin "$2"
        git checkout --detach FETCH_HEAD
    ' sh "$repo" "$ref"
fi
# Pre-pull the pinned HTTP probe before health checks use their 30-second timeout.
"$docker" --context colima-preview-hub pull curlimages/curl:8.12.1
# The official CLI image includes Buildx; the context and socket belong to this VM.
"$docker" --context colima-preview-hub run --rm -v /var/run/docker.sock:/var/run/docker.sock -v "$context/repo:/work:ro" docker:27-cli buildx build --load -t phub/hub:local /work
colima ssh --profile preview-hub -- sudo mkdir -p /opt/phub
colima ssh --profile preview-hub -- sudo cp "$context/repo/deploy/hub-stack/compose.yaml" "$context/repo/deploy/hub-stack/catalog.yaml" /opt/phub/
"$docker" --context colima-preview-hub run --rm --user 0:0 -v /var/run/docker.sock:/var/run/docker.sock -v /opt/phub:/opt/phub -w /opt/phub phub/hub:local docker compose -p phub-hub -f /opt/phub/compose.yaml up -d
REMOTE
)
command="export PATH=$(quote "$remote_path"); sh -c $(quote "$remote_script") sh $(quote "$mode") $(quote "$ref") $(quote "$repo") $(quote "$remote_docker")"
if [ "$mode" = source ]; then
    ssh ${PHUB_SSH_OPTS:-} "${PHUB_SSH_HOST:-trading-macstudio}" "$command" < "$archive"
else
    ssh ${PHUB_SSH_OPTS:-} "${PHUB_SSH_HOST:-trading-macstudio}" "$command" < /dev/null
fi
