#!/bin/bash
# Start FileBrowser in the background so the base start script continues to
# bring up SSH + Jupyter and then sleeps. FILEBROWSER_CONFIG points at the
# baked config (trustProxyHeaders on). Set FILEBROWSER_ADMIN_PASSWORD to skip
# the generated temp password that otherwise lands in /filebrowser.log.

mkdir -p /workspace/.filebrowser

echo "Starting FileBrowser on :80..."
# tee so output shows in the pod's log stream (PID 1 stdout) as well as the
# file. With a plain '> /filebrowser.log' redirect, a startup error is only
# visible via `cat` inside the pod, not in the Runpod console.
nohup filebrowser 2>&1 | tee /filebrowser.log &
