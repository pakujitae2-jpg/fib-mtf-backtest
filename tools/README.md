# tools/ — 외부 도구 연동 (codebase-memory-mcp, OmniRoute)

두 저장소는 `external/` 에 클론돼 있고(참조용 소스), 실행 파일은 각각 릴리스 바이너리 / npm 전역 패키지를 쓴다.

| 도구 | 소스 | 실행 본체 | 이 프로젝트에서의 역할 |
|---|---|---|---|
| codebase-memory-mcp | `external/codebase-memory-mcp` (v0.10.8 소스) | `%LOCALAPPDATA%\Programs\codebase-memory-mcp\codebase-memory-mcp.exe` | 코드 지식그래프 MCP 서버 — `search_graph`, `trace_path`, `get_architecture` 등으로 `fib_mtf.py`/`fib_engine_c.py` 호출 관계 탐색 |
| OmniRoute | `external/OmniRoute` (3.8.51 소스) | `npm -g omniroute` 3.8.50, `http://localhost:20128` | 로컬 AI 게이트웨이 — Python(`llm_gateway.py`) 과 Claude Code MCP(`omniroute`) 에서 OpenAI 호환 단일 엔드포인트로 사용 |

## codebase-memory-mcp

* **경로 문제**: v0.10.8 은 MCP 프로세스의 작업 디렉터리에 한글이 있으면 데몬 세션을 거부한다(`daemon session context was rejected`).
  그래서 `cbm-mcp.cmd` 가 `%USERPROFILE%` 로 이동한 뒤 서버를 띄우고, 프로젝트는 ASCII 정션 `C:\Users\zxaswe\Desktop\fibmtf` (→ 이 폴더) 로 인덱싱했다.
* 등록: Claude Code **user 스코프** (`~/.claude.json`) 의 `codebase-memory-mcp` = `cmd /c %LOCALAPPDATA%\Programs\codebase-memory-mcp\cbm-mcp.cmd` (래퍼 사본). 프로젝트 `.mcp.json` 에는 넣지 않았다 — 같은 이름을 두 스코프에 두면 Claude Code 가 충돌 경고를 낸다. 래퍼 원본은 `tools/cbm-mcp.cmd`.
* 인덱스: 프로젝트명 `fibmtf` (1,639 nodes / 7,250 edges, `external/`·대용량 CSV 제외). 재인덱싱:
  ```
  cd %USERPROFILE%
  codebase-memory-mcp cli --progress --json index_repository --repo-path C:/Users/zxaswe/Desktop/fibmtf --mode fast --name fibmtf
  ```
* 그래프 UI: `http://localhost:9749` (데몬이 켜져 있을 때).

## OmniRoute

* 서버 기동: `tools\omniroute-start.cmd` (백그라운드 데몬, 포트 20128). 종료 `omniroute stop`. 대시보드 `http://localhost:20128`.
* 키 발급/설정: `python tools\omniroute_setup.py` (CLI 머신 토큰으로 `omniroute api api-keys post-api-keys --body '{"name":...}'` 호출; 발급된 키는 `sk-...`) → `.env.omniroute` (Python 용) 와 `.claude\settings.local.json` 의 `env` (`.mcp.json` 의 `${OMNIROUTE_API_KEY}` 확장용) 에 기록.
* Python: `llm_gateway.py` — `chat()`, `models()`, `health()`. 예시 `report_assist.py` (교정 결과 요약).
* Claude Code MCP: `.mcp.json` 의 `omniroute` (streamable-HTTP `/api/mcp/stream`, 헤더 `Authorization: Bearer ${OMNIROUTE_API_KEY}`). 프로젝트 스코프 서버라 **처음 `claude` 를 이 폴더에서 실행할 때 승인**해야 하고, 서버가 켜져 있어야 연결된다.
* Claude Code 자체를 OmniRoute 로 라우팅하려면 (선택): `omniroute launch` 또는 `settings.json` 의 `env` 에 `ANTHROPIC_BASE_URL=http://localhost:20128`, `ANTHROPIC_AUTH_TOKEN=<OMNIROUTE_API_KEY>` — 이 프로젝트 설정에는 넣지 않았다(현재 세션의 모델을 바꾸지 않기 위해).
* 기본 모델 `auto` 는 OmniRoute 의 무료 풀(OpenCode Free 등)로 라우팅된다. 특정 제공자를 쓰려면 대시보드 Providers 에서 키/OAuth 를 등록하고 `.env.omniroute` 의 `OMNIROUTE_MODEL` 을 바꾼다.
