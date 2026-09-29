# Context map

```mermaid
flowchart LR
    subgraph MB["MacBook (사용자)"]
        U["phub 래퍼<br/>ssh → docker exec phub-hub"]
        BR["브라우저<br/>ssh -L 18080 → *.localhost:18080"]
    end
    subgraph GH["GitHub (외부 권위)"]
        REPO_BE["preview-example-backend<br/>preview.yaml + 브랜치"]
        REPO_FE["preview-example-frontend<br/>preview.yaml + 브랜치"]
        REPO_N["notifier (S2)<br/>preview.yaml"]
        PR["PR 코멘트 /preview (S3)"]
    end
    subgraph MS["trading-macstudio (호스트에는 Colima VM만)"]
        subgraph VM["Colima 프로필 preview-hub (전용 Docker 데몬)"]
            HUB["phub-hub 컨테이너 (PROPOSED)<br/>카탈로그·조합·생명주기<br/>레지스트리 볼륨 phub-state"]
            RUN["실행기 Runner<br/>ComposeRunner (v1)"]
            ACT["runner 컨테이너 (S3)"]
            PX["phub-proxy (Traefik)<br/>포트 18080 → 호스트 127.0.0.1"]
            ENV1["phub-envA: backend@sha, frontend@sha, postgres"]
            ENV2["phub-envB: ..."]
        end
    end
    AIQA["ai-qa (후속 프로젝트)<br/>환경 기술서 소비"]

    U --> HUB
    BR --> PX
    PR --> ACT --> HUB
    HUB -->|"ref → commit (git ls-remote)<br/>소스 가져오기"| REPO_BE
    HUB --> REPO_FE
    HUB --> REPO_N
    HUB --> RUN --> VM
    PX --> ENV1
    PX --> ENV2
    HUB -->|"environment-descriptor/v1"| AIQA
    ACT -->|"결과 코멘트"| PR
```

- Authority: GitHub owns code and refs; the hub owns environment identity, pinned commits and lifecycle state; the Docker daemon of the `preview-hub` Colima VM owns running objects, which the hub reconciles by label.
- Host footprint: only the Colima VM. The hub, its registry and caches, the proxy, every environment and (S3) the bot runner are containers or named volumes inside the VM; the host sees one forwarded port bound to 127.0.0.1.
- Upstream/downstream: example repositories are upstream (read only). ai-qa is downstream and only reads the descriptor and writes its own report; it never mutates environments through the hub in v1.
- Genuine external boundaries: `GitSource` (git/GitHub), `Runner` (Docker/Compose), `GitHubComments` (S3). No other adapter layers.
