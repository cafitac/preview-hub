#!/bin/sh
# Requires curl, python3, git, SSH access and a bootstrapped hub. Never pushes.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
phub=$root/scripts/phub
: "${E2E_ORIGINAL_SHA:?Set the original backend commit (40 hex)}"
: "${E2E_MOVED_SHA:?Set the expected second backend commit (40 hex)}"
branch=${E2E_BRANCH:-e2e-alt}
frontend=${E2E_FRONTEND_BRANCH:-main}
broken=${E2E_BROKEN_BRANCH:-e2e-broken}
repo=${E2E_BACKEND_REPO:-https://github.com/cafitac/preview-example-backend.git}
prefix=ee-$(date +%s)-$$
a=$prefix-a b=$prefix-b expiry=$prefix-ttl bad=$prefix-bad
work=$(mktemp -d)
tunnel_pid=
cleanup() {
    code=$?
    trap - EXIT HUP INT TERM
    for env in "$a" "$b" "$expiry" "$bad"; do
        "$phub" down "$env" --format json || code=1
        "$phub" inventory "$env" > "$work/inventory.json" || code=1
        python3 -c 'import json,sys; assert not any(json.load(open(sys.argv[1])).values())' "$work/inventory.json" || code=1
    done
    if [ -n "$tunnel_pid" ]; then kill "$tunnel_pid" 2>/dev/null || :; wait "$tunnel_pid" 2>/dev/null || :; fi
    rm -rf "$work"
    exit "$code"
}
trap cleanup EXIT HUP INT TERM
if [ "${E2E_EXISTING_TUNNEL:-0}" != 1 ]; then
    "$phub" tunnel >"$work/tunnel.log" 2>&1 &
    tunnel_pid=$!
    sleep 2
    kill -0 "$tunnel_pid"
fi
inventory() {
    echo "Inventory: $1"
    for env in "$a" "$b" "$expiry" "$bad"; do "$phub" inventory "$env"; done
}
empty() { "$phub" inventory "$1" | python3 -c 'import json,sys; assert not any(json.load(sys.stdin).values())'; }
request() {
    host=$1; shift
    curl --fail --silent --show-error --max-time 20 --resolve "$host:18080:127.0.0.1" "$@" "http://$host:18080${endpoint:-/healthz}"
}
check_sha() {
    "$phub" status "$a" --format descriptor | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["state"]=="READY"; assert next(s["commit"] for s in d["services"] if s["name"]=="backend")==sys.argv[1]' "$E2E_ORIGINAL_SHA"
}
inventory 'before A1'
[ "$(git ls-remote "$repo" "refs/heads/$branch" | awk '{print $1}')" = "$E2E_ORIGINAL_SHA" ]
"$phub" up "$a" --set "backend=$branch" --set "frontend=$frontend" --format json
check_sha
echo "A1: move $branch to $E2E_MOVED_SHA externally now; waiting (no push is performed)."
count=0
while [ "$(git ls-remote "$repo" "refs/heads/$branch" | awk '{print $1}')" != "$E2E_MOVED_SHA" ]; do
    count=$((count + 1)); [ "$count" -lt "${E2E_MOVE_POLLS:-60}" ]; sleep 5
done
[ "$E2E_MOVED_SHA" != "$E2E_ORIGINAL_SHA" ]
check_sha
inventory 'after A1 / before A2'
"$phub" up "$b" --set "backend=$branch" --set "frontend=$frontend" --format json
endpoint=/api/notes request "api.$a.localhost" -H 'Content-Type: application/json' -d "{\"text\":\"$prefix\"}"
endpoint=/api/notes request "api.$a.localhost" > "$work/a.json"
endpoint=/api/notes request "api.$b.localhost" > "$work/b.json"
python3 -c 'import json,sys; a,b=[json.load(open(p)) for p in sys.argv[1:3]]; assert any(n["text"]==sys.argv[3] for n in a); assert not any(n["text"]==sys.argv[3] for n in b)' "$work/a.json" "$work/b.json" "$prefix"
for env in "$a" "$b"; do
    endpoint=/config.js request "app.$env.localhost" | python3 -c 'import sys; assert sys.argv[1] in sys.stdin.read()' "http://api.$env.localhost:18080"
done
inventory 'after A2 / before A3'
"$phub" down "$a" --format json
empty "$a"
request "api.$b.localhost"
endpoint=/ request "app.$b.localhost" >/dev/null
inventory 'after A3 / before A4'
"$phub" status "$b" --format json > "$work/before.json"
"$phub" up "$b" --set "backend=$branch" --set "frontend=$frontend" --format json > "$work/after.json"
python3 -c 'import json,sys; a,b=[json.load(open(p)) for p in sys.argv[1:]]; assert a["id"]==b["id"] and a["version"]==b["version"]' "$work/before.json" "$work/after.json"
"$phub" up "$expiry" --ttl 5s --set "frontend=$frontend" --format json
sleep 6
"$phub" gc --format json
empty "$expiry"
inventory 'after A4 / before A5'
set +e
"$phub" up "$bad" --set "backend=$broken" --set "frontend=$frontend" --format json
code=$?
set -e
[ "$code" = 5 ]
"$phub" status "$bad" --format json > "$work/bad.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["state"]=="FAILED"; e=d.get("last_error") or json.loads(d["last_error_json"]); assert e["stage"]=="health" and e["service"]=="backend" and e["log_excerpt"]' "$work/bad.json"
"$phub" logs "$bad" backend
"$phub" down "$bad" --format json
empty "$bad"
inventory 'after A5'
echo 'A1-A5 passed'
