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
| K1 | `runners/kubernetes.py` — render · apply · health · inventory · destroy · logs, 골든 · 가짜 실행기 테스트 | 이 PR |
| K2 | 빌더(BuildKit Job → 클러스터 레지스트리), `phub gc` 의 이미지 정리, CLI `runner: kubernetes` 연결 · 디스크 가드 | 다음 |
| K3 | bot 실행기 — `docker exec phub-hub` 대신 같은 파드에서 CLI 호출, 환경 설명(C7)의 `proxy` 값을 러너가 채움 | |
| K4 | homelab `apps/preview-hub` — hub · bot · 레지스트리 · BuildKit, RBAC, Argo CD | |
| K5 | 전환 — `preview-hub.cafitac.com` · `*.cafitac.com` 을 homelab 터널로, e2e(up → ai-qa → down 뒤 남는 것 없음), colima `preview-hub` 정리 | |
