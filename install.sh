#!/bin/sh
# Install or update pdf-rag in the current project. Re-run the same command to update:
#   curl -fsSL https://raw.githubusercontent.com/MasterTyping/DOCP/main/install.sh | sh -s -- [claude|cursor|vscode|gemini|codex]
set -eu

SOURCE=git+https://github.com/MasterTyping/DOCP

# Wrapped in main so a truncated download cannot run half a script.
main() {
    client="${1:-claude}"
    case "$client" in
        claude | cursor | vscode | gemini | codex) ;;
        *)
            echo "오류: 지원하지 않는 클라이언트입니다: $client (claude, cursor, vscode, gemini, codex)" >&2
            exit 1
            ;;
    esac

    registered=""
    if [ "$client" = claude ]; then
        command -v claude >/dev/null || {
            echo "오류: Claude Code(claude)를 찾을 수 없습니다. 먼저 설치하세요: https://code.claude.com" >&2
            exit 1
        }
        if claude mcp get pdf-rag >/dev/null 2>&1 </dev/null; then
            registered=1
        fi
    fi

    if ! command -v uvx >/dev/null; then
        command -v curl >/dev/null || {
            echo "오류: uv 설치에 curl이 필요합니다." >&2
            exit 1
        }
        echo "uv를 설치합니다..."
        curl -fsSL https://astral.sh/uv/install.sh | sh
        PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        command -v uvx >/dev/null || {
            echo "오류: uv 설치 후에도 uvx를 찾을 수 없습니다." >&2
            exit 1
        }
    fi

    # Fetch first, so a failed download changes no registration. The server exits on stdin EOF.
    echo "최신 버전을 받는 중입니다..."
    uvx -q --refresh --from "$SOURCE" pdf-rag-server </dev/null >/dev/null || {
        echo "오류: 최신 버전을 받지 못했습니다. 기존 등록은 변경하지 않았습니다." >&2
        exit 1
    }

    if [ "$client" != claude ]; then
        uvx -q --from "$SOURCE" pdf-rag-add "$client" "$PWD/rag" </dev/null
    elif [ -z "$registered" ]; then
        folder="$PWD/rag"
        # PDFs can be private, so ignore them, but never hide files in a rag/ folder the project already had.
        if [ ! -e "$folder" ]; then
            mkdir -p "$folder"
            printf '*\n' >"$folder/.gitignore"
        fi
        # Absolute uvx path: Claude Code may start without the PATH a fresh uv install just added.
        claude mcp add pdf-rag --transport stdio --scope local -e "PDF_RAG_DIR=$folder" -- \
            "$(command -v uvx)" --from "$SOURCE" pdf-rag-server </dev/null
        echo "claude: 등록 완료. PDF 폴더: $folder"
    elif claude mcp get pdf-rag </dev/null 2>/dev/null | grep -Fq "$SOURCE"; then
        echo "claude: 업데이트 완료. 기존 PDF 폴더와 설정은 유지합니다."
    else
        echo "claude: 이 프로젝트는 GitHub 설치본이 아닌 서버로 등록되어 있어 자동 업데이트되지 않습니다."
        echo "클론해서 쓰는 경우 해당 폴더에서 git pull 후 ./setup.sh 를 실행하세요."
    fi

    echo
    echo "$client 를 다시 시작하면 적용됩니다."
}

main "$@"
