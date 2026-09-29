# 설계 검토

- 기능 / 범위: preview-hub v1 — 여러 저장소의 서비스를 브랜치별로 고정해 한 환경으로 띄우기 (S1~S4 계약, S1 구현 기준)
- 근거 상태: 현재(CURRENT) / 제안(PROPOSED) / 미결정(OPEN)
- 기준 산출물: `01-context-map.md`, `02-domain-model.puml`, `04-target-schema.dbml`, `05-transaction-flows.puml`, `06-state-machines.puml`, `07-consistency-migration.md`, `08-acceptance-trace.md`, `11-interface-contracts.md`
- 검토 언어: 한국어
- 표현 원칙: TARGET_OVERVIEW_FIRST

## 한눈에 보는 최종 구조

- 현재: 아무것도 없음(신규). Mac Studio는 Colima 프로필마다 Docker가 따로 도는 구조이고, 디스크 여유 44 GiB.
- 완성 후: Mac Studio 호스트에는 Colima 가상 머신 하나만 있고, 그 안에서 모든 것이 컨테이너로 돈다. hub 컨테이너(`phub-hub`)가 저장소별 `preview.yaml`과 카탈로그만 읽고 브랜치를 커밋으로 고정해 환경별 Compose 프로젝트(서비스 + 전용 PostgreSQL)를 띄운다. 공용 프록시가 `api.<환경>.localhost:18080` 이름으로 연결하고, MacBook은 SSH 포트 포워딩으로 접속한다.
- 안전 경계: hub는 자기가 떠 있는 VM의 Docker에만 닿는다(다른 프로젝트 데몬은 보이지 않음). 레지스트리·소스 캐시도 VM 안 볼륨이라 호스트 파일을 쓰지 않는다. 삭제는 `dev.phub.env` 라벨로만. 환경 5개·빌드 동시 2개·디스크 여유 하한으로 호스트를 지킨다. VM을 지우면 흔적이 남지 않는다.

## 시각화

### 전체 목표 구조

근거: `01-context-map.md`, `07-consistency-migration.md`

```mermaid
flowchart LR
    U["사용자(MacBook)<br/>phub 래퍼 → ssh → docker exec"] --> HUB
    B["브라우저(MacBook)<br/>ssh -L 18080 → *.localhost:18080"] --> PX
    PR["PR 코멘트 (S3)"] --> BOT
    subgraph MS["Mac Studio (호스트에는 Colima VM만)"]
        subgraph VM["Colima 프로필 preview-hub · 전용 Docker · 모두 컨테이너"]
            HUB["hub 컨테이너 phub-hub (제안 PROPOSED)<br/>카탈로그 · 조합 · 생명주기<br/>레지스트리 볼륨(SQLite)"]
            BOT["봇 runner 컨테이너 (S3)"]
            PX["공용 프록시 phub-proxy<br/>18080 → 호스트 127.0.0.1"]
            subgraph E1["환경 feat-x"]
                FE1["frontend@a1b2"]
                BE1["backend@c3d4"]
                DB1[("PostgreSQL 전용")]
            end
            subgraph E2["환경 feat-y"]
                FE2["frontend@a1b2"]
                BE2["backend@e5f6"]
                DB2[("PostgreSQL 전용")]
            end
        end
    end
    GH["GitHub 저장소들<br/>preview.yaml + 브랜치"]
    AIQA["ai-qa (후속)<br/>환경 기술서 읽기"]
    HUB -->|"브랜치 → 커밋 고정(ls-remote)"| GH
    HUB -->|"실행기(Runner) 경유"| PX
    BOT --> HUB
    PX --> FE1 & BE1 & FE2 & BE2
    FE1 -->|"자기 환경 API만"| BE1 --> DB1
    FE2 --> BE2 --> DB2
    HUB -->|"environment-descriptor/v1"| AIQA
```

같은 프론트 커밋(`a1b2`)이 두 환경에서 서로 다른 백엔드에 붙는 것이 핵심 가치 1이다. 이미지는 커밋당 한 번만 빌드하고, 백엔드 주소는 빌드가 아니라 **컨테이너 시작 시 주입**하기 때문에 가능하다.

### 목표 데이터 구조

근거: `04-target-schema.dbml`

```mermaid
erDiagram
    environments ||--|{ environment_services : "고정된 서비스 커밋"
    environments ||--o{ operations : "작업 이력(누가·언제·결과)"
    environments {
        integer id PK
        text name "활성 환경 중 유일(부분 유니크)"
        text state "생명주기 상태"
        text spec_json "요청한 조합"
        text ttl_expires_at "만료 시각"
        integer version "상태 변경마다 +1"
        text last_error_json "실패 단계·서비스·로그"
    }
    environment_services {
        integer environment_id FK
        text service "서비스 이름"
        text requested_ref "요청 브랜치"
        text commit_sha "고정 커밋(불변)"
        text image "phub/서비스:커밋"
        text public_url "외부 주소"
    }
    operations {
        integer id PK
        integer environment_id FK
        text kind "CREATE UPDATE DELETE EXPIRE"
        text status "RUNNING SUCCEEDED FAILED INTERRUPTED"
        text requested_by "cli 또는 gh 로그인#PR"
        integer pid "실행 프로세스"
        text heartbeat_at "생존 신호"
    }
```

### 핵심 트랜잭션 흐름 — 환경 만들기

근거: `05-transaction-flows.puml`

```mermaid
sequenceDiagram
    actor Caller as 사용자·봇
    participant UC as 환경 만들기(CreateEnvironment)
    participant L as 환경 잠금 파일
    participant DB as 레지스트리(SQLite)
    participant G as Git 소스(GitSource)
    participant R as 실행기(Runner)
    Caller->>UC: up feat-x --set backend=feat-x
    UC->>L: 잠금 획득(이미 작업 중이면 거절)
    UC->>DB: 트랜잭션: 같은 이름·같은 요청이면 그대로 반환 / 없으면 REQUESTED + 작업 기록
    UC->>G: 서비스마다 브랜치 → 커밋 확정
    UC->>DB: 트랜잭션: 커밋 고정 저장, BUILDING
    UC->>R: 없는 (서비스, 커밋) 이미지만 빌드(동시 2개)
    UC->>DB: 트랜잭션: STARTING
    UC->>R: 환경 적용: DB → 마이그레이션·시드 → 서비스, 프록시 연결(모두 라벨 부착)
    UC->>R: 헬스 확인(타임아웃)
    alt 전부 정상
        UC->>DB: 트랜잭션: READY, 주소·상태 저장
    else 어느 단계든 실패
        UC->>DB: 트랜잭션: FAILED + 실패 단계·로그(객체는 조사용으로 남김)
    end
    UC->>L: 잠금 해제
    UC-->>Caller: 상태, 주소, 고정 커밋
```

DB 트랜잭션은 매번 짧게 끝나고, git·빌드·기동 같은 오래 걸리는 외부 작업은 **환경 잠금만 쥔 채** 트랜잭션 밖에서 한다. 프로세스가 도중에 죽으면 다음 명령이 오래된 작업 기록을 INTERRUPTED로 바꾸고 환경을 FAILED로 둔다. 삭제는 레지스트리가 아니라 Docker 라벨 기준이라 고아 객체가 남지 않는다.

### 도메인 상태와 권한 — 환경 생명주기

근거: `06-state-machines.puml`, `07-consistency-migration.md`

```mermaid
stateDiagram-v2
    state "요청됨" as REQUESTED
    state "커밋 확정 중" as RESOLVING
    state "이미지 빌드" as BUILDING
    state "기동 중" as STARTING
    state "준비됨" as READY
    state "갱신 중" as UPDATING
    state "실패" as FAILED
    state "삭제 중" as DELETING
    state "삭제됨" as DELETED
    [*] --> REQUESTED: up
    REQUESTED --> RESOLVING
    RESOLVING --> BUILDING: 모든 브랜치 → 커밋
    BUILDING --> STARTING: 이미지 준비
    STARTING --> READY: 전부 헬스 정상
    READY --> READY: 같은 요청 up(변화 없음)
    READY --> UPDATING: update svc=ref
    UPDATING --> BUILDING
    RESOLVING --> FAILED
    BUILDING --> FAILED
    STARTING --> FAILED
    UPDATING --> FAILED
    FAILED --> UPDATING: 새 브랜치로 재시도
    READY --> DELETING: down 또는 만료
    FAILED --> DELETING: down 또는 만료
    DELETING --> DELETED: 라벨 객체 0개
    DELETING --> DELETING: 잔여물 → 재시도
    DELETED --> [*]
```

### 계약 요약 (확장성 = 핵심 가치 2)

근거: `11-interface-contracts.md`

```mermaid
flowchart TB
    subgraph REPO["서비스 저장소마다"]
        MF["preview.yaml(서비스 매니페스트 C1)<br/>빌드 · 포트 · 헬스 · 의존 · DB · 주입 변수"]
    end
    subgraph HUBCFG["hub 설정(코드 아님)"]
        CAT["catalog.yaml(C2)<br/>서비스 → 저장소 · 기본 브랜치"]
    end
    SPEC["조합 명세(C3)<br/>up feat-x --set backend=feat-x"]
    PLAN["환경 계획(EnvironmentPlan)<br/>실행기 중립"]
    RUNNER["실행기 인터페이스(C4)<br/>ComposeRunner · 이후 K3dRunner"]
    DESC["환경 기술서(C7) → ai-qa<br/>QA 리포트(C8) ← ai-qa"]
    MF --> PLAN
    CAT --> PLAN
    SPEC --> PLAN --> RUNNER
    PLAN --> DESC
```

세 번째 서비스(notifier)를 붙일 때 바뀌는 것은 **그 저장소의 `preview.yaml`과 카탈로그 한 줄**뿐이다. 백엔드는 `requires: notifier (optional)`로 선언해 두어, notifier가 없는 환경에서도 그대로 뜬다.

## 전달 계획 참고 (보조 정보)

| 순서 | PR 단위(가칭) | 담당 설계 범위 | 검증 / 관찰 | 롤백 경계 |
|---|---|---|---|---|
| 1 | U-BE 예제 백엔드 | C1 매니페스트, DB·시드, `/healthz` | 저장소 CI | 저장소 단위 |
| 2 | U-FE 예제 프론트 | C1, 런타임 설정 주입 | 저장소 CI | 저장소 단위 |
| 3 | U-CORE hub 계약·레지스트리·생명주기 | C2~C5, 스키마, 상태 흐름, FakeRunner | 단위 테스트 A1 A4 A5 A7 | 저장소 단위 |
| 4 | U-RUN ComposeRunner·프록시·hub 컨테이너·Colima 프로필 | 격리, 라벨 정리, SSH 포워딩 접속 | Mac Studio E2E A1~A5 | `phub down` + 프로필 삭제 |
| 5 | U-N notifier (S2) | 확장성 | E2E A6, hub diff 0 | 카탈로그 한 줄 제거 |
| 6 | U-BOT PR 봇 (S3) | C6 | 실제 PR A9 | 워크플로 제거 |
| 7 | U-QA 기술서·리포트 스키마 (S4) | C7 C8 | 스키마 테스트 A8 | 저장소 단위 |

## 확인이 필요한 결정

- 이 설계(호스트에는 Colima VM만·나머지 전부 컨테이너, VM 안 볼륨의 SQLite 레지스트리, 커밋 고정·시작 시 주입, 라벨 기반 정리, `*.localhost` 이름 + SSH 포트 포워딩, 계약 C1~C8)를 승인하고 자율 진행 범위(스프린트 매니페스트) 작성으로 넘어갈지, 수정할지, 멈출지.
- O1(접속 방법)은 SSH 포트 포워딩으로 확정했다. Tailscale 컨테이너는 필요할 때 추가하며 공개 주소 템플릿만 바뀐다. O2(개인 계정 PR 봇 러너 등록)는 S3 계획 때 정한다.
