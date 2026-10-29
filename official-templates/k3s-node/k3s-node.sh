#!/bin/sh
# Entrypoint for the k3s node image. Wraps `k3s agent` so the kubelet advertises only what the
# Runpod pod may use.
#
# The kubelet reads the host's /proc, so inside a pod it always sees the whole machine. Under
# sysbox, the pod's own cgroup limits are visible at /sys/fs/cgroup (on cgroup v1, the memory limit
# only; see below). This script reserves the part of the host above those limits in the kubelet. A
# pod that owns its host has no limits ("max"), and then only the headroom below is reserved.
set -eu

# Headroom for the kubelet, containerd and the Runpod daemon.
RESERVE_CPU_M="${K3S_NODE_RESERVE_CPU_M:-500}"
RESERVE_MEM_MI="${K3S_NODE_RESERVE_MEM_MI:-1024}"
CG=/sys/fs/cgroup

# cpuset_count "0-3,8,10-11" prints 7.
cpuset_count() {
  echo "$1" | tr ',' '\n' | awk -F- 'NF { n += (NF == 2 ? $2 - $1 + 1 : 1) } END { print n + 0 }'
}

if [ "${1:-}" = agent ]; then
  host_cpu_m=$(( $(grep -c '^processor' /proc/cpuinfo) * 1000 ))
  host_mem_mi=$(( $(awk '/^MemTotal:/ { print $2 }' /proc/meminfo) / 1024 ))

  # cgroup v2 has one tree with cpu.max and memory.max. v1 has one tree per controller; there "no
  # limit" is a quota of -1, or a memory limit above the host's memory.
  if [ "$(stat -fc %T "$CG")" = cgroup2fs ]; then
    cgroup_v1=false
    quota=max period=100000
    if [ -r "$CG/cpu.max" ]; then read -r quota period < "$CG/cpu.max"; fi
    cpuset_file=$CG/cpuset.cpus.effective
    mem_file=$CG/memory.max
  else
    cgroup_v1=true
    quota=$(cat "$CG/cpu,cpuacct/cpu.cfs_quota_us" 2>/dev/null || echo -1)
    period=$(cat "$CG/cpu,cpuacct/cpu.cfs_period_us" 2>/dev/null || echo 100000)
    if [ "$quota" -lt 0 ]; then quota=max; fi
    cpuset_file=$CG/cpuset/cpuset.effective_cpus
    mem_file=$CG/memory/memory.limit_in_bytes
  fi

  limit_cpu_m=$host_cpu_m
  if [ "$quota" != max ]; then limit_cpu_m=$(( quota * 1000 / period )); fi
  if [ -r "$cpuset_file" ]; then
    cpuset_m=$(( $(cpuset_count "$(cat "$cpuset_file")") * 1000 ))
    if [ "$cpuset_m" -gt 0 ] && [ "$cpuset_m" -lt "$limit_cpu_m" ]; then limit_cpu_m=$cpuset_m; fi
  fi

  limit_mem_mi=$host_mem_mi
  if [ -r "$mem_file" ] && [ "$(cat "$mem_file")" != max ]; then
    mem_file_mi=$(( $(cat "$mem_file") / 1048576 ))
    if [ "$mem_file_mi" -lt "$host_mem_mi" ]; then limit_mem_mi=$mem_file_mi; fi
  fi

  cpu_m=$RESERVE_CPU_M
  mem_mi=$RESERVE_MEM_MI
  if [ "$limit_cpu_m" -lt "$host_cpu_m" ]; then cpu_m=$(( cpu_m + host_cpu_m - limit_cpu_m )); fi
  if [ "$limit_mem_mi" -lt "$host_mem_mi" ]; then mem_mi=$(( mem_mi + host_mem_mi - limit_mem_mi )); fi

  shift
  set -- agent --kubelet-arg="system-reserved=cpu=${cpu_m}m,memory=${mem_mi}Mi" "$@"
  echo "k3s-node: host cpu=${host_cpu_m}m mem=${host_mem_mi}Mi, pod limit cpu=${limit_cpu_m}m mem=${limit_mem_mi}Mi, system-reserved cpu=${cpu_m}m memory=${mem_mi}Mi" >&2

  # cgroup v1: the kubelet refuses to start unless fail-cgroupv1=false. Under sysbox, the pod's CPU
  # quota sits on a parent cgroup the node cannot see (so limit_cpu_m above is the host's), and v1
  # rejects a child quota above it ("cpu.cfs_quota_us: invalid argument"): every k8s pod with a
  # higher CPU limit fails to start. So the kubelet sets no CFS quotas: CPU limits are not enforced
  # per k8s pod, while CPU requests (cpu.shares) and the Runpod pod's own quota still apply.
  if [ "$cgroup_v1" = true ]; then
    shift
    set -- agent --kubelet-arg=fail-cgroupv1=false --kubelet-arg=cpu-cfs-quota=false "$@"
    echo "k3s-node: cgroup v1: kubelet fail-cgroupv1=false, cpu-cfs-quota=false" >&2
  fi
fi

# A K8S node pod starts before its control plane exists. It gets K3S_TOKEN and WG_ENDPOINT (the
# stack's API record) once the stack is up; that pod edit restarts it. Until then it waits,
# instead of crash-looping without a server.
if [ "${1:-}" = agent ] && { [ -z "${K3S_TOKEN:-}" ] || [ -z "${K3S_URL:-}${WG_ENDPOINT:-}" ]; }; then
  echo "k3s-node: K3S_TOKEN and WG_ENDPOINT not set (waiting for control plane to be available)" >&2
  exec sleep infinity
fi

# WireGuard to the server: the agent joins https://<WG_SERVER_ADDRESS>:6443 (K3S_URL) through the
# tunnel. Every key follows from K3S_TOKEN, as in the server's wg sidecar (images/k3s-wireguard):
# the server's from "wireguard-server", the node's (and its tunnel address) from NODE_RANK. So every
# node pod has the same env, and nothing hands out keys.
# WireGuard resolves the endpoint name once, and a restarted server task has a new public IP:
# re-resolve every 5 s.
if [ "${1:-}" = agent ] && [ -n "${WG_ENDPOINT:-}" ]; then
  WG_SERVER_ADDRESS="${WG_SERVER_ADDRESS:-10.200.0.1}"
  # The server's tunnel address: the same for every cluster, so the pod env may leave it out.
  export K3S_URL="${K3S_URL:-https://$WG_SERVER_ADDRESS:6443}"
  WG_MAX_NODES="${WG_MAX_NODES:-200}"
  case "${NODE_RANK:-}" in
    ''|*[!0-9]*) echo "k3s-node: NODE_RANK is not set" >&2; exit 1 ;;
  esac
  if [ "$NODE_RANK" -ge "$WG_MAX_NODES" ]; then
    echo "k3s-node: NODE_RANK $NODE_RANK: the server admits ranks 0 to $((WG_MAX_NODES - 1))" >&2; exit 1
  fi
  WG_ADDRESS="${WG_SERVER_ADDRESS%.*}.$(( ${WG_SERVER_ADDRESS##*.} + NODE_RANK + 1 ))"
  ( umask 077; printf 'wireguard-node-%s' "$NODE_RANK" \
      | openssl dgst -sha256 -hmac "$K3S_TOKEN" -binary | base64 > /run/wg.key )
  WG_SERVER_PUBLIC_KEY="$(printf 'wireguard-server' \
      | openssl dgst -sha256 -hmac "$K3S_TOKEN" -binary | base64 | wg pubkey)"
  ip link del wg0 2>/dev/null || true
  ip link add wg0 type wireguard
  wg set wg0 private-key /run/wg.key
  ip addr add "$WG_ADDRESS/32" dev wg0
  ip link set wg0 up
  ip route replace "$WG_SERVER_ADDRESS/32" dev wg0
  peer() {
    wg set wg0 peer "$WG_SERVER_PUBLIC_KEY" endpoint "$WG_ENDPOINT" \
      allowed-ips "$WG_SERVER_ADDRESS/32" persistent-keepalive 25
  }
  until peer; do echo "k3s-node: waiting to resolve $WG_ENDPOINT" >&2; sleep 2; done
  echo "k3s-node: wg0 $WG_ADDRESS -> $WG_SERVER_ADDRESS via $WG_ENDPOINT" >&2
  ( while sleep 5; do peer 2>/dev/null || echo "k3s-node: cannot resolve $WG_ENDPOINT" >&2; done ) &
fi

# The node password: k3s stores a random one in /etc/rancher/node/password on the first join, and
# the server keeps it per node name (secret <node>.node-password.k3s). A recreated node pod (image
# bump, pod edit, host reboot) has a new container filesystem, so a new password, and the server
# rejects it ("Node password rejected"). Derive it from K3S_TOKEN and NODE_RANK instead
# (PBKDF2-HMAC-SHA256): the same node rank always presents the same password. If the derivation
# fails, the node does not start.
if [ "${1:-}" = agent ] && [ -n "${K3S_TOKEN:-}" ] && [ -n "${NODE_RANK:-}" ]; then
  (
    umask 077
    mkdir -p /etc/rancher/node || exit 1

    node_password=$(
      openssl kdf -keylen 32 \
        -kdfopt digest:SHA256 \
        -kdfopt "pass:$K3S_TOKEN" \
        -kdfopt "salt:node-password-$NODE_RANK" \
        -kdfopt iter:600000 \
        PBKDF2
    ) || {
      printf '%s\n' 'k3s-node: failed to derive the node password' >&2
      exit 1
    }

    node_password=$(printf '%s' "$node_password" | tr -d '[:space:]:') || exit 1
    printf '%s\n' "$node_password" > /etc/rancher/node/password || exit 1
    chmod 600 /etc/rancher/node/password || exit 1
  ) || exit 1
fi

# The cluster network: on a node group with one, the host gives every cluster pod its own overlay
# address (NODE_ADDR, e.g. 10.65.0.3/24) on a VXLAN between the hosts. The node registers with it,
# and flannel sends pod traffic over it: node to node directly, not through the server's tunnel.
# Without it, every node has the host's container address (the same on every host).
if [ "${1:-}" = agent ] && [ -n "${NODE_ADDR:-}" ]; then
  node_ip="${NODE_ADDR%/*}"
  node_iface="$(ip -o -4 addr show | awk -v ip="$node_ip" '{ split($4, a, "/") } a[1] == ip { print $2; exit }')"
  if [ -z "$node_iface" ]; then
    echo "k3s-node: no interface has NODE_ADDR $NODE_ADDR" >&2; exit 1
  fi
  shift
  set -- agent --node-ip="$node_ip" --flannel-iface="$node_iface" "$@"
  echo "k3s-node: cluster network $node_ip on $node_iface" >&2
fi

# runc: k3s v1.37.1+k3s1 bundles runc 1.4.2, below the security minimum 1.4.3. A bundled tool
# (ctr) makes k3s unpack its data dir; then our runc (Dockerfile, RUNC_VERSION) replaces its runc,
# which k3s's containerd finds first. REMOVE this block, and the runc download in the Dockerfile,
# once a k3s release bundles runc >= 1.4.3.
if [ -x /usr/local/lib/k3s-node/runc ]; then
  /bin/k3s ctr --version >/dev/null 2>&1 || true
  k3s_data="$(readlink -f /var/lib/rancher/k3s/data/current)"
  if [ -d "$k3s_data/bin" ]; then
    install -m 0755 /usr/local/lib/k3s-node/runc "$k3s_data/bin/runc"
    echo "k3s-node: $("$k3s_data/bin/runc" --version | head -1) (replaces the bundled runc)"
  fi
fi

exec /bin/k3s "$@"
