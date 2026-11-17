#!/usr/bin/env bash
# CMD of the ray-cluster inference variant, run on every node after the
# entrypoint (/opt/runpod/ray/entrypoint) has started Ray.
#
#   - Worker: nothing beyond Ray; vLLM runs from the head.
#   - Head: wait until NUM_NODES nodes have joined Ray, then `vllm serve
#     $MODEL_REPO` across the whole cluster: tensor parallelism is the GPUs per
#     node, pipeline parallelism the node count. vLLM listens on
#     127.0.0.1:8000; nginx's front door on 8001 checks the key
#     (/etc/nginx/vllm-api.conf).
#   - No NODE_RANK (a plain pod): `vllm serve` on this pod's GPUs, without Ray.
#
# Every path ends in /start.sh (SSH, Jupyter on the head, the dashboard front
# door, monitoring), and vLLM runs beside it, so the pod stays up for
# interactive use when vLLM is not started or exits.
#
# Never `set -x` here: the vLLM key is in the environment.
set -uo pipefail

readonly INFERENCE_DIR=/opt/runpod/inference
readonly VLLM_PORT=8000
readonly FRONT_PORT=8001
readonly KEY_MAP=/etc/nginx/vllm-api-key.map

log() { echo "[ray-inference] $*"; }
services() { exec /start.sh; }

# Reloads nginx if it is running already; otherwise /start.sh starts it with
# the current map. A reload missed in a race leaves the shipped map in force,
# which accepts nothing, so serve() reloads once more before starting vLLM.
reload_nginx() {
    [[ -s /run/nginx.pid ]] && nginx -s reload 2> /dev/null
    return 0
}

if [[ -n "${NODE_RANK:-}" && "$NODE_RANK" != 0 ]]; then
    log "worker node: Ray only; vLLM runs from the head"
    services
fi

if [[ -z "${MODEL_REPO:-}" ]]; then
    log "error: MODEL_REPO is not set, so vLLM was not started. Set it to a Hugging Face model, such as Qwen/Qwen3-235B-A22B, and restart the pod. The pod stays up for interactive use."
    services
fi

# --- Authentication --------------------------------------------------------- #
# The key is VLLM_API_KEY (vLLM's own variable), else the head's
# JUPYTER_PASSWORD (the console's password for the pod), used verbatim so it
# matches Jupyter's. With neither, vLLM is not started. Pasted whitespace
# around VLLM_API_KEY is trimmed. nginx checks it on 8001 (vllm-api.conf); vLLM
# itself runs without one, reachable only from this pod.
key=${VLLM_API_KEY:-}
key="${key#"${key%%[![:space:]]*}"}"
key="${key%"${key##*[![:space:]]}"}"
if [[ -n "$key" ]]; then
    key_source=VLLM_API_KEY
elif [[ -n "${JUPYTER_PASSWORD:-}" ]]; then
    key=$JUPYTER_PASSWORD
    key_source=JUPYTER_PASSWORD
else
    log "error: neither VLLM_API_KEY nor JUPYTER_PASSWORD is set, so vLLM was not started. Set VLLM_API_KEY, or VLLM_API_KEY=none to serve without authentication, and restart the pod."
    services
fi
# A header can't carry control characters, so such a key could never match.
if [[ "$key" == *[[:cntrl:]]* ]]; then
    log "error: the key in $key_source contains control characters, so vLLM was not started"
    services
fi
if [[ "$key_source" == VLLM_API_KEY && "${key,,}" == none ]]; then
    map_entries='default 1;'
    log "warn: VLLM_API_KEY=none: the API on $FRONT_PORT answers every request without authentication"
else
    # An nginx quoted string: only \ and " need escaping; map keys are
    # literal, so a $ in the key is not a variable.
    escaped=${key//\\/\\\\}
    escaped=${escaped//\"/\\\"}
    map_entries=$(printf 'default 0;\n"Bearer %s" 1;' "$escaped")
    log "authentication on (key from $key_source): every route on $FRONT_PORT except /health and /ping needs 'Authorization: Bearer <key>'"
fi
# Root-only, written whole, then swapped in: nginx never reads half a map.
(
    umask 077
    printf '%s\n' "$map_entries" > "$KEY_MAP.tmp"
) && mv "$KEY_MAP.tmp" "$KEY_MAP"
reload_nginx
# vLLM reads VLLM_API_KEY itself; nginx has already checked the key.
unset VLLM_API_KEY

# --- Shape -------------------------------------------------------------------- #
parallel_args=()
if [[ -n "${NODE_RANK:-}" ]]; then
    nodes=${NUM_NODES:-1}
    if ! [[ "$nodes" =~ ^[0-9]{1,4}$ ]] || ((10#$nodes < 1)); then
        log "error: NUM_NODES '$nodes' is not a node count, so vLLM was not started"
        services
    fi
    nodes=$((10#$nodes))
    gpus=$(python3 "$INFERENCE_DIR/wait_for_nodes.py" "$nodes")
    case $? in
        0) ;;
        2)
            log "error: the cluster can't be split into $nodes pipeline stages, so vLLM was not started"
            services
            ;;
        *)
            log "error: could not read the cluster's nodes from Ray (see above and /tmp/ray/session_latest/logs), so vLLM was not started"
            services
            ;;
    esac
    parallel_args=(--distributed-executor-backend ray --pipeline-parallel-size "$nodes")
else
    gpus=$(nvidia-smi -L 2> /dev/null | grep -c '^GPU ') || gpus=0
    if ((gpus == 0)); then
        log "error: no GPU visible, so vLLM was not started"
        services
    fi
fi
parallel_args+=(--tensor-parallel-size "$gpus")

# --- Serve ---------------------------------------------------------------------- #
model_args=()
[[ -n "${MAX_MODEL_LENGTH:-}" ]] && model_args+=(--max-model-len "$MAX_MODEL_LENGTH")

read -ra extra_args <<< "${VLLM_EXTRA_ARGS:-}"
for arg in "${extra_args[@]}"; do
    case "$arg" in
        --api-key | --api-key=*)
            log "warn: VLLM_EXTRA_ARGS sets --api-key, and vLLM prints its arguments at startup, so that key is now in the pod logs. Set VLLM_API_KEY instead; nginx checks it on $FRONT_PORT."
            ;;
        *) ;;
    esac
done

# VLLM_EXTRA_ARGS follows the derived settings so it can override them; the
# listen address is last, so vLLM stays behind the front door.
cmd=(vllm serve "$MODEL_REPO" "${parallel_args[@]}" "${model_args[@]}" "${extra_args[@]}"
    --host 127.0.0.1 --port "$VLLM_PORT")
reload_nginx
log "starting vLLM on 127.0.0.1:$VLLM_PORT, served on $FRONT_PORT: ${cmd[*]}"
(
    "${cmd[@]}"
    log "vLLM exited with status $?; the pod stays up. Restart the pod to serve again."
) &

services
