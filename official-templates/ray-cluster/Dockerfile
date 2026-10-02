# The `-ray-cluster` variant: a Ray head/worker cluster image layered on top of
# runpod/pytorch's `-cluster` variant, so it inherits the full cluster feature
# set — the RDMA/InfiniBand user-space stack and the self-contained monitoring
# stack (DCGM + node_exporter on every node; Prometheus + Grafana on node-0) —
# and adds Ray on top, with Ray's own metrics wired into that Prometheus.
#
# Design: the host daemon injects only the topology env and observes Ray from
# outside the container (dashboard :8265 for readiness/liveness, Ray metrics on
# RAY_METRICS_PORT). The image owns launch: /ray-entrypoint.sh runs `ray start`
# (head/worker), fabric preflight, and metrics-port pinning. There is no
# host-injected init script. See runpod/host docs/ray-init-refactor.md.
#
# BASE_IMAGE is a published runpod/pytorch `-cluster` tag (see docker-bake.hcl).

ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Pin Ray so the dashboard/metrics/nodes payload shapes the host parses
# (pkg/rayready, pkg/raymetrics) stay stable across image rebuilds. >= 2.53 for
# the unified /api/healthz endpoint the host and the local probe rely on.
ARG RAY_VERSION=2.53.0
RUN python -m pip install --no-cache-dir "ray[default]==${RAY_VERSION}" hf_transfer

# Ray launch + health assets. fabric.sh is the preflight library the image now
# owns (the daemon no longer bind-mounts it for Ray). ray.conf hands the Ray
# process to the inherited supervisord.
COPY --chmod=755 ray-entrypoint.sh /ray-entrypoint.sh
COPY --chmod=755 ray-health.sh /ray-health.sh
COPY config/fabric.sh /opt/ray-cluster/fabric.sh
COPY config/supervisor/ray.conf /etc/supervisor/conf.d/ray.conf
# Ray Grafana dashboard, dropped alongside the inherited GPU/system dashboards
# (the provisioning provider loads every file in this directory).
COPY config/dashboards/06-ray-cluster.json /var/lib/grafana/dashboards/06-ray-cluster.json

# Preserve the inherited monitoring bringup, then install our orchestrator on
# top: our /post_start.sh calls /post_start.cluster.sh (the parent's) and then
# wires Ray scraping into Prometheus. See post_start.sh.
RUN mv /post_start.sh /post_start.cluster.sh
COPY --chmod=755 post_start.sh /post_start.sh

# Exposed to the host (all host-internal, reached on the docker bridge; the
# daemon leaves them unmapped):
#   8265  Ray dashboard (readiness/liveness poll target)
#   8080  Ray Prometheus metrics (RAY_METRICS_PORT; host scrape target)
#   52365 Ray dashboard agent (per-node raylet healthz)
#   6379  Ray GCS (workers register here)
# 8889 Grafana (HTTP) is inherited from the -cluster base.
EXPOSE 8265 8080 52365 6379

# Local health signal (defence-in-depth; the authoritative verdict is host-side).
# Long start-period: multi-node formation can take a while on cold nodes.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD /ray-health.sh liveness || exit 1

LABEL com.runpod.template.variant="ray-cluster" \
      com.runpod.ports.8265="Ray Dashboard (HTTP)"

# CMD ["/start.sh"] is inherited from the base image; /start.sh runs
# /post_start.sh, which brings up monitoring + Ray.
