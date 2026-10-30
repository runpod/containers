# syntax=docker/dockerfile:1
# k3s agent image for Runpod K8S clusters: every pod of a K8S cluster runs it, under the
# sysbox-runc runtime, on CPU and NVIDIA hosts (amd64 and arm64).
#
# Why not FROM rancher/k3s: that image is busybox without glibc. On a GPU host the node container
# gets the driver libraries as a CDI device, and the NVIDIA CDI hooks (glibc binaries) must run in
# the node to create the library symlinks and update the ld cache for pods. This image adds glibc
# (Ubuntu) and nvidia-container-toolkit. k3s also detects /usr/bin/nvidia-container-runtime at start
# and adds an "nvidia" containerd runtime and RuntimeClass.
#
# WireGuard: the node reaches the server through a tunnel (see k3s-node.sh). The host kernel has
# WireGuard, and the node container (sysbox) may create the interface: no TUN device needed.
ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

ARG K3S_VERSION
ARG K3S_SHA256_AMD64
ARG K3S_SHA256_ARM64
ARG NVIDIA_CTK_VERSION
# runc for k3s: v1.37.1+k3s1 bundles runc 1.4.2, below the security minimum 1.4.3. k3s-node.sh
# swaps it in. REMOVE these, the download below and the swap in k3s-node.sh once a k3s release
# bundles runc >= 1.4.3 (check the "Runc" row in the k3s release notes).
ARG RUNC_VERSION
ARG RUNC_SHA256_AMD64
ARG RUNC_SHA256_ARM64
# Set by BuildKit: amd64 for x86 hosts, arm64 for GB10/Grace hosts.
ARG TARGETARCH

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# The k3s release binary is self-contained: containerd, runc, flannel and iptables extract to
# /var/lib/rancher/k3s/data on first start. Its name and checksum depend on the architecture.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && case "${TARGETARCH}" in \
      amd64) k3s_bin=k3s;       k3s_sha=${K3S_SHA256_AMD64}; runc_sha=${RUNC_SHA256_AMD64} ;; \
      arm64) k3s_bin=k3s-arm64; k3s_sha=${K3S_SHA256_ARM64}; runc_sha=${RUNC_SHA256_ARM64} ;; \
      *) echo "unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac \
 && curl -fsSLo /bin/k3s "https://github.com/k3s-io/k3s/releases/download/${K3S_VERSION/+/%2B}/${k3s_bin}" \
 && echo "${k3s_sha}  /bin/k3s" | sha256sum -c - \
 && chmod 0755 /bin/k3s \
 && mkdir -p /usr/local/lib/k3s-node \
 && curl -fsSLo /usr/local/lib/k3s-node/runc "https://github.com/opencontainers/runc/releases/download/${RUNC_VERSION}/runc.${TARGETARCH}" \
 && echo "${runc_sha}  /usr/local/lib/k3s-node/runc" | sha256sum -c - \
 && chmod 0755 /usr/local/lib/k3s-node/runc \
 && curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
 && curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
    "nvidia-container-toolkit=${NVIDIA_CTK_VERSION}" "nvidia-container-toolkit-base=${NVIDIA_CTK_VERSION}" \
    "libnvidia-container-tools=${NVIDIA_CTK_VERSION}" "libnvidia-container1=${NVIDIA_CTK_VERSION}" \
    wireguard-tools iproute2 openssl \
 && apt-get purge -y curl gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Same volumes and environment as rancher/k3s. Volumes keep containerd's snapshots off the
# container's overlayfs.
VOLUME ["/var/lib/kubelet", "/var/lib/rancher/k3s", "/var/lib/cni", "/var/log"]
ENV PATH="/var/lib/rancher/k3s/data/cni:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    CRI_CONFIG_FILE=/var/lib/rancher/k3s/agent/etc/crictl.yaml

# Sets the kubelet's system-reserved to what the Runpod pod does not rent (see k3s-node.sh).
COPY --chmod=0755 k3s-node.sh /usr/local/bin/k3s-node
ENTRYPOINT ["/usr/local/bin/k3s-node"]
CMD ["agent"]
