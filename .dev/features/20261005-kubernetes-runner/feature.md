# 20261005-kubernetes-runner: 프리뷰 환경 = Kubernetes namespace

- Status: IN_PROGRESS
- Owner: cafitac (personal project)
- Repository: cafitac/preview-hub, 배포는 cafitac/homelab(apps/preview-hub)
- Created: 2026-10-05
- 배경: Mac Studio 의 모든 사이드 프로젝트를 k3s 한 클러스터로 옮긴다(homelab PLAN 3 단계). preview-hub 는 compose 러너가 docker.sock 으로 환경을 띄우고 있어 그대로는 옮길 수 없다
- 결정(사용자 2026-10-05): ① 이미지는 BuildKit + 클러스터 안 레지스트리 ② k8s 호출은 kubectl 하위 프로세스(server-side apply) ③ 기존 환경 · 상태는 옮기지 않고 새로 시작
- 설계: [design.md](design.md)

## 단위

| 단위 | 내용 | 상태 |
| --- | --- | --- |
| K1 | `runners/kubernetes.py` — render · apply · health · inventory · destroy · logs, 골든 · 가짜 실행기 테스트 | 완료 #16 |
| K2 | 빌더(BuildKit Job → 클러스터 레지스트리), `phub gc` 의 이미지 정리, CLI `runner: kubernetes` 연결 · 디스크 가드 | #17 |
| K3 | bot 실행기 — `docker exec phub-hub` 대신 같은 파드에서 CLI 호출, 환경 설명(C7)의 `proxy` 값을 설정으로(`PHUB_HUB_EXEC`, `PHUB_PROXY_ADDRESS` · `_PORT`) | #18 |
| K4 | homelab `apps/preview-hub` — hub · bot · 레지스트리 · BuildKit, RBAC, Argo CD (이미지 스크립트 #19) | 완료 — homelab 768baef · ca07cf4 |
| K5 | 전환 — `preview-hub.cafitac.com` · `*.cafitac.com` 을 homelab 터널로, e2e(up → ai-qa → down 뒤 남는 것 없음), colima `preview-hub` 정리 | |

## K2 실험 기록 (2026-10-05, homelab k3s)

- k3s 노드가 docker 런타임이라 이미지는 VM 의 도커 데몬이 받는다 — 클러스터 DNS 를 모른다. 레지스트리를 `hostPort: 5000, hostIP: 127.0.0.1` 로 노드 루프백에만 열었다
  - VM 안에 소켓이 생기지 않고(iptables DNAT) lima 도 포트를 넘기지 않는다 → Mac · LAN · tailnet 에 열리지 않는다(Mac 의 :5000 은 macOS AirPlay 수신기)
  - 노드 도커가 `localhost:5000` 으로 push · pull 하고, 파드가 `localhost:5000/...` 이미지로 뜬다
- 새 hub 이미지 안에서 `BuildKitBuilder` 로 preview-example-backend(544fd35) 를 클러스터 buildkitd 로 빌드 → 레지스트리 push → 두 번째 호출은 재사용 → 노드가 받아 실행(`import app.main` 성공)
- buildkitd 는 root(privileged)로 돌린다 — `--oci-worker-no-process-sandbox` 는 rootless 에서만 된다
