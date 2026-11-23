# 로컬 PDF·Markdown 검색 MCP 서버

로컬 PDF와 Markdown(`.md`)을 구조 파악, 키워드 검색, 페이지 읽기 순서로 탐색하는 `stdio` 기반 MCP 서버입니다. 도구는 인자로 받은 `file_path`만 열고, 다른 디렉토리를 스캔하지 않습니다.

## 도구

| 도구 | 설명 |
|---|---|
| `get_pdf_info(file_path)` | 총 페이지 수, 메타데이터, 목차(TOC) 반환 |
| `search_pdf(file_path, query, max_results=5)` | 대소문자 무시 키워드 검색, 페이지 번호와 문맥 스니펫 반환 (최대 50건) |
| `read_pdf_pages(file_path, start_page, end_page)` | 페이지 범위의 전체 텍스트 반환 (1부터 시작, 양 끝 포함, 한 번에 최대 5페이지) |

## 준비물

[Claude Code](https://code.claude.com)가 필요합니다. [uv](https://docs.astral.sh/uv/)가 없으면 한 줄 설치가 자동으로 설치합니다. 저장소를 직접 클론할 필요는 없습니다.

## 프로젝트에 등록하기

전역(`--scope user`)으로 등록하지 말고, 이 도구가 필요한 프로젝트 폴더에서 개별 등록하세요. PDF 폴더는 프로젝트마다 따로 저장됩니다.

### 한 줄 설치 (추천)

```bash
cd /path/to/your-project
curl -fsSL https://raw.githubusercontent.com/MasterTyping/DOCP/main/install.sh | sh
```

`<프로젝트>/rag`를 PDF 폴더로 만들어 `local` 등록합니다. 새로 만든 `rag/`는 git에서 제외하고, 이미 있던 폴더는 그대로 둡니다. 이미 등록되어 있으면 아무것도 바꾸지 않습니다. 완료 후 Claude Code를 다시 시작하세요.

### 다른 AI 도구에 등록

명령 끝에 도구 이름을 붙이면 해당 도구의 프로젝트 설정에 추가합니다. 기존 설정은 유지합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/MasterTyping/DOCP/main/install.sh | sh -s -- cursor
```

| 이름 | 도구 | 설정 파일 |
|---|---|---|
| `cursor` | Cursor | `.cursor/mcp.json` |
| `vscode` | VS Code (Copilot) | `.vscode/mcp.json` |
| `gemini` | Gemini CLI | `.gemini/settings.json` |
| `codex` | Codex | `.codex/config.toml` (신뢰한 프로젝트에서만 로드) |

이 설정 파일에는 이 PC의 절대 경로가 들어가므로 커밋하지 않는 것이 좋습니다. 주석이 있는 JSON 설정은 변경하지 않고 오류로 종료하니, 이때는 직접 추가하세요.

### 실행기로 등록 (폴더 선택)

```bash
cd /path/to/your-project
uvx --from git+https://github.com/MasterTyping/DOCP pdf-rag
```

- 이미 등록되어 있으면 바로 Claude Code를 엽니다.
- 등록되어 있지 않으면 폴더 선택 창을 띄우고, 고른 폴더를 이 프로젝트의 PDF 폴더로 `local` 등록합니다.
- 선택을 취소했거나 GUI가 없으면 `<프로젝트>/rag`를 만들어 사용합니다.

### 명령어로 직접 등록

`local`은 나만 이 프로젝트에서 사용합니다.

```bash
cd /path/to/your-project
mkdir -p rag
claude mcp add pdf-rag --transport stdio --scope local -e PDF_RAG_DIR="$PWD/rag" -- uvx --from git+https://github.com/MasterTyping/DOCP pdf-rag-server
```

`--scope local`을 `--scope project`로 바꾸면 프로젝트의 `.mcp.json`에 기록됩니다. 이 파일에는 `PDF_RAG_DIR`의 절대 경로가 저장되므로, 커밋해서 공유하면 경로가 같은 환경에서만 동작합니다.

### 클론해서 로컬 `.venv`로 사용

`uv` 없이 쓰려면 저장소를 클론한 뒤 `setup.sh`를 실행하세요. Python 3.10 이상이 필요하고, 완료되면 이 PC의 경로가 반영된 등록 명령을 출력합니다.

```bash
git clone https://github.com/MasterTyping/DOCP
cd DOCP
./setup.sh
```

특정 Python을 쓰려면 `PYTHON=python3.12 ./setup.sh`로 실행합니다. 클론한 폴더를 옮기면 `.venv`를 지우고 다시 실행한 뒤 재등록해야 합니다.

### 확인, 경로 변경, 제거

```bash
claude mcp get pdf-rag
claude mcp remove pdf-rag --scope local   # 제거 후 다시 등록하면 PDF 폴더가 바뀝니다
```

Claude Code 안에서는 `/mcp`로 연결 상태를 볼 수 있습니다.

## 사용하기

PDF나 `.md` 파일을 등록한 폴더에 넣고 Claude Code에 요청하면 됩니다. `file_path`에는 `문서.pdf` 같은 상대 경로나 절대 경로를 쓸 수 있습니다. `.md`는 등록한 폴더 안의 UTF-8 파일만 읽으며, 100줄을 한 페이지로 계산하고 제목(`#`)을 목차로 반환합니다.

```text
문서.pdf의 목차를 보여주고 "인증"이 나오는 부분을 찾아 페이지 번호와 함께 요약해줘
```

## 업데이트

uv가 설치본을 캐시하므로, 새 버전을 받으려면 캐시를 비운 뒤 Claude Code를 다시 시작하세요.

```bash
uv cache clean pdf-rag-mcp
```

## 제한 사항

- 스캔본처럼 텍스트 레이어가 없는 PDF는 OCR을 하지 않으므로 빈 텍스트가 반환됩니다.
- 비밀번호로 보호된 PDF는 오류를 반환합니다.
- 검색은 의미 검색이 아니라 키워드 일치 방식입니다.
