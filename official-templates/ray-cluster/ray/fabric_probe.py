#!/usr/bin/env python3
"""Opt-in NCCL fabric diagnostic for a Ray cluster.

Run on the head node once every node has joined: /opt/runpod/ray/fabric-probe
It all-reduces across one GPU per node and prints a single verdict line,
  RAYFABRIC ok=<1|0|skip> reason=<...> gbps=<...> nodes=<...> iface=<...> ib=<...>
and always exits 0. Not on the boot path; the host pins the fabric NIC itself.
Knobs: RAY_FABRIC_MIN_GBPS (5), RAY_FABRIC_PORT (29517),
RAY_FABRIC_GET_TIMEOUT_S (40).
"""
import contextlib
import os
import sys
import time
from datetime import timedelta


def emit(ok, **kv):
    # The verdict line is space-separated k=v grepped by callers, so
    # every field must stay one token — detail fields hold exception text,
    # which carries spaces and newlines. Map all whitespace to underscores,
    # same idiom as iface's .replace(',', '+') below.
    def scrub(v):
        return '_'.join(str(v).split())

    print(f"RAYFABRIC ok={ok} {' '.join(f'{k}={scrub(v)}' for k, v in sorted(kv.items()))}", flush=True)


try:
    import ray
    import torch
    import torch.distributed as dist
except Exception as e:
    # Every failure degrades to a verdict line rather than a traceback.
    emit('skip', reason='imports-failed', detail=type(e).__name__)
    sys.exit(0)

iface = (os.environ.get('NCCL_SOCKET_IFNAME') or '-').replace(',', '+')
ib = '1' if os.environ.get('NCCL_IB_DISABLE') == '0' else '0'
min_gbps = float(os.environ.get('RAY_FABRIC_MIN_GBPS', '5'))
port = int(os.environ.get('RAY_FABRIC_PORT', '29517'))
want_nodes = int(os.environ.get('NUM_NODES', '0'))
# Bounds each collective; the whole probe waits at most twice this.
get_timeout_s = float(os.environ.get('RAY_FABRIC_GET_TIMEOUT_S', '40'))

# Below this there is no fabric to measure — a single node has nothing to
# all-reduce with, so the probe reports skip rather than a meaningless pass.
MIN_NODES = 2

ray.init(address='auto')
try:
    nodes = [n for n in ray.nodes()
             if n['Alive'] and n['Resources'].get('GPU', 0) > 0]
    world = len(nodes)
    if want_nodes and world < want_nodes:
        emit('skip', reason='partial-nodes', nodes=world, want=want_nodes)
        sys.exit(0)
    if world < MIN_NODES:
        emit('skip', reason='single-node', nodes=world)
        sys.exit(0)
    head_ip = (os.environ.get('NODE_ADDR') or '').split('/')[0]
    if not head_ip:
        emit('skip', reason='no-head-ip')
        sys.exit(0)
    # rank 0 must be this pod: the probe runs on the head, and
    # ray.nodes() ordering is not contractual, so anchor rank to self-identity
    # (our own overlay IP) instead of list position.
    nodes.sort(key=lambda n: (n['NodeManagerAddress'] != head_ip, n['NodeManagerAddress']))

    @ray.remote
    class Rank:
        def __init__(self, rank, world):
            self.node_rank = rank
            self.world = world

        def run(self):
            try:
                dist.init_process_group(
                    'nccl',
                    init_method=f'tcp://{head_ip}:{port}',
                    rank=self.node_rank,
                    world_size=self.world,
                    timeout=timedelta(seconds=get_timeout_s),
                )
                torch.cuda.set_device(0)
                x = torch.full((16 * 1024 * 1024,), 1.0, dtype=torch.float16, device='cuda')  # 32Mi
                for _ in range(5):
                    dist.all_reduce(x)
                torch.cuda.synchronize()
                t0 = time.perf_counter()
                iters = 20
                for _ in range(iters):
                    dist.all_reduce(x)
                torch.cuda.synchronize()
                dt = (time.perf_counter() - t0) / iters
                size = x.nelement() * x.element_size()
                busbw = size * 2 * (self.world - 1) / self.world / dt / 1e9
            except Exception as e:
                return ('err', str(e)[:120])
            else:
                return ('ok', busbw)
            finally:
                with contextlib.suppress(Exception):
                    dist.destroy_process_group()

    handles = [
        Rank.options(num_gpus=1, resources={f'node:{n["NodeManagerAddress"]}': 0.001}).remote(r, world)
        for r, n in enumerate(nodes)
    ]
    try:
        results = ray.get([h.run.remote() for h in handles], timeout=get_timeout_s * 2)
    except Exception as e:
        emit('0', reason='collective-timeout', detail=type(e).__name__, iface=iface, ib=ib)
        sys.exit(0)
    errs = [r for r in results if r[0] != 'ok']
    if errs:
        emit('0', reason='rank-error', detail=errs[0][1], iface=iface, ib=ib)
        sys.exit(0)
    busbw = min(r[1] for r in results)  # slowest link bounds the collective
    if busbw >= min_gbps:
        emit('1', gbps=round(busbw, 1), nodes=world, iface=iface, ib=ib, reason='ok')
    else:
        emit('0', gbps=round(busbw, 1), nodes=world, iface=iface, ib=ib,
             reason=f'below-min:{min_gbps}')
finally:
    ray.shutdown()
