### Runpod AutoResearch

**Pre-configured environment for [autoresearch](https://github.com/runpod/autoresearch), Karpathy's autonomous ML research loop.**

An AI coding agent autonomously runs ML experiments: it modifies `train.py`, trains for 5 minutes, checks if val_bpb improved, keeps or discards, and repeats. ~100 experiments overnight on a single GPU.

### What's included

- **Ready on first boot**: Dependencies are installed and the training data and tokenizer are prepared at build time. On first start the repo is copied to `/workspace/autoresearch`, so your edits persist on the volume.
- **CUDA 12.8 to 13.2**: Images are published for CUDA 12.8.1, 12.9.0, 13.0.0 and 13.2.0. The tag says which toolkit you get and which host driver it needs. PyTorch is the same in all of them: 2.9.1 from the `cu128` wheel index.
- **Bring your own agent**: No coding agent is installed in the image. Connect one from your machine over SSH (Claude Code, Cursor, etc.). `runpodctl` is preinstalled for managing pods.

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

Defaults in `train.py` assume an 80 GB card. On smaller GPUs lower `DEVICE_BATCH_SIZE` first — on a 24 GB card 32 runs at ~11.7 GB peak, while the default 128 runs out of memory.

### Links

- [autoresearch repo](https://github.com/runpod/autoresearch) (Runpod fork)
- [Original repo](https://github.com/karpathy/autoresearch) by Karpathy
