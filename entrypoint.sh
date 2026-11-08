#!/bin/sh
# Run the claimer, optionally on a virtual display.
#
#   HEADLESS=true  (default) -> plain headless Chrome
#   HEADLESS=false           -> Xvfb + headed Chrome, which looks much more like
#                               a normal browser to Cloudflare and to the
#                               page's own client-side feature checks.
set -e

if [ "${HEADLESS:-true}" = "false" ] || [ "${HEADLESS:-true}" = "0" ]; then
    if [ -z "${DISPLAY:-}" ]; then
        exec xvfb-run -a --server-args="-screen 0 1440x900x24" python3 buzz.py "$@"
    fi
fi

exec python3 buzz.py "$@"
