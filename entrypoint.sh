#!/bin/sh
# Run the claimer, optionally on a virtual display, and let it exit on success.
#
#   HEADLESS=true  (default) -> plain headless Chrome
#   HEADLESS=false           -> Xvfb + headed Chrome, which looks much more like
#                               a normal browser to Cloudflare.
#
# The process (and therefore the container) ends as soon as buzz.py exits:
# exit 0 = claimed / already claimed today, non-zero = see README exit codes.
set -e

if [ -z "${CIVITAI_COOKIE:-}" ]; then
    echo "[entrypoint] CIVITAI_COOKIE is not set." >&2
    echo "[entrypoint] Usage: docker run --rm -e CIVITAI_COOKIE='a=b; c=d' -e USER_AGENT='...' civitai-buzz" >&2
    exit 2
fi

echo "[entrypoint] user=$(id -un) headless=${HEADLESS:-true} display=${DISPLAY:-<unset>}"

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

# RUN_TIMEOUT is the hard stop so a stuck browser can never keep the container
# alive forever; a normal run finishes in well under a minute.
echo "[entrypoint] launching: python3 buzz.py $*"
if command -v timeout >/dev/null 2>&1; then
    exec timeout "${RUN_TIMEOUT:-900}" python3 buzz.py "$@"
fi
exec python3 buzz.py "$@"
