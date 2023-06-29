ARG BASE_IMAGE=runpod/stack:20.04
FROM ${BASE_IMAGE} as dev-base

RUN pip install tqdm

ADD sim_loader.py .

CMD python3 sim_loader.py
