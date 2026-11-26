# 로컬 PDF·Markdown 검색 MCP 서버

로컬 PDF와 Markdown(`.md`)을 구조 파악, 핵심 요약 읽기, 키워드 검색, 페이지 읽기 순서로 탐색하고, 결과를 md·HTML·PDF·Word·PowerPoint 파일로 내보내는 `stdio` 기반 MCP 서버입니다. 도구는 등록한 폴더 안의 문서만 열고, `@` 자동완성 목록은 등록한 폴더 안의 파일 이름만 읽습니다.

## 도구

| 도구 | 설명 |
|---|---|
| `get_pdf_info(file_path)` | 총 페이지 수, 메타데이터, 목차(TOC) 반환. 텍스트 없는(스캔본) PDF는 `warning`으로 표시 |
| `skim_document(file_path, query="", max_chars=6000)` | 대용량 문서의 핵심만 반환: `query`가 있으면 가장 많이 언급된 페이지, 목차가 있으면 각 절의 첫 부분, 없으면 고르게 고른 페이지의 첫 부분 |
| `search_pdf(file_path, query, max_results=5)` | 대소문자 무시 키워드 검색. 구절이 그대로 없으면 모든 단어가 들어 있는 페이지를 찾음(`mode: all_words`). 최대 50건 |
| `read_pdf_pages(file_path, start_page, end_page)` | 페이지 범위의 전체 텍스트 반환 (1부터 시작, 양 끝 포함, 한 번에 최대 5페이지·4만 자) |
| `list_documents(folder="")` | 하위 폴더까지 포함해 해당 폴더의 문서 목록 반환 (최대 500개) |
| `search_folder(folder, query, max_results=5)` | 해당 폴더의 문서만 검색, 많이 일치한 문서부터 파일 경로·페이지·스니펫 반환 (최대 50건) |
| `export_document(content, format, file_name)` | Markdown 내용을 `md`·`html`·`pdf`·`docx`·`pptx` 파일로 저장 (기존 파일은 덮어쓰지 않음). `notion`은 md 백업 후 Notion 로그인 절차를 안내 |

추출한 텍스트는 파일이 바뀌기 전까지 메모리에 캐시하므로, 같은 문서를 반복 검색해도 다시 추출하지 않습니다.

## 준비물

[Claude Code](https://code.claude.com)가 필요합니다. [uv](https://docs.astral.sh/uv/)가 없으면 한 줄 설치가 자동으로 설치합니다. 저장소를 직접 클론할 필요는 없습니다.

## 프로젝트에 등록하기

전역(`--scope user`)으로 등록하지 말고, 이 도구가 필요한 프로젝트 폴더에서 개별 등록하세요. PDF 폴더는 프로젝트마다 따로 저장됩니다.

### 한 줄 설치 (추천)

```bash
cd /path/to/your-project
curl -fsSL https://raw.githubusercontent.com/MasterTyping/DOCP/main/install.sh | sh
```

`<프로젝트>/rag`를 PDF 폴더로 만들어 `local` 등록합니다. 다른 폴더를 쓰려면 `sh -s -- claude 폴더경로`처럼 두 번째 인자로 넘깁니다. Claude Code에는 `.claude/agents/doc-skimmer.md` 서브에이전트도 함께 추가합니다(이미 있으면 유지). 새로 만든 `rag/`는 git에서 제외하고, 이미 있던 폴더는 그대로 둡니다. 이미 등록되어 있으면 아무것도 바꾸지 않습니다. 완료 후 Claude Code를 다시 시작하세요.

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

`uv` 없이 쓰려면 저장소를 클론한 뒤 `setup.sh`를 실행하세요. Python 3.11 이상이 필요하고, 완료되면 이 PC의 경로가 반영된 등록 명령을 출력합니다.

```bash
git clone https://github.com/MasterTyping/DOCP
cd DOCP
./src/setup.sh
```

특정 Python을 쓰려면 `PYTHON=python3.12 ./src/setup.sh`로 실행합니다. 클론한 폴더를 옮기면 `.venv`를 지우고 다시 실행한 뒤 재등록해야 합니다.

### 확인, 경로 변경, 제거

```bash
claude mcp get pdf-rag
claude mcp remove pdf-rag --scope local   # 제거 후 다시 등록하면 PDF 폴더가 바뀝니다
```

Claude Code 안에서는 `/mcp`로 연결 상태를 볼 수 있습니다.

## 사용하기

PDF나 `.md` 파일을 등록한 폴더에 넣고 Claude Code에 요청하면 됩니다. `file_path`에는 `문서.pdf` 같은 상대 경로를 쓰고, 절대 경로는 등록한 폴더 안일 때만 열립니다. `.md`는 UTF-8 파일만 읽으며, 100줄을 한 페이지로 계산하고 제목(`#`)을 목차로 반환합니다.

```text
문서.pdf의 목차를 보여주고 "인증"이 나오는 부분을 찾아 페이지 번호와 함께 요약해줘
```

### 폴더별로 참조 범위 정하기

`rag` 아래에 주제별 폴더를 만들고 요청에 폴더 이름을 적으면 그 폴더의 문서만 검색합니다. 하위 폴더도 함께 포함됩니다.

```text
rag/
├── 법규/
└── 매뉴얼/
```

```text
법규 폴더 문서만 참고해서 "안전 기준"을 찾아 파일명과 페이지와 함께 요약해줘
```

### `@` 자동완성

Claude Code 프롬프트에 `@`와 파일명 일부를 입력하면 등록한 폴더의 PDF와 `.md`가 목록에 나타납니다. 선택하면 본문 전체가 아니라 목차와 페이지 수만 첨부되고, 내용은 검색·읽기 도구로 필요한 부분만 가져옵니다. 파일을 새로 넣은 뒤에는 `/mcp`에서 `pdf-rag`를 다시 연결하세요.

### 대용량 문서의 핵심만 읽기

```text
매뉴얼.pdf 핵심만 훑어서 정리해줘
매뉴얼.pdf에서 "비상 정지" 관련 부분만 요약해줘
```

`skim_document`가 전체 페이지 대신 목차별 첫 부분이나 질문과 관련된 페이지만 정해진 글자 수 안에서 돌려줍니다. 자세한 내용은 그다음에 `read_pdf_pages`로 필요한 페이지만 읽습니다.

### 가벼운 작업은 저렴한 모델로 (토큰 절약)

Claude Code에서는 설치 시 추가되는 `doc-skimmer` 서브에이전트가 Haiku 모델로 문서를 읽고 요약합니다. 많은 페이지를 읽는 일은 서브에이전트가 맡고, 메인 대화에는 짧은 요약과 `파일:페이지` 출처만 돌아오므로 메인 모델의 토큰이 크게 줄어듭니다. 서버가 이 위임을 안내하며, 직접 지정할 수도 있습니다.

```text
doc-skimmer로 법규 폴더 문서들을 요약해줘
```

모델을 바꾸려면 `.claude/agents/doc-skimmer.md`의 `model:` 값을 수정하세요. 다른 AI 도구에는 서브에이전트가 설치되지 않습니다.

### 결과 내보내기 (md · HTML · PDF · Word · PPT · Notion)

원하는 형식을 말로 요청하면 해당 형식으로 저장합니다.

```text
방금 요약을 PPT로 만들어줘
검색 결과를 워드 파일로 저장해줘
보고서를 PDF랑 HTML로 뽑아줘
이 내용을 노션 페이지로 올려줘
```

- 파일은 프로젝트의 `exports/` 폴더에 저장됩니다. 다른 위치를 쓰려면 등록할 때 `-e PDF_RAG_OUT=/경로`를 추가하세요.
- 같은 이름이 있으면 `이름-1.pptx`처럼 새 이름으로 저장하고, 기존 파일은 덮어쓰지 않습니다.
- PPT는 `#`, `##` 제목마다 슬라이드를 하나씩 만듭니다. Word와 PPT에서 굵게·링크 같은 인라인 서식은 일반 텍스트가 됩니다.
- Notion은 이 서버가 아니라 Claude Code에 연결된 Notion MCP가 페이지를 만듭니다. 요청하면 먼저 내용을 `exports/`에 md로 백업합니다. Notion이 연결되어 있지 않거나 로그인이 풀려 있으면 작업을 멈추고 로그인을 요청합니다. 로그인 후 "로그인했어"라고 말하면 백업한 내용으로 이어서 페이지를 만듭니다.

  ```bash
  claude mcp add --transport http notion https://mcp.notion.com/mcp   # 연결 (한 번만)
  ```
  Claude Code에서 `/mcp` → `notion` → Authenticate를 눌러 브라우저에서 로그인합니다.

## 업데이트

설치한 프로젝트 폴더에서 **설치 명령을 그대로 다시 실행**한 뒤 해당 도구를 재시작하세요. 최신 버전을 받고, 기존 PDF 폴더와 등록 설정은 유지합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/MasterTyping/DOCP/main/install.sh | sh              # Claude Code
curl -fsSL https://raw.githubusercontent.com/MasterTyping/DOCP/main/install.sh | sh -s -- cursor # 다른 도구
```

클론해서 로컬 `.venv`로 쓰는 경우에는 저장소에서 `git pull` 후 `./setup.sh`를 실행하세요.

## 제한 사항

- 스캔본처럼 텍스트 레이어가 없는 PDF는 OCR을 하지 않습니다. `get_pdf_info`가 `warning`으로 알려줍니다.
- 비밀번호로 보호된 PDF는 오류를 반환합니다.
- 검색과 `skim_document`는 의미 검색이 아니라 키워드·구조 기반입니다. 진짜 요약은 이 결과를 읽은 모델(또는 `doc-skimmer`)이 만듭니다.
