# AXit — 회의 문서 종합 플랫폼

AXit은 여러 회의 자료를 한곳에 모아 분석하고, 핵심 내용과 근거를 바탕으로
통합 문서를 생성·편집할 수 있는 회의 문서 종합 플랫폼입니다.

- **백엔드**: FastAPI (Python 3.12) + PostgreSQL
- **프런트엔드**: React 19 + TypeScript + Vite (`AXit_project-main_goal_frontend`)
- **패키지 매니저**: 프런트엔드는 pnpm 워크스페이스, 백엔드는 `uv`
- **실행 환경**: Docker Compose 기반 (Postgres / Migrate / API / Orchestrator / Web 5개 서비스)

이 문서는 **아무것도 설치되어 있지 않은 클린 환경**을 기준으로, 런타임 설치부터
의존성 설치, 실행, 빌드까지의 과정만 설명합니다.

---

## 빠른 시작

처음 실행하는 사용자는 아래 순서만 따르면 됩니다. 저장소는 Windows의
Docker BuildKit 한글 경로 문제를 피하도록 **영문 경로**에 클론하세요.

### Windows PowerShell

```powershell
git clone https://github.com/CONNECTOR-AXit/AXit_project.git C:\dev\AXit_project
cd C:\dev\AXit_project
Copy-Item .env.example .env

# .env.grok.local은 저장소 루트에 준비되어 있다고 가정합니다.
uv sync --locked
pwsh -NoProfile -File scripts/start-dev.ps1
```

### macOS / Linux

```bash
git clone https://github.com/CONNECTOR-AXit/AXit_project.git ~/dev/AXit_project
cd ~/dev/AXit_project
cp .env.example .env

# .env.grok.local은 저장소 루트에 준비되어 있다고 가정합니다.
uv sync --locked
chmod +x scripts/start-dev.sh
./scripts/start-dev.sh
```

기동이 끝나면 다음 두 가지만 확인합니다.

```bash
docker compose ps
```

- `postgres`, `api`, `orchestrator`, `web`이 모두 `healthy`
- 브라우저에서 http://localhost:3000 접속 가능

> API는 호스트의 `localhost:8000`에 직접 공개하지 않는 것이 정상입니다. Web
> 컨테이너가 내부 Docker 네트워크의 `api:8000`으로 프록시합니다. 따라서 서비스는
> 항상 http://localhost:3000 에서 확인하세요.

첫 사용 흐름은 **회원가입 → 로그인 → 프로젝트 생성 → 문서 2개 이상 업로드 →
AI 분석 시작 → 분석 결과 확인**입니다. 업로드가 50%에서 움직이지 않으면
`.logs/file-extraction-worker.err.log`를 확인하세요.

---

## 1. 클린 환경 준비 (런타임 · 도구 설치)

### 1.1 필수 항목

| 도구 | 버전 | 확인 방법 | 용도 |
| --- | --- | --- | --- |
| Git | 최신 | `git --version` | 항상 필요 |
| Docker Desktop/Engine + Compose v2 | 최신 | `docker version`, `docker compose version` | 권장 전체 실행에 필요 |
| uv | 최신 | `uv --version` | Python 설치·의존성·문서 추출 워커에 필요 |
| Python | `3.12.11` (`.python-version`) | `uv run python --version` | `uv`가 자동 설치·관리 |
| Node.js | `22.17.0` (`.nvmrc`) | `node -v` | 로컬 프런트엔드 빌드/개발 시 필요 |
| pnpm | `11.4.0` (`package.json`) | `pnpm -v` | 로컬 프런트엔드 빌드/개발 시 필요 |

> 권장 실행 경로는 **Docker + 호스트 문서 추출 워커**입니다. 이 경로는
> Git, Docker, uv가 필요하고 Node/pnpm은 Docker 이미지 안에서 사용합니다.
> Node/pnpm을 호스트에 설치하는 이유는 4.2절의 로컬 개발과 5절의 개별
> 컴파일·검증을 실행하기 위해서입니다.

### 1.2 Windows 10/11 클린 설치 (권장 환경)

1. BIOS/UEFI 가상화를 켜고 관리자 PowerShell에서 WSL 2를 설치·갱신합니다.

   ```powershell
   wsl --install
   wsl --update
   ```

2. Git, Docker Desktop, uv를 설치합니다. `winget`이 없는 환경은 각 공식 설치
   링크([Git](https://git-scm.com/download/win),
   [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/),
   [uv](https://docs.astral.sh/uv/getting-started/installation/))를 사용하세요.

   ```powershell
   winget install --id Git.Git -e
   winget install --id Docker.DockerDesktop -e
   winget install --id astral-sh.uv -e
   ```

3. **터미널을 새로 열고 Docker Desktop을 실행**한 다음 Linux container 엔진이
   준비될 때까지 기다립니다. Python 3.12.11은 uv로 설치합니다.

   ```powershell
   uv python install 3.12.11
   git --version
   uv --version
   uv run --python 3.12.11 python --version
   docker version
   docker compose version
   ```

4. 로컬 프런트엔드 컴파일도 할 경우에만
   [nvm-windows 공식 설치 프로그램](https://github.com/coreybutler/nvm-windows/releases)을
   설치하고 새 관리자 PowerShell에서 아래를 실행합니다.

   ```powershell
   nvm install 22.17.0
   nvm use 22.17.0
   corepack enable
   corepack prepare pnpm@11.4.0 --activate
   node -v
   pnpm -v
   ```

### 1.3 macOS / Ubuntu 클린 설치

먼저 Git과 curl을 준비합니다.

```bash
# macOS: 명령줄 개발 도구(Git 포함)
xcode-select --install

# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y git curl ca-certificates
```

Docker는 운영체제 공식 절차로 설치하고 실행합니다:
[macOS Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/),
[Ubuntu Docker Engine](https://docs.docker.com/engine/install/ubuntu/). 설치 후
`docker version`과 `docker compose version`이 모두 성공해야 합니다.

uv와 uv 관리 Python을 설치합니다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
exec "$SHELL" -l
uv python install 3.12.11
uv --version
uv run --python 3.12.11 python --version
```

로컬 프런트엔드 컴파일도 할 경우에만 nvm과 Node/pnpm을 설치합니다.

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.6/install.sh | bash
exec "$SHELL" -l
nvm install 22.17.0
nvm use 22.17.0
corepack enable
corepack prepare pnpm@11.4.0 --activate
node -v
pnpm -v
```

### 1.4 버전 확인 체크리스트

```bash
git --version
docker version
docker compose version
uv --version
uv run --python 3.12.11 python --version
```

로컬 빌드까지 수행한다면 추가로 `node -v`가 `v22.17.0`, `pnpm -v`가
`11.4.0`인지 확인합니다.

<details>
<summary>기존 설치 안내(도구별 상세)를 펼치기</summary>

#### Node.js 22.17.0 설치

Windows(PowerShell) 기준, [nvm-windows](https://github.com/coreybutler/nvm-windows) 사용을 권장합니다.

```powershell
nvm install 22.17.0
nvm use 22.17.0
node -v   # v22.17.0
```

macOS/Linux는 `nvm`(nvm-sh) 사용:

```bash
nvm install
nvm use
```

#### pnpm 11.4.0 설치 (corepack)

Node 22에는 corepack이 내장되어 있습니다. `package.json`의
`packageManager` 필드가 pnpm 버전을 고정하므로, corepack만 활성화하면 됩니다.

```bash
corepack enable
corepack prepare pnpm@11.4.0 --activate
pnpm -v   # 11.4.0
```

#### Python 3.12.11 + uv 설치

Python 3.12 계열이 설치되어 있어야 합니다 (`pyproject.toml`의
`requires-python = "==3.12.*"`).

```powershell
# Windows
winget install Python.Python.3.12
```

```bash
# macOS / Linux
# (pyenv 사용 권장) pyenv install 3.12.11 && pyenv local 3.12.11
```

`uv`(Python 패키지·가상환경 관리 도구)를 설치합니다.

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

> 설치 스크립트는 `uv`를 `~/.local/bin`(Windows는
> `%USERPROFILE%\.local\bin`)에 설치하고 PATH에 등록하지만, **이미 열려
> 있던 터미널에는 즉시 반영되지 않습니다.** 설치 직후 같은 창에서
> `uv --version`이 "찾을 수 없음"으로 나오면 터미널(또는 IDE 통합 터미널)을
> 새로 열어 다시 시도하세요.

#### Docker Desktop 설치

전체 스택(DB + API + Orchestrator + Web)을 한 번에 띄우려면 Docker Desktop(WSL2
백엔드 권장, Windows 기준)을 설치하고 실행해 둡니다.

</details>

---

## 2. 저장소 클론 및 의존성 설치

```bash
git clone https://github.com/CONNECTOR-AXit/AXit_project.git
cd AXit_project
```

> Windows에서는 `C:\dev\AXit_project`처럼 전체 경로에도 한글이 없는 위치를
> 권장합니다.

### 2.1 Node/pnpm 워크스페이스 의존성 설치

루트에서 실행하면 `pnpm-workspace.yaml`에 정의된 다음 워크스페이스가 함께
설치됩니다: `AXit_project-main_goal_frontend`, `packages/*`,
`spikes/document-ingestion/viewer`.

```bash
corepack pnpm install --frozen-lockfile
```

### 2.2 Python 의존성 설치 (uv)

루트에서 실행하면 `pyproject.toml` / `uv.lock`에 고정된 버전으로 `.venv`가
생성됩니다 (FastAPI, SQLAlchemy, Alembic, pytest, mypy, ruff 등 포함).

```bash
uv sync --locked
```

가상환경 파이썬 실행 파일 경로:

- Windows: `.venv\Scripts\python.exe`
- macOS/Linux: `.venv/bin/python`

---

## 3. 환경 변수 설정

`.env.example`을 복사해 `.env`를 만듭니다.

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

```
POSTGRES_DB=axit
POSTGRES_USER=axit
POSTGRES_PASSWORD=axit-phase0-only
PUBLIC_ORIGIN=http://localhost:3000
PUBLIC_HOST=localhost:3000
SESSION_COOKIE_SECURE=false
WEB_BIND_ADDRESS=127.0.0.1
AXIT_BLOB_ROOT=./.axit-blobs
AXIT_G0_IMAGE=axit-ingestion-g0:local
XAI_API_KEY=
GROK_MODEL=grok-4.5
```

> `.env`는 절대 커밋하지 않습니다 (`.gitignore`에서 차단됨). LAN 테스트처럼
> `0.0.0.0` 바인딩이 필요한 특수한 경우가 아니면 `WEB_BIND_ADDRESS`를
> `127.0.0.1`로 유지하세요.

### 3.1 xAI(Grok) API 키 — `.env.grok.local`

저장소 루트에 `.env.grok.local` 파일을 만들어 실제 xAI 키를 넣습니다
(`.gitignore`의 `.env.*` 패턴에 걸려 있어 커밋되지 않습니다). AI 분석
파이프라인(문서 요약·외부검증·통합 문서·편집기 추천)과 새 프로젝트 다이얼로그의
"AI로 설명 구체화" 기능이 이 키를 사용합니다.

```
XAI_API_KEY=xai-실제키
GROK_MODEL=grok-4.5
```

`docker-compose.yml`의 `api`/`orchestrator` 서비스가 이 파일을 `env_file`로
자동 로드하므로(`required: false`) `docker compose up`을 실행할 때마다 별도
조치 없이 반영됩니다.

---

## 4. 실행 방법

### 4.1 방법 A — Docker Compose로 기본 스택 실행 (권장, 가장 쉬움)

`docker-compose.yml`은 5개 서비스를 정의합니다: `postgres`(DB) →
`migrate`(1회성 스키마 마이그레이션) → `api`(FastAPI) + `orchestrator`(백그라운드
워커) → `web`(React 프로덕션 서버).

> **이 기본 스택에는 원본 문서의 OCR/파싱을 담당하는 파일 추출 워커가 포함되지
> 않습니다** (이유는 4.3절 참고 — 호스트 Docker 소켓이 필요해 의도적으로
> Compose 밖에서 실행합니다). `docker compose up`만 실행하고 이 워커를
> 깜빡하면, 웹/API/AI 보고서 생성 기능은 정상 동작해도 **업로드한 PDF/HWPX/
> DOCX 등은 "처리 중"(진행률 50%)에서 영원히 멈춘 것처럼 보입니다** — 이건
> 버그가 아니라 워커가 없어서 큐가 아예 소비되지 않는 상태입니다.
>
> 그래서 **아래 두 명령을 매번 세트로 실행**하거나(권장), 이 세트를 한 번에
> 실행하는 스크립트(`scripts/start-dev.ps1` / `scripts/start-dev.sh`)를
> 쓰세요. 스크립트는 이미 떠 있는 컨테이너/워커를 감지해 중복 실행하지
> 않으므로 여러 번 실행해도 안전합니다.

```powershell
# Windows (PowerShell)
pwsh -NoProfile -File scripts/start-dev.ps1
```

```bash
# macOS / Linux
chmod +x scripts/start-dev.sh
./scripts/start-dev.sh
```

- 스크립트가 하는 일: `docker compose up -d --build` → 서비스 healthy 대기 →
  `axit-ingestion-g0:local` 이미지 빌드(4.3절) → `app.file_extraction_worker`를
  백그라운드로 기동. 로그는 `.logs/file-extraction-worker.{out,err}.log`에
  남습니다.
- **완료 확인:** 파일을 하나 업로드했을 때 진행률이 몇 초~수십 초 안에 50%를
  지나 100%(또는 실패 시 0%)로 움직이면 워커가 정상 동작 중인 것입니다.
  50%에서 멈춰 있다면 워커 로그(`.logs/file-extraction-worker.err.log`)와
  `docker ps`(Postgres/Docker Desktop이 켜져 있는지)를 확인하세요.

수동으로 하나씩 실행하고 싶다면(스크립트를 쓰지 않는 경우) 아래처럼 두
단계를 **모두** 실행해야 합니다: 이 절의 `docker compose up --build`와,
4.3절의 파일 추출 워커 실행.

```bash
docker compose up --build
```

> ⚠️ **Windows + 경로에 한글이 포함된 경우 (이 저장소 기본 폴더명
> `해커톤_AXit팀` 포함) 이 명령이 아래 에러로 즉시 실패할 수 있습니다.**
>
> ```
> failed to dial gRPC: rpc error: code = Internal desc = rpc error: code = Internal desc =
> header key "x-docker-expose-session-sharedkey" contains value with non-printable ASCII characters
> ```
>
> Docker Compose가 이미지를 빌드할 때 내부적으로 `docker buildx bake`를 쓰는데,
> 세션 키에 프로젝트 경로가 들어가면서 경로에 포함된 한글(비-ASCII 문자) 때문에
> gRPC 헤더가 깨지는 Windows 환경의 알려진 문제입니다. `docker compose build`도
> 동일하게 실패합니다.
>
> **해결 방법 (택 1):**
>
> 1. **(권장) 저장소를 한글이 없는 경로로 옮기기** — 예:
>    `C:\dev\axit` 등 ASCII 경로로 clone/이동 후 다시 시도하면 `--build`가
>    정상 동작합니다.
> 2. **(우회) `docker build`로 이미지를 미리 만들고 `--build` 없이 실행** —
>    `docker build`(bake를 쓰지 않는 방식)는 한글 경로에서도 정상 동작합니다.
>
>    ```bash
>    docker build -f apps/api/Dockerfile -t axit-phase0-migrate .
>    docker tag axit-phase0-migrate axit-phase0-api
>    docker tag axit-phase0-migrate axit-phase0-orchestrator
>    docker build -f AXit_project-main_goal_frontend/Dockerfile -t axit-phase0-web .
>    docker compose up -d
>    ```
>
>    (`docker-compose.yml`의 최상단 `name: axit-phase0` + 서비스 이름 조합으로
>    이미지 태그를 맞춘 것입니다. 소스를 수정했다면 위 4개 빌드 명령을 다시
>    실행한 뒤 `docker compose up -d`를 다시 실행하세요.)

- 웹: http://localhost:3000
- API: 컨테이너 내부 네트워크에서만 노출 (`web` → `api:8000`로 프록시).
  따라서 `http://localhost:8000`이 열리지 않는 것이 정상입니다. API를 직접
  디버깅할 때만 아래 4.2의 로컬 실행 방식을 사용하세요.

종료:

```powershell
# Windows: 호스트 파일 추출 워커 종료 후 Compose 종료
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
  Where-Object { $_.CommandLine -like '*app.file_extraction_worker*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId }
docker compose down
```

```bash
# macOS / Linux
pkill -f app.file_extraction_worker || true
docker compose down
```

DB 데이터를 초기화하려면(볼륨은 tmpfs라 컨테이너 재생성 시 자동 초기화됩니다):

```bash
docker compose down -v
```

### 4.2 방법 B — 로컬에서 개별 프로세스로 실행 (개발용)

DB만 Docker로 띄우고, API/오케스트레이터/웹은 로컬 프로세스로 직접 실행하면
코드 변경 시 즉시 반영(hot reload)됩니다.

**1) Postgres만 기동**

```bash
docker compose up -d postgres
```

기본적으로 호스트의 `54329` 포트로 노출됩니다
(`postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit`).

**2) 데이터베이스 마이그레이션 적용**

```bash
# Windows
$env:DATABASE_URL = "postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit"
$env:PYTHONPATH = "apps/api"
.\.venv\Scripts\python.exe -m app.migrations upgrade
```

```bash
# macOS / Linux
export DATABASE_URL="postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit"
export PYTHONPATH="apps/api"
.venv/bin/python -m app.migrations upgrade
```

> `pyproject.toml`의 `pythonpath` 설정은 pytest 실행에만 적용됩니다. 일반 Python
> 명령에서는 위와 같이 `PYTHONPATH=apps/api`를 직접 지정하거나 `cd apps/api` 후
> 가상환경 Python을 실행해야 합니다.

**3) API 서버 실행**

```bash
cd apps/api
$env:DATABASE_URL = "postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit"   # PowerShell
..\..\.venv\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
# macOS / Linux
cd apps/api
export DATABASE_URL="postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit"
../../.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- 헬스체크: http://localhost:8000/health

**4) 오케스트레이터(생성/제안 큐 워커) 실행 — 선택 사항**

```powershell
# Windows (새 PowerShell 창, 저장소 루트에서 시작)
cd apps/api
$env:DATABASE_URL = "postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit"
..\..\.venv\Scripts\python.exe -m app.orchestrator
```

```bash
# macOS / Linux (새 터미널, 저장소 루트에서 시작)
cd apps/api
export DATABASE_URL="postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit"
../../.venv/bin/python -m app.orchestrator
```

**5) 프런트엔드 개발 서버 실행**

```bash
corepack pnpm --dir AXit_project-main_goal_frontend run dev
```

- 개발 서버: http://localhost:5173
- 프런트엔드는 `@axit/api-client` 워크스페이스 패키지를 통해 API 계약
  타입을 참조합니다.

### 4.3 문서 처리(OCR/파싱) 워커 — 문서 업로드 기능 사용 시 필수

업로드한 원본 파일(PDF/PNG/JPEG/HWP/HWPX/DOCX/PPTX/XLSX)을 실제로 열어 텍스트를 추출하는
`app.file_extraction_worker`는 **`docker-compose.yml`에 서비스로 포함되어
있지 않습니다.** 파싱을 위해 별도의 격리된 샌드박스 컨테이너(`axit-ingestion-g0`)를
호스트에서 직접 실행해야 합니다(호스트 Docker 소켓을 컨테이너에 마운트하지
않는 설계이기 때문입니다). **이 단계를 건너뛰면 업로드한 문서가 "처리 중"
50%에서 절대 넘어가지 않습니다** — 아래는 4.1절의 `scripts/start-dev.ps1` /
`scripts/start-dev.sh`가 자동으로 실행하는 것과 같은 내용이니, 그 스크립트를
썼다면 이 절은 참고용이고 아래 명령을 따로 실행할 필요가 없습니다.

```powershell
# Windows (PowerShell) — Postgres/Docker Desktop이 켜져 있어야 합니다
$env:DATABASE_URL = "postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit"
New-Item -ItemType Directory -Force .\.axit-blobs | Out-Null
$env:AXIT_BLOB_ROOT = (Resolve-Path .\.axit-blobs).Path
$env:AXIT_G0_IMAGE = "axit-ingestion-g0:local"
$env:PYTHONPATH = "apps/api"
docker build --pull=false -f spikes/document-ingestion/Dockerfile -t axit-ingestion-g0:local .
.\.venv\Scripts\python.exe -m app.file_extraction_worker
```

```bash
# macOS / Linux — Postgres/Docker가 실행 중이어야 합니다
export DATABASE_URL="postgresql://axit:axit-phase0-only@127.0.0.1:54329/axit"
mkdir -p .axit-blobs
export AXIT_BLOB_ROOT="$(pwd)/.axit-blobs"
export AXIT_G0_IMAGE="axit-ingestion-g0:local"
export PYTHONPATH="apps/api"
docker build --pull=false -f spikes/document-ingestion/Dockerfile -t axit-ingestion-g0:local .
.venv/bin/python -m app.file_extraction_worker
```

파일 추출 워커는 API와 같은 `AXIT_BLOB_ROOT`를 사용해야 합니다. 방법 A의 전체
Compose 기본 스택을 먼저 실행했다면 루트의 `.axit-blobs`가 이미 생성되어 있을 수
있지만, 클린 환경과 방법 B에서도 동작하도록 위 명령은 디렉터리를 명시적으로
생성합니다.

> ⚠️ **`localhost`가 아니라 반드시 `127.0.0.1`을 쓰세요.** Windows에서
> `localhost`는 IPv6(`::1`)로 먼저 해석을 시도하는데, Docker는 Postgres
> 포트를 IPv4(`127.0.0.1`)에만 게시합니다. 그 결과 연결마다 IPv6 시도
> 실패 후 IPv4로 폴백하는 데 10초 이상 걸려 매우 느려집니다. `127.0.0.1`을
> 쓰면 즉시(수십 ms) 연결됩니다. 같은 이유로 4.2절의 API 서버를 호스트에서
> 직접 띄울 때도 `127.0.0.1`을 쓰는 것이 좋습니다.

이 워커는 큐에 쌓인 작업을 하나 처리하고 종료하는 `--once` 옵션도 지원합니다
(디버깅용).

---

## 5. 컴파일 / 빌드 방법

모든 명령은 **저장소 루트**에서 실행합니다. 클린 환경이라면 먼저 아래 두
의존성 설치를 완료합니다. Docker 이미지 빌드만 할 때는 Dockerfile이 이미지
안에서 의존성을 설치하므로 이 단계는 생략할 수 있습니다.

```bash
corepack pnpm install --frozen-lockfile
uv sync --locked
```

### 5.1 프런트엔드 빌드 (TypeScript 컴파일 + Vite 번들)

```bash
corepack pnpm --dir AXit_project-main_goal_frontend run build
```

내부적으로 `tsc -b && vite build`가 실행되며, 결과물은
`AXit_project-main_goal_frontend/dist`에 생성됩니다. 빌드된 결과는
`server/server.mjs`(Node 프로덕션 서버)로 서빙합니다.

```bash
corepack pnpm --dir AXit_project-main_goal_frontend run start
```

### 5.2 워크스페이스 전체 빌드

루트 `package.json`의 스크립트는 `--if-present` 옵션으로 각 워크스페이스의
`build`/`lint`/`test`/`typecheck` 스크립트를 존재하는 곳에서만 실행합니다.

```bash
corepack pnpm build
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm --dir AXit_project-main_goal_frontend test
```

`corepack pnpm test`는 프런트엔드뿐 아니라 G0 문서 뷰어의 캡처 provenance와
Playwright 증거까지 검사하는 전체 워크스페이스 검증입니다. 제출 증거 fixture를
갱신하거나 검토하는 경우에만 별도로 실행하세요.

### 5.3 Python 백엔드 — 패키징 없음, 실행만

`pyproject.toml`은 `[tool.uv] package = false`로 설정되어 있어 별도의 빌드
산출물(wheel 등)이 없습니다. `uv sync`로 설치된 `.venv`를 그대로 실행에
사용합니다.

Python 소스 전체의 문법/바이트코드 컴파일 가능 여부는 아래처럼 확인합니다.

```bash
uv run python -m compileall -q apps/api/app
```

### 5.4 Docker 이미지 빌드

모든 명령은 루트 디렉터리를 빌드 컨텍스트로 사용합니다.

```bash
# API (FastAPI, Python 3.12-slim 기반)
docker build -f apps/api/Dockerfile -t axit-api:local .

# Web (Node 22-bookworm-slim, pnpm 멀티스테이지 빌드)
docker build -f AXit_project-main_goal_frontend/Dockerfile -t axit-web:local .

# 문서 OCR/파싱 샌드박스
docker build --pull=false -f spikes/document-ingestion/Dockerfile -t axit-ingestion-g0:local .
```

Compose가 사용하는 실제 태그로 API/migrate/orchestrator와 Web을 한꺼번에
빌드하려면 다음을 실행합니다. 문서 파싱 샌드박스는 Compose 밖에서 사용하므로
두 번째 명령이 별도로 필요합니다.

```bash
docker compose build
docker build --pull=false -f spikes/document-ingestion/Dockerfile -t axit-ingestion-g0:local .
```

`docker compose up --build` 또는 4.1절의 시작 스크립트는 Compose 이미지를
빌드하면서 실행까지 이어갑니다. 시작 스크립트는 파싱 샌드박스도 함께 빌드합니다.

### 5.5 빌드·품질 게이트

제출 직전 최소 검증 순서는 다음과 같습니다.

```bash
# 프런트엔드/워크스페이스
corepack pnpm typecheck
corepack pnpm lint
corepack pnpm --dir AXit_project-main_goal_frontend test
corepack pnpm build

# Python 정적 검사
uv run ruff check apps/api tests
uv run mypy apps/api/app
uv run python -m compileall -q apps/api/app

# 배포 이미지와 서비스 상태
docker compose build
docker build --pull=false -f spikes/document-ingestion/Dockerfile -t axit-ingestion-g0:local .
docker compose up -d
docker compose ps
```

Python 테스트는 저장소 루트를 import 경로에 포함해 실행합니다.

```powershell
# Windows PowerShell
$env:PYTHONPATH = "."
uv run pytest -q
```

```bash
# macOS / Linux
PYTHONPATH=. uv run pytest -q
```

마지막 `docker compose ps`에서 `postgres`, `api`, `orchestrator`, `web`이 모두
`healthy`이면 빌드와 기본 기동 검증이 완료된 것입니다. `migrate`는 정상적으로
종료되는 1회성 작업이라 목록에 계속 실행 중으로 보이지 않는 것이 정상입니다.
