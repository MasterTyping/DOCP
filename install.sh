#!/bin/sh
# Register pdf-rag in the current project:
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

    if [ "$client" = claude ]; then
        command -v claude >/dev/null || {
            echo "오류: Claude Code(claude)를 찾을 수 없습니다. 먼저 설치하세요: https://code.claude.com" >&2
            exit 1
        }
        if claude mcp get pdf-rag >/dev/null 2>&1 </dev/null; then
            echo "pdf-rag가 이 프로젝트에 이미 등록되어 있습니다. 확인: claude mcp get pdf-rag"
            exit 0
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

    folder="$PWD/rag"
    # PDFs can be private, so ignore them, but never hide files in a rag/ folder the project already had.
    if [ ! -e "$folder" ]; then
        mkdir -p "$folder"
        printf '*\n' >"$folder/.gitignore"
    fi

    if [ "$client" = claude ]; then
        # Absolute uvx path: Claude Code may start without the PATH a fresh uv install just added.
        claude mcp add pdf-rag --transport stdio --scope local -e "PDF_RAG_DIR=$folder" -- \
            "$(command -v uvx)" --from "$SOURCE" pdf-rag-server </dev/null
    else
        uvx --from "$SOURCE" pdf-rag-add "$client" "$folder" </dev/null
    fi

    echo
    echo "PDF를 $folder 에 넣고 $client 를 다시 시작하세요."
}

main "$@"
