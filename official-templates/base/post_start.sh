#!/bin/bash

if [[ -z "${RUNPOD_PROJECT_ID}" ]]; then
    echo "RUNPOD_PROJECT_ID environment variable is not set. Exiting."
    exit 0
fi

interval=${POD_INACTIVITY_TIMEOUT:-60}

# Function to monitor the number of active SSH connections
monitor_ssh() {
    echo "Monitoring SSH connections every $interval seconds"

    while true; do
        sleep $interval

        connections=$(ss -tn | grep ':22' | wc -l)

        if [[ "$connections" -eq 0 ]]; then
            runpodctl remove pod $RUNPOD_POD_ID
        fi

    done
}

monitor_ssh &
