#!/bin/bash
# Start FileBrowser in the background so the base start script continues to
# bring up SSH + Jupyter and then sleeps. FILEBROWSER_CONFIG points at the
# baked config (trustProxyHeaders on). Set FILEBROWSER_ADMIN_PASSWORD to skip
# the generated temp password that otherwise lands in /filebrowser.log.

mkdir -p /workspace/.filebrowser

echo "Starting FileBrowser on :80..."
nohup filebrowser > /filebrowser.log 2>&1 &
