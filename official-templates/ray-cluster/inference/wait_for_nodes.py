"""Wait until NUM_NODES nodes are ALIVE in Ray, then print GPUs per node.

Run on the head by /opt/runpod/inference/start, after the entrypoint started
Ray. The start script sizes vLLM from the output: tensor parallelism is the
GPUs per node, pipeline parallelism the node count. No deadline: workers join
whenever they start, and a missing worker is a reason to wait, as it is for
the workers waiting on the head. Exits 2, with the reason on stderr, when the
nodes can't be split evenly into pipeline stages, and 1 when Ray can't be
reached.

Usage: wait_for_nodes.py <num_nodes>
"""

import sys
import time

import ray

EXIT_SHAPE = 2
LOG_EVERY_S = 60
POLL_S = 5


def log(msg: str) -> None:
    print(f"[ray-inference] {msg}", file=sys.stderr, flush=True)


def gpus_per_alive_node() -> list[int]:
    return [
        int(node["Resources"].get("GPU", 0))
        for node in ray.nodes()
        if node["Alive"]
    ]


def main() -> int:
    want = int(sys.argv[1])
    # The entrypoint exported RAY_AUTH_TOKEN, so this joins as an authenticated
    # driver of the local cluster.
    ray.init(address="auto", logging_level="ERROR", log_to_driver=False)

    started = time.monotonic()
    next_log = started
    while True:
        gpus = gpus_per_alive_node()
        if len(gpus) >= want:
            break
        if time.monotonic() >= next_log:
            log(f"{len(gpus)} of {want} nodes have joined Ray, "
                f"{int(time.monotonic() - started)}s; waiting for the rest")
            next_log += LOG_EVERY_S
        time.sleep(POLL_S)

    if len(gpus) > want:
        log(f"{len(gpus)} nodes are in Ray but NUM_NODES is {want}")
        return EXIT_SHAPE
    if min(gpus) == 0 or len(set(gpus)) != 1:
        log(f"GPUs per node differ or are missing ({gpus}); pipeline stages "
            "need the same GPU count on every node")
        return EXIT_SHAPE
    log(f"all {want} nodes joined, {gpus[0]} GPUs each")
    print(gpus[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
