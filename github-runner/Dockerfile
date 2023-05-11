FROM runpod/pytorch:3.10-2.0.0-117

WORKDIR /

#input GitHub runner version argument
ARG RUNNER_VERSION
ENV DEBIAN_FRONTEND=noninteractive
ENV RUNNER_ALLOW_RUNASROOT=1

# LABEL Author="Marcel L"
# LABEL Email="pwd9000@hotmail.co.uk"
# LABEL GitHub="https://github.com/Pwd9000-ML"
# LABEL BaseImage="ubuntu:20.04"
# LABEL RunnerVersion=${RUNNER_VERSION}

# update the base packages
RUN apt-get update -y && apt-get upgrade -y

# install the packages and dependencies along with jq so we can parse JSON (add additional packages as necessary)
RUN apt-get install -y --no-install-recommends \
    curl nodejs wget unzip vim git azure-cli jq build-essential libssl-dev libffi-dev python3 python3-venv python3-dev python3-pip

# cd into the user directory, download and unzip the github actions runner
RUN mkdir actions-runner && cd actions-runner \
    && curl -O -L https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz \
    && tar xzf ./actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz

# install some additional dependencies
RUN /actions-runner/bin/installdependencies.sh

# add over the start.sh script
ADD start.sh start.sh

# make the script executable
RUN chmod +x start.sh

# set the entrypoint to the start.sh script
ENTRYPOINT ["./start.sh"]
