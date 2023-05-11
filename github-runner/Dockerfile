FROM runpod/pytorch:3.10-2.0.0-117

WORKDIR /

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV RUNNER_ALLOW_RUNASROOT=1

# Input GitHub runner version argument
ARG RUNNER_VERSION

# Update base packages and install dependencies
RUN apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        curl nodejs wget unzip vim git azure-cli jq build-essential libssl-dev libffi-dev python3 python3-venv python3-dev python3-pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# cd into the user directory, download and unzip the github actions runner
RUN mkdir actions-runner && cd actions-runner \
    && curl -O -L https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz \
    && tar xzf ./actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz && \
    rm -rf ./actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz

# install some additional dependencies
RUN /actions-runner/bin/installdependencies.sh

# Copy the start.sh script and make it executable
COPY start.sh /start.sh
RUN chmod +x /start.sh

# set the entrypoint to the start.sh script
ENTRYPOINT ["./start.sh"]
