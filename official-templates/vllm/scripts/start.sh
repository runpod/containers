#!/bin/bash
# Never `set -x` here: VLLM_API_KEY is in the environment.
set -euo pipefail

AUTH_MODULE_DIR="/opt/runpod/vllm"
AUTH_MIDDLEWARE="runpod_vllm_auth.BearerAuth"
LISTEN_HOST="0.0.0.0"
LISTEN_PORT="8000"

# Stay up instead of exiting, so Runpod doesn't restart into the same refusal.
hold_without_vllm() {
    local pid=""
    trap 'kill "$pid" 2>/dev/null; exit 0' SIGTERM SIGINT
    while true; do
        sleep 86400 &
        pid=$!
        wait "$pid" || true
    done
}

# Trim pasted whitespace; vLLM's own /v1 check reads the exported value too.
key="${VLLM_API_KEY:-}"
key="${key#"${key%%[![:space:]]*}"}"
key="${key%"${key##*[![:space:]]}"}"

# vLLM logs its CLI args at startup.
for arg in "$@"; do
    case "$arg" in
        --api-key | --api-key=*)
            echo "WARNING: --api-key is set in the container command. vLLM prints its"
            echo "WARNING: arguments at startup, so that key is now in the Pod logs."
            echo "WARNING: Remove it and set the VLLM_API_KEY environment variable instead."
            ;;
    esac
done

# A set key wins over VLLM_DISABLE_AUTH.
if [ -n "$key" ]; then
    export VLLM_API_KEY="$key"
    if [ "${VLLM_DISABLE_AUTH:-}" = "true" ]; then
        echo "VLLM_DISABLE_AUTH=true is ignored because VLLM_API_KEY is set."
    fi
    echo "Authentication on: every route except /health, /ping and /metrics"
    echo "requires the header 'Authorization: Bearer <VLLM_API_KEY>'."
    export PYTHONPATH="${AUTH_MODULE_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
    AUTH_ARGS=(--middleware "$AUTH_MIDDLEWARE")
elif [ "${VLLM_DISABLE_AUTH:-}" = "true" ]; then
    unset VLLM_API_KEY
    echo "WARNING: VLLM_DISABLE_AUTH=true -- starting vLLM with NO authentication."
    echo "WARNING: anyone with this Pod's :${LISTEN_PORT} proxy URL can run the model"
    echo "WARNING: on your GPU, and reach every route vLLM serves."
    AUTH_ARGS=()
else
    echo "============================================================"
    echo "  vLLM was NOT started: VLLM_API_KEY is not set."
    echo ""
    echo "  This image requires a key on every route of :${LISTEN_PORT}."
    echo "  Redeploy the Pod with one of these environment variables:"
    echo "    VLLM_API_KEY=<a long random secret>   (recommended)"
    echo "    VLLM_DISABLE_AUTH=true                (no authentication;"
    echo "                                           anyone with the URL can use it)"
    echo "============================================================"
    hold_without_vllm
    exit 0
fi

echo "Starting vLLM on ${LISTEN_HOST}:${LISTEN_PORT}"
# Last, so they override any --host/--port in CMD.
exec vllm serve "$@" ${AUTH_ARGS[@]+"${AUTH_ARGS[@]}"} --host "$LISTEN_HOST" --port "$LISTEN_PORT"
