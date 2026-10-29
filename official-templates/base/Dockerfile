ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

ARG RP_SKIP_PYTHON

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV SHELL=/bin/bash
ENV PYTHONUNBUFFERED=True
ENV DEBIAN_FRONTEND=noninteractive

# Set the default workspace directory
ENV RP_WORKSPACE=/workspace

# Override the default huggingface cache directory.
ENV HF_HOME="${RP_WORKSPACE}/.cache/huggingface/"

# Shared python package cache
ENV VIRTUALENV_OVERRIDE_APP_DATA="${RP_WORKSPACE}/.cache/virtualenv/"
ENV PIP_CACHE_DIR="${RP_WORKSPACE}/.cache/pip/"
ENV UV_CACHE_DIR="${RP_WORKSPACE}/.cache/uv/"

# Faster transfer of models from the hub to the container
ENV HF_HUB_ENABLE_HF_TRANSFER=1
ENV HF_XET_HIGH_PERFORMANCE=1

# modern pip workarounds
ENV PIP_BREAK_SYSTEM_PACKAGES=1
ENV PIP_ROOT_USER_ACTION=ignore

# Set TZ and Locale
ENV TZ=Etc/UTC

WORKDIR /

RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Install.
# 26.04 dropped ATLAS (libopenblas-dev is the BLAS that replaces it) and
# libpostproc, which FFmpeg 8 removed. 24.04 keeps its existing set.
RUN . /etc/os-release && \
    case "${VERSION_ID}" in \
      24.04) release_pkgs="libatlas-base-dev libpostproc-dev" ;; \
      *) release_pkgs="libopenblas-dev" ;; \
    esac && \
    apt-get update --yes && \
    apt-get upgrade --yes && \
    apt-get install --yes --no-install-recommends \
    build-essential ca-certificates cifs-utils cmake curl dirmngr dnsutils ffmpeg \
    file gfortran git gpg gpg-agent inetutils-traceroute inotify-tools iputils-ping jq \
    libavcodec-dev libavfilter-dev libavformat-dev libblas-dev libffi-dev \
    libgl1 libhdf5-dev libjpeg-dev liblapack-dev libnuma-dev libpng-dev ${release_pkgs} \
    libsm6 libssl-dev libswscale-dev libtiff-dev libv4l-dev libx264-dev libxrender-dev \
    libxvidcore-dev lsof make mtr nano nfs-common nginx openssh-server rsync slurm-wlm \
    software-properties-common sudo tmux unzip vim wget zip zstd && \
    rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub && \
    rm -rf /var/lib/apt/lists/*

# CON-1869: CUDA bases pin apt to a snapshot that lags the emSign removal
# (CVE-2026-111943), and plain `apt-get upgrade` there only reaches the stale
# version. Pull the patched ca-certificates from the archive over https,
# checksum it, and install only when newer so we never downgrade a fresher one.
RUN . /etc/os-release && \
    ver="20260816ubuntu0.${VERSION_ID}.1" && \
    deb="ca-certificates_${ver}_all.deb" && \
    case "${VERSION_ID}" in \
      24.04) sha=8a0a754aaafed72cc8efb8c1731808133284a84fbfc76a4fcc73fce9e01b4187 ;; \
      26.04) sha=5b6326f1932cfd7be57130561dc78192f09ed9f58bfbe6606ed0c50510c3b6cd ;; \
      *) echo "no pinned ca-certificates for ${VERSION_ID}" && exit 1 ;; \
    esac && \
    cur="$(dpkg-query -W -f='${Version}' ca-certificates 2>/dev/null || echo 0)" && \
    if dpkg --compare-versions "$cur" lt "$ver"; then \
      curl -fsSL --proto '=https' --tlsv1.2 -o "/tmp/${deb}" \
        "https://security.ubuntu.com/ubuntu/pool/main/c/ca-certificates/${deb}" && \
      echo "${sha}  /tmp/${deb}" | sha256sum -c - && \
      dpkg -i "/tmp/${deb}" && rm "/tmp/${deb}"; \
    fi && \
    update-ca-certificates
    
# Strip AWS EFA Nsight plugin — AWS-only hardware, not used on RunPod.
# Its nic_sampler Go binary ships old Go stdlib that triggers HIGH Trivy CVEs.
RUN find /opt/nvidia /usr/local/cuda* -type d -name 'efa_metrics' \
        -print -exec rm -rf {} + 2>/dev/null || true

# Install Python versions. Each Ubuntu release gets its system interpreter from
# the archive and the rest from deadsnakes (24.04: 3.12, 26.04: 3.14), so the
# same list resolves on both.
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get install --yes --no-install-recommends \
        python3.11-dev python3.11-venv python3.11-distutils \
        python3.12-dev python3.12-venv \
        python3.13-dev python3.13-venv && \
    . /etc/os-release && \
    if [[ "${VERSION_ID}" != "24.04" ]]; then \
      apt-mark manual lsb-release libcap2-bin && \
      apt-get purge --yes software-properties-common && \
      apt-get autoremove --purge --yes; \
    fi && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*;

# /usr/lib/python3/dist-packages holds apt's modules, built for the system
# python3 only, yet every Debian-built interpreter puts it on sys.path. On 26.04
# that includes the default 3.12: pip counts apt's cryptography as installed and
# it then fails to import. Hide it from all but the system interpreter.
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    sys_ver="$(/usr/bin/python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')" && \
    for v in 3.11 3.12 3.13; do \
      [[ "$v" == "$sys_ver" ]] && continue; \
      printf '%s\n' \
        'import sys' \
        'sys.path[:] = [p for p in sys.path if p != "/usr/lib/python3/dist-packages"]' \
        >> "/etc/python${v}/sitecustomize.py" || exit 1; \
    done;

# Install pip via verified get-pip.py
ARG GET_PIP_COMMIT=0d4515b4d114f9cd820446a4bd4bd0986393d454
ARG GET_PIP_SHA256=66904bccb878e363db6236ea900e6935e507dcb887e9f178f6212edfe7f46a76
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/get-pip.py \
        "https://raw.githubusercontent.com/pypa/get-pip/${GET_PIP_COMMIT}/public/get-pip.py" && \
    echo "${GET_PIP_SHA256}  /tmp/get-pip.py" | sha256sum -c - && \
    python3.11 /tmp/get-pip.py && \
    python3.12 /tmp/get-pip.py && \
    python3.13 /tmp/get-pip.py && \
    rm /tmp/get-pip.py

# Install virtualenv
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    for py in python3.11 python3.12 python3.13; do \
      "$py" -m pip install --upgrade --no-cache-dir \
        "pip==26.2.0" "virtualenv==21.14.13" "filelock==4.2.1" || exit 1; \
    done;

# Symlink default python/pip. python3 too: on 26.04 the system one is 3.14.
RUN [[ -n "$RP_SKIP_PYTHON" ]] && exit 0; \
    ln -sf /usr/bin/python3.12 /usr/local/bin/python && \
    ln -sf /usr/bin/python3.12 /usr/local/bin/python3 && \
    ln -sf /usr/local/bin/pip3.12 /usr/local/bin/pip && \
    ln -sf /usr/local/bin/pip3.12 /usr/local/bin/pip3;

COPY --from=ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b /uv /uvx /bin/

# Drop any pip-installed uv from the base image (e.g. NGC ships an old one in
# /usr/local/bin that shadows our pinned /bin/uv and trips Grype).
RUN pip uninstall -y uv 2>/dev/null || true

COPY --from=requirements requirements.txt /requirements.txt
COPY --from=scrub_stale_metadata scrub-stale-metadata.py /tmp/scrub-stale-metadata.py

# Install Jupyter and hf_transfer packages
RUN python -m pip install --upgrade --no-cache-dir -r requirements.txt && \
    python /tmp/scrub-stale-metadata.py /requirements.txt && \
    rm /tmp/scrub-stale-metadata.py

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy snippets /etc/nginx/snippets
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Script
COPY --from=scripts --chmod=755 start.sh /

# Welcome Message
COPY --from=logo runpod.txt /etc/runpod.txt
RUN cat >> /root/.bashrc <<'EOF'
cat /etc/runpod.txt
cat <<'BANNER'

For detailed documentation and guides, please visit:
https://docs.runpod.io/
and https://blog.runpod.io

BANNER
EOF

CMD ["/start.sh"]
