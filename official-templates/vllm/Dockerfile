# Upstream vLLM pinned by tag + digest in docker-bake.hcl.
ARG VLLM_IMAGE=non-existing
FROM ${VLLM_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN . /etc/os-release && \
    printf 'deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg snapshot=no] %s %s main universe\n' \
      http://archive.ubuntu.com/ubuntu "${VERSION_CODENAME}" \
      http://archive.ubuntu.com/ubuntu "${VERSION_CODENAME}-updates" \
      http://security.ubuntu.com/ubuntu "${VERSION_CODENAME}-security" > /tmp/fixes.list && \
    apt_fix=(-o Dir::Etc::SourceList=/tmp/fixes.list -o Dir::Etc::SourceParts=-) && \
    apt-get "${apt_fix[@]}" update && \
    apt-get "${apt_fix[@]}" install --yes --only-upgrade --no-install-recommends \
      openssl libssl3t64 apt apt-utils libapt-pkg6.0t64 \
      dirmngr gnupg gnupg-utils gnupg2 gpg gpg-agent gpgconf gpgsm gpgv keyboxd && \
    DEBIAN_FRONTEND=noninteractive apt-get "${apt_fix[@]}" install --yes --no-install-recommends \
      openssh-server openssh-client && \
    rm -rf /tmp/fixes.list /var/lib/apt/lists/* && \
    sed -i 's/^#*PasswordAuthentication .*/PasswordAuthentication no/' /etc/ssh/sshd_config && \
    grep -q '^PasswordAuthentication no$' /etc/ssh/sshd_config && \
    mkdir -p /run/sshd && \
    ssh-keygen -A -q && /usr/sbin/sshd -t && rm -f /etc/ssh/ssh_host_* && \
    for fix in libssl3t64:3.0.13-0ubuntu3.16 libapt-pkg6.0t64:2.8.4ubuntu0.1 gpgv:2.4.4-2ubuntu17.4; do \
      cur="$(dpkg-query -W -f='${Version}' "${fix%%:*}")"; \
      if ! dpkg --compare-versions "$cur" ge "${fix#*:}"; then echo "${fix%%:*} $cur < ${fix#*:}"; exit 1; fi; \
    done

# mooncake: Go etcd wrapper with critical stdlib/x/net CVEs; only used for
# multi-node KV transfer, which a single Pod never does. PyNvVideoCodec: its
# newest release (2.2.4) bundles FFmpeg 9.0.1 with HIGH CVEs fixed in 9.0.2;
# vLLM imports it only for the opt-in pynvvideocodec video backend (default is
# opencv). opencv-python-headless 5.0.0.93 bundles FFmpeg 8.1.1; 5.1.0.95
# bundles 9.0.2 and needs numpy>=2.
RUN drop="$(python3 -c 'import importlib.metadata as m; print(" ".join(d.metadata["Name"] for d in m.distributions() if d.metadata["Name"].lower().startswith(("mooncake", "pynvvideocodec"))))')" && \
    if [ -n "$drop" ]; then read -ra pkgs <<< "$drop" && uv pip uninstall --system "${pkgs[@]}"; fi && \
    env -u UV_OVERRIDE uv pip install --system --no-cache dnspython==2.9.2 \
      opencv-python-headless==5.1.0.95 && \
    python3 -c 'import importlib.metadata as m, importlib.util as u; \
assert u.find_spec("mooncake") is None, "mooncake still installed"; \
assert u.find_spec("PyNvVideoCodec") is None, "PyNvVideoCodec still installed"; \
assert m.version("dnspython") == "2.9.2", m.version("dnspython"); \
assert m.version("opencv-python-headless") == "5.1.0.95", m.version("opencv-python-headless"); \
import cv2, numpy; assert int(numpy.__version__.split(".")[0]) >= 2, numpy.__version__'

# Fail on any bundled FFmpeg below 9.0.2, naming the file. Same files Grype's
# ffmpeg rule reads (libav*, libswresample*, ffmpeg), minus apt-owned ones,
# which Grype skips too.
RUN uv cache clean && \
    rm -rf /opt/uv/cache /opt/pip/cache /root/.cache/uv /root/.cache/pip && \
    stale="" && \
    while IFS= read -r -d '' f; do \
      dpkg -S "$f" >/dev/null 2>&1 && continue; \
      v="$(grep -a -oE 'FFmpeg version [0-9]+\.[0-9]+(\.[0-9]+)?' "$f" | head -1 | awk '{print $3}')" || true; \
      echo "bundled FFmpeg: $f (${v:-no version string})"; \
      if [ -n "$v" ] && dpkg --compare-versions "$v" lt 9.0.2; then stale+="  $f ($v)"$'\n'; fi; \
    done < <(find / \( -path /proc -o -path /sys -o -path /dev -o -path /var/lib/dpkg \) -prune -o -type f \
               \( -name 'libav*' -o -name 'libswresample*' -o -name 'ffmpeg' \) -print0) && \
    if [ -n "$stale" ]; then printf 'FFmpeg below 9.0.2 still in the image:\n%s' "$stale"; exit 1; fi

COPY --chmod=0644 scripts/runpod_vllm_auth.py /opt/runpod/vllm/runpod_vllm_auth.py
COPY --chmod=0644 scripts/runpod_vllm_cmdcheck.py /opt/runpod/vllm/runpod_vllm_cmdcheck.py
COPY --chmod=0755 scripts/start.sh /start.sh

RUN register="$(python3 -c 'import importlib.util as u; print(u.find_spec("vllm").submodule_search_locations[0])')" && \
    register="$register/entrypoints/serve/middleware/register.py" && \
    { grep -q 'for middleware in args.middleware' "$register" || \
      { echo "vLLM no longer loads --middleware in $register"; exit 1; }; } && \
    PYTHONPATH=/opt/runpod/vllm python3 -c 'import runpod_vllm_auth'

# Models download to the Pod volume, not the small container disk.
ENV HF_HOME=/workspace/.huggingface

EXPOSE 8000

ENTRYPOINT ["/start.sh"]
