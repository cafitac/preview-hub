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
| PH-6 | 생성 단계별 시간 기록 | 배포 | 대기 |
| PH-7 | 한 환경 안 서비스 빌드 병렬화 | 배포 | 대기 |
| PH-5 | 봇 명령을 polling 에서 떼어 냄 | 배포 | 대기 |
| PH-8 | 남는 파일 정리(gc) | 배포 | 대기 |
| PH-9 | 환경 namespace 방어(PSA, SA 토큰, egress) | 배포 | 대기 |
| PH-4 / HL-2 | GitHub 토큰 마운트, secrets.sh | 클러스터 | 대기 |
| HL-1 | 레지스트리 NetworkPolicy 좁히기 | 클러스터 + 실측 | 대기 |
| HL-3 | `/metrics` · 경보 | 배포 + 클러스터 + Cloudflare | 대기 |
| HL-4 | hub 쓰기 범위 VAP | 클러스터 | 대기 |
| PH-11 · HL-5 · HL-6 | 문구 · 레지스트리 GC · buildkit 캐시 상한 | 배포 / 클러스터 | 대기 |

## 진행 기록
- 2026-11-14: AQP-1 sprint 세션(「agent-skills 작업」)이 P8 실환경 검증에 hub API 로 환경을 만든다. hub 배포나 클러스터 변경 전에는 그 세션에 먼저 알린다(코드 PR 은 조율 불필요)
- 2026-11-14 PH-2: `kubectl wait` 를 `get job` 2초 폴링으로 바꿈. Failed 조건이면 바로 실패 + Job 로그 50줄. 검증 625 passed(ruff · pyright 통과)
- 2026-11-14 PH-2: PR #22 게시, CI 통과(5ad9bf0). 머지는 소유자. 배포는 다음 hub 이미지 태그와 함께(소유자 승인)
- 2026-11-14 PH-1: READY 환경의 descriptor 는 runner.health 로 다시 계산(실패하면 allHealthy=false), checkedAt=조회 시각, 대시보드 5초 캐시, health 에 resource StatefulSet 포함. 634 passed
- 2026-11-14 PH-3: `GET /api/environments/{name}/inventory`, `scripts/phub-remote`(cloudflared access curl). 650 passed. 실제 Access 경유 호출은 배포 뒤 소유자 세션으로 확인 필요
- 2026-11-14 PH-10: 점검 노트의 제안(작업 행에 host/instance 저장)은 쓰지 않았다. bot 은 hub 와 같은 파드의 다른 컨테이너(shareProcessNamespace 없음)라 instance 가 달라, hub GC 가 살아 있는 bot 작업을 끊는다. 대신 「작업은 처음부터 끝까지 env flock 을 잡는다 → recover 는 flock 을 잡았을 때만 불린다 → RUNNING 은 주인이 없다」로 PID · heartbeat 검사를 없앴다. 마이그레이션 없음. 652 passed
