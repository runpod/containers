#!/bin/bash

# Start script
echo "Pod started"

# SSH setup
if [[ $PUBLIC_KEY ]]
then
    echo "Setting up SSH..."
    mkdir -p ~/.ssh
    echo $PUBLIC_KEY >> ~/.ssh/authorized_keys
    chmod 700 -R ~/.ssh
    service ssh start
fi

# Export specific ENV variables to /etc/rp_environment
echo "Exporting environment variables..."
printenv | grep -E '^RUNPOD_POD_ID=|^RUNPOD_GPU_COUNT=|^RUNPOD_PUBLIC_IP=|^RUNPOD_HOSTNAME=|^RUNPOD_TCP_PORT=|^RUNPOD_API_KEY=|^PATH=|^_=' | \
sed 's/^\(.*\)=\(.*\)$/export \1="\2"/' >> /etc/rp_environment
echo 'source /etc/rp_environment' >> ~/.bashrc

# Start Jupyter lab if JUPYTER_PASSWORD is set, otherwise sleep
if [[ $JUPYTER_PASSWORD ]]
then
    echo "Starting Jupyter Lab..."
    jupyter lab --allow-root --no-browser --port=8888 --ip=* --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' --ServerApp.token=$JUPYTER_PASSWORD --ServerApp.allow_origin=* --ServerApp.preferred_dir=/workspace
else
    echo "JUPYTER_PASSWORD not set. Going to sleep mode..."
    sleep infinity
fi
