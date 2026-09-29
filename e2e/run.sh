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
n=$prefix-n y=$prefix-y
work=$(mktemp -d)
tunnel_pid=
cleanup() {
    code=$?
    trap - EXIT HUP INT TERM
    for env in "$a" "$b" "$expiry" "$bad" "$n" "$y"; do
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
    for env in "$a" "$b" "$expiry" "$bad" "$n" "$y"; do "$phub" inventory "$env"; done
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

# Read-only Docker access through the same SSH configuration as scripts/phub.
# phub has no arbitrary exec command; never use the host's default context.
quote() { printf "'"; printf '%s' "$1" | sed "s/'/'\\\\''/g"; printf "'"; }
vm_docker() {
    command="export PATH=$(quote "${PHUB_REMOTE_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin}"); $(quote "${PHUB_REMOTE_DOCKER:-docker}") --context colima-preview-hub"
    for arg do command="$command $(quote "$arg")"; done
    ssh ${PHUB_SSH_OPTS:-} "${PHUB_SSH_HOST:-trading-macstudio}" "$command"
}
container_id() {
    vm_docker ps --no-trunc -q --filter label=dev.phub.managed=true \
        --filter "label=dev.phub.env=$1" --filter "label=dev.phub.service=$2" \
        --filter label=dev.phub.role=service |
        python3 -c 'import sys; ids=sys.stdin.read().split(); assert len(ids)==1, ids; print(ids[0])'
}
ready() {
    "$phub" status "$1" --format descriptor > "$work/descriptor.json"
    python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["state"]=="READY" and d["readiness"]["allHealthy"]' "$work/descriptor.json"
}
notifications() {
    notifier_id=$(container_id "$1" notifier)
    vm_docker exec "$notifier_id" python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/api/notifications", timeout=10).read().decode())'
}
check_notifications() {
    notifications "$1" > "$work/notifications.json"
    shift
    python3 -c 'import json,sys; entries=json.load(open(sys.argv[1])); expected=sys.argv[2:]; assert len(entries)==len(expected), entries; assert all(e["event"]=="note.created" for e in entries); assert sorted(e["payload"]["text"] for e in entries)==sorted(expected)' "$work/notifications.json" "$@"
}

inventory 'before A6(a)'
"$phub" up "$n" --set notifier=main --format json
ready "$n"
# N=3: multiple notes catch loss, duplicates and unrelated deliveries.
for i in 1 2 3; do
    endpoint=/api/notes request "api.$n.localhost" -H 'Content-Type: application/json' -d "{\"text\":\"$prefix-note-$i\"}"
done
check_notifications "$n" "$prefix-note-1" "$prefix-note-2" "$prefix-note-3"
inventory 'after A6(a) / before A6(b)'
"$phub" up "$y" --format json
ready "$y"
python3 -c 'import json,sys; assert all(s["name"]!="notifier" for s in json.load(open(sys.argv[1]))["services"])' "$work/descriptor.json"
endpoint=/api/notes request "api.$y.localhost" -H 'Content-Type: application/json' -d "{\"text\":\"$prefix-without\"}"
endpoint=/api/notes request "api.$y.localhost" > "$work/y.json"
python3 -c 'import json,sys; assert sum(n["text"]==sys.argv[2] for n in json.load(open(sys.argv[1])))==1' "$work/y.json" "$prefix-without"
inventory 'after A6(b) / before A6(c)'
backend_before=$(container_id "$y" backend)
"$phub" update "$y" --set notifier=main --format json
ready "$y"
backend_after=$(container_id "$y" backend)
[ "$backend_before" != "$backend_after" ]
echo "Backend restarted: $backend_before -> $backend_after"
endpoint=/api/notes request "api.$y.localhost" -H 'Content-Type: application/json' -d "{\"text\":\"$prefix-after\"}"
check_notifications "$y" "$prefix-after"
# Adding notifier to y must not deliver to or reset n.
check_notifications "$n" "$prefix-note-1" "$prefix-note-2" "$prefix-note-3"
inventory 'after A6(c)'
echo 'A6(d): protected-path diff (expected empty; reviewed by the main task)'
git -C "$root" diff --stat "${E2E_BASE_REF:-11d0aa8}..HEAD" -- preview_hub schemas

# Send the checked-out schemas as data so fallback validation tests this head.
ready "$y"
python3 - "$root" "$work/descriptor.json" > "$work/schema-input.json" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
pairs = [
    ("environment-descriptor", pathlib.Path(sys.argv[2])),
    ("qa-report", root / "e2e/fixtures/sample-qa-report.json"),
]
json.dump([
    [json.loads((root / "schemas" / (name + ".schema.json")).read_text()),
     json.loads(path.read_text())]
    for name, path in pairs
], sys.stdout)
PY
validator='import json,sys; from jsonschema import Draft202012Validator, FormatChecker; assert "date-time" in FormatChecker.checkers, "A8: date-time format checker unavailable; install jsonschema[format-nongpl]"; pairs=json.load(sys.stdin); [Draft202012Validator.check_schema(s) for s,d in pairs]; [Draft202012Validator(s, format_checker=FormatChecker()).validate(d) for s,d in pairs]; print("A8: descriptor and sample QA report validate")'
if python3 -c 'import jsonschema' >/dev/null 2>&1; then
    echo 'A8 validator: local python3 + jsonschema'
    python3 -c "$validator" < "$work/schema-input.json"
else
    echo 'A8 validator: phub-hub Python over SSH (colima-preview-hub)'
    vm_docker exec -i phub-hub python -c "$validator" < "$work/schema-input.json"
fi
inventory 'after A8'
echo 'A1-A6 and A8 passed; cleanup will verify empty inventories'
