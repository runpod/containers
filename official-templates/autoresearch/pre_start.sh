#!/bin/bash
# Populate /workspace/autoresearch on first boot.
# Everything except .venv is copied (so user edits persist on the volume).
# .venv is symlinked to /opt (12GB, stays on fast container layer).

if [ ! -f /workspace/autoresearch/pyproject.toml ]; then
  rsync -a --exclude '.venv' /opt/autoresearch/ /workspace/autoresearch/
fi

# Always refresh the .venv symlink (container layer may have been updated)
ln -sfn /opt/autoresearch/.venv /workspace/autoresearch/.venv
