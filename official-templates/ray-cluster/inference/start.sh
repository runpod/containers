#!/usr/bin/env bash
# CMD of the ray-cluster inference variant, run on every node after the
# entrypoint (/opt/runpod/ray/entrypoint) has started Ray.
#
#   - Worker: nothing beyond Ray; vLLM runs from the head.
#   - Head: wait until NUM_NODES nodes have joined Ray, then `vllm serve
#     $MODEL_REPO` on 8000 across the whole cluster: tensor parallelism is the
#     GPUs per node, pipeline parallelism the node count.
#   - No NODE_RANK (a plain pod): `vllm serve` on this pod's GPUs, without Ray.
#
# Every path ends in /start.sh (SSH, Jupyter on the head, the dashboard front
# door, monitoring), and vLLM runs beside it, so the pod stays up for
# interactive use when vLLM is not started or exits.
#
# Never `set -x` here: the vLLM key is in the environment.
set -uo pipefail

readonly INFERENCE_DIR=/opt/runpod/inference
readonly AUTH_MIDDLEWARE=runpod_vllm_auth.BearerAuth
readonly VLLM_PORT=8000

log() { echo "[ray-inference] $*"; }
services() { exec /start.sh; }

if [[ -n "${NODE_RANK:-}" && "$NODE_RANK" != 0 ]]; then
    log "worker node: Ray only; vLLM runs from the head"
    services
fi

if [[ -z "${MODEL_REPO:-}" ]]; then
    log "error: MODEL_REPO is not set, so vLLM was not started. Set it to a Hugging Face model, such as Qwen/Qwen3-235B-A22B, and restart the pod. The pod stays up for interactive use."
    services
fi

# --- Authentication --------------------------------------------------------- #
# The middleware requires the key on every route except /health, /ping and
# /metrics; vLLM's own --api-key would leave routes such as /invocations open.
# The key is VLLM_API_KEY (vLLM's own variable), else the head's
# JUPYTER_PASSWORD (the console's password for the pod), used verbatim so it
# matches Jupyter's. With neither, vLLM is not started. The middleware and
# vLLM's own /v1 check both read the key back from VLLM_API_KEY, exported below.
# Pasted whitespace around VLLM_API_KEY is trimmed.
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
auth_args=()
if [[ "$key_source" == VLLM_API_KEY && "${key,,}" == none ]]; then
    # Unset, or vLLM's own /v1 check would require the literal "none".
    unset VLLM_API_KEY
    log "warn: VLLM_API_KEY=none: vLLM on $VLLM_PORT answers every request without authentication"
else
    export VLLM_API_KEY=$key
    export PYTHONPATH="$INFERENCE_DIR${PYTHONPATH:+:$PYTHONPATH}"
    auth_args=(--middleware "$AUTH_MIDDLEWARE")
    log "authentication on (key from $key_source): every route except /health, /ping and /metrics needs 'Authorization: Bearer <key>'"
fi

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
            log "warn: VLLM_EXTRA_ARGS sets --api-key, and vLLM prints its arguments at startup, so that key is now in the pod logs. Set VLLM_API_KEY instead."
            ;;
        *) ;;
    esac
done

# VLLM_EXTRA_ARGS follows the derived settings so it can override them; the
# listen address is last, so the documented port holds.
cmd=(vllm serve "$MODEL_REPO" "${parallel_args[@]}" "${model_args[@]}" "${extra_args[@]}"
    "${auth_args[@]}" --host 0.0.0.0 --port "$VLLM_PORT")
log "starting vLLM on $VLLM_PORT: ${cmd[*]}"
(
    "${cmd[@]}"
    log "vLLM exited with status $?; the pod stays up. Restart the pod to serve again."
) &

services
