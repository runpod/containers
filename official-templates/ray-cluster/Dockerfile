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
# validated against it. >= 2.54 so token authentication (RAY_AUTH_MODE) also
# covers the dashboard agent's HTTP server (52365), which serves job submission.
ARG RAY_VERSION=2.59.0
# Ray's own dependencies are pinned in requirements.txt; hf_transfer comes
# pinned from the base image. The wheel's bundled Java runtime (ray/jars) is
# removed: Java and cross-language workers are unsupported here, and its
# shaded jackson/guava/httpcore5 carry advisories. Ray falls back to
# Python-only when the directory is missing.
COPY requirements.txt /tmp/ray-requirements.txt
RUN python -m pip install --no-cache-dir "ray[default]==${RAY_VERSION}" -r /tmp/ray-requirements.txt && \
    rm /tmp/ray-requirements.txt && \
    jars=$(python -c 'import os, ray; print(os.path.join(os.path.dirname(ray.__file__), "jars"))') && \
    rm -rf "$jars" && \
    [[ ! -e "$jars" ]]

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

# Head metrics stack: Ray's generated dashboards next to the inherited ones,
# plus Runpod's Ray overview as Grafana's landing page (it links to the
# inherited GPU home), and capped Prometheus retention so the stack can't fill
# the head's disk.
COPY config/provisioning/dashboards/ray.yml /etc/grafana/provisioning/dashboards/ray.yml
COPY config/dashboards/06-ray-cluster.json /var/lib/grafana/dashboards/06-ray-cluster.json
RUN sed -i 's|^default_home_dashboard_path = .*|default_home_dashboard_path = /var/lib/grafana/dashboards/06-ray-cluster.json|' \
        /etc/grafana/grafana.ini && \
    grep -q '^default_home_dashboard_path = /var/lib/grafana/dashboards/06-ray-cluster.json$' /etc/grafana/grafana.ini && \
    sed -i 's|--web.listen-address=127.0.0.1:9090|& --storage.tsdb.retention.time=7d --storage.tsdb.retention.size=10GB|' \
        /etc/supervisor/conf.d/cluster.conf && \
    grep -q -- '--storage.tsdb.retention.size=10GB' /etc/supervisor/conf.d/cluster.conf

# Keep the inherited monitoring bringup; our /post_start.sh runs it, then wires
# Ray scraping into Prometheus. It picks the head by NODE_RANK=0, the rule the
# entrypoint and our /post_start.sh use, so Prometheus/Grafana and the Ray
# scrape job land on the same node.
RUN mv /post_start.sh /post_start.cluster.sh
COPY --chmod=755 post_start.sh /post_start.sh

# Dashboard front door on 8266 for the console's `?token=` link, served by the
# base image's nginx (/start.sh starts it). The base nginx.conf has no include
# directory, so splice one include into its http block.
COPY config/nginx/ray-dashboard.conf /etc/nginx/ray-dashboard.conf
RUN sed -i 's|^http {$|&\n    include /etc/nginx/ray-dashboard.conf;|' /etc/nginx/nginx.conf && \
    grep -q 'include /etc/nginx/ray-dashboard.conf;' /etc/nginx/nginx.conf && \
    nginx -t

#   8266  Ray dashboard for the cluster owner's browser: nginx turns the
#         console's `?token=` into Ray's session cookie, then proxies to 8265.
#         Map this one in the Runpod template.
#   8265  Ray dashboard: host readiness/liveness poll (host-internal; browsers
#         and API clients use 8266). Token-authenticated by Ray itself (the
#         entrypoint sets RAY_AUTH_MODE=token).
#   20217 Ray metrics: host scrape and the head's Prometheus (host-internal)
#   52365 Ray dashboard agent: the head's dashboard reaches each node's agent
#         for jobs and logs (host-internal; token-authenticated by Ray, except
#         its /api/healthz and /api/local_raylet_healthz)
#   6379  Ray GCS: workers register here (host-internal; token-gated gRPC)
# 8889 Grafana (token-authenticated) is inherited from the -cluster base.
EXPOSE 8266 8265 20217 52365 6379

# No HEALTHCHECK: readiness and liveness are the host's (pkg/rayready polls the
# head dashboard), and nothing acts on Docker's health status.

LABEL com.runpod.template.variant="ray-cluster" \
      com.runpod.ray-cluster.contract="v1"

ENTRYPOINT ["/opt/runpod/ray/entrypoint"]
CMD ["/start.sh"]
