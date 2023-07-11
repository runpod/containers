FROM runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel

ENV NCCL_DEBUG=TRACE

WORKDIR /verify-nccl

RUN git clone https://github.com/NVIDIA/cuda-samples.git && \
    cd cuda-samples/Samples/0_Introduction/simpleP2P && \
    make

COPY check_nccl.sh .
RUN chmod +x check_nccl.sh

# Start Container
CMD tail -f /dev/null
