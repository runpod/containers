#!/bin/bash

# Start Nginx service
echo "Starting Nginx service..."
service nginx start

# ---------------------------------------------------------------------------- #
#                               Pre-Start Script                               #
# ---------------------------------------------------------------------------- #
if [[ -x /pre_start.sh ]]
then
    echo "Running pre-start script..."
    chmod +x /pre_start.sh
    /pre_start.sh
fi

# ---------------------------------------------------------------------------- #
#                                 Start Script                                 #
# ---------------------------------------------------------------------------- #
echo "Pod Started"

# SSH setup
if [[ $PUBLIC_KEY ]]
then
    echo "Setting up SSH..."
    mkdir -p ~/.ssh
    echo "$PUBLIC_KEY" >> ~/.ssh/authorized_keys
    chmod 700 -R ~/.ssh
    service ssh start
fi

# Export specific ENV variables to /etc/rp_environment
echo "Exporting environment variables..."
printenv | grep -E '^RUNPOD_|^PATH=|^_=' | sed 's/^\(.*\)=\(.*\)$/export \1="\2"/' >> /etc/rp_environment
echo 'source /etc/rp_environment' >> ~/.bashrc

# Start Jupyter lab if JUPYTER_PASSWORD is set
if [[ $JUPYTER_PASSWORD ]]
then
    echo "Starting Jupyter Lab..."
    mkdir -p /workspace && \
    cd / && \
    jupyter lab --allow-root --no-browser --port=8888 --ip=* --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' --ServerApp.token=$JUPYTER_PASSWORD --ServerApp.allow_origin=* --ServerApp.preferred_dir=/workspace &
    echo "Jupyter Lab started"
fi

# ---------------------------------------------------------------------------- #
#                               Post-Start Script                              #
# ---------------------------------------------------------------------------- #
if [[ -x /post_start.sh ]]
then
    echo "Running post-start script..."
    chmod +x /post_start.sh
    /post_start.sh
fi

sleep infinity
