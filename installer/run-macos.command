#!/bin/bash
# macOS: двойной клик в Finder или запуск из Терминала.
cd "$(dirname "$0")" || exit 1
exec python3 portal_installer.py "$@"
