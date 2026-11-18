#!/usr/bin/env bash
# CMD of the ray-cluster inference variant, run on every node after the
# entrypoint (/opt/runpod/ray/entrypoint) has started Ray.
#
#   - Worker: nothing beyond Ray; vLLM runs from the head.
#   - Head: wait until NUM_NODES nodes have joined Ray, then `vllm serve
#     $MODEL_REPO` across the whole cluster: tensor parallelism is the GPUs per
#     node, pipeline parallelism the node count. vLLM listens on
#     127.0.0.1:8000 only; the API on 4000 (LiteLLM's default) is LiteLLM's
#     proxy in front of it,
#     which checks the key.
#   - No NODE_RANK (a plain pod): the same on this pod's GPUs, without Ray.
#
# Every path ends in /start.sh (SSH, Jupyter on the head, the dashboard front
# door, monitoring), and vLLM and LiteLLM run beside it, so the pod stays up
# for interactive use when they are not started or exit.
#
# Never `set -x` here: the API key is in the environment.
set -uo pipefail

readonly INFERENCE_DIR=/opt/runpod/inference
readonly LITELLM=/opt/litellm/bin/litellm
readonly LITELLM_DIR=/etc/litellm
readonly VLLM_PORT=8000
readonly API_PORT=4000

log() { echo "[ray-inference] $*"; }
services() { exec /start.sh; }

if [[ -n "${NODE_RANK:-}" && "$NODE_RANK" != 0 ]]; then
    log "worker node: Ray only; vLLM runs from the head"
    services
fi

# Not set is a choice (an interactive pod), not a failure, so it's worded like
# start.sh's "JUPYTER_PASSWORD is not set; skipping JupyterLab".
if [[ -z "${MODEL_REPO:-}" ]]; then
    log "MODEL_REPO is not set; skipping vLLM. To serve a model, set it to a Hugging Face model, such as Qwen/Qwen3-235B-A22B, and restart the pod. The pod stays up for interactive use."
    services
fi

# --- Authentication --------------------------------------------------------- #
# LiteLLM's master key is LITELLM_MASTER_KEY (LiteLLM's own variable), else the
# head's JUPYTER_PASSWORD (the console's password for the pod), used verbatim
# so it matches Jupyter's. With neither, nothing is started. Pasted whitespace
# around LITELLM_MASTER_KEY is trimmed. LiteLLM checks it on every route but
# its health checks, /metrics included; vLLM behind it takes no key, being
# reachable only from this pod. The key also goes, root-only, to
# $LITELLM_DIR/master_key, which the head's Prometheus sends when it scrapes
# LiteLLM (post_start.sh).
key=${LITELLM_MASTER_KEY:-}
key="${key#"${key%%[![:space:]]*}"}"
key="${key%"${key##*[![:space:]]}"}"
if [[ -n "$key" ]]; then
    key_source=LITELLM_MASTER_KEY
elif [[ -n "${JUPYTER_PASSWORD:-}" ]]; then
    key=$JUPYTER_PASSWORD
    key_source=JUPYTER_PASSWORD
else
    log "error: neither LITELLM_MASTER_KEY nor JUPYTER_PASSWORD is set, so vLLM was not started. Set LITELLM_MASTER_KEY, or LITELLM_MASTER_KEY=none to serve without authentication, and restart the pod."
    services
fi
mkdir -p "$LITELLM_DIR" && chmod 700 "$LITELLM_DIR"
litellm_env=(DISABLE_ADMIN_UI=True LITELLM_LOCAL_MODEL_COST_MAP=True)
if [[ "$key_source" == LITELLM_MASTER_KEY && "${key,,}" == none ]]; then
    unset LITELLM_MASTER_KEY
    key=none
    # LiteLLM refuses to start without a master key unless told to.
    litellm_env+=(LITELLM_DANGEROUSLY_PERMIT_WEAK_OR_UNSET_MASTER_KEY=true)
    log "warn: LITELLM_MASTER_KEY=none: the API on $API_PORT answers every request without authentication"
else
    export LITELLM_MASTER_KEY=$key
    log "authentication on (key from $key_source): every route on $API_PORT except LiteLLM's health checks needs 'Authorization: Bearer <key>'"
fi
(
    umask 077
    printf '%s' "$key" > "$LITELLM_DIR/master_key"
)
# vLLM reads VLLM_API_KEY itself, and LiteLLM sends it none.
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

# --- vLLM --------------------------------------------------------------------- #
model_args=()
[[ -n "${MAX_MODEL_LENGTH:-}" ]] && model_args+=(--max-model-len "$MAX_MODEL_LENGTH")

read -ra extra_args <<< "${VLLM_EXTRA_ARGS:-}"
for arg in "${extra_args[@]}"; do
    case "$arg" in
        --api-key | --api-key=*)
            log "error: VLLM_EXTRA_ARGS sets --api-key, which LiteLLM can't send, and vLLM prints its arguments at startup, so that key is now in the pod logs. Remove it (LiteLLM checks LITELLM_MASTER_KEY on $API_PORT) and restart the pod. vLLM was not started."
            services
            ;;
        *) ;;
    esac
done

# VLLM_EXTRA_ARGS follows the derived settings so it can override them; the
# listen address is last, so vLLM stays reachable only from this pod.
cmd=(vllm serve "$MODEL_REPO" "${parallel_args[@]}" "${model_args[@]}" "${extra_args[@]}"
    --host 127.0.0.1 --port "$VLLM_PORT")
log "starting vLLM on 127.0.0.1:$VLLM_PORT: ${cmd[*]}"
(
    env -u LITELLM_MASTER_KEY "${cmd[@]}"
    log "vLLM exited with status $?; the pod stays up. Restart the pod to serve again."
) &
vllm_job=$!

# --- LiteLLM ------------------------------------------------------------------ #
# One model, MODEL_REPO, under its own name, so clients use the same model id
# as with vLLM directly. Written as JSON (valid YAML), so no model name can
# break the config. LiteLLM starts only once vLLM answers /health, so while the
# model loads nothing listens on the API port (the Runpod proxy answers 502)
# instead of LiteLLM failing every request with a 500 and a logged traceback.
# If vLLM exits first, LiteLLM is not started. Prometheus metrics on /metrics.
# No admin UI (it needs a database this pod doesn't have) and no fetch of the
# model price map. Without a database, a key other than the master key gets
# LiteLLM's 400 "No connected db." rather than a 401: still refused. LiteLLM
# also refuses to start on a publicly known master key, such as sk-1234.
if ! python3 - "$MODEL_REPO" "$VLLM_PORT" > "$LITELLM_DIR/config.json" << 'EOF'
import json, sys

model, vllm_port = sys.argv[1:]
print(json.dumps({
    "model_list": [{
        "model_name": model,
        "litellm_params": {
            "model": f"hosted_vllm/{model}",
            "api_base": f"http://127.0.0.1:{vllm_port}/v1",
            "api_key": "unused",
        },
    }],
    "litellm_settings": {
        "callbacks": ["prometheus"],
        # A rejected key is recorded as-is in this label, so a mistyped key
        # would sit in plain text in Prometheus and Grafana.
        "prometheus_exclude_labels": ["hashed_api_key"],
    },
}, indent=2))
EOF
then
    log "error: could not write $LITELLM_DIR/config.json (see above), so LiteLLM was not started"
    services
fi
log "LiteLLM will start on $API_PORT for $MODEL_REPO once vLLM has loaded the model"
(
    until curl -sf -o /dev/null "http://127.0.0.1:$VLLM_PORT/health"; do
        if ! kill -0 "$vllm_job" 2> /dev/null; then
            log "vLLM exited before it was ready, so LiteLLM was not started"
            exit 0
        fi
        sleep 5
    done
    log "vLLM is ready; starting LiteLLM on $API_PORT"
    env "${litellm_env[@]}" "$LITELLM" --config "$LITELLM_DIR/config.json" --host 0.0.0.0 --port "$API_PORT"
    log "LiteLLM exited with status $?; the pod stays up. Restart the pod to serve again."
) &

services
