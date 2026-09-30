#!/bin/sh
# MacBook live A11-A14. Deploy this head first; owner browser check is manual.
# Temporary PRs only in the two example repositories; never print credentials.
set +x
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
phub=$root/scripts/phub
backend=cafitac/preview-example-backend
frontend=cafitac/preview-example-frontend
stamp=$(date -u +%Y%m%d%H%M%S)-$$
branch=e2e/pub-$stamp
env=pub-$(date +%s)-$$
bad=pub-bad-$$
interval=${PHUB_BOT_INTERVAL:-20}
printf '%s\n' 'public E2E: setup' >&2
for tool in gh jq python3 curl ssh; do command -v "$tool" >/dev/null; done
wait_seconds=$(python3 -c 'import math,sys; n=float(sys.argv[1]); assert math.isfinite(n) and n>0; print(math.ceil(2*n))' "$interval")
access_team_domain=${PHUB_ACCESS_TEAM_DOMAIN-cafitac.cloudflareaccess.com}
python3 - "$access_team_domain" <<'PYTHON'
import re
import sys
host = sys.argv[1]
if len(host) > 253 or not all(
    re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
    for label in host.split(".")
):
    sys.exit("PHUB_ACCESS_TEAM_DOMAIN must be a hostname (without scheme, port or path)")
PYTHON
work=$(mktemp -d)
bpr= fpr= bbranch=0 fbranch=0 bad_owned=0 env_owned=0
owner_gh() {
    token=$(GH_DEBUG= gh auth token --user cafitac) || return
    [ -n "$token" ] || return 1
    GH_TOKEN=$token GH_DEBUG= gh "$@"
    result=$?
    unset token
    return "$result"
}
api() { owner_gh api "$@"; }
retry_read() (
    step=$1; shift
    attempt=1
    while :; do
        if output=$(api "$@" 2>/dev/null); then
            printf '%s\n' "$output"
            return 0
        fi
        [ "$attempt" -lt 5 ] || { printf 'GitHub read failed: %s\n' "$step" >&2; return 1; }
        attempt=$((attempt + 1))
        sleep 2
    done
)
wait_pr_head() (
    repo=$1 pr=$2 expected=$3
    deadline=$(($(date +%s) + 60))
    while :; do
        head=$(retry_read pr-head "repos/$repo/pulls/$pr" --jq .head.sha) || return
        if [ "$head" = "$expected" ]; then
            printf '%s\n' "$head"
            return 0
        fi
        [ "$(date +%s)" -lt "$deadline" ] || { printf '%s\n' 'PR head timeout (60 seconds)' >&2; return 1; }
        sleep 1
    done
)
quote() { printf "'"; printf '%s' "$1" | sed "s/'/'\\\\''/g"; printf "'"; }
vm_docker() {
    command="export PATH=$(quote "${PHUB_REMOTE_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin}"); $(quote "${PHUB_REMOTE_DOCKER:-docker}") --context colima-preview-hub"
    for arg do command="$command $(quote "$arg")"; done
    ssh ${PHUB_SSH_OPTS:-} "${PHUB_SSH_HOST:-trading-macstudio}" "$command"
}
empty() {
    "$phub" inventory "$1" > "$work/inventory.json" || return
    jq -e 'all(.[]; length == 0)' "$work/inventory.json" >/dev/null
}
close_pr() {
    [ -n "$2" ] || return 0
    api -X PATCH "repos/$1/pulls/$2" -f state=closed >/dev/null
}
delete_branch() {
    if api -X DELETE "repos/$1/git/refs/heads/$branch" --include > "$work/delete-response" 2>/dev/null; then
        return 0
    fi
    # gh --include exposes the HTTP status even on an API error; never print its body.
    if python3 - "$work/delete-response" <<'PYTHON'
import re
import sys
with open(sys.argv[1]) as stream:
    first_line = stream.readline().strip()
sys.exit(0 if re.fullmatch(r"HTTP/\S+ (404|422)(?: .*)?", first_line) else 1)
PYTHON
    then return 0; fi
    printf '%s\n' 'GitHub write failed: delete-branch' >&2
    return 1
}
cleanup() {
    code=$?
    trap - 0 HUP INT TERM
    if [ "$env_owned" = 1 ]; then
        "$phub" down "$env" --format json >/dev/null || code=1
        empty "$env" || code=1
    fi
    if [ "$bad_owned" = 1 ]; then
        "$phub" down "$bad" --format json >/dev/null || code=1
        empty "$bad" || code=1
    fi
    close_pr "$backend" "$bpr" || code=1
    close_pr "$frontend" "$fpr" || code=1
    if [ "$bbranch" = 1 ]; then delete_branch "$backend" || code=1; fi
    if [ "$fbranch" = 1 ]; then delete_branch "$frontend" || code=1; fi
    rm -rf "$work"
    printf 'cleanup exit=%s\n' "$code"
    exit "$code"
}
trap cleanup 0
trap 'exit 130' HUP INT TERM
# Discover a shared stack network rather than relying on a Compose project name.
vm_docker inspect phub-cloudflared > "$work/tunnel.json"
jq -e '.[0].State.Running == true' "$work/tunnel.json" >/dev/null
[ "$("$root/scripts/tunnel-credentials" --check)" = 'credentials present' ]
vm_docker inspect phub-proxy phub-hub > "$work/networks.json"
network=$(jq -er '.[0].NetworkSettings.Networks as $p | .[1].NetworkSettings.Networks | keys[] | select($p[.] != null)' "$work/networks.json" | head -n 1)
[ -n "$network" ]
public_check() {
    host=$1 expected=$2
    status=$(curl --silent --show-error --max-time 30 --output /dev/null --dump-header "$work/headers" --write-out '%{http_code}' "https://$host/")
    [ "$status" = "$expected" ]
    if [ "$expected" = 302 ]; then
        # Do not display Location: Access redirects can contain session parameters.
        python3 - "$work/headers" "$access_team_domain" <<'PY'
import sys
from urllib.parse import urlsplit
headers = open(sys.argv[1]).read().splitlines()
locations = [line.split(":", 1)[1].strip() for line in headers if line.lower().startswith("location:")]
assert len(locations) == 1
url = urlsplit(locations[0])
if url.scheme != "https" or url.netloc.lower() != sys.argv[2].lower():
    sys.exit(f"Access redirect expected team domain {sys.argv[2]}; got different host")
assert url.path.startswith("/")
PY
    fi
    printf 'public %s -> %s\n' "$host" "$status"
}
vm_check() {
    expected=$1 url=$2; shift 2
    status=$(vm_docker run --rm --network "$network" curlimages/curl:8.12.1 --silent --show-error --max-time 20 --output /dev/null --write-out '%{http_code}' "$@" "$url")
    [ "$status" = "$expected" ] || { printf 'VM HTTP expected %s got %s\n' "$expected" "$status" >&2; return 1; }
}
printf '%s\n' 'public E2E: public checks' >&2
public_check preview-hub.cafitac.com 302
public_check phub-zz-nonexistent.cafitac.com 302
public_check gather.cafitac.com 200
public_check interview.cafitac.com 200
printf '%s\n' 'public E2E: vm checks' >&2
vm_check 401 http://phub-hub:8080/api/environments
vm_check 404 http://phub-proxy/ -H 'Host: phub-zz-nonexistent.cafitac.com'
# Refuse to adopt or delete a pre-existing negative-test environment.
"$phub" list --format json > "$work/list.json"
jq -e --arg name "$bad" --arg env "$env" 'all(.[]; .name != $name and .name != $env)' "$work/list.json" >/dev/null
empty "$bad"
empty "$env"
bad_owned=1
env_owned=1
commit_readme() {
    retry_read readme "repos/$1/contents/README.md?ref=$branch" > "$work/readme.json"
    python3 - "$work/readme.json" "$branch" > "$work/commit.json" <<'PY'
import base64
import json
import sys
with open(sys.argv[1]) as stream:
    readme = json.load(stream)
content = base64.b64decode(readme["content"]) + b"\n<!-- public preview E2E -->\n"
json.dump({"message": "test: exercise public preview", "branch": sys.argv[2],
           "sha": readme["sha"], "content": base64.b64encode(content).decode()}, sys.stdout)
PY
    api -X PUT "repos/$1/contents/README.md" --input "$work/commit.json" --jq .commit.sha
}
create_branch() (
    repo=$1
    sha=$(retry_read main-sha "repos/$repo/git/ref/heads/main" --jq .object.sha) || return
    attempt=1
    while :; do
        if api -X POST "repos/$repo/git/refs" -f "ref=refs/heads/$branch" -f "sha=$sha" >/dev/null 2>&1; then return 0; fi
        # A failed response may still have created the ref. Confirm before retrying.
        existing=$(retry_read branch-check "repos/$repo/git/matching-refs/heads/$branch" --jq ".[] | select(.ref == \"refs/heads/$branch\") | .object.sha") || return
        [ -z "$existing" ] || return 0
        [ "$attempt" -lt 5 ] || { printf '%s\n' 'GitHub write failed: create-branch' >&2; return 1; }
        attempt=$((attempt + 1))
        sleep 2
    done
)
create_pr() (
    repo=$1
    attempt=1
    while :; do
        if number=$(api -X POST "repos/$repo/pulls" -f "head=$branch" -f base=main -f title='E2E: public preview (temporary)' -f body='Automated U14 scenario; closed and cleaned up after verification.' --jq .number 2>/dev/null); then
            printf '%s\n' "$number"
            return 0
        fi
        number=$(retry_read pr-check "repos/$repo/pulls?state=open&head=${repo%%/*}:$branch" --jq '.[0].number // empty') || return
        if [ -n "$number" ]; then printf '%s\n' "$number"; return 0; fi
        [ "$attempt" -lt 5 ] || { printf '%s\n' 'GitHub write failed: create-pr' >&2; return 1; }
        attempt=$((attempt + 1))
        sleep 2
    done
)
printf '%s\n' 'public E2E: branches/PRs' >&2
bbranch=1
create_branch "$backend"
bcommit=$(commit_readme "$backend")
bpr=$(create_pr "$backend")
fbranch=1
create_branch "$frontend"
fcommit=$(commit_readme "$frontend")
fpr=$(create_pr "$frontend")
bsha=$(wait_pr_head "$backend" "$bpr" "$bcommit")
fsha=$(wait_pr_head "$frontend" "$fpr" "$fcommit")
ready() {
    "$phub" status "$env" --format json > "$work/status.json"
    jq -e --arg b "$bsha" --arg f "$fsha" '.state == "READY" and any(.services[]; .service == "backend" and .commit_sha == $b) and any(.services[]; .service == "frontend" and .commit_sha == $f)' "$work/status.json" >/dev/null
}
links() {
    # Both PRs share one deadline: at most two deployed bot intervals.
    deadline=$(($(date +%s) + wait_seconds))
    while :; do
        matched=1
        for service in backend frontend; do
            if [ "$service" = backend ]; then repo=$backend pr=$bpr; else repo=$frontend pr=$fpr; fi
            retry_read comments --paginate --slurp "repos/$repo/issues/$pr/comments?per_page=100" > "$work/pages.json"
            jq --arg marker "<!-- phub-link env=$env -->" 'add | [.[] | select(.body | contains($marker))]' "$work/pages.json" > "$work/$service-links.json"
            count=$(jq length "$work/$service-links.json")
            [ "$count" -le 1 ] || { echo 'Duplicate cross-link comment' >&2; return 1; }
            if ! jq -e --arg first "preview $env: $1" --arg b "$(printf '%.12s' "$bsha")" --arg f "$(printf '%.12s' "$fsha")" --arg state "$1" 'length == 1 and (.[0].body | split("\n")[0]) == $first and ($state == "removed" or (.[0].body | contains($b) and contains($f)))' "$work/$service-links.json" >/dev/null; then matched=0; fi
            if [ -f "$work/$service-id" ] && [ "$count" = 1 ]; then
                [ "$(jq -r '.[0].id' "$work/$service-links.json")" = "$(cat "$work/$service-id")" ] || { echo 'Cross-link replaced instead of edited' >&2; return 1; }
            fi
        done
        [ "$matched" = 0 ] || break
        [ "$(date +%s)" -lt "$deadline" ] || { echo 'Cross-link timeout (two bot intervals)' >&2; return 1; }
        sleep 1
    done
    for service in backend frontend; do jq -r '.[0].id' "$work/$service-links.json" > "$work/$service-id"; done
}
printf '%s\n' 'public E2E: up' >&2
"$phub" up "$env" --set "backend=pr-$bpr" --set "frontend=pr-$fpr" --format json >/dev/null
ready
printf '%s\n' 'public E2E: links' >&2
links READY
vm_check 401 http://phub-proxy/ -H "Host: phub-$env.cafitac.com"
vm_check 401 http://phub-proxy/_svc/api/api/notes -H "Host: phub-$env.cafitac.com"
vm_check 200 http://phub-proxy/api/notes -H "Host: api.$env.localhost"
printf '%s\n' 'public E2E: update' >&2
old_sha=$bsha
bcommit=$(commit_readme "$backend")
bsha=$(wait_pr_head "$backend" "$bpr" "$bcommit")
[ "$bsha" != "$old_sha" ]
"$phub" update "$env" --set "backend=pr-$bpr" --format json >/dev/null
ready
links READY
printf '%s\n' 'public E2E: down' >&2
"$phub" down "$env" --format json >/dev/null
empty "$env"
links removed
printf '%s\n' 'public E2E: negative' >&2
set +e
"$phub" up "$bad" --set backend=pr-999999 --format json > "$work/negative.json" 2> "$work/negative.err"
code=$?
set -e
[ "$code" = 2 ]
empty "$bad"
"$phub" list --format json > "$work/list.json"
jq -e --arg name "$bad" 'all(.[]; .name != $name)' "$work/list.json" >/dev/null
printf '%s\n' 'Public automated checks passed.' 'Manual owner check: open https://preview-hub.cafitac.com, create an environment choosing an open backend PR and frontend main, open its URL, then delete it. Record the result separately.'
