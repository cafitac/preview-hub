# 설계 — Kubernetes 러너

## 지금

```text
GitHub PR ── bot ──(docker exec)── hub(CLI · 대시보드 · Access 검증)
                                    │ docker.sock
                                    ├─ compose 러너: 환경마다 compose 프로젝트 + 네트워크 phub-<env>
                                    └─ phub-proxy(Traefik, 도커 라벨) ◀── 터널 phub(*.cafitac.com)
```

## 바뀐 뒤

```text
GitHub PR ── bot(hub 파드 사이드카) ── hub(ServiceAccount + RBAC)
                                        │ kubectl apply --server-side --field-manager phub
                                        ├─ k8s 러너: 환경 = namespace phub-<env>
                                        └─ 빌드: BuildKit → 클러스터 레지스트리
클러스터 Traefik(Ingress + Middleware CRD) ◀── 터널 homelab(*.cafitac.com)
```

## 러너 포트(C4)는 그대로다

`EnvironmentPlan` · `ServicePlan` · `ResourcePlan` · `RunResult` · `Inventory` 는 Docker 를 모른다. k8s 러너는 같은 프로토콜을 구현하고, 계획(PlanBuilder)도 바꾸지 않는다.

| 메서드 | compose | k8s |
| --- | --- | --- |
| `build` | `docker buildx build --load` | 주입된 빌더(K2: BuildKit Job → 레지스트리) |
| `apply` | compose 파일 → 서비스 순서로 `up` | `render()` → 단계별 server-side apply. 리소스 StatefulSet → `rollout status`(90s) → init Job(지우고 다시 · `wait complete`) → Deployment · Service · Ingress · Middleware. 끝나면 계획에서 빠진 서비스 정리(prune, 라벨 범위) |
| `health` | curl 컨테이너로 HTTP 확인 · 도커 healthcheck | Deployment `readyReplicas`. 회복하지 않는 대기(CrashLoopBackOff · 이미지 오류)는 UNHEALTHY |
| `destroy` | 라벨로 컨테이너 · 네트워크 · 볼륨 · 이미지 정리 | 소유 라벨이 붙은 namespace 만 삭제(전부 연쇄 삭제, local-path PV 회수) |
| `inventory` | 라벨로 도커 객체 | 라벨로 namespace(종료 중 포함) · 파드 · PVC. 이미지는 레지스트리 몫 |
| `logs` | `docker logs` | `kubectl logs deployment/<서비스>` |
| 잘못된 대상 방지 | 도커 데몬 이름이 `colima-preview-hub` | hub namespace(`preview-hub`)가 있는 클러스터 |

## 바꾸지 않아도 되는 이유

- **서비스 간 주소** `http://<서비스>:<포트>`(plan.py) — namespace 안 Service 이름이 같다
- **DB 주소** `postgresql://preview:preview@<서비스>--<id>:5432/preview` — StatefulSet 의 Service 이름이 `<서비스>--<id>`
- **메모리** `512Mi` 형식이 이미 k8s 수량 형식이다
- **ai-qa** 는 hub 의 환경 설명(C7)만 본다 — 공개 주소 형식이 같으면 고칠 것이 없다

## 매핑 세부

- **헬스**: 매니페스트 `health.http` → `httpGet`, `health.cmd` → `exec`. 매니페스트 timeout(기본 90s)은 startupProbe 의 실패 허용 횟수(2 초 간격)로, readiness 는 이후 상태를 본다
- **공개 경로**: `public_access` 가 있으면 `phub-<env>.cafitac.com` + `/_svc/<subdomain>` Ingress 에 Middleware 두 개(ForwardAuth → hub `/auth/verify`, StripPrefix). 우선순위 annotation 은 compose 와 같다(경로 100 · 진입 서비스 10). 클러스터 안에서 의미가 없는 `.localhost` 경로는 만들지 않는다
- **격리**: namespace 마다 ResourceQuota(서비스 · DB 메모리 합 + init 하나 몫), NetworkPolicy(같은 namespace · Traefik 만)
- **재시작**: 파드 템플릿에 (이미지, env) 해시 annotation — 바뀐 서비스만 굴러간다. Deployment 는 Recreate(쿼터 안에서 교체)
- **⚠️ `enableServiceLinks: false`**: Service 이름으로 `<NAME>_PORT=tcp://…` 가 주입되어 앱 설정을 덮는 문제(homelab interview-coach 이전에서 실제로 겪었다)

## 위험

- **와일드카드 DNS 전환(K5)** 순간 떠 있던 환경 주소가 끊긴다 → 환경은 일회용이라 전환 직전에 모두 내리고 새로 만든다
- **동시 환경 5 개** — 환경 쿼터가 서비스 수에 비례(예시 3 서비스 약 2.5GiB). 노드 64GB 에서 여유가 있다
- **검증**: K1 은 골든 + 가짜 실행기 테스트, 그리고 실제 클러스터 server-side dry-run 으로 렌더 결과 16 개 객체가 모두 받아들여지는 것을 확인했다(2026-10-05)
