# 20261114-reliability-hardening: preview-hub 신뢰성 · 보안 · 운영 공백 메우기

- Record schema: 4
- Status: REGISTERED
- Planning mode: FROM_AUDIT_NOTE
- Execution mode: MANUAL_GATED
- Record kind: FEATURE
- Owner: cafitac (personal project)
- Repository: cafitac/preview-hub, 배포 · 클러스터 쪽은 cafitac/homelab(apps/preview-hub)
- Created: 2026-11-14
- Updated: 2026-11-14
- 근거: agent-skills `.dev/notes/preview-hub-ai-qa-audit-20261114.md` 「브리프 A」(ID PH-*, HL-*)
- Current slice: S1 — 백로그 순서대로 ID 하나씩
- Current PR unit: PH-1
- Delivery strategy: STANDALONE (PR 하나 = ID 하나, 각각 독립 머지)
- Current delivery bundle: N/A
- Target/base: main
- Base ref: origin/main
- Base decision: 저장소 관례(단일 main, squash 머지). PR 단위마다 직전 fetch 한 origin/main 에서 worktree 를 만든다
- Verification topology: LOCAL_LIGHT(`uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`) + CI_EXACT_SHA
- Worktree cleanup policy: AUTO_AFTER_SAFE_TERMINAL
- Worktree/branch: ../.worktrees/ph-2 · fix/ph-2-init-job-fail-fast (base 8d9fdbe)
- Worktree cleanup status: ACTIVE
- Canonical record: ~/Project/cafitac/portfolio/preview-hub/.dev/features/20261114-reliability-hardening/feature.md
- Design profile: NONE (단위별로 다시 판단. 마이그레이션이 생기는 PH-6 · PH-10 은 PR 본문에 스키마 변경을 적는다)
- Design status: NOT_REQUIRED

## 권한 (사용자 2026-11-14)

- 코드 PR 은 추천안으로 진행하고, 배포 영향이 없는(inert) 코드 PR 은 머지까지 한다
- 소유자 승인이 필요한 것: 배포(homelab kustomization `newTag`, `deploy/k8s-image.sh`), 클러스터 변경
  (NetworkPolicy, RBAC/VAP, Secret, 마운트, 경보 규칙), Cloudflare 설정, kubectl 실측
- homelab 수정은 `~/Project/cafitac/homelab` 에서 worktree 로 한다
- GitHub 쓰기는 `GH_TOKEN=$(gh auth token --user cafitac)`. 커밋 · PR 에 attribution 줄을 넣지 않는다
- PR 크기: 테스트 포함 300줄 이하 목표, 500줄 초과면 이유, 1000줄 상한
- 하지 않는 것: P10(서비스 토큰 identity, AQP-1 sprint 2 · `feat/qh1-service-identity` worktree), ai-qa 저장소

## 단위

| 단위 | 내용 | 결정 | 상태 |
| --- | --- | --- | --- |
| PH-2 | init Job 실패를 600초 기다리지 않고 바로 끝낸다 | 배포 | #22 CI 통과, 머지 대기 |
| PH-1 | descriptor 의 readiness 를 live 로 계산 | 배포 | PR (#22 위에 쌓음) |
| PH-3 | inventory API + `scripts/phub-remote` | 배포 | PR (#23 위에 쌓음) |
| PH-10 | hub 재시작 뒤 중단 작업 즉시 회수 | 배포 | PR (#24 위에 쌓음) |
| PH-6 | 생성 단계별 시간 기록 | 배포 | PR (#25 위에 쌓음) |
| PH-7 | 한 환경 안 서비스 빌드 병렬화 | 배포 | PR (#26 위에 쌓음) |
| PH-5 | 봇 명령을 polling 에서 떼어 냄 | 배포 | PR (#27 위에 쌓음) |
| PH-8 | 남는 파일 정리(gc) | 배포 | PR (#28 위에 쌓음) |
| PH-9 | 환경 namespace 방어(PSA, SA 토큰, egress) | 배포 | PR (#29 위에 쌓음) |
| PH-4 / HL-2 | GitHub 토큰 마운트, secrets.sh | 클러스터 | homelab#201(머지=배포, 승인 필요) · homelab#202 |
| HL-1 | 레지스트리 NetworkPolicy 좁히기 | 클러스터 + 실측 | 실측 대기(소유자 kubectl) |
| HL-3 | `/metrics` · 경보 | 배포 + 클러스터 | hub 지표 PR (#30 위) + homelab#204(hub 배포와 함께 머지) |
| HL-4 | hub 쓰기 범위 VAP | 클러스터 | homelab#203(머지=적용, 승인 필요) |
| PH-11 · HL-5 · HL-6 | 문구 · 레지스트리 GC · buildkit 캐시 상한 | 배포 / 클러스터 | PH-11 PR (#31 위) · HL-5 결정 대기 · homelab#205 |

## 진행 기록
- 2026-11-14: AQP-1 sprint 세션(「agent-skills 작업」)이 P8 실환경 검증에 hub API 로 환경을 만든다. hub 배포나 클러스터 변경 전에는 그 세션에 먼저 알린다(코드 PR 은 조율 불필요)
- 2026-11-14 PH-2: `kubectl wait` 를 `get job` 2초 폴링으로 바꿈. Failed 조건이면 바로 실패 + Job 로그 50줄. 검증 625 passed(ruff · pyright 통과)
- 2026-11-14 PH-2: PR #22 게시, CI 통과(5ad9bf0). 머지는 소유자. 배포는 다음 hub 이미지 태그와 함께(소유자 승인)
- 2026-11-14 PH-1: READY 환경의 descriptor 는 runner.health 로 다시 계산(실패하면 allHealthy=false), checkedAt=조회 시각, 대시보드 5초 캐시, health 에 resource StatefulSet 포함. 634 passed
- 2026-11-14 PH-3: `GET /api/environments/{name}/inventory`, `scripts/phub-remote`(cloudflared access curl). 650 passed. 실제 Access 경유 호출은 배포 뒤 소유자 세션으로 확인 필요
- 2026-11-14 PH-10: 점검 노트의 제안(작업 행에 host/instance 저장)은 쓰지 않았다. bot 은 hub 와 같은 파드의 다른 컨테이너(shareProcessNamespace 없음)라 instance 가 달라, hub GC 가 살아 있는 bot 작업을 끊는다. 대신 「작업은 처음부터 끝까지 env flock 을 잡는다 → recover 는 flock 을 잡았을 때만 불린다 → RUNNING 은 주인이 없다」로 PID · heartbeat 검사를 없앴다. 마이그레이션 없음. 652 passed
- 2026-11-14 PH-6: operation_stages 테이블(마이그레이션 0004), resolve · checkout · build(서비스별) · apply · health · delete. 상세 API 와 `status --format json` 에 stages. 660 passed
- 2026-11-14 PH-7: 바뀐 서비스를 ThreadPoolExecutor(build_concurrency)로 병렬 빌드, 실패는 제출 순서상 첫 실패 서비스로 보고. 665 passed
- 2026-11-14 PH-4: homelab#201 — Secret 디렉터리 마운트 /run/phub-secrets/github + PHUB_GITHUB_TOKEN_FILE. 머지 = Argo CD 반영(파드 재시작) → 소유자 승인 · AQP-1 세션 조율 필요. preview-hub README 의 토큰 경로 문구는 적용 뒤 고친다
- 2026-11-14 HL-2: homelab#202 — secrets.sh 가 파일 · stdin(github), 인자(access)로 값을 받는다. 클러스터 영향 없음
- 2026-11-14 PH-5: 봇 명령을 스레드 워커(4개)로 실행, 환경별 직렬, recover 는 진행 중 행을 건너뛰고 재시작 전 RUNNING 은 바로 중단 처리. 669 passed
- 2026-11-14 HL-4: homelab#203 — VAP 를 platform/admission 에 둔다(apps/preview-hub 의 namespace 변환이 VAP 에 namespace 를 붙이기 때문). CEL 서버 검증은 적용 뒤 소유자 확인 필요
- 2026-11-14 PH-8: gc 가 안 쓰는 체크아웃(7일), 웹 로그(14일), 삭제된 환경의 매니페스트 · 잠금 파일을 지운다. Registry.lock 은 flock 뒤 inode 를 확인한다. 체크아웃 재사용 시 mtime 갱신(진행 중 생성과의 경쟁 방지). 675 passed. 실제 디스크 사용량 실측은 소유자 kubectl 필요
- 2026-11-14 PH-9: namespace PSA baseline(warn restricted), 모든 파드 automountServiceAccountToken=false, egress 는 DNS · 같은 namespace · 공인 주소만. 676 passed. 배포 뒤 e2e 로 서비스 간 통신 · DNS 확인 필요(k3s kube-router 의 egress 적용)
- 2026-11-14 HL-3: hub 는 별도 포트(PHUB_METRICS_PORT, 9100)에 Access 없이 /metrics. homelab#204 는 PodMonitor + PreviewHubDown/GcStale/OpStuck. Cloudflare bypass 와 phub-* namespace 경보는 쓰지 않음(이유는 PR 본문). 680 passed
- 2026-11-14 PH-11: 오류 문구를 대시보드 · /preview · phub 공통으로, README 의 BuildKit Job → buildkitd. 681 passed
- 2026-11-14 HL-6: homelab#205 — buildkitd.toml(reservedSpace 2GB, maxUsedSpace 20GB, minFreeSpace 20GB). 머지 전 캐시 사용량 실측 권장
- 2026-11-14 HL-1: 레지스트리가 보는 노드 pull 의 출발 주소(hostPort 127.0.0.1 DNAT 뒤 SNAT 여부) 실측 전에는 from 을 정할 수 없다. 측정 요청을 소유자에게 넘김. PH-9 의 egress 가 환경 파드 → 레지스트리 경로는 먼저 막는다
- 2026-11-14 HL-5: 레지스트리 GC 를 읽기 전용 모드로 돌리는 방식(CronJob 이 registry 를 readonly 로 재시작 → gc → 복구) vs hub 가 빌드 슬롯을 잡고 GC 를 트리거하는 방식 — 소유자 결정 대기
- 2026-11-14 배포: homelab #202·#203·#205·#206 머지, hub d25f45824e27(#207). #201 은 bot 이 PHUB_GITHUB_TOKEN_FILE 을 읽지 않아(polling.py:425) `token missing` → #208 로 되돌림. HL-1 실측: registry remoteaddr 는 hub · buildkitd · 10.42.0.1(노드) 셋뿐(homelab #206). HL-6 실측: buildkit 1.2G
- 2026-11-14 INIT-RETRY: e2e 두 번 모두 backend--db--init-1 이 DB 에 Connection refused. 새 파드가 뜬 직후 약 1초 동안 NetworkPolicy 가 연결을 거부한다(racetest: 첫 시도 FAIL, 이후 open). PH-9 이전 이미지에서도 AQP-1 P8 이 같은 Job 에서 실패했다. init Job backoffLimit 0 → 2. 681 passed
- 2026-11-14 INIT-WAIT: hub 46ab027771c9 배포 뒤 e2e 에서 init-0 이 재시도 2번까지 세 파드 모두 Connection refused. Job 재시도는 새 파드라 매번 같은 1초 구간에 걸린다. init Job 앞에 initContainer wait-db(postgres:<버전>, pg_isready -h <db 서비스> 를 1초마다 최대 120초)를 두고 backoffLimit 은 0 으로 되돌림
- 2026-11-14 배포 완료: hub 051f66c9d010(homelab #210), e2e-051f READY 28초(init-0·init-1 Complete), 삭제 뒤 inventory 비어 있음. #204 반영(PodMonitor, PrometheusRule, /metrics 확인)
- 2026-11-14 BOT-TOKEN: bot 이 PHUB_GITHUB_TOKEN_FILE 을 읽도록 github.token_file() 하나로 모음(hub · web · bot 공통). 이 이미지 배포 뒤 homelab #201 을 다시 적용한다. 682 passed
