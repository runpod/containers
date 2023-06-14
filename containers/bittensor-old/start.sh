#!/bin/bash
echo "Container Started"
export PYTHONUNBUFFERED=1

echo "*** syncing files, please wait ***"
rsync --remove-source-files -rlptDu /.bashrc /root/
rsync --remove-source-files -rlptDu /runpod_bittensor_tmp/.bittensor/ /root/.bittensor/
rsync --remove-source-files -rlptDu /runpod_bittensor_tmp/.nvm/ /root/.nvm/
rsync --remove-source-files -rlptDu /runpod_bittensor_tmp/.npm/ /root/.npm/

echo "*** file sync complete ***"

source /root/.bashrc

pm2 list
pm2 resurrect

sleep infinity
