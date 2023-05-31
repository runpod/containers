#!/bin/bash

while true; do
    if lsof -Pi :9090 -sTCP:LISTEN -t >/dev/null ; then
        # Your service is running on port 9090
        # Configure Nginx to proxy to a different port (e.g., 9091)
        sed -i 's/9090/9091/g' /etc/nginx/nginx.conf
    else
        # Your service is not running on port 9090
        # Configure Nginx to proxy to port 9090
        sed -i 's/9091/9090/g' /etc/nginx/nginx.conf
    fi

    # Reload Nginx configuration
    nginx -s reload

    # Wait for 5 seconds before checking again
    sleep 5
done
