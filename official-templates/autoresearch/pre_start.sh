#!/bin/bash
# Populate /workspace/autoresearch on first boot.
# Source files are copied (so user edits persist on the volume).
# .venv is symlinked to /opt (12GB, stays on fast container layer).

if [ ! -f /workspace/autoresearch/pyproject.toml ]; then
  mkdir -p /workspace/autoresearch
  # Copy only source files (lightweight)
  cp -a /opt/autoresearch/*.py /workspace/autoresearch/
  cp -a /opt/autoresearch/*.md /workspace/autoresearch/
  cp -a /opt/autoresearch/*.toml /workspace/autoresearch/
  cp -a /opt/autoresearch/*.lock /workspace/autoresearch/
  cp -a /opt/autoresearch/*.png /workspace/autoresearch/ 2>/dev/null
  cp -a /opt/autoresearch/*.ipynb /workspace/autoresearch/ 2>/dev/null
  cp -a /opt/autoresearch/*.sh /workspace/autoresearch/ 2>/dev/null
  cp -a /opt/autoresearch/.git /workspace/autoresearch/ 2>/dev/null
  cp -a /opt/autoresearch/.python-version /workspace/autoresearch/ 2>/dev/null
fi

# Always refresh the .venv symlink (container layer may have been updated)
ln -sfn /opt/autoresearch/.venv /workspace/autoresearch/.venv
