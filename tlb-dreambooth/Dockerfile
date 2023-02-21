FROM runpod/pytorch:3.10-1.13.1-116

SHELL ["/bin/bash", "-c"]

ENV PATH="${PATH}:/workspace/stable-diffusion-webui/venv/bin"

WORKDIR /src

RUN git clone https://github.com/TheLastBen/fast-stable-diffusion.git
RUN git clone --depth 1 --branch updt https://github.com/TheLastBen/diffusers

RUN pip install setuptools
RUN pip install xformers==0.0.16
RUN pip install bitsandbytes==0.37.0
RUN pip install diffusers==0.12.1
RUN pip install torch==1.13.1 --extra-index-url=https://download.pytorch.org/whl/cu116
RUN pip install ftfy==6.1.1
RUN pip install scipy==1.9.3
RUN pip install transformers==4.21.1
RUN pip install accelerate==0.12.0
RUN pip install triton==2.0.0.dev20221120
RUN pip install runpod==0.9.0

# ADD model_fetcher.py /src/
# RUN python model_fetcher.py

RUN curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | bash
RUN apt-get install git-lfs -y
ADD model_fetcher.sh /src/
RUN sh /src/model_fetcher.sh

ADD dreambooth.py /src/
ADD handler.py /src/
ADD start.sh /src/
ADD test_input.json /src/

RUN chmod +x /src/start.sh
CMD ["/src/start.sh"]
