FROM nvidia/cuda:11.7.1-cudnn8-runtime-ubuntu20.04

ENV DEBIAN_FRONTEND=noninteractive

# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
    # support env timezones
    tzdata \
    # vscode requirements
    gnome-keyring wget curl python3-minimal ca-certificates \
    # development tools
    git build-essential \
    # clean up
    && apt-get autoremove -y && apt-get clean -y && rm -rf /var/lib/apt/lists/*

# install vscode-server
# hadolint ignore=DL4006
RUN wget -q -O- https://aka.ms/install-vscode-server/setup.sh | sh

# copy scripts
COPY src/* /usr/local/bin/

# entrypoint
ENTRYPOINT [ "start-vscode" ]

# expose port
EXPOSE 8000

# NGINX Proxy
COPY --from=proxy nginx.conf /etc/nginx/nginx.conf
COPY --from=proxy readme.html /usr/share/nginx/html/readme.html

# Copy the README.md
COPY README.md /usr/share/nginx/html/README.md

# Start Scripts
COPY --from=scripts start.sh /
RUN chmod +x /start.sh

CMD [ "/start.sh" ]
