# Upstream vLLM pinned by tag + digest in docker-bake.hcl.
ARG VLLM_IMAGE=non-existing
FROM ${VLLM_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN . /etc/os-release && \
    printf 'deb [signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg snapshot=no] %s %s main universe\n' \
      http://archive.ubuntu.com/ubuntu "${VERSION_CODENAME}-updates" \
      http://security.ubuntu.com/ubuntu "${VERSION_CODENAME}-security" > /tmp/fixes.list && \
    apt_fix=(-o Dir::Etc::SourceList=/tmp/fixes.list -o Dir::Etc::SourceParts=-) && \
    apt-get "${apt_fix[@]}" update && \
    apt-get "${apt_fix[@]}" install --yes --only-upgrade --no-install-recommends \
      openssl libssl3t64 apt apt-utils libapt-pkg6.0t64 \
      dirmngr gnupg gnupg-utils gnupg2 gpg gpg-agent gpgconf gpgsm gpgv keyboxd && \
    rm -rf /tmp/fixes.list /var/lib/apt/lists/* && \
    for fix in libssl3t64:3.0.13-0ubuntu3.16 libapt-pkg6.0t64:2.8.4ubuntu0.1 gpgv:2.4.4-2ubuntu17.4; do \
      cur="$(dpkg-query -W -f='${Version}' "${fix%%:*}")" && \
      dpkg --compare-versions "$cur" ge "${fix#*:}" || { echo "${fix%%:*} $cur < ${fix#*:}"; exit 1; }; \
    done

# mooncake: Go etcd wrapper with critical stdlib/x/net CVEs; only used for
# multi-node KV transfer, which a single Pod never does. PyNvVideoCodec 2.0.4
# bundles FFmpeg 8.1.1; 2.2.4 bundles 9.0.1 and keeps the API vLLM calls.
RUN mooncake="$(python3 -c 'import importlib.metadata as m; print(" ".join(d.metadata["Name"] for d in m.distributions() if d.metadata["Name"].lower().startswith("mooncake")))')" && \
    if [ -n "$mooncake" ]; then read -ra pkgs <<< "$mooncake" && uv pip uninstall --system "${pkgs[@]}"; fi && \
    env -u UV_OVERRIDE uv pip install --system --no-cache PyNvVideoCodec==2.2.4 dnspython==2.9.2 && \
    python3 -c 'import importlib.metadata as m, importlib.util as u; \
assert u.find_spec("mooncake") is None, "mooncake still installed"; \
assert m.version("PyNvVideoCodec") == "2.2.4", m.version("PyNvVideoCodec"); \
assert m.version("dnspython") == "2.9.2", m.version("dnspython")'

COPY --chmod=0644 scripts/runpod_vllm_auth.py /opt/runpod/vllm/runpod_vllm_auth.py
COPY --chmod=0755 scripts/start.sh /start.sh

RUN register="$(python3 -c 'import importlib.util as u; print(u.find_spec("vllm").submodule_search_locations[0])')" && \
    register="$register/entrypoints/serve/middleware/register.py" && \
    { grep -q 'for middleware in args.middleware' "$register" || \
      { echo "vLLM no longer loads --middleware in $register"; exit 1; }; } && \
    PYTHONPATH=/opt/runpod/vllm python3 -c 'import runpod_vllm_auth'

EXPOSE 8000

ENTRYPOINT ["/start.sh"]
