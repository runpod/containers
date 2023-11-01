#!/bin/bash

if [[ -z "${RUNPOD_PROJECT_ID}" ]]; then
    echo "RUNPOD_PROJECT_ID environment variable is not set. Exiting."
    exit 0
fi

interval=60

# Function to monitor the number of active SSH connections
monitor_ssh() {
    sleep $interval

    while true; do
        # Using 'ss' to count active SSH connections
        connections=$(ss -tn | grep ':22' | wc -l)
        if [[ "$connections" -gt 0 ]]; then
            echo "ssh connections active"
        else
            echo "no active ssh connections"
            runpodctl remove pod $RUNPOD_POD_ID
        fi
        sleep $interval
    done
}

monitor_ssh &
