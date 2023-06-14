#!/bin/bash

echo "pod starting"

# ---------------------------------------------------------------------------- #
#                               Pre-Start Script                               #
# ---------------------------------------------------------------------------- #
if [[ -x /pre_start.sh ]]
then
    echo "Running pre-start script..."
    /pre_start.sh
fi

# Export specific ENV variables to /etc/rp_environment
echo "Exporting environment variables..."
printenv | grep -E '^RUNPOD_|^PATH=|^_=' | sed 's/^\(.*\)=\(.*\)$/export \1="\2"/' >> /etc/rp_environment
echo 'source /etc/rp_environment' >> ~/.bashrc

if [[ $PUBLIC_KEY ]]
then
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    cd ~/.ssh
    echo $PUBLIC_KEY >> authorized_keys
    chmod 700 -R ~/.ssh
    cd /
    service ssh start
else
    echo "No PUBLIC_KEY ENV variable provided, not starting openSSH daemon"
fi

# ---------------------------------------------------------------------------- #
#                               Post-Start Script                              #
# ---------------------------------------------------------------------------- #
if [[ -x /post_start.sh ]]
then
    echo "Running post-start script..."
    /post_start.sh
fi

if [[ $JUPYTER_PASSWORD ]]
then
    cd /
    jupyter lab --allow-root --no-browser --port=8888 --ip=* --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' --ServerApp.token=$JUPYTER_PASSWORD --ServerApp.allow_origin=* --ServerApp.preferred_dir=/workspace
else
    echo "No JUPYTER_PASSWORD ENV variable provided, not starting jupyter lab"
    sleep infinity
fi
