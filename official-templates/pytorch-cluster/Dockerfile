# The `-cluster` variant: a thin layer on top of runpod/pytorch that adds the
# RDMA/InfiniBand user-space stack plus a self-contained monitoring stack
# (DCGM + node_exporter on every node; Prometheus + Grafana on node-0).
#
# BASE_IMAGE is a published runpod/pytorch tag (see docker-bake.hcl).

ARG BASE_IMAGE=non-existing

# dcgm-exporter binary source. We lift only the exporter binary + default
# counter CSVs from NVIDIA's pinned image; the DCGM runtime it links against
# (libdcgm) is installed via apt below and must share the same DCGM major
# version (4.x) as this image.
# ⚠️ If bumping the tag, re-verify /usr/bin/dcgm-exporter and /etc/dcgm-exporter.
ARG DCGM_EXPORTER_IMAGE=nvcr.io/nvidia/k8s/dcgm-exporter:4.5.2-4.8.1-ubuntu22.04
FROM ${DCGM_EXPORTER_IMAGE} AS dcgm-exporter-src

FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# DCGM runtime package. `datacenter-gpu-manager-4` is a virtual package; apt
# needs the concrete CUDA-major provider (datacenter-gpu-manager-4-cuda12 for
# CUDA 12.x bases, -cuda13 for CUDA 13.x). docker-bake.hcl sets this per matrix
# entry; the default matches the CUDA 12.x targets.
# ⚠️ Its DCGM major (4.x) must match DCGM_EXPORTER_IMAGE.
ARG DCGM_PACKAGE=datacenter-gpu-manager-4-cuda12

# RDMA/InfiniBand user-space stack, supervisor (process manager for the
# monitoring daemons), the DCGM runtime (provides libdcgm for the embedded
# dcgm-exporter), and MariaDB (server + client) for the Slurm accounting
# (slurmdbd) backend on node-0. The NVIDIA CUDA apt repo is already configured
# in the base image.
RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
        libibverbs1 ibverbs-providers rdma-core ibverbs-utils infiniband-diags perftest \
        supervisor \
        unzip \
        mariadb-server mariadb-client \
        "${DCGM_PACKAGE}" && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# node_exporter — system metrics (pinned + SHA-256 verified).
ARG NODE_EXPORTER_VERSION=1.11.1
ARG NODE_EXPORTER_SHA256=9f5ea48e5bc7b656f8a91a32e7d7deb89f70f73dabd0d974418aca15f37d6810
RUN curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/node_exporter.tar.gz \
        "https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz" && \
    echo "${NODE_EXPORTER_SHA256}  /tmp/node_exporter.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/node_exporter.tar.gz -C /tmp && \
    mv "/tmp/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter" /usr/local/bin/node_exporter && \
    chmod +x /usr/local/bin/node_exporter && \
    rm -rf /tmp/node_exporter*

# Prometheus — scraper + query engine (pinned + SHA-256 verified).
ARG PROMETHEUS_VERSION=3.13.1
ARG PROMETHEUS_SHA256=962b812371aff838d152b6ff2d56fdb7a6396f5542f48ebf73421b9721f0d103
RUN curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/prometheus.tar.gz \
        "https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz" && \
    echo "${PROMETHEUS_SHA256}  /tmp/prometheus.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/prometheus.tar.gz -C /tmp && \
    mv "/tmp/prometheus-${PROMETHEUS_VERSION}.linux-amd64/prometheus" /usr/local/bin/prometheus && \
    mv "/tmp/prometheus-${PROMETHEUS_VERSION}.linux-amd64/promtool" /usr/local/bin/promtool && \
    chmod +x /usr/local/bin/prometheus /usr/local/bin/promtool && \
    rm -rf /tmp/prometheus*

# Grafana OSS — dashboards (pinned + SHA-256 verified).
ARG GRAFANA_VERSION=13.1.0
ARG GRAFANA_BUILD=28013217238
ARG GRAFANA_SHA256=4f562bb224b8bb758b47789381babb284cb41687da8d714f2ff0e118e945e775
RUN curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/grafana.tar.gz \
        "https://dl.grafana.com/grafana/release/${GRAFANA_VERSION}/grafana_${GRAFANA_VERSION}_${GRAFANA_BUILD}_linux_amd64.tar.gz" && \
    echo "${GRAFANA_SHA256}  /tmp/grafana.tar.gz" | sha256sum -c - && \
    mkdir -p /usr/share/grafana && \
    tar -xzf /tmp/grafana.tar.gz -C /usr/share/grafana --strip-components=1 && \
    ln -sf /usr/share/grafana/bin/grafana /usr/local/bin/grafana && \
    rm -f /tmp/grafana.tar.gz

# Loki — log aggregation store, head-node only (pinned + SHA-256 verified).
# Ships as a zip (bare `loki-linux-amd64` binary, no wrapping dir) — hence unzip
# above, unlike the tar.gz downloads. ⚠️ Re-verify the extracted name on bumps.
ARG LOKI_VERSION=3.7.3
ARG LOKI_SHA256=cd28bc1e12f005c39fdf3c49e6be793206749b0f16db5eed742727b484a027ae
RUN curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/loki.zip \
        "https://github.com/grafana/loki/releases/download/v${LOKI_VERSION}/loki-linux-amd64.zip" && \
    echo "${LOKI_SHA256}  /tmp/loki.zip" | sha256sum -c - && \
    unzip -o /tmp/loki.zip -d /tmp && \
    mv /tmp/loki-linux-amd64 /usr/local/bin/loki && \
    chmod +x /usr/local/bin/loki && \
    rm -f /tmp/loki.zip

# Grafana Alloy — log shipper, runs on every node (pinned + SHA-256 verified).
# Alloy is the supported successor to Promtail (Promtail is EOL and was dropped
# from Loki releases after 3.5.x). Separate repo/versioning from Loki. Ships as
# a zip with a bare `alloy-linux-amd64` binary.
ARG ALLOY_VERSION=1.17.1
ARG ALLOY_SHA256=b92bfa2815a0a2c51477b4965d1ace3bf2ffc7b841e1361bd4cda6069e8c65bd
RUN curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/alloy.zip \
        "https://github.com/grafana/alloy/releases/download/v${ALLOY_VERSION}/alloy-linux-amd64.zip" && \
    echo "${ALLOY_SHA256}  /tmp/alloy.zip" | sha256sum -c - && \
    unzip -o /tmp/alloy.zip -d /tmp && \
    mv /tmp/alloy-linux-amd64 /usr/local/bin/alloy && \
    chmod +x /usr/local/bin/alloy && \
    rm -f /tmp/alloy.zip

# dcgm-exporter — GPU metrics (embedded DCGM mode; links libdcgm from apt).
COPY --from=dcgm-exporter-src /usr/bin/dcgm-exporter /usr/local/bin/dcgm-exporter
COPY --from=dcgm-exporter-src /etc/dcgm-exporter /etc/dcgm-exporter
# Runpod extended counter set (DCP profiling + reliability fields used by the
# dashboards). Sourced from runpod/ansible-host monitoring role.
COPY config/dcgm/extended-counters.csv /etc/dcgm-exporter/extended-counters.csv

# Monitoring config + supervisor programs + the start hook.
COPY config/supervisor/cluster.conf /etc/supervisor/conf.d/cluster.conf
COPY config/grafana.ini /etc/grafana/grafana.ini
COPY config/provisioning /etc/grafana/provisioning
# Log-aggregation config: Loki (head-node store) + Alloy (per-node shipper).
COPY config/loki/loki.yaml /etc/loki/loki.yaml
COPY config/alloy/config.alloy /etc/alloy/config.alloy
# MariaDB drop-in tuning for the Slurm accounting backend (head-node only).
COPY config/mariadb/99-slurm-acct.cnf /etc/mysql/mariadb.conf.d/99-slurm-acct.cnf
# Tiny shared-token front proxy for Grafana (mirrors Jupyter's token model and
# reuses the same JUPYTER_PASSWORD secret, passed in the URL as ?token=). Pure
# stdlib — no extra deps. It checks the token and injects the auth.proxy header.
COPY config/grafana-proxy/auth_proxy.py /opt/grafana-proxy/auth_proxy.py
# Pre-baked Grafana dashboards (loaded by the provisioning provider above).
COPY config/dashboards /var/lib/grafana/dashboards
COPY --chmod=755 post_start.sh /post_start.sh

RUN mkdir -p /etc/prometheus /var/lib/prometheus \
             /var/lib/grafana /var/log/grafana /var/log/supervisor \
             /var/lib/loki /var/lib/alloy/data

# Exposed service: the Grafana UI is served on 8889 (via the auth proxy). The
# Runpod template for this variant must map 8889/HTTP named "Grafana".
# (Inherited from pytorch/base: 8888 Jupyter, 22 SSH, 8080 filebrowser.)
EXPOSE 8889
LABEL com.runpod.template.variant="pytorch-cluster" \
      com.runpod.ports.8889="Grafana (HTTP)"

# CMD ["/start.sh"] is inherited from the base image; /start.sh runs
# /post_start.sh, which is where the cluster monitoring is brought up.
