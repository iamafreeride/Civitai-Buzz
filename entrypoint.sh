#!/bin/sh
# Run the claimer, optionally on a virtual display.
#
#   HEADLESS=true  (default) -> plain headless Chrome
#   HEADLESS=false           -> Xvfb + headed Chrome, which looks much more like
#                               a normal browser to Cloudflare and to the
#                               page's own client-side feature checks.
#
# Started manually instead of via xvfb-run: xvfb-run wraps the whole process and
# gives no output when it fails, which looks exactly like a hang.
set -e

echo "[entrypoint] HEADLESS=${HEADLESS:-true} DISPLAY=${DISPLAY:-<unset>} USER=$(id -un)"

if [ "${HEADLESS:-true}" = "false" ] || [ "${HEADLESS:-true}" = "0" ]; then
    if [ -z "${DISPLAY:-}" ]; then
        DISPLAY_NUM="${XVFB_DISPLAY:-99}"
        echo "[entrypoint] starting Xvfb on :${DISPLAY_NUM}"
        Xvfb ":${DISPLAY_NUM}" -screen 0 1440x900x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
        sleep 2
        export DISPLAY=":${DISPLAY_NUM}"
        echo "[entrypoint] DISPLAY=${DISPLAY} (xvfb log: /tmp/xvfb.log)"
    fi
    export HEADLESS=false
fi

echo "[entrypoint] launching: python3 buzz.py $*"
if command -v timeout >/dev/null 2>&1; then
    exec timeout "${RUN_TIMEOUT:-1200}" python3 buzz.py "$@"
fi
exec python3 buzz.py "$@"
