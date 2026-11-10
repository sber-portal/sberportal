#!/bin/bash
# Linux: ./run-linux.sh [аргументы]
cd "$(dirname "$0")" || exit 1
exec python3 portal_installer.py "$@"
