#Get some information about the cluster properties
export HEAD_IP=$(cat /etc/hosts | grep node-0 | cut -d " " -f 1)
export N_NODES=$(cat /etc/hosts | grep node- | wc -l)
export N_GPUS=$(nvidia-smi | grep -i nvidia | grep -v SMI | wc -l)

test "$HOSTNAME" = "node-0" && python -m pip install hf_transfer || sleep 20 
test "$HOSTNAME" = "node-0" && ray start --head --port=6379 --node-ip-address=$HEAD_IP --dashboard-host=0.0.0.0 --disable-usage-stats || ray start --address=$HEAD_IP:6379 --disable-usage-stats

test "$HOSTNAME" = "node-0" && vllm serve $HF_MODEL --tensor-parallel-size $N_GPUS --pipeline-parallel-size $N_NODES
