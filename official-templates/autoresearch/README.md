### Runpod AutoResearch

**Pre-configured environment for [autoresearch](https://github.com/runpod/autoresearch), Karpathy's autonomous ML research loop.**

An AI coding agent autonomously runs ML experiments: it modifies `train.py`, trains for 5 minutes, checks if val_bpb improved, keeps or discards, and repeats. ~100 experiments overnight on a single GPU.

### What's included

- **Zero setup**: Dependencies installed, data prepared, ready to go on launch.
- **GPU accelerated**: Full CUDA 12.8 support with PyTorch 2.9.1.
- **Agent ready**: SSH in, connect your coding agent, and start experimenting.

### Getting started

1. Launch a pod with this template
2. Connect your coding agent (Claude Code, Cursor, etc.) via SSH
3. Tell the agent:
   ```
   Read /workspace/autoresearch/program.md and let's kick off a new experiment!
   ```

### GPU recommendations

| GPU | VRAM | Notes |
|-----|------|-------|
| RTX 4090 | 24 GB | Budget option. Smaller optimal model size. |
| A40 | 48 GB | Good middle ground. |
| A100 80GB | 80 GB | Plenty of room for larger models. |
| H100 | 80 GB | Fastest. What Karpathy used. |

The 5-minute fixed time budget means cheaper GPUs work fine — you get a different optimal model size. Results are comparable within the same GPU type.

### Available images

- Ubuntu 22.04: `runpod/autoresearch:1.0.2-cuda1281-ubuntu2204`
- Ubuntu 24.04: `runpod/autoresearch:1.0.2-cuda1281-ubuntu2404`

### Links

- [autoresearch repo](https://github.com/runpod/autoresearch) (Runpod fork)
- [Original repo](https://github.com/karpathy/autoresearch) by Karpathy
