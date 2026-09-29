#!/bin/sh
# MacBook live A9(a)-(e); needs gh, jq, python3 and scripts/phub SSH access.
# A9(f): non-collaborator/fork rejection is covered by unit tests.
# Dedicated PR, sequential commands: C6 replies have no source-comment marker,
# so correlate by command ID windows and assert the total reply count as well.
# Never pushes to main; owner credentials are fetched per gh invocation.
set +x
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
phub=$root/scripts/phub
repo=cafitac/preview-example-backend
branch=e2e/bot-$(date -u +%Y%m%d%H%M%S)-$$
# Set this to the deployed PHUB_BOT_INTERVAL (default 20 seconds).
interval=${PHUB_BOT_INTERVAL:-20}
wait_seconds=$(python3 -c 'import math,sys; n=float(sys.argv[1]); assert math.isfinite(n) and n>0; print(math.ceil(2*n))' "$interval")
for tool in gh jq python3; do command -v "$tool" >/dev/null; done
work=$(mktemp -d)
pr= env= branch_created=0
owner_gh() {
    # Neither xtrace nor gh debug output may expose request credentials.
    token=$(GH_DEBUG= gh auth token --user cafitac) || return
    [ -n "$token" ] || return 1
    GH_TOKEN=$token GH_DEBUG= gh "$@"
    result=$?
    unset token
    return "$result"
}
api() { owner_gh api "$@"; }
empty() {
    "$phub" inventory "$env" > "$work/inventory.json" || return
    jq -e 'all(.[]; length == 0)' "$work/inventory.json" >/dev/null
}
cleanup() {
    code=$?
    trap - 0 HUP INT TERM
    if [ -n "$pr" ]; then
        state=$(api "repos/$repo/pulls/$pr" --jq .state) || code=1
        if [ "${state:-}" = open ]; then
            api -X PATCH "repos/$repo/pulls/$pr" -f state=closed >/dev/null || code=1
        fi
    fi
    if [ -n "$env" ]; then
        "$phub" down "$env" --format json >/dev/null || code=1
        empty || code=1
    fi
    if [ "$branch_created" = 1 ]; then
        api -X DELETE "repos/$repo/git/refs/heads/$branch" >/dev/null || code=1
    fi
    rm -rf "$work"
    printf 'cleanup exit=%s\n' "$code"
    exit "$code"
}
trap cleanup 0
trap 'exit 130' HUP INT TERM
comments() {
    api --paginate --slurp "repos/$repo/issues/$pr/comments?per_page=100" > "$work/pages.json"
    jq 'add' "$work/pages.json" > "$work/comments.json"
}
reply_count() {
    jq --arg prefix "preview $env:" --argjson start "$1" --argjson end "$2" \
        '[.[] | select(.id > $start and .id < $end and (.body | startswith($prefix)))] | length' "$work/comments.json"
}
assert_total() {
    comments
    count=$(reply_count 0 9007199254740991)
    [ "$count" -eq "$1" ] || { echo "Unexpected total reply count: $count" >&2; return 1; }
}
command_reply() {
    command_id=$(api -X POST "repos/$repo/issues/$pr/comments" -f "body=/preview $1" --jq .id)
    printf 'command=%s comment=%s\n' "$1" "$command_id"
    deadline=$(($(date +%s) + 180))
    while :; do
        comments
        count=$(reply_count "$command_id" 9007199254740991)
        [ "$count" -le 1 ] || { echo 'Duplicate reply' >&2; return 1; }
        if [ "$count" -eq 1 ]; then break; fi
        [ "$(date +%s)" -lt "$deadline" ] || { echo 'Reply timeout (180s)' >&2; return 1; }
        sleep 5
    done
    jq -r --arg prefix "preview $env:" --argjson id "$command_id" \
        '.[] | select(.id > $id and (.body | startswith($prefix))) | .body' "$work/comments.json" > "$work/reply.txt"
    first=$(head -n 1 "$work/reply.txt")
    printf 'reply: %s\n' "$first"
    [ "$first" = "preview $env: $2" ]
}
ready() {
    "$phub" status "$env" --format json > "$work/status.json"
    jq -e --arg sha "$head_sha" '.state == "READY" and any(.services[]; .service == "backend" and .commit_sha == $sha)' "$work/status.json" >/dev/null
    grep -F "| backend | $(printf '%.12s' "$head_sha") |" "$work/reply.txt" >/dev/null
    printf 'state=READY environment=%s backend=%.12s\n' "$env" "$head_sha"
}
deleted() {
    "$phub" status "$env" --format json > "$work/status.json" || return
    jq -e '.state == "DELETED"' "$work/status.json" >/dev/null || return
    empty || return
    printf 'state=DELETED environment=%s inventory=empty\n' "$env"
}
main_sha=$(api "repos/$repo/git/ref/heads/main" --jq .object.sha)
api -X POST "repos/$repo/git/refs" -f "ref=refs/heads/$branch" -f "sha=$main_sha" >/dev/null
branch_created=1
api "repos/$repo/contents/README.md?ref=$branch" > "$work/readme.json"
python3 - "$work/readme.json" "$branch" > "$work/commit.json" <<'PY'
import base64
import json
import sys

with open(sys.argv[1]) as stream:
    readme = json.load(stream)
content = base64.b64decode(readme["content"]) + b"\n<!-- preview bot E2E -->\n"
json.dump({"message": "test: exercise preview bot", "branch": sys.argv[2],
           "sha": readme["sha"], "content": base64.b64encode(content).decode()}, sys.stdout)
PY
head_sha=$(api -X PUT "repos/$repo/contents/README.md" --input "$work/commit.json" --jq .commit.sha)
pr=$(api -X POST "repos/$repo/pulls" -f "head=$branch" -f base=main \
    -f title='E2E: PR preview bot (temporary)' -f body='Automated U9 scenario; closed and cleaned up after verification.' --jq .number)
env=pr-backend-$pr
printf 'PR=%s environment=%s\n' "$pr" "$env"
command_reply up READY
up_id=$command_id
ready
assert_total 1
"$phub" list --format json > "$work/list-before.json"
cp "$work/status.json" "$work/status-before.json"
command_reply status READY
status_id=$command_id
assert_total 2
sleep "$wait_seconds"
assert_total 2
[ "$(reply_count "$up_id" "$status_id")" -eq 1 ]
"$phub" list --format json > "$work/list-after.json"
"$phub" status "$env" --format json > "$work/status-after.json"
python3 - "$work" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
def read(name):
    return json.loads((root / name).read_text())
assert read("list-before.json") == read("list-after.json"), "Environment list changed"
a, b = read("status-before.json"), read("status-after.json")
assert (a["id"], a["version"]) == (b["id"], b["version"]), "Environment mutated"
PY
printf 'exactly-once: replies=2 list/id/version unchanged\n'
command_reply down DELETED
assert_total 3
deleted
command_reply up READY
ready
assert_total 4
api -X PATCH "repos/$repo/pulls/$pr" -f state=closed >/dev/null
deadline=$(($(date +%s) + 120))
until deleted; do
    [ "$(date +%s)" -lt "$deadline" ] || { echo 'PR-close cleanup timeout (120s)' >&2; exit 1; }
    sleep 5
done
assert_total 4
printf 'A9(a)-(e) passed; cleanup follows\n'
