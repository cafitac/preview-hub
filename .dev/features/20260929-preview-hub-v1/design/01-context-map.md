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
            ACT["phub-bot 컨테이너 (S3)<br/>GitHub API 폴링 → docker exec phub-hub"]
            PX["phub-proxy (Traefik)<br/>포트 18080 → 호스트 127.0.0.1"]
            ENV1["phub-envA: backend@sha, frontend@sha, postgres"]
            ENV2["phub-envB: ..."]
        end
    end
    AIQA["ai-qa (후속 프로젝트)<br/>환경 기술서 소비"]

    U --> HUB
    BR --> PX
    ACT -->|"20초마다 코멘트·닫힌 PR 조회"| PR
    ACT --> HUB
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
- Genuine external boundaries: `GitSource` (git/GitHub), `Runner` (Docker/Compose), `GitHubApi` (S3 bot: list comments, list closed PRs, read PR head, post comment). No other adapter layers.
- The bot is outbound-only: GitHub never connects to the VM.

## Revision 4 (S4) — public access and dashboard

```mermaid
flowchart LR
    OWNER["소유자 브라우저"] -->|"HTTPS"| EDGE["Cloudflare 엣지<br/>Access 로그인(무료)<br/>preview-hub · phub-*"]
    EDGE -->|"터널(VM에서 바깥으로만 연결)"| CFD["phub-cloudflared (VM, 제안)"]
    subgraph VM["Colima VM preview-hub"]
        CFD -->|"preview-hub.cafitac.com"| HUBW["phub-hub HTTP :8080 (제안)<br/>대시보드 + JSON API<br/>Access JWT 검증"]
        CFD -->|"*.cafitac.com"| PX["phub-proxy (Traefik)<br/>phub-&lt;env&gt; 호스트만 라우팅, 나머지 404<br/>forwardAuth → hub /auth/verify"]
        HUBW -->|"phub up/update/down (자식 프로세스)"| LIFE["기존 수명주기·레지스트리"]
        PX --> ENVS["환경: phub-&lt;env&gt;.cafitac.com<br/>/ = 프론트, /_svc/api = 백엔드"]
        BOT["phub-bot"] -->|"교차 링크 코멘트(제안)"| GHAPI
    end
    HUBW -->|"브랜치·열린 PR 조회, pr-n 해석(읽기)"| GHAPI["GitHub API"]
    USERCF["사용자가 만드는 것: 터널·자격 파일, DNS preview-hub + *, Access 앱"] -.-> EDGE
```

- Cloudflare is an external authority owned by the user; the hub never writes to it.
- The dashboard is a second entry point into the same lifecycle (next to the CLI and the bot); it adds no new state authority.
- GitHub gains read calls from `phub-hub` (listing, `pr-<n>`); writes remain in `phub-bot`.
