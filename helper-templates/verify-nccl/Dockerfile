FROM runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel

ENV NCCL_DEBUG=TRACE

RUN groupadd -r nonroot \
    && useradd -r -g nonroot nonroot

WORKDIR /verify-nccl

# Install additional packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    nano \
    pciutils \
    && rm -rf /var/lib/apt/lists/* &&\
    git clone https://github.com/NVIDIA/cuda-samples.git 
    
WORKDIR /verify-nccl/cuda-samples/Samples/0_Introduction/simpleP2P

RUN make

COPY --chmod=755 check_nccl.sh .

USER nonroot

# Start Container
CMD ["tail", "-f", "/dev/null"]
