#!/bin/bash
set -e  # Exit the script if any statement returns a non-true return value

COMFYUI_DIR="/workspace/runpod-slim/ComfyUI"
BAKED_COMFYUI_DIR="/opt/comfyui-baked"
BUNDLE_VERSION_FILE=".runpod-bundle-version"
VENV_NAME="${COMFYUI_VENV_NAME:-.venv-cu128}"
VENV_DIR="$COMFYUI_DIR/$VENV_NAME"
OLD_VENV_DIR="$COMFYUI_DIR/.venv"
DB_FILE="/workspace/runpod-slim/filebrowser.db"
PIP_CONSTRAINT_FILE="/opt/comfyui-runtime-constraints.txt"
BAKED_NODES=("ComfyUI-Manager" "ComfyUI-KJNodes" "Civicomfy" "ComfyUI-RunpodDirect")
# 8188 is the port the template exposes. The password proxy owns it, and
# ComfyUI listens on loopback only, on the internal port.
COMFYUI_PUBLIC_PORT=8188
COMFYUI_INTERNAL_PORT=18188
AUTH_PROXY="/opt/comfyui-auth-proxy/auth_proxy.py"
# The image's interpreter, not the venv on the volume: a package installed
# there must not be able to change the proxy.
SYSTEM_PYTHON="/usr/bin/python3.12"
AUTH_PROXY_RESTART_DELAY=5
AUTH_PROXY_MAX_FAST_FAILURES=5
AUTH_PROXY_FAST_FAILURE_SECONDS=30
# Same floor as FileBrowser's: the :8188 URL is public and guessable.
COMFYUI_PASSWORD_MIN_LENGTH=12

# ---------------------------------------------------------------------------- #
#                          Function Definitions                                  #
# ---------------------------------------------------------------------------- #

# Setup SSH; login is by key only
setup_ssh() {
    mkdir -p ~/.ssh

    if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
        ssh-keygen -A -q
    fi

    # If PUBLIC_KEY is provided, use it
    if [[ $PUBLIC_KEY ]]; then
        echo "$PUBLIC_KEY" >> ~/.ssh/authorized_keys
        chmod 700 -R ~/.ssh
        if ! printf '%s\n' "$PUBLIC_KEY" | ssh-keygen -lf - > /dev/null 2>&1; then
            echo "WARNING: PUBLIC_KEY is not a valid SSH public key, so sshd will"
            echo "ignore it and direct SSH to port 22 will be refused. It must be"
            echo "the contents of your .pub file, one line, e.g. ssh-ed25519 AAAA..."
        fi
    else
        echo "PUBLIC_KEY is not set, so no key is authorized here and direct SSH"
        echo "to port 22 is refused. Connecting through ssh.runpod.io is"
        echo "unaffected. For port 22, set PUBLIC_KEY and restart the pod."
    fi

    # Start SSH service
    /usr/sbin/sshd
}

# Export environment variables
export_env_vars() {
    echo "Exporting environment variables..."
    
    # Create environment files
    ENV_FILE="/etc/environment"
    PAM_ENV_FILE="/etc/security/pam_env.conf"
    SSH_ENV_DIR="/root/.ssh/environment"
    
    # Backup original files
    cp "$ENV_FILE" "${ENV_FILE}.bak" 2>/dev/null || true
    cp "$PAM_ENV_FILE" "${PAM_ENV_FILE}.bak" 2>/dev/null || true
    
    # Clear files
    : > "$ENV_FILE"
    : > "$PAM_ENV_FILE"
    : > /etc/rp_environment
    mkdir -p /root/.ssh
    : > "$SSH_ENV_DIR"
    
    # Export to multiple locations for maximum compatibility
    # PIP_EXTRA_INDEX_URL travels with PIP_CONSTRAINT: the constraint pins a
    # +cuXXX build that only the PyTorch index serves, so one without the other
    # makes every install in an SSH session unresolvable.
    printenv | grep -E '^RUNPOD_|^PATH=|^_=|^CUDA|^LD_LIBRARY_PATH|^PYTHONPATH|^PIP_CONSTRAINT=|^PIP_BUILD_CONSTRAINT=|^PIP_EXTRA_INDEX_URL=|^PIP_DISABLE_PIP_VERSION_CHECK=' | while read -r line; do
        # Get variable name and value
        name=$(echo "$line" | cut -d= -f1)
        value=$(echo "$line" | cut -d= -f2-)
        
        # Add to /etc/environment (system-wide)
        echo "$name=\"$value\"" >> "$ENV_FILE"
        
        # Add to PAM environment
        echo "$name DEFAULT=\"$value\"" >> "$PAM_ENV_FILE"
        
        # Add to SSH environment file
        echo "$name=\"$value\"" >> "$SSH_ENV_DIR"
        
        # Add to current shell
        echo "export $name=\"$value\"" >> /etc/rp_environment
    done
    
    # Add sourcing to shell startup files
    echo 'source /etc/rp_environment' >> ~/.bashrc
    echo 'source /etc/rp_environment' >> /etc/bash.bashrc
    
    # Set permissions
    chmod 644 "$ENV_FILE" "$PAM_ENV_FILE"
    chmod 600 "$SSH_ENV_DIR"
}

# Start Jupyter Lab server for remote access
start_jupyter() {
    local JUPYTER_TOKEN
    mkdir -p /workspace

    # JUPYTER_DISABLE_AUTH=true runs with no token, a set JUPYTER_PASSWORD becomes
    # the token, and anything else leaves Jupyter off. No token is generated here
    # because the console never sees one minted in the container.
    if [ "${JUPYTER_DISABLE_AUTH:-}" = "true" ]; then
        echo "WARNING: JUPYTER_DISABLE_AUTH=true -- starting JupyterLab with NO authentication."
        echo "WARNING: anyone with this pod's :8888 proxy URL gets a root shell and full access to /workspace."
        JUPYTER_TOKEN=""
    elif [ -n "${JUPYTER_PASSWORD:-}" ]; then
        JUPYTER_TOKEN="$JUPYTER_PASSWORD"
    else
        echo "JUPYTER_PASSWORD is not set; skipping JupyterLab. Redeploy with"
        echo "\"Start Jupyter notebook\" enabled, set JUPYTER_PASSWORD yourself, or set"
        echo "JUPYTER_DISABLE_AUTH=true to run it with no password (understand the risk)."
        return 0
    fi

    echo "Starting Jupyter Lab on port 8888..."
    nohup jupyter lab \
        --allow-root \
        --no-browser \
        --port=8888 \
        --ip=0.0.0.0 \
        --FileContentsManager.delete_to_trash=False \
        --FileContentsManager.preferred_dir=/workspace \
        --ServerApp.root_dir=/workspace \
        --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' \
        --IdentityProvider.token="${JUPYTER_TOKEN}" \
        --ServerApp.allow_origin=* &> /jupyter.log &
    echo "Jupyter Lab started"
}

# A filebrowser CLI call against the pod's database. Quiet on success; on
# failure its output is printed with FILEBROWSER_PASSWORD masked out.
filebrowser_cli() {
    local out
    if out=$(filebrowser -d "$DB_FILE" "$@" 2>&1); then
        return 0
    fi
    if [ -n "${FILEBROWSER_PASSWORD:-}" ]; then
        out=${out//"$FILEBROWSER_PASSWORD"/<FILEBROWSER_PASSWORD>}
    fi
    echo "$out"
    return 1
}

# FileBrowser always requires a login: a set FILEBROWSER_PASSWORD is the admin
# password, and without one FileBrowser is not started. There is no opt-out.
# Images before this one created admin with the published default
# adminadmin12 whenever FILEBROWSER_PASSWORD was unset, so admin's password is
# set from the env on every start rather than only when the database is first
# created, and the login method is forced back to json in case a database was
# switched to noauth.
start_filebrowser() {
    if [ -z "${FILEBROWSER_PASSWORD:-}" ]; then
        echo "============================================="
        echo "  FILEBROWSER_PASSWORD is not set, so FileBrowser was not started."
        echo "  Set FILEBROWSER_PASSWORD, at least 12 characters, on the pod"
        echo "  and restart it; sign in as admin with it."
        echo "============================================="
        return 0
    fi

    if [ ! -f "$DB_FILE" ]; then
        echo "Initializing FileBrowser..."
        if ! { filebrowser_cli config init \
            && filebrowser_cli config set --address 0.0.0.0 --port 8080 --root /workspace; }; then
            echo "ERROR: could not initialize FileBrowser (see above); it was not started."
            return 0
        fi
    fi

    if ! filebrowser_cli config set --auth.method=json; then
        echo "ERROR: could not set FileBrowser's login method (see above); it was not started."
        return 0
    fi

    local ok=1
    if filebrowser_cli users find admin > /dev/null; then
        filebrowser_cli users update admin --password "$FILEBROWSER_PASSWORD" || ok=0
    else
        filebrowser_cli users add admin "$FILEBROWSER_PASSWORD" --perm.admin || ok=0
    fi
    if [ "$ok" = 0 ]; then
        echo "ERROR: could not set the FileBrowser admin password (see above), so FileBrowser"
        echo "was not started. It must be 12 or more characters and not a common password."
        return 0
    fi

    echo "Starting FileBrowser on port 8080..."
    nohup filebrowser -d "$DB_FILE" &> /filebrowser.log &
}

# Decides whether ComfyUI is served. It always requires a password; there is
# no opt-out:
#   COMFYUI_PASSWORD set   ComfyUI on loopback, the password proxy on 8188
#   not set                ComfyUI is not started
# A password shorter than COMFYUI_PASSWORD_MIN_LENGTH counts as not set: the
# URL is public, so a short one could be guessed.
# Sets COMFYUI_AUTH_MODE to proxy or off, and for off, COMFYUI_OFF_REASON to
# finish the sentence "COMFYUI_PASSWORD ...". The password is never printed.
resolve_comfyui_auth() {
    COMFYUI_OFF_REASON=""
    if [ -z "${COMFYUI_PASSWORD:-}" ]; then
        COMFYUI_AUTH_MODE=off
        COMFYUI_OFF_REASON="is not set"
    elif [ "${#COMFYUI_PASSWORD}" -lt "$COMFYUI_PASSWORD_MIN_LENGTH" ]; then
        COMFYUI_AUTH_MODE=off
        COMFYUI_OFF_REASON="is shorter than $COMFYUI_PASSWORD_MIN_LENGTH characters"
    else
        COMFYUI_AUTH_MODE=proxy
    fi
}

# The password proxy, restarted if it exits, so a crash does not leave
# ComfyUI unreachable until the pod restarts. Exit code 2 is the proxy
# refusing its configuration, which a restart cannot fix. A cause the proxy
# cannot report as 2 (the port already bound, a broken aiohttp) makes it die
# straight away every time, so after AUTH_PROXY_MAX_FAST_FAILURES exits in a
# row within AUTH_PROXY_FAST_FAILURE_SECONDS of starting, the loop gives up
# instead of logging a warning every few seconds forever. A run that lasted
# longer resets the count. Runs in the background; on_shutdown stops this
# loop and then the proxy.
run_auth_proxy() {
    local code started fast=0
    while true; do
        code=0
        started=$SECONDS
        COMFYUI_PROXY_PORT=$COMFYUI_PUBLIC_PORT \
        COMFYUI_UPSTREAM="127.0.0.1:$COMFYUI_INTERNAL_PORT" \
            "$SYSTEM_PYTHON" -I "$AUTH_PROXY" || code=$?
        if [ "$code" = 2 ]; then
            echo "ERROR: the ComfyUI password proxy refused to start (see above); port $COMFYUI_PUBLIC_PORT stays closed."
            return 0
        fi
        if [ $((SECONDS - started)) -lt "$AUTH_PROXY_FAST_FAILURE_SECONDS" ]; then
            fast=$((fast + 1))
        else
            fast=0
        fi
        if [ "$fast" -ge "$AUTH_PROXY_MAX_FAST_FAILURES" ]; then
            echo "ERROR: the ComfyUI password proxy exited (code $code) $fast times in a row right after starting; giving up, port $COMFYUI_PUBLIC_PORT stays closed. See the errors above, fix the cause and restart the pod."
            return 0
        fi
        echo "WARNING: the ComfyUI password proxy exited (code $code); restarting it in ${AUTH_PROXY_RESTART_DELAY}s."
        sleep "$AUTH_PROXY_RESTART_DELAY"
    done
}

# Appends $ARGS_FILE to COMFY_ARGS, one array element per word, since a line
# may hold `--foo bar`. --listen and --port are the script's to set: a
# --listen 0.0.0.0 there would put ComfyUI on the network beside the proxy,
# around the password.
append_user_args() {
    local words=() word next i=0
    [ -s "$ARGS_FILE" ] || return 0
    while read -r word; do
        if [ -n "$word" ]; then
            words+=("$word")
        fi
    done < <(grep -v '^[[:space:]]*#' "$ARGS_FILE" | tr -s '[:space:]' '\n')
    while [ "$i" -lt "${#words[@]}" ]; do
        word=${words[$i]}
        case "$word" in
            --listen | --port)
                # --listen takes an optional value, --port a required one.
                next=${words[$((i + 1))]:-}
                if [ "$word" = --port ] || { [ -n "$next" ] && [ "${next#-}" = "$next" ]; }; then
                    i=$((i + 1))
                fi
                echo "WARNING: ignoring $word in $ARGS_FILE; this script sets the listen address and port."
                ;;
            --listen=* | --port=*)
                echo "WARNING: ignoring ${word%%=*} in $ARGS_FILE; this script sets the listen address and port."
                ;;
            --)
                # Would turn the script's own --listen/--port, which follow,
                # into positional arguments.
                echo "WARNING: ignoring -- in $ARGS_FILE."
                ;;
            *)
                COMFY_ARGS+=("$word")
                ;;
        esac
        i=$((i + 1))
    done
}

# Sets COMFY_ARGS (an array: argparse needs each flag as its own argv entry)
# and COMFY_LISTEN_PORT from $ARGS_FILE. ComfyUI always listens on loopback,
# on the internal port; only the password proxy is reachable from outside.
# The script's --listen and --port go last. argparse keeps the last value
# given and accepts any unambiguous prefix of a flag, so a `--lis 0.0.0.0`
# that append_user_args does not recognise is still overridden by them.
# No --enable-cors-header: it replaces ComfyUI's refusal of cross-site
# requests with a CORS policy that lets any site in.
build_comfy_args() {
    COMFY_ARGS=()
    append_user_args
    COMFY_LISTEN_PORT=$COMFYUI_INTERNAL_PORT
    COMFY_ARGS+=(--listen 127.0.0.1 --port "$COMFY_LISTEN_PORT")
}

# ComfyUI-Manager's security settings, pinned rather than inherited from
# whatever a Manager release defaults to. This is load-bearing, not defence
# in depth: Manager decides "local mode" from --listen (the launch address,
# not the client's IP), and with ComfyUI on 127.0.0.1 behind the proxy every
# loopback-gated install is open unless config.ini closes it. Under
# --listen 0.0.0.0 they were closed whatever the config said. In the pinned
# Manager (MANAGER_SHA) loopback gates exactly three things, and all three
# are written on every start:
#   security_level = normal      high-risk installs stay refused
#   allow_git_url_install = False
#   allow_pip_install = False
# Manager reads them once at startup, so an edit to config.ini while
# ComfyUI runs is overwritten here before it can take effect.
# Newer Manager releases add allow_flagged_nodepack_install, ORed with
# loopback, which no config value can close; the Dockerfile fails the build
# if the pinned Manager gains it, so a bump has to decide about it.
# The new config is written; a legacy one (user/default/ComfyUI-Manager) is
# pinned too when it exists, since Manager migrates it into the new path.
pin_manager_security() {
    "$SYSTEM_PYTHON" -I - "$COMFYUI_DIR/user" <<'PY' || echo "WARNING: could not pin ComfyUI-Manager's security settings; Manager falls back to its own config."
import configparser
import os
import sys

user = sys.argv[1]
new = os.path.join(user, "__manager", "config.ini")
legacy = os.path.join(user, "default", "ComfyUI-Manager", "config.ini")
targets = [p for p in (new, legacy) if os.path.exists(p)] or [new]
for path in targets:
    config = configparser.ConfigParser(strict=False, interpolation=None)
    config.read(path)
    if not config.has_section("default"):
        config.add_section("default")
    config["default"]["security_level"] = "normal"
    config["default"]["allow_git_url_install"] = "False"
    config["default"]["allow_pip_install"] = "False"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        config.write(f)
    os.replace(path + ".tmp", path)
print("ComfyUI-Manager: security_level=normal, git URL and pip installs off")
PY
}

# The manifest alone is not proof: a `cp -r` from an older image, interrupted
# mid-copy, could leave it behind without the files it stands for.
comfyui_core_present() {
    [ -f "$COMFYUI_DIR/main.py" ] \
        && [ -d "$COMFYUI_DIR/comfy" ] \
        && [ -d "$COMFYUI_DIR/comfy_extras" ]
}

# Kept apart from upgrade_comfyui_if_needed so the whole sync, several minutes
# of it on a network volume, can run as one step under a heartbeat.
sync_comfyui_from_baked() {
    # Sync ComfyUI core and remove files that no longer exist in the new
    # release. Excluded paths belong to the user or are managed separately.
    rsync -a --delete \
        --exclude="/$BUNDLE_VERSION_FILE" \
        --exclude="/.venv*" \
        --exclude="/models" \
        --exclude="/input" \
        --exclude="/output" \
        --exclude="/user" \
        --exclude="/custom_nodes" \
        --exclude="/extra_model_paths.yaml" \
        "$BAKED_COMFYUI_DIR/" "$COMFYUI_DIR/"

    mkdir -p "$COMFYUI_DIR/custom_nodes"

    # Update files located directly under custom_nodes without deleting
    # user-provided files or directories.
    rsync -a --exclude="*/" \
        "$BAKED_COMFYUI_DIR/custom_nodes/" "$COMFYUI_DIR/custom_nodes/"

    # Image-managed nodes are pinned with the image and must be upgraded.
    # Other custom-node directories are user-owned and remain untouched.
    local node
    for node in "${BAKED_NODES[@]}"; do
        if [ -d "$BAKED_COMFYUI_DIR/custom_nodes/$node" ]; then
            mkdir -p "$COMFYUI_DIR/custom_nodes/$node"
            rsync -a --delete \
                "$BAKED_COMFYUI_DIR/custom_nodes/$node/" \
                "$COMFYUI_DIR/custom_nodes/$node/"
        fi
    done
}

# Upgrade the image-managed ComfyUI files while leaving user data on the
# persistent workspace untouched.
upgrade_comfyui_if_needed() {
    local baked_manifest="$BAKED_COMFYUI_DIR/$BUNDLE_VERSION_FILE"
    local installed_manifest="$COMFYUI_DIR/$BUNDLE_VERSION_FILE"

    # A missing workspace is handled by the first-time setup below.
    if [ ! -d "$COMFYUI_DIR" ]; then
        return
    fi

    if [ ! -f "$baked_manifest" ]; then
        echo "WARNING: Baked ComfyUI bundle manifest is missing; skipping upgrade"
        return
    fi

    if [ -f "$installed_manifest" ] && cmp -s "$baked_manifest" "$installed_manifest" \
        && comfyui_core_present; then
        echo "Using existing ComfyUI installation (bundle is current)"
        return
    fi

    if ! comfyui_core_present; then
        echo "Workspace ComfyUI is missing core files; restoring them from the image"
    fi

    echo "============================================="
    echo "  Upgrading ComfyUI workspace from baked bundle"
    echo "  Preserving models, user data, and custom nodes"
    echo "============================================="

    local started=$SECONDS
    run_with_heartbeat "still syncing" sync_comfyui_from_baked

    # Write the manifest only after every sync succeeds. An interrupted
    # migration is retried on the next container start.
    cp "$baked_manifest" "${installed_manifest}.tmp"
    mv "${installed_manifest}.tmp" "$installed_manifest"
    echo "ComfyUI workspace upgraded successfully in $((SECONDS - started))s"
}

# A venv belonging to another CUDA variant means this volume carries custom
# nodes whose deps live there, not in this image — so a missing venv of our own
# is a move between variants, not a fresh volume.
find_previous_venv() {
    local candidate found=""
    for candidate in "$COMFYUI_DIR"/.venv "$COMFYUI_DIR"/.venv-cu*; do
        case "$candidate" in
            "$VENV_DIR" | *.bak*) continue ;;
        esac
        if [ -x "$candidate/bin/python" ]; then
            found="$candidate"
        fi
    done
    echo "$found"
}

# Baked nodes are skipped: their deps are in the image's system site-packages.
# The old venv is left in place so going back to its own image still works.
reinstall_user_node_deps() {
    local previous="$1" req node count=0
    echo "============================================="
    echo "  This volume was last used with $(basename "$previous")"
    echo "  Reinstalling custom node deps into $VENV_NAME"
    echo "  This may take several minutes"
    echo "============================================="
    for req in "$COMFYUI_DIR"/custom_nodes/*/requirements.txt; do
        [ -f "$req" ] || continue
        node=$(basename "$(dirname "$req")")
        case " ${BAKED_NODES[*]} " in
            *" $node "*) continue ;;
        esac
        count=$((count + 1))
        echo "[$count] $node"
        python -m pip install -r "$req" 2>&1 | grep -E "^(Successfully|ERROR)" || true
    done
    echo "Done — $count user nodes processed."
    echo "Packages you installed by hand were not carried over; list them with:"
    echo "  $previous/bin/python -m pip freeze --local"
    if [ "$previous" = "$OLD_VENV_DIR" ]; then
        echo "$previous predates every current image, so nothing needs it."
    else
        echo "$previous was left in place; it is only needed if you go back to the"
        echo "CUDA variant that created it."
    fi
    echo "Delete it to free volume space:"
    echo "  rm -rf $previous"
}

# The venv has no pip of its own, so a bare `pip` would resolve to
# /usr/local/bin/pip and install against the base interpreter. Custom-node
# install scripts do call it that way. Existing venvs keep their real pip.
create_pip_shim() {
    if [ -e "$VENV_DIR/bin/pip" ]; then
        return
    fi
    if printf '#!/bin/sh\nexec "%s/bin/python" -m pip "$@"\n' "$VENV_DIR" \
        > "$VENV_DIR/bin/pip" 2>/dev/null; then
        chmod +x "$VENV_DIR/bin/pip"
    else
        echo "WARNING: could not write $VENV_DIR/bin/pip — is the volume full?"
    fi
}

# Run a long step in the background and print a heartbeat every 10s, so minutes
# of silence on a network volume do not read as a hung pod. Returns its status.
run_with_heartbeat() {
    local label="$1" started=$SECONDS tick=0 pid
    shift
    # Without clearing the ERR trap the child would run keep_pod_alive itself,
    # hold there, and leave the heartbeat below ticking forever.
    ( trap - ERR; "$@" ) &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 5
        tick=$((tick + 1))
        if [ $((tick % 2)) -eq 0 ]; then
            echo "  $label... $((SECONDS - started))s elapsed"
        fi
    done
    wait "$pid"
}

# ComfyUI pins its bundled packages (frontend, workflow templates, comfy-kitchen)
# to exact versions, and the workspace checkout can move away from the image via
# Manager or git — then main.py imports a comfy-kitchen that predates it and dies.
# Deps are resolved normally because the template content lives in the
# workflow-templates sub-packages; PIP_CONSTRAINT keeps torch where it is.
sync_comfyui_pinned_packages() {
    local requirements="$COMFYUI_DIR/requirements.txt"
    local installed pins spec name have
    local missing=()

    if [ ! -f "$requirements" ]; then
        return
    fi

    # No --local: the packages to compare against live in the image, not the venv.
    # Names are normalised on both sides because pip and ComfyUI disagree on
    # hyphens vs underscores (comfy-kitchen / comfy_kitchen).
    installed=$(python -m pip freeze 2>/dev/null | tr -d '\r' | tr 'A-Z_' 'a-z-')
    if [ -z "$installed" ]; then
        echo "WARNING: could not list installed packages; skipping the ComfyUI package check."
        return
    fi

    # Only exact pins; every other line in the file is a range we leave alone.
    # torch and friends are kept aligned by /opt/comfyui-runtime-constraints.txt.
    pins=$(tr -d '\r' < "$requirements" \
        | grep -E '^[A-Za-z0-9][A-Za-z0-9._-]*==[^[:space:];#]+$' \
        | tr 'A-Z_' 'a-z-' \
        | grep -vE '^(torch|torchvision|torchaudio)==' || true)

    while read -r spec; do
        if [ -z "$spec" ] || grep -qxF "$spec" <<< "$installed"; then
            continue
        fi
        name=${spec%%==*}
        have=$(grep -m1 -E "^${name}==" <<< "$installed" | cut -d= -f3)
        echo "  $name: installed ${have:-nothing}, ComfyUI wants ${spec#*==}"
        missing+=("$spec")
    done <<< "$pins"

    if [ "${#missing[@]}" = "0" ]; then
        return
    fi

    local started=$SECONDS
    echo "============================================="
    echo "  Workspace ComfyUI disagrees with the packages in this image (see above)."
    echo "  Installing the versions it asks for into $VENV_DIR"
    echo "  On a network volume this takes a few minutes; ComfyUI starts after it."
    echo "============================================="
    if run_with_heartbeat "still installing" \
        python -m pip install --no-cache-dir "${missing[@]}"; then
        echo "Packages installed in $((SECONDS - started))s"
    else
        echo "WARNING: could not install them. If ComfyUI fails to import, redeploy"
        echo "         on a newer image instead of updating ComfyUI in place."
    fi
}

log_cuda_venv_diagnostics() {
    local expected_build local_packages status
    expected_build=$(sed -n 's/^torch==.*+\(cu[0-9][0-9]*\).*$/\1/p' \
        "$PIP_CONSTRAINT_FILE" | head -n 1)

    echo "============================================="
    echo "  CUDA / venv diagnostics"
    echo "  active venv: $VENV_DIR"
    echo "  expected image torch build: ${expected_build:-unknown}"

    # Fail open: a crashed probe must not abort startup (set -e).
    if ! status=$(VENV_DIR="$VENV_DIR" EXPECTED_TORCH_BUILD="$expected_build" \
        python - <<'PY'
import os
import sys

try:
    venv = os.path.realpath(os.environ["VENV_DIR"])
    expected = os.environ.get("EXPECTED_TORCH_BUILD", "")
    print(f"  python: {sys.executable}")

    try:
        import torch
    except Exception as exc:
        print(f"  torch import: FAILED ({type(exc).__name__}: {exc})")
        print("TORCH_STATUS=IMPORT_FAILED")
    else:
        actual = f"cu{torch.version.cuda.replace('.', '')}" if torch.version.cuda else "cpu"
        location = os.path.realpath(torch.__file__)
        local_torch = location.startswith(venv + os.sep)
        print(f"  torch: {torch.__version__}")
        print(f"  torch CUDA build: {actual}")
        print(f"  torch location: {location}")
        print(f"  torch from active venv: {local_torch}")
        print(f"  CUDA available: {torch.cuda.is_available()}")
        print(f"  CUDA device count: {torch.cuda.device_count()}")
        if expected and actual != expected:
            print("TORCH_STATUS=CUDA_MISMATCH")
        elif local_torch:
            print("TORCH_STATUS=LOCAL_TORCH")
        else:
            print("TORCH_STATUS=OK")
except Exception as exc:
    print(f"  probe failed: {type(exc).__name__}: {exc}")
    print("TORCH_STATUS=PROBE_FAILED")
PY
    ); then
        echo "  WARNING: CUDA / venv probe exited unexpectedly; continuing startup."
    fi
    echo "$status" | grep -v '^TORCH_STATUS=' || true

    # Allow optional spaces before ==/@ so PEP 508 direct URL lines match
    # (e.g. "xformers @ https://..."), and include onnxruntime-gpu.
    local_packages=$(python -m pip freeze --local \
        | grep -Ei '^(torch|torchvision|torchaudio|xformers|triton|onnxruntime(-gpu)?|sageattention)[[:space:]]*(==|@)' \
        || true)
    if [ -n "$local_packages" ]; then
        echo "  locally installed CUDA-sensitive packages:"
        echo "    ${local_packages//$'\n'/$'\n'    }"
    else
        echo "  locally installed CUDA-sensitive packages: none"
    fi

    case "$status" in
        *"TORCH_STATUS=OK"*)
            echo "  CUDA / venv status: OK — using the image PyTorch stack."
            ;;
        *"TORCH_STATUS=LOCAL_TORCH"*)
            echo "  WARNING: PyTorch is installed inside the persistent venv."
            echo "  It overrides the image PyTorch stack; verify it matches this image's CUDA build."
            ;;
        *"TORCH_STATUS=CUDA_MISMATCH"*)
            echo "  WARNING: Persistent venv PyTorch does not match this image's CUDA build."
            echo "  This can prevent CUDA from initializing. No files were changed automatically."
            ;;
        *)
            echo "  WARNING: Could not verify the persistent venv PyTorch stack."
            ;;
    esac
    echo "============================================="
}

# ---------------------------------------------------------------------------- #
#                               Main Program                                     #
# ---------------------------------------------------------------------------- #

# Setup environment
if [ -f "$PIP_CONSTRAINT_FILE" ]; then
    export PIP_CONSTRAINT="$PIP_CONSTRAINT_FILE"
    # Since pip 26.2, PIP_CONSTRAINT no longer reaches isolated build envs, so a
    # node built from source (e.g. sam2) would resolve its own torch without this.
    export PIP_BUILD_CONSTRAINT="$PIP_CONSTRAINT_FILE"
    echo "Using runtime pip constraints from $PIP_CONSTRAINT_FILE"
fi

setup_ssh
export_env_vars

start_filebrowser
start_jupyter

# With `set -e` an unexpected failure during the rest of startup would exit and
# the container would be restarted straight back into it, tearing down
# SSH/Jupyter/FileBrowser each time. Hold the pod instead. Cleared once ComfyUI
# starts.
# Bash runs no trap while it waits on a foreground command, so a plain
# `sleep infinity` would swallow the stop signal until Docker sends SIGKILL.
hold_pod() {
    sleep infinity &
    wait $! || true
}

keep_pod_alive() {
    local rc=$?
    echo "============================================="
    echo "  Pod setup failed before ComfyUI could be started (exit code $rc)."
    echo "  The error is above. SSH, JupyterLab and FileBrowser stay up so you"
    echo "  can inspect the pod; nothing is retried automatically."
    echo "============================================="
    hold_pod
}
set -E
trap keep_pod_alive ERR

# Installed here, not at the ComfyUI launch below: a pod stopped while setup is
# still running (or held by keep_pod_alive) would otherwise die with no trace.
# Everything is done here and the handler exits itself — on a pod, execution
# does not resume after it returns, so nothing may be left for the `wait` below.
# Docker only signals PID 1, hence the pkills for the nohup'd services.
on_shutdown() {
    echo "Pod is shutting down (stop/restart/terminate) — stopping ComfyUI, Jupyter and FileBrowser."
    if [ -n "${COMFY_PID:-}" ] && kill -0 "$COMFY_PID" 2>/dev/null; then
        kill "$COMFY_PID" 2>/dev/null || true
        wait "$COMFY_PID" 2>/dev/null || true
    fi
    if [ -n "${PROXY_PID:-}" ]; then
        # The restart loop first, so it cannot start the proxy again.
        kill "$PROXY_PID" 2>/dev/null || true
        pkill -TERM -f "$AUTH_PROXY" 2>/dev/null || true
    fi
    pkill -TERM -f "jupyter-lab" 2>/dev/null || true
    pkill -TERM -x "filebrowser" 2>/dev/null || true
    exit 0
}
trap on_shutdown SIGTERM SIGINT

# Before any of the ComfyUI setup below, which on a network volume takes
# minutes, so a pod that will not run ComfyUI says so at once.
resolve_comfyui_auth
if [ "$COMFYUI_AUTH_MODE" = off ]; then
    echo "============================================="
    echo "  COMFYUI_PASSWORD $COMFYUI_OFF_REASON, so ComfyUI was not started."
    echo "  ComfyUI has no login of its own: without a password, anyone"
    echo "  with this pod's :8188 URL could use your GPU and run code here."
    echo "  Set COMFYUI_PASSWORD, at least $COMFYUI_PASSWORD_MIN_LENGTH characters, on the"
    echo "  pod and restart it; the browser then asks for it."
    echo "  SSH, JupyterLab and FileBrowser are not affected."
    echo "============================================="
    hold_pod
    exit 0
fi

# Create default comfyui_args.txt if it doesn't exist
ARGS_FILE="/workspace/runpod-slim/comfyui_args.txt"
if [ ! -f "$ARGS_FILE" ]; then
    echo "# Add your custom ComfyUI arguments here (one per line)" > "$ARGS_FILE"
    echo "Created empty ComfyUI arguments file at $ARGS_FILE"
fi

upgrade_comfyui_if_needed

# Migrate old CUDA 12.4 venv to cu128. Only the image that owns .venv-cu128
# does this; on any other variant the plain .venv is handled as a move below.
if [ -d "$OLD_VENV_DIR" ] && [ ! -d "$VENV_DIR" ] && [ "$VENV_NAME" = ".venv-cu128" ]; then
    NODE_COUNT=$(find "$COMFYUI_DIR/custom_nodes" -maxdepth 2 -name "requirements.txt" 2>/dev/null | wc -l)
    echo "============================================="
    echo "  CUDA 12.4 -> 12.8 migration"
    echo "  Reinstalling deps for $NODE_COUNT custom nodes"
    echo "  This may take several minutes"
    echo "============================================="
    # Timestamped, and failure must not abort the boot: with a plain `.bak`
    # target left over from an earlier migration, `mv` moves the venv *inside*
    # it, fails under `set -e`, and the pod restarts in a loop.
    VENV_BACKUP="${OLD_VENV_DIR}.bak.$(date +%Y%m%d%H%M%S)"
    if mv "$OLD_VENV_DIR" "$VENV_BACKUP"; then
        BACKED_UP=1
    else
        BACKED_UP=0
        echo "WARNING: could not move $OLD_VENV_DIR aside; continuing with a fresh venv"
    fi
    cd "$COMFYUI_DIR"
    python3.12 -m venv --system-site-packages --without-pip "$VENV_DIR"
    # The venv is created at runtime, so there is nothing for shellcheck to follow.
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    # Skip nodes baked into the image — their deps are in system site-packages
    CURRENT=0
    INSTALLED=0
    for req in "$COMFYUI_DIR"/custom_nodes/*/requirements.txt; do
        if [ -f "$req" ]; then
            NODE_NAME=$(basename "$(dirname "$req")")
            case " ${BAKED_NODES[*]} " in
                *" $NODE_NAME "*) continue ;;
            esac
            CURRENT=$((CURRENT + 1))
            echo "[$CURRENT] $NODE_NAME"
            python -m pip install -r "$req" 2>&1 | grep -E "^(Successfully|ERROR)" || true
            INSTALLED=$((INSTALLED + 1))
        fi
    done
    echo "Ensuring ComfyUI requirements are present..."
    python -m pip install -r "$COMFYUI_DIR/requirements.txt" 2>&1 | grep -E "^(Successfully|ERROR)" || true
    echo "Migration complete — $INSTALLED user nodes processed (${NODE_COUNT} total, baked nodes skipped)"
    if [ "$BACKED_UP" = "1" ]; then
        echo "Old venv backed up at $VENV_BACKUP — delete it to free space:"
        echo "  rm -rf $VENV_BACKUP"
    fi
fi

# A stage directory left by an interrupted copy is resumed into below, but it
# is dead weight on the volume once the real directory exists.
if [ -d "$COMFYUI_DIR" ] && [ -d "${COMFYUI_DIR}.incomplete" ]; then
    echo "Removing leftover ${COMFYUI_DIR}.incomplete"
    rm -rf "${COMFYUI_DIR}.incomplete"
fi

# `python3.12 -m venv` has been seen leaving the directory behind without
# bin/activate, and a directory test then passes for a venv nothing can source.
venv_is_usable() { [ -f "$VENV_DIR/bin/activate" ]; }

# Setup ComfyUI if needed
if [ ! -d "$COMFYUI_DIR" ] || ! venv_is_usable; then
    PREVIOUS_VENV=$(find_previous_venv)
    # Copy baked ComfyUI from image (no git, no network). Staged under a
    # temporary name so an interrupted copy is never taken for a finished one.
    if [ ! -d "$COMFYUI_DIR" ]; then
        echo "============================================="
        echo "  First-time setup: copying ComfyUI to $COMFYUI_DIR"
        echo "  On a network volume this takes several minutes, and the"
        echo "  ComfyUI port stays closed until it finishes. This is normal."
        echo "  Stopping the pod now leaves the copy to be resumed on the"
        echo "  next start — nothing is lost, but the wait starts over."
        echo "============================================="
        COPY_STARTED=$SECONDS
        mkdir -p "${COMFYUI_DIR}.incomplete"
        run_with_heartbeat "still copying" \
            rsync -a --delete "$BAKED_COMFYUI_DIR/" "${COMFYUI_DIR}.incomplete/"
        mv "${COMFYUI_DIR}.incomplete" "$COMFYUI_DIR"
        echo "ComfyUI copied to workspace in $((SECONDS - COPY_STARTED))s"
    fi

    # Create venv with access to system packages (torch, numpy, etc. pre-installed in image)
    if ! venv_is_usable; then
        cd "$COMFYUI_DIR"
        if [ -d "$VENV_DIR" ]; then
            # Reached only with bin/activate missing. It is written last, so a
            # venv that failed mid-creation holds nothing — but if one does,
            # keep it.
            if [ -n "$(ls -A "$VENV_DIR"/lib/python*/site-packages 2>/dev/null)" ]; then
                VENV_BROKEN="${VENV_DIR}.broken.$(date +%Y%m%d%H%M%S)"
                echo "$VENV_DIR has no bin/activate but is not empty — moving it to $VENV_BROKEN"
                echo "  Installed packages are kept there; delete it to free space."
                mv "$VENV_DIR" "$VENV_BROKEN" || true
            else
                echo "Discarding unusable $VENV_DIR (no bin/activate) and recreating it"
                rm -rf "$VENV_DIR"
            fi
        fi
        # --without-pip: pip stays in the image (local disk, bytecode compiled
        # at build) instead of on the network volume, where importing it can
        # exceed ComfyUI-Manager's probe timeout. --system-site-packages keeps
        # it importable, and installs still land in this venv via sys.prefix.
        python3.12 -m venv --system-site-packages --without-pip "$VENV_DIR" || true
        # Keep SSH/Jupyter/FileBrowser reachable instead of crash-looping on a
        # bare `source: No such file or directory`.
        if ! venv_is_usable; then
            echo "============================================="
            echo "  Could not create the Python environment at $VENV_DIR"
            echo "  (see the error above). ComfyUI was not started."
            echo "  SSH, JupyterLab and FileBrowser stay up so you can inspect"
            echo "  the pod; nothing is retried automatically."
            echo "============================================="
            hold_pod
        fi
        echo "Base packages (torch, numpy, etc.) available from system site-packages"
        echo "ComfyUI ready — all dependencies pre-installed in image"
    fi
fi

# Activated on every path: a resumed copy can restore a workspace that already
# carries a usable venv, and then neither branch above would have sourced it.
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
echo "Using ComfyUI installation at $COMFYUI_DIR"

# After activation, so the reinstalled packages land in the venv we just made.
if [ -n "${PREVIOUS_VENV:-}" ]; then
    reinstall_user_node_deps "$PREVIOUS_VENV"
fi

create_pip_shim

# Interactive sessions are started by sshd, not by this script, and the PATH
# copied into the login files above was captured before the venv existed —
# `python` was then missing entirely and `pip` resolved to the base interpreter.
printf 'if [ -f "%s/bin/activate" ]; then . "%s/bin/activate"; fi\n' \
    "$VENV_DIR" "$VENV_DIR" >> /etc/rp_environment

# Warm up pip before Manager probes it. Log wall time — the Dockerfile raises
# Manager's timeout to 30s.
echo "Warming up pip (Manager timeout is 30s)..."
time python -m pip --version

sync_comfyui_pinned_packages

log_cuda_venv_diagnostics

pin_manager_security

# Start ComfyUI — keep container alive if it crashes so SSH/Jupyter remain accessible
cd "$COMFYUI_DIR"

build_comfy_args

# Startup is over: from here the crash banner below owns failures, and a live
# ERR trap would also fire on the shutdown path and hold the pod open.
trap - ERR

run_auth_proxy &
PROXY_PID=$!

echo "Starting ComfyUI with args: ${COMFY_ARGS[*]}"
python main.py "${COMFY_ARGS[@]}" &
COMFY_PID=$!

# ComfyUI-Manager's "All startup tasks have been completed" trails the usable
# UI by minutes while it pages through api.comfy.org, so announce the port
# itself. Users read that line as the ready signal and stop pods before it.
announce_when_ready() {
    local started=$SECONDS
    until curl -fs -o /dev/null --max-time 2 "http://127.0.0.1:$COMFY_LISTEN_PORT/"; do
        kill -0 "$COMFY_PID" 2>/dev/null || return
        sleep 2
    done
    echo "============================================="
    # The proxy must answer, and must refuse a request with no password.
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
        "http://127.0.0.1:$COMFYUI_PUBLIC_PORT/" || true)
    if [ "$code" = 401 ]; then
        echo "  ComfyUI is READY on port $COMFYUI_PUBLIC_PORT after $((SECONDS - started))s."
        echo "  It asks for a password: the pod's COMFYUI_PASSWORD."
    else
        echo "  ComfyUI started, but the password proxy on port"
        echo "  $COMFYUI_PUBLIC_PORT is not answering (got: ${code:-nothing})."
        echo "  ComfyUI stays on 127.0.0.1 and is not reachable from outside."
    fi
    echo "  ComfyUI-Manager may still be refreshing its node list below;"
    echo "  that runs in the background and does not hold up the UI."
    echo "============================================="
}
announce_when_ready &

# Only a real ComfyUI exit gets past this: a stopped pod leaves through
# on_shutdown, which exits before this returns.
COMFY_EXIT=0
wait $COMFY_PID || COMFY_EXIT=$?

# 137 is SIGKILL: normally the cgroup OOM killer, but a manual kill is
# indistinguishable, so confirm against the cgroup's own counter. Both reads go
# through cat, because a missing file aborts awk and `set -e` would then kill
# the script before it prints anything. An unreadable counter reads as an OOM,
# which is what a SIGKILL in a pod almost always is.
OOM_KILLS=$(cat /sys/fs/cgroup/memory.events 2>/dev/null \
    | awk '$1 == "oom_kill" {print $2; exit}')
# A huge limit in cgroup v1 means "unlimited"; v2 writes "max" instead.
RAM_LIMIT=$(cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null \
    | awk '$1 ~ /^[0-9]+$/ && $1 < 1e15 {printf " (limit %.0f GiB)", $1/1073741824; exit}')

echo "============================================="
if [ "$COMFY_EXIT" = "137" ] && [ "$OOM_KILLS" != "0" ]; then
    echo "  ComfyUI was killed: the container ran out of RAM${RAM_LIMIT}."
    echo "  There is no traceback above — it was terminated from outside."
    echo "  Load a smaller model, or redeploy the pod with more RAM."
elif [ "$COMFY_EXIT" = "137" ]; then
    echo "  ComfyUI was killed from outside (SIGKILL). The memory limit was"
    echo "  never reached, so this was not an out-of-memory kill."
else
    echo "  ComfyUI exited unexpectedly (exit code $COMFY_EXIT)."
    echo "  Check the logs above for the error/traceback."
fi

echo "  SSH, JupyterLab and FileBrowser stay up. ComfyUI is not restarted"
echo "  automatically; to start it again in this pod:"
echo "    cd $COMFYUI_DIR && source $VENV_NAME/bin/activate"
echo "    python main.py ${COMFY_ARGS[*]}"
echo "============================================="

hold_pod
