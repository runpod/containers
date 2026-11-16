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
BAKED_NODES=("ComfyUI-Manager" "ComfyUI-KJNodes" "Civicomfy" "ComfyUI-RunpodDirect")

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
        case " ${BAKED_NODES[*]} " in
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
    # "2.2.0+torch2.10.0.cu128.sm90fix1" -> "torch2.10.0.cu128.sm90fix1"
    return version.partition("+")[2]


user, bundled = find(True), find(False)
if user is None or bundled is None:
    sys.exit(0)
pip = os.path.join(os.environ["VENV_DIR"], "bin", "pip")
if release(user.version) < release(bundled.version):
    print(f"WARNING: SageAttention {user.version} installed in {os.environ['VENV_DIR']} overrides "
          f"the pre-installed {bundled.version}, which is newer and built for this image's "
          "PyTorch and CUDA.")
    print(f"  To use the pre-installed one, uninstall yours: {pip} uninstall -y sageattention")
elif release(user.version) == release(bundled.version) and build(user.version) != build(bundled.version):
    print(f"WARNING: SageAttention {user.version} installed in {os.environ['VENV_DIR']} overrides "
          f"the pre-installed {bundled.version}: the same release, but built for a different "
          "PyTorch or CUDA than this image, so it will likely fail to load.")
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

setup_ssh
export_env_vars

# Initialize FileBrowser if not already done
if [ ! -f "$DB_FILE" ]; then
    echo "Initializing FileBrowser..."
    filebrowser config init
    filebrowser config set --address 0.0.0.0
    filebrowser config set --port 8080
    filebrowser config set --root /workspace
    filebrowser config set --auth.method=json
    filebrowser users add admin "${FILEBROWSER_PASSWORD:-adminadmin12}" --perm.admin
else
    echo "Using existing FileBrowser configuration..."
fi

# Start FileBrowser
echo "Starting FileBrowser on port 8080..."
nohup filebrowser &> /filebrowser.log &

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
    pkill -TERM -f "jupyter-lab" 2>/dev/null || true
    pkill -TERM -x "filebrowser" 2>/dev/null || true
    exit 0
}
trap on_shutdown SIGTERM SIGINT

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
log_sageattention_override

# Start ComfyUI — keep container alive if it crashes so SSH/Jupyter remain accessible
cd "$COMFYUI_DIR"

# Array, not a string: argparse needs each flag as its own argv entry.
# No --enable-cors-header: bare, it lets any website's page call this ComfyUI
# from the visitor's browser. Owners who need it add it with their own origin
# to comfyui_args.txt.
COMFY_ARGS=(--listen 0.0.0.0 --port 8188)

# One array element per word, since a line may hold `--foo bar`.
if [ -s "$ARGS_FILE" ]; then
    while read -r word; do
        if [ -n "$word" ]; then
            COMFY_ARGS+=("$word")
        fi
    done < <(grep -v '^[[:space:]]*#' "$ARGS_FILE" | tr -s '[:space:]' '\n')
fi

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

echo "Starting ComfyUI with args: ${COMFY_ARGS[*]}"
python main.py "${COMFY_ARGS[@]}" &
COMFY_PID=$!

# ComfyUI-Manager's "All startup tasks have been completed" trails the usable
# UI by minutes while it pages through api.comfy.org, so announce the port
# itself. Users read that line as the ready signal and stop pods before it.
announce_when_ready() {
    local started=$SECONDS
    until curl -fs -o /dev/null --max-time 2 http://127.0.0.1:8188/; do
        kill -0 "$COMFY_PID" 2>/dev/null || return
        sleep 2
    done
    echo "============================================="
    echo "  ComfyUI is READY on port 8188 after $((SECONDS - started))s."
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
