# The `ray-cluster` image: Runpod's supported Ray cluster image, layered on
# runpod/pytorch-cluster so it inherits the RDMA/InfiniBand
# user-space stack and the monitoring stack (DCGM + node_exporter on every node;
# Prometheus + Grafana on the head), with Ray's metrics wired into it.
#
# Contract v1 with runpod/host: the host injects only topology env and observes
# Ray from outside the container (dashboard 8265 for readiness/liveness, Ray
# metrics on 20217). The image owns launch: the ENTRYPOINT starts Ray, then
# execs the CMD. Customers extend it with `FROM runpod/ray-cluster:<tag>`,
# keeping the ENTRYPOINT, the Ray version and the contract ports. See
# README.md and runpod/host docs/ray-init-refactor.md.
#
# BASE_IMAGE is a published runpod/pytorch-cluster tag (see docker-bake.hcl).

ARG BASE_IMAGE=non-existing
FROM ${BASE_IMAGE}

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive

# Pinned Ray: head and workers share this image, so versions always match, and
# the host's version-sensitive parsers (pkg/rayready, pkg/raymetrics) are
# validated against it. >= 2.53 for the unified /api/healthz endpoint.
ARG RAY_VERSION=2.53.0
RUN python -m pip install --no-cache-dir "ray[default]==${RAY_VERSION}" hf_transfer

# Static defaults. The two ports are fixed by contract v1 and the entrypoint
# refuses overrides; they are exported so customer code can read them.
# NCCL_NET_GDR_LEVEL only takes effect when NCCL uses IB.
ENV RAY_CLUSTER_RAY_VERSION=${RAY_VERSION} \
    RAY_GCS_PORT=6379 \
    RAY_DASHBOARD_PORT=8265 \
    RAY_METRICS_PORT=20217 \
    RAY_USAGE_STATS_ENABLED=0 \
    NCCL_SOCKET_FAMILY=AF_INET \
    NCCL_DEBUG=WARN \
    NCCL_NET_GDR_LEVEL=PHB

COPY --chmod=755 ray/entrypoint.sh /opt/runpod/ray/entrypoint
COPY --chmod=755 ray/health.sh /opt/runpod/ray/health
COPY --chmod=755 ray/fabric_probe.py /opt/runpod/ray/fabric-probe

# Dashboard access proxy: the dashboard on 8265 is unauthenticated job
# submission (ShadowRay, CVE-2023-48022) and stays unmapped; this token-gated
# proxy (supervisord program started by post_start.sh on the head) exposes the
# same UI behind JUPYTER_PASSWORD / RAY_DASHBOARD_PASSWORD on 8266, the one
# dashboard port safe to expose through Runpod's proxy.
COPY ray/dashboard_proxy.py /opt/runpod/ray/dashboard-proxy
COPY config/supervisor/ray-dashboard-proxy.conf /etc/supervisor/conf.d/ray-dashboard-proxy.conf

# Head metrics stack: Ray's generated dashboards next to the inherited ones,
# plus Runpod's Ray overview, and capped Prometheus retention so the stack
# can't fill the head's disk.
COPY config/provisioning/dashboards/ray.yml /etc/grafana/provisioning/dashboards/ray.yml
COPY config/dashboards/06-ray-cluster.json /var/lib/grafana/dashboards/06-ray-cluster.json
RUN sed -i 's|--web.listen-address=127.0.0.1:9090|& --storage.tsdb.retention.time=7d --storage.tsdb.retention.size=10GB|' \
        /etc/supervisor/conf.d/cluster.conf && \
    grep -q -- '--storage.tsdb.retention.size=10GB' /etc/supervisor/conf.d/cluster.conf

# Keep the inherited monitoring bringup; our /post_start.sh runs it, then wires
# Ray scraping into Prometheus.
RUN mv /post_start.sh /post_start.cluster.sh
COPY --chmod=755 post_start.sh /post_start.sh

# Host-internal (reached on the docker bridge, left unmapped by the daemon):
#   8265  Ray dashboard: host readiness/liveness poll. Not exposed through the
#         Runpod proxy: it is unauthenticated and allows job submission.
#   20217 Ray metrics: host scrape and the head's Prometheus
#   52365 Ray dashboard agent: local HEALTHCHECK
#   6379  Ray GCS: workers register here
#   8266  Ray dashboard, behind the token-gated proxy on the head: the one
#         dashboard port safe to expose through the Runpod proxy
# 8889 Grafana (token-authenticated) is inherited from the -cluster base.
EXPOSE 8265 20217 52365 6379 8266

# Local, defence-in-depth signal; the authoritative verdict is host-side.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD /opt/runpod/ray/health || exit 1

LABEL com.runpod.template.variant="ray-cluster" \
      com.runpod.ray-cluster.contract="v1"

ENTRYPOINT ["/opt/runpod/ray/entrypoint"]
CMD ["/start.sh"]
