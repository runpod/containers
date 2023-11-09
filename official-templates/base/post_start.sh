#!/bin/bash

if [[ -z "${RUNPOD_PROJECT_ID}" ]]; then
    echo "RUNPOD_PROJECT_ID environment variable is not set. Exiting."
    exit 0
fi

check_interval=60
countdown_time=${POD_INACTIVITY_TIMEOUT:-300}

# Function to monitor the number of active SSH connections
monitor_ssh() {
    echo "Monitoring SSH connections every $check_interval seconds, with a countdown of $countdown_time seconds."
    countdown=$countdown_time

    while true; do
        sleep $check_interval

        connections=$(ss -tn | grep ':22' | grep -v 'LISTEN' | wc -l)

        if [[ "$connections" -eq 0 ]]; then
            ((countdown-=$check_interval))
            echo "No SSH connections found. Countdown: $countdown seconds remaining."

            if [[ "$countdown" -le 0 ]]; then
                echo "Countdown reached zero. Removing pod: $RUNPOD_POD_ID"
                runpodctl remove pod $RUNPOD_POD_ID
                exit 0
            fi
        else
            if [[ "$countdown" -ne $countdown_time ]]; then
                echo "SSH connection detected. Countdown aborted."
            fi
            countdown=$countdown_time
        fi
    done
}

monitor_ssh &
filebrowser -a 0.0.0.0 -p 4040 -r / &
