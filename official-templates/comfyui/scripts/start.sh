#!/bin/bash
set -e  # Exit the script if any statement returns a non-true return value

COMFYUI_DIR="/workspace/runpod-slim/ComfyUI"
BAKED_COMFYUI_DIR="/opt/comfyui-baked"
BUNDLE_VERSION_FILE=".runpod-bundle-version"
VENV_NAME="${COMFYUI_VENV_NAME:-.venv-cu128}"
VENV_DIR="$COMFYUI_DIR/$VENV_NAME"
OLD_VENV_DIR="$COMFYUI_DIR/.venv"
MIGRATION_MARKER=".runpod-migration-incomplete"
DB_FILE="/workspace/runpod-slim/filebrowser.db"
PIP_CONSTRAINT_FILE="/opt/comfyui-runtime-constraints.txt"
BAKED_NODES=("ComfyUI-KJNodes" "Civicomfy" "ComfyUI-RunpodDirect")
# ComfyUI-Manager now ships as the comfyui_manager pip package in the image, and
# ComfyUI ignores any copy under custom_nodes once --enable-manager is set
# (main.py -> comfyui_manager.should_be_disabled). Volumes created by an older
# image still carry the 3.x clone; it is dead weight, so skip its requirements
# along with the baked nodes.
DEP_SKIP_NODES=("${BAKED_NODES[@]}" "ComfyUI-Manager")
CUDA_COMPAT_DIR="/opt/cuda-compat"
CUDA_COMPAT_STATUS="not installed"
# 8188 is the port the template exposes. The password proxy owns it, and
# ComfyUI listens on loopback only, on the internal port. With
# COMFYUI_DISABLE_AUTH set there is no proxy and ComfyUI itself listens on it.
COMFYUI_PUBLIC_PORT=8188
COMFYUI_INTERNAL_PORT=18188
AUTH_PROXY="/opt/comfyui-auth-proxy/auth_proxy.py"
# The image's interpreter, not the venv on the volume: a package installed
# there must not be able to change the proxy.
SYSTEM_PYTHON="/usr/bin/python3.12"
AUTH_PROXY_RESTART_DELAY=5
AUTH_PROXY_MAX_FAST_FAILURES=5
AUTH_PROXY_FAST_FAILURE_SECONDS=30

# ---------------------------------------------------------------------------- #
#                          Function Definitions                                  #
# ---------------------------------------------------------------------------- #

# For the *_DISABLE_AUTH flags: true, 1 or yes in any case is true. Anything
# else, empty included, is false, so a typo keeps the password.
is_true() {
    case "${1:-}" in
        [Tt][Rr][Uu][Ee] | 1 | [Yy][Ee][Ss]) return 0 ;;
        *) return 1 ;;
    esac
}

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

# Decides whether ComfyUI is served, and how. The flag is checked first, so a
# password the platform set does not cancel it:
#   COMFYUI_DISABLE_AUTH true  disabled: ComfyUI on 0.0.0.0:8188, no password
#   COMFYUI_PASSWORD set       proxy: ComfyUI on loopback, the password proxy
#                              on 8188; any non-empty password is accepted
#   neither                    off: ComfyUI is not started
# Sets COMFYUI_AUTH_MODE. The password is never printed.
resolve_comfyui_auth() {
    if is_true "${COMFYUI_DISABLE_AUTH:-}"; then
        COMFYUI_AUTH_MODE=disabled
    elif [ -n "${COMFYUI_PASSWORD:-}" ]; then
        COMFYUI_AUTH_MODE=proxy
    else
        COMFYUI_AUTH_MODE=off
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
# and COMFY_LISTEN_PORT from $ARGS_FILE. ComfyUI listens on loopback, on the
# internal port, so only the password proxy is reachable from outside. With
# auth disabled there is no proxy and ComfyUI listens on 0.0.0.0, public port.
# The script's --listen and --port go last. argparse keeps the last value
# given and accepts any unambiguous prefix of a flag, so a `--lis 0.0.0.0`
# that append_user_args does not recognise is still overridden by them.
# No --enable-cors-header: it replaces ComfyUI's refusal of cross-site
# requests with a CORS policy that lets any site in.
build_comfy_args() {
    # --enable-manager loads the comfyui_manager package installed in the image.
    # Add --enable-manager-legacy-ui to comfyui_args.txt for the 3.x Manager UI.
    COMFY_ARGS=(--enable-manager)
    append_user_args
    local address=127.0.0.1
    COMFY_LISTEN_PORT=$COMFYUI_INTERNAL_PORT
    if [ "${COMFYUI_AUTH_MODE:-}" = disabled ]; then
        address=0.0.0.0
        COMFY_LISTEN_PORT=$COMFYUI_PUBLIC_PORT
    fi
    COMFY_ARGS+=(--listen "$address" --port "$COMFY_LISTEN_PORT")
}

# ComfyUI-Manager's security settings, pinned rather than inherited from
# whatever a Manager release defaults to. This is load-bearing, not defence
# in depth: Manager decides "local mode" from --listen (the launch address,
# not the client's IP), and with ComfyUI on 127.0.0.1 behind the proxy every
# loopback-gated install is open unless config.ini closes it. Under
# --listen 0.0.0.0 they were closed whatever the config said. In the pinned
# Manager (MANAGER_VERSION) loopback gates exactly three things, and all
# three are written on every start:
#   security_level = normal      high-risk installs stay refused
#   allow_git_url_install = False
#   allow_pip_install = False
# use_uv goes with them: the image removes uv on purpose, and an explicit
# `use_uv = True` on the volume is honoured, which sends Manager's installs
# through a uv that is not there. Manager's own default is already False.
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
    config["default"]["use_uv"] = "False"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        config.write(f)
    os.replace(path + ".tmp", path)
print("ComfyUI-Manager: security_level=normal, git URL and pip installs off, uv off")
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
            "$VENV_DIR" | *.bak* | *.broken*) continue ;;
        esac
        if [ -x "$candidate/bin/python" ] && [ ! -e "$candidate/$MIGRATION_MARKER" ]; then
            found="$candidate"
        fi
    done
    echo "$found"
}

# Name backstop for the .so check in list_cuda_bound_dists.
CUDA_BUILT_PACKAGES_RE='^(torch|torchvision|torchaudio|xformers|triton|flash-attn|sageattention|nunchaku|onnxruntime-gpu|spconv.*|cupy-cuda.*|nvidia-.*)$'

# Print the distribution count in site-packages $1, then each one that may be
# built for another torch/CUDA: local version, URL/git install, name match, or
# a .so linking libtorch/libc10/CUDA (C extensions under plain == versions,
# which break on the torch 2.10 -> 2.13 ABI change on cu132).
list_cuda_bound_dists() {
    CUDA_BUILT_PACKAGES_RE="$CUDA_BUILT_PACKAGES_RE" python - "$1" <<'PY'
import importlib.metadata as md
import json
import os
import re
import struct
import sys

name_re = re.compile(os.environ["CUDA_BUILT_PACKAGES_RE"])
lib_re = re.compile(
    r"^lib(torch[a-z_]*|c10[a-z_]*|cuda|cudart|cublas(Lt)?|cudnn[a-z_]*|cufft|"
    r"curand|cusparse|cusolver|nvrtc|nvJitLink|nccl)\.so"
)


def needed(path):
    """DT_NEEDED entries of a 64-bit ELF file; [] for anything else."""
    try:
        with open(path, "rb") as f:
            h = f.read(64)
            if len(h) < 64 or h[:4] != b"\x7fELF" or h[4] != 2:
                return []
            e = "<" if h[5] == 1 else ">"
            phoff = struct.unpack_from(e + "Q", h, 0x20)[0]
            phentsize, phnum = struct.unpack_from(e + "HH", h, 0x36)
            f.seek(phoff)
            ph = f.read(phentsize * phnum)
            loads, dyn = [], None
            for i in range(phnum):
                p = struct.unpack_from(e + "IIQQQQQQ", ph, i * phentsize)
                if p[0] == 1:  # PT_LOAD: vaddr, offset, filesz
                    loads.append((p[3], p[2], p[5]))
                elif p[0] == 2:  # PT_DYNAMIC: offset, filesz
                    dyn = (p[2], p[5])
            if dyn is None:
                return []
            f.seek(dyn[0])
            d = f.read(dyn[1])
            offs, strtab, strsz = [], None, 0
            for i in range(0, len(d) - 15, 16):
                tag, val = struct.unpack_from(e + "qQ", d, i)
                if tag == 0:
                    break
                if tag == 1:
                    offs.append(val)
                elif tag == 5:
                    strtab = val
                elif tag == 10:
                    strsz = val
            if strtab is None:
                return []
            base = next((o + strtab - v for v, o, s in loads if v <= strtab < v + s), None)
            if base is None:
                return []
            f.seek(base)
            s = f.read(strsz)
            return [s[n:s.find(b"\0", n)].decode(errors="replace") for n in offs if n < len(s)]
    except (OSError, struct.error):
        return []


dists = list(md.distributions(path=[sys.argv[1]]))
print(len(dists))
for dist in dists:
    raw = dist.metadata["Name"] or ""
    if not raw:
        continue
    name = re.sub(r"[-_.]+", "-", raw).lower()
    flagged = "+" in dist.version or bool(name_re.match(name))
    if not flagged:
        direct = dist.read_text("direct_url.json")
        if direct:
            try:
                flagged = not json.loads(direct).get("dir_info", {}).get("editable", False)
            except ValueError:
                flagged = True
    if not flagged:
        for file in dist.files or ():
            rel = str(file)
            if (rel.endswith(".so") or ".so." in rel) and any(
                lib_re.match(lib) for lib in needed(dist.locate_file(file))
            ):
                flagged = True
                break
    if flagged:
        print(name)
PY
}

# rm unlinks, so the old venv's hard-linked files are untouched.
clear_site_packages() {
    find "$1" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
}

# Hard-link the previous venv's packages into the active one (seconds instead
# of re-downloading), then remove those built for another torch/CUDA.
# rsync --link-dest, not cp: it never writes through a shared inode, so the old
# venv stays intact (pip also unlinks before writing). pip/setuptools are left
# out to keep pip off the volume, as --without-pip does.
seed_venv_from_previous() {
    local previous="$1" src dst listing total script
    local dropped=()

    src=$(compgen -G "$previous/lib/python3*/site-packages" | head -n 1)
    dst=$(compgen -G "$VENV_DIR/lib/python3*/site-packages" | head -n 1)
    # Compiled modules are tied to the interpreter's minor version.
    if [ -z "$src" ] || [ -z "$dst" ] \
        || [ "$(basename "$(dirname "$src")")" != "$(basename "$(dirname "$dst")")" ]; then
        return 1
    fi
    echo "Copying packages from $(basename "$previous")"
    if ! rsync -a --link-dest="$src" \
        --exclude='/pip' --exclude='/pip-*.dist-info' \
        --exclude='/setuptools' --exclude='/setuptools-*.dist-info' \
        --exclude='/pkg_resources' --exclude='/_distutils_hack' \
        --exclude='/distutils-precedence.pth' \
        --exclude='/wheel' --exclude='/wheel-*.dist-info' \
        "$src/" "$dst/"; then
        clear_site_packages "$dst"
        return 1
    fi

    # Repoint console-script shebangs at this venv.
    for script in "$previous"/bin/*; do
        case "$(basename "$script")" in
            python* | activate* | Activate.ps1 | pip*) continue ;;
        esac
        [ -f "$script" ] && [ ! -e "$VENV_DIR/bin/$(basename "$script")" ] || continue
        if head -n 1 "$script" | grep -q "^#!$previous/bin/python"; then
            sed "1s|^#!$previous/bin/python[0-9.]*|#!$VENV_DIR/bin/python|" "$script" \
                > "$VENV_DIR/bin/$(basename "$script")" \
                && chmod +x "$VENV_DIR/bin/$(basename "$script")"
        fi
    done

    if ! listing=$(list_cuda_bound_dists "$dst") || [ -z "$listing" ]; then
        echo "  Could not inspect the copied packages."
        clear_site_packages "$dst"
        return 1
    fi
    total=$(head -n 1 <<< "$listing")
    mapfile -t dropped < <(tail -n +2 <<< "$listing")
    echo "Copied $total packages"
    if [ "${#dropped[@]}" != "0" ]; then
        echo "  Removing ones built for another torch/CUDA or installed from a URL: ${dropped[*]}"
        if ! python -m pip uninstall --quiet -y "${dropped[@]}"; then
            clear_site_packages "$dst"
            return 1
        fi
    fi
}

# Baked nodes are skipped: their deps are in the image's system site-packages.
# The old venv is left in place so going back to its own image still works.
# Fast path: seed from the old venv, then one combined resolve. The per-node
# loop is only the fallback.
reinstall_user_node_deps() {
    local previous="$1" req node count=0 seeded=0 started=$SECONDS
    local reqs=() nodes=() req_args=()
    echo "============================================="
    echo "  This volume was last used with $(basename "$previous")"
    echo "  Reinstalling custom node deps into $VENV_NAME"
    echo "  This may take a few minutes"
    echo "============================================="
    for req in "$COMFYUI_DIR"/custom_nodes/*/requirements.txt; do
        [ -f "$req" ] || continue
        node=$(basename "$(dirname "$req")")
        case " ${DEP_SKIP_NODES[*]} " in
            *" $node "*) continue ;;
        esac
        reqs+=("$req")
        nodes+=("$node")
        req_args+=(-r "$req")
    done
    count=${#reqs[@]}

    if [ "$count" != "0" ] && seed_venv_from_previous "$previous"; then
        seeded=1
    fi
    if [ "$seeded" = "1" ] \
        && echo "Checking requirements of $count user nodes in one pass" \
        && run_with_heartbeat "still resolving" \
            python -m pip install --quiet "${req_args[@]}"; then
        echo "Done — deps for $count user nodes in place after $((SECONDS - started))s."
    else
        if [ "$count" != "0" ]; then
            echo "Fast path did not complete; installing node by node instead."
        fi
        local i
        for i in "${!reqs[@]}"; do
            echo "[$((i + 1))] ${nodes[$i]}"
            python -m pip install -r "${reqs[$i]}" 2>&1 | grep -E "^(Successfully|ERROR)" || true
        done
        echo "Done — $count user nodes processed in $((SECONDS - started))s."
    fi
    rm -f "$VENV_DIR/$MIGRATION_MARKER"
    if [ "$seeded" = "1" ]; then
        echo "Packages you installed by hand were copied, except CUDA-specific ones"
        echo "(xformers, sageattention, nunchaku, ...), which need a build for this"
        echo "image. The old venv's list:"
    else
        echo "Packages you installed by hand (not in a node's requirements.txt) were"
        echo "not carried over; reinstall the ones you need. The old venv's list:"
    fi
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

# comfyui_manager is patched in the image (manager-patches/ in the Dockerfile)
# and lives in the system site-packages the venv reaches through
# --system-site-packages. A copy inside the venv comes first on sys.path and
# would shadow it, running a Manager without the 403s on update_comfyui,
# comfyui_switch_version, share and the credential routes. So: drop any such
# copy, and when the workspace ComfyUI asks for another version, say so rather
# than install it. The fixes travel with the image, not with the workspace.
pin_image_manager() {
    local pinned have

    # Fail open: a crashed probe must not abort startup (set -e).
    if python - <<'PY'
import importlib.metadata as md
import os
import sys

venv = os.path.realpath(sys.prefix) + os.sep
for dist in md.distributions():
    name = (dist.metadata["Name"] or "").lower().replace("_", "-")
    if name != "comfyui-manager":
        continue
    where = os.path.realpath(str(dist.locate_file("")))
    if (where + os.sep).startswith(venv):
        print(f"ComfyUI-Manager: a copy in {where} shadows the image's patched one; removing it.")
        sys.exit(0)
sys.exit(1)
PY
    then
        python -m pip uninstall -y comfyui_manager > /dev/null 2>&1 \
            || echo "WARNING: could not remove it; ComfyUI-Manager runs without the Runpod fixes."
    fi

    [ -f "$COMFYUI_DIR/manager_requirements.txt" ] || return 0
    pinned=$(tr -d '\r' < "$COMFYUI_DIR/manager_requirements.txt" \
        | grep -oE '^comfyui[-_]manager==[^[:space:];#]+' | head -1 | cut -d= -f3)
    have=$(python -c 'import importlib.metadata as m; print(m.version("comfyui_manager"))' 2>/dev/null || true)
    if [ -n "$pinned" ] && [ -n "$have" ] && [ "$pinned" != "$have" ]; then
        echo "WARNING: the workspace ComfyUI asks for ComfyUI-Manager $pinned; this image ships $have."
        echo "         The image's Manager carries the Runpod fixes, so it is the one that runs."
        echo "         Redeploy on a tag whose ComfyUI pins $pinned if you need that version."
    fi
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

    # manager_requirements.txt is deliberately not read here: comfyui_manager is
    # patched in the image and installing it would put an unpatched copy in the
    # venv, ahead of the patched one on sys.path. pin_image_manager owns it.
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
        | grep -vE '^(torch|torchvision|torchaudio|comfyui-manager)==' || true)

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

# Print "<driver_version> <cuInit_rc> <libcuda_path>" for whichever libcuda.so.1
# the dynamic loader picks up with the current LD_LIBRARY_PATH.
probe_libcuda() {
    python3.12 - <<'PY' 2>/dev/null
import ctypes
try:
    lib = ctypes.CDLL("libcuda.so.1")
except OSError:
    print("0 -1 none")
    raise SystemExit
version = ctypes.c_int(0)
lib.cuDriverGetVersion(ctypes.byref(version))
rc = lib.cuInit(0)
path = "unknown"
with open("/proc/self/maps") as maps:
    for line in maps:
        if "libcuda.so" in line:
            path = line.split()[-1]
            break
print(version.value, rc, path)
PY
}

# Undo compat that the NVIDIA Container Toolkit (>= 1.17.5) enabled on its own:
# its enable-cuda-compat hook finds /usr/local/cuda/compat in the image and puts
# it in the loader cache, even when the host driver already supports the
# image's CUDA (e.g. user-mode 595.112 on a 595.91 kernel module), and on
# GeForce cards across driver branches, where cuInit fails with 804 (seen: RTX
# 4090, host 570.172, compat 580.196). Seen on Runpod hosts in two forms, both
# handled here: an /etc/ld.so.conf.d/00-compat-*.conf entry, or an ldconfig run
# with the compat dir on its command line (cache only, no conf file).
# Rebuilding the cache from the remaining conf files drops both. Fails open.
drop_runtime_cuda_compat() {
    local conf
    for conf in /etc/ld.so.conf.d/*.conf; do
        [ -f "$conf" ] || continue
        if grep -qE '^[[:space:]]*/usr/local/cuda[^/]*/compat/?[[:space:]]*$' "$conf"; then
            mv "$conf" "$conf.disabled-by-start-sh" 2>/dev/null || true
        fi
    done
    ldconfig 2>/dev/null || true
}

# CUDA version of the image's toolkit in cuDriverGetVersion form (13.0 -> 13000),
# or 0 if it cannot be read.
image_cuda_version() {
    python3.12 - <<'PY' 2>/dev/null || echo 0
import json
import re
import subprocess
try:
    with open("/usr/local/cuda/version.json") as f:
        major, minor = json.load(f)["cuda"]["version"].split(".")[:2]
except Exception:
    out = subprocess.run(["/usr/local/cuda/bin/nvcc", "--version"],
                         capture_output=True, text=True).stdout
    major, minor = re.search(r"release (\d+)\.(\d+)", out).groups()
print(int(major) * 1000 + int(minor) * 10)
PY
}

# Directory of the host's injected libcuda.so.1, i.e. any loader-cache entry or
# usual driver path that is not a compat dir. Prints nothing if there is none.
find_host_libcuda_dir() {
    local lib
    for lib in $(ldconfig -p 2>/dev/null | awk '$1 == "libcuda.so.1" {print $NF}') \
        /usr/lib/x86_64-linux-gnu/libcuda.so.1 /usr/lib64/libcuda.so.1; do
        [[ "$lib" == */compat/* ]] && continue
        if [ -e "$lib" ]; then
            dirname "$lib"
            return
        fi
    done
}

# Enable NVIDIA CUDA forward compatibility when the host driver is older than
# the CUDA version this image was built for (e.g. the cu130 image landing on a
# 12.8/12.9 host). The compat libcuda only works on datacenter-class GPUs and
# supported driver branches, and it breaks CUDA if the host driver is newer, so
# it is enabled only after a real cuInit() succeeds with it. Fails open.
setup_cuda_compat() {
    if [ ! -e "$CUDA_COMPAT_DIR/libcuda.so.1" ]; then
        return
    fi

    local host_ver host_rc host_path compat_ver compat_rc compat_path runtime_note=""
    local host_dir override_ver override_rc override_path image_ver opted_out=0
    read -r host_ver host_rc host_path <<< "$(probe_libcuda || echo '0 -1 none')"

    # Opt-out: leave the loader setup exactly as the container runtime made it,
    # including any compat the runtime enabled itself. Checked before the
    # rollback below so it never takes away compat that was working.
    if [ "${DISABLE_CUDA_COMPAT:-}" = "1" ]; then
        opted_out=1
        if [[ "$host_path" == */compat/* ]] && [ "${host_rc:--1}" != "0" ]; then
            CUDA_COMPAT_STATUS="UNAVAILABLE (DISABLE_CUDA_COMPAT=1 left compat enabled by the container runtime in place: $host_path, cuInit returned $host_rc; unset it so start.sh can remove it)"
        elif [[ "$host_path" == */compat/* ]]; then
            CUDA_COMPAT_STATUS="disabled (DISABLE_CUDA_COMPAT=1); compat enabled by the container runtime left in place (CUDA $host_ver via $host_path)"
        else
            CUDA_COMPAT_STATUS="disabled (DISABLE_CUDA_COMPAT=1)"
        fi
    else
        # The container runtime already put compat in the loader cache, so the
        # probe above measured the compat lib, not the host driver. Always remove
        # it and re-probe: the checks below then compare against the real host
        # driver and re-enable compat themselves only when the host is older.
        if [[ "$host_path" == */compat/* ]]; then
            drop_runtime_cuda_compat
            runtime_note="; removed compat enabled by the container runtime (cuInit with it returned $host_rc)"
            read -r host_ver host_rc host_path <<< "$(probe_libcuda || echo '0 -1 none')"
        fi

        # The cache rebuild did not take (e.g. read-only /etc). LD_LIBRARY_PATH
        # is searched ahead of ld.so.cache, so pointing it at the host's libcuda
        # overrides the cached compat entry without touching /etc.
        if [[ "$host_path" == */compat/* ]]; then
            host_dir=$(find_host_libcuda_dir)
            if [ -n "$host_dir" ]; then
                read -r override_ver override_rc override_path <<< "$(LD_LIBRARY_PATH="$host_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" probe_libcuda || echo '0 -1 none')"
                if [ "${override_path:-none}" != "none" ] && [[ "$override_path" != */compat/* ]]; then
                    export LD_LIBRARY_PATH="$host_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
                    runtime_note="; overrode compat enabled by the container runtime with LD_LIBRARY_PATH=$host_dir (cuInit with it returned $host_rc; the loader cache could not be rebuilt)"
                    host_ver=$override_ver host_rc=$override_rc host_path=$override_path
                fi
            fi
        fi

        read -r compat_ver compat_rc compat_path <<< "$(LD_LIBRARY_PATH="$CUDA_COMPAT_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" probe_libcuda || echo '0 -1 none')"
    fi

    if [ "$opted_out" = "1" ]; then
        :
    elif [ "${host_path:-none}" = "none" ]; then
        CUDA_COMPAT_STATUS="skipped (no host NVIDIA driver visible)$runtime_note"
    elif [[ "$host_path" == */compat/* ]]; then
        # Runtime-enabled compat is still active: neither the cache rebuild nor
        # the LD_LIBRARY_PATH override got rid of it. Report what is in use.
        if [ "${host_rc:--1}" = "0" ]; then
            CUDA_COMPAT_STATUS="ENABLED by container runtime, could not be removed (CUDA $host_ver via $host_path)"
        else
            CUDA_COMPAT_STATUS="UNAVAILABLE (container runtime enabled $host_path, cuInit returned $host_rc, and it could not be removed)"
        fi
    elif [ "${compat_ver:-0}" -le 0 ]; then
        # The compat libcuda is in the image but would not load (broken symlink,
        # missing dependency). Compare the host against the toolkit instead.
        image_ver=$(image_cuda_version)
        if [ "${image_ver:-0}" -gt 0 ] && [ "${host_ver:-0}" -ge "$image_ver" ]; then
            CUDA_COMPAT_STATUS="not needed (host driver supports CUDA $host_ver; the bundled compat driver did not load)$runtime_note"
        else
            CUDA_COMPAT_STATUS="UNAVAILABLE (the bundled compat driver did not load; host driver CUDA $host_ver, image CUDA ${image_ver:-unknown})$runtime_note"
        fi
    elif [ "${host_ver:-0}" -ge "${compat_ver:-0}" ]; then
        CUDA_COMPAT_STATUS="not needed (host driver supports CUDA $host_ver)$runtime_note"
    elif [ "${compat_rc:--1}" = "0" ] && [ "$compat_path" != "$host_path" ]; then
        export LD_LIBRARY_PATH="$CUDA_COMPAT_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        CUDA_COMPAT_STATUS="ENABLED (host driver CUDA $host_ver -> CUDA $compat_ver via $compat_path)"
    else
        local reason="cuInit returned $compat_rc"
        case "$compat_rc" in
            804) reason="this GPU does not support CUDA forward compatibility (consumer/GeForce cards are not supported)" ;;
            803) reason="the host driver branch is not supported by the bundled compat driver" ;;
        esac
        CUDA_COMPAT_STATUS="UNAVAILABLE (host driver CUDA $host_ver < image CUDA $compat_ver; $reason)$runtime_note"
    fi

    echo "============================================="
    echo "  CUDA forward compat: $CUDA_COMPAT_STATUS"
    case "$CUDA_COMPAT_STATUS" in
        UNAVAILABLE*)
            echo "  ComfyUI will likely fail with 'The NVIDIA driver on your system is too old'."
            echo "  Redeploy on a host whose driver supports this image's CUDA (filter by CUDA"
            echo "  version), or, for non-Blackwell GPUs, use the ComfyUI CUDA 12.8 template."
            ;;
    esac
    echo "============================================="
}

log_cuda_venv_diagnostics() {
    local expected_build local_packages status
    expected_build=$(sed -n 's/^torch==.*+\(cu[0-9][0-9]*\).*$/\1/p' \
        "$PIP_CONSTRAINT_FILE" | head -n 1)

    echo "============================================="
    echo "  CUDA / venv diagnostics"
    echo "  active venv: $VENV_DIR"
    echo "  expected image torch build: ${expected_build:-unknown}"
    echo "  CUDA forward compat: $CUDA_COMPAT_STATUS"

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

# The image ships SageAttention in the system site-packages, which the venv
# reaches through --system-site-packages. A copy installed into the venv (pip
# install, or a custom node's requirements) comes first on sys.path and is the
# one ComfyUI and custom nodes import, so say so — and when it is older than
# ours, how to drop it. Reads dist-info only: importing needs CUDA.
log_sageattention_override() {
    # Fail open: a crashed probe must not abort startup (set -e).
    VENV_DIR="$VENV_DIR" python - <<'PY' || true
import importlib.metadata as md
import os
import re
import sys

venv = os.path.realpath(sys.prefix) + os.sep


def find(in_venv):
    for entry in sys.path:
        if not entry or not os.path.isdir(entry):
            continue
        if (os.path.realpath(entry) + os.sep).startswith(venv) != in_venv:
            continue
        for dist in md.distributions(path=[entry]):
            if re.sub(r"[-_.]+", "-", dist.metadata["Name"] or "").lower() == "sageattention":
                return dist
    return None


def release(version):
    # "2.2.0+torch2.10.0.cu128.sm90fix1" -> (2, 2, 0); the local part is the build
    parts = [int(n) for n in re.findall(r"\d+", version.split("+")[0])[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def build(version):
    # "2.2.0+torch2.10.0.cu128.sm90fix1" -> ("2.10.0", "cu128"); None without
    # a torch/CUDA build tag (a source build, or PyPI's 1.x). A suffix such as
    # sm90fix1 is not part of it: same torch and CUDA means the same ABI.
    m = re.search(r"\+torch(\d+(?:\.\d+)*)\.(cu\d+)", version)
    return (m.group(1), m.group(2)) if m else None


user, bundled = find(True), find(False)
if user is None or bundled is None:
    sys.exit(0)
venv = os.environ["VENV_DIR"]
pip = os.path.join(venv, "bin", "pip")
ours = build(bundled.version)
theirs = build(user.version)
if release(user.version) < release(bundled.version):
    print(f"WARNING: SageAttention {user.version} installed in {venv} overrides "
          f"the pre-installed {bundled.version}, which is newer and built for this image's "
          "PyTorch and CUDA.")
    print(f"  To use the pre-installed one, uninstall yours: {pip} uninstall -y sageattention")
elif theirs != ours:
    # The build tag, not the release, decides whether it loads: a wheel built
    # for another torch or CUDA fails at import with an undefined symbol,
    # whatever its release number.
    if theirs is None:
        why = ("it has no torch/CUDA build tag, so it may be built for a different "
               "PyTorch or CUDA than this image and fail to load")
    elif ours is None:
        why = (f"it is built for torch {theirs[0]} {theirs[1]}, which may not match "
               "this image's PyTorch and CUDA")
    else:
        why = (f"it is built for torch {theirs[0]} {theirs[1]}, this image has torch "
               f"{ours[0]} {ours[1]}, so it will likely fail to load")
    print(f"WARNING: SageAttention {user.version} installed in {venv} overrides "
          f"the pre-installed {bundled.version}: {why}.")
    print(f"  To use the pre-installed one, uninstall yours: {pip} uninstall -y sageattention")
elif user.version != bundled.version:
    print(f"NOTE: using SageAttention {user.version} installed in {os.environ['VENV_DIR']} "
          f"instead of the pre-installed {bundled.version}.")
    print(f"  If it fails to load, uninstall it to use the pre-installed one: "
          f"{pip} uninstall -y sageattention")
PY
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

# Must run before export_env_vars/Jupyter so SSH and notebook sessions inherit
# the compat LD_LIBRARY_PATH too.
setup_cuda_compat

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
    echo "  COMFYUI_PASSWORD is not set, so ComfyUI was not started."
    echo "  ComfyUI has no login of its own: without a password, anyone"
    echo "  with this pod's :8188 URL could use your GPU and run code here."
    echo "  Set COMFYUI_PASSWORD on the pod and restart it; the browser then"
    echo "  asks for it. Or set COMFYUI_DISABLE_AUTH=true to run ComfyUI with"
    echo "  no password (understand the risk)."
    echo "  SSH, JupyterLab and FileBrowser are not affected."
    echo "============================================="
    hold_pod
    exit 0
fi
if [ "$COMFYUI_AUTH_MODE" = disabled ]; then
    echo "WARNING: COMFYUI_DISABLE_AUTH is set -- starting ComfyUI with NO password: anyone with this pod's :$COMFYUI_PUBLIC_PORT URL can use the GPU and run code in the pod."
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
            case " ${DEP_SKIP_NODES[*]} " in
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
venv_has_activate() { [ -f "$VENV_DIR/bin/activate" ]; }
# The marker is written before the venv is created and removed when the
# migration finishes, so an interrupted migration is redone. Older venvs have
# no marker and stay usable.
venv_is_usable() { venv_has_activate && [ ! -e "$VENV_DIR/$MIGRATION_MARKER" ]; }

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
            # No bin/activate or an interrupted migration. Keep it aside if it
            # holds packages.
            if [ -n "$(ls -A "$VENV_DIR"/lib/python*/site-packages 2>/dev/null)" ]; then
                VENV_BROKEN="${VENV_DIR}.broken.$(date +%Y%m%d%H%M%S)"
                echo "$VENV_DIR is incomplete (no bin/activate, or an interrupted"
                echo "  migration) — moving it to $VENV_BROKEN and starting over."
                echo "  Installed packages are kept there; delete it to free space."
                mv "$VENV_DIR" "$VENV_BROKEN" || true
            else
                echo "Discarding unusable $VENV_DIR and recreating it"
                rm -rf "$VENV_DIR"
            fi
        fi
        if [ -n "$PREVIOUS_VENV" ]; then
            mkdir -p "$VENV_DIR"
            touch "$VENV_DIR/$MIGRATION_MARKER"
        fi
        # --without-pip: pip stays in the image (local disk, bytecode compiled
        # at build) instead of on the network volume, where importing it can
        # exceed ComfyUI-Manager's probe timeout. --system-site-packages keeps
        # it importable, and installs still land in this venv via sys.prefix.
        python3.12 -m venv --system-site-packages --without-pip "$VENV_DIR" || true
        # Keep SSH/Jupyter/FileBrowser reachable instead of crash-looping on a
        # bare `source: No such file or directory`.
        if ! venv_has_activate; then
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

if [ -d "$COMFYUI_DIR/custom_nodes/ComfyUI-Manager" ]; then
    echo "ComfyUI-Manager now ships as a pip package in the image; ComfyUI ignores"
    echo "the copy left in custom_nodes. Your settings, snapshots and installed nodes"
    echo "are unaffected. Delete it to free volume space:"
    echo "  rm -rf $COMFYUI_DIR/custom_nodes/ComfyUI-Manager"
fi

# Interactive sessions are started by sshd, not by this script, and the PATH
# copied into the login files above was captured before the venv existed —
# `python` was then missing entirely and `pip` resolved to the base interpreter.
printf 'if [ -f "%s/bin/activate" ]; then . "%s/bin/activate"; fi\n' \
    "$VENV_DIR" "$VENV_DIR" >> /etc/rp_environment

# Warm up pip before Manager probes it. Log wall time — the Dockerfile raises
# Manager's timeout to 30s.
echo "Warming up pip (Manager timeout is 30s)..."
time python -m pip --version

pin_image_manager
sync_comfyui_pinned_packages

log_cuda_venv_diagnostics
log_sageattention_override

pin_manager_security

# Start ComfyUI — keep container alive if it crashes so SSH/Jupyter remain accessible
cd "$COMFYUI_DIR"

build_comfy_args

# ComfyUI exits at import when --use-sage-attention is set and the package is
# missing, so a volume moved to an image without it (an older tag, or a future
# variant with no wheel) would otherwise leave ComfyUI dead. find_spec only
# locates it: importing needs CUDA.
if [[ " ${COMFY_ARGS[*]} " == *" --use-sage-attention "* ]]; then
    if python -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec("sageattention") is None)'; then
        # Kernels exist for SM 8.0-9.0 and 12.0; elsewhere ComfyUI falls back
        # to PyTorch attention but logs an error on every call.
        compute_caps=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | sort -u | tr '\n' ' ')
        for cap in $compute_caps; do
            case "$cap" in
                8.0|8.6|8.9|9.0|12.0) ;;
                *) echo "WARNING: SageAttention has no kernels for this GPU (compute capability $cap); ComfyUI will fall back to PyTorch attention." ;;
            esac
        done
    else
        echo "WARNING: --use-sage-attention is set but SageAttention is not installed in this image; starting ComfyUI without it."
        filtered_args=()
        for arg in "${COMFY_ARGS[@]}"; do
            [ "$arg" = "--use-sage-attention" ] || filtered_args+=("$arg")
        done
        COMFY_ARGS=("${filtered_args[@]}")
    fi
fi

# Startup is over: from here the crash banner below owns failures, and a live
# ERR trap would also fire on the shutdown path and hold the pod open.
trap - ERR

if [ "$COMFYUI_AUTH_MODE" = proxy ]; then
    run_auth_proxy &
    PROXY_PID=$!
fi

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
    if [ "$COMFYUI_AUTH_MODE" = disabled ]; then
        echo "  ComfyUI is READY on port $COMFYUI_PUBLIC_PORT after $((SECONDS - started))s."
        echo "  It has NO password (COMFYUI_DISABLE_AUTH is set)."
    elif [ "$code" = 401 ]; then
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
