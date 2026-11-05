#!/bin/sh
# 找得到可用的 python3 才執行 hook 腳本，否則安靜跳過，不擋使用者的訊息。
# macOS 沒裝 Command Line Tools 時，/usr/bin/python3 只是一個會跳出安裝視窗的殼，
# 每則訊息都觸發一次會很擾人，所以先用 xcode-select 確認（它不會跳視窗）。
PY=$(command -v python3 2>/dev/null) || exit 0
if [ "$PY" = /usr/bin/python3 ] && [ "$(uname)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then
  exit 0
fi
exec "$PY" "$@"
