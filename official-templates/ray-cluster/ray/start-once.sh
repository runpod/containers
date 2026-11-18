#!/usr/bin/env bash
# /start.sh in the ray-cluster image: runs the inherited start script, renamed
# /start.base.sh at build time, once per container. The entrypoint already
# starts it in the background for any CMD other than /start.sh, so a CMD that
# runs /start.sh itself (`my-app & exec /start.sh`) would otherwise start nginx,
# SSH and Jupyter a second time, and the second Jupyter failing would end that
# CMD. The later run waits instead, as the first one's `sleep infinity` does.
#
# The lock is held by this process only: /start.base.sh runs as a child with
# the lock's fd closed, so the services it leaves behind (nginx, Jupyter,
# supervisord) don't inherit it. If the first run dies part-way, the lock goes
# with it, and a waiting or later run takes over.
exec 9> /run/runpod-start.lock
if ! flock -n 9; then
    echo "[ray-cluster] /start.sh is already running in this container; waiting, and taking over if it exits"
    flock 9
fi
/start.base.sh 9>&-
