FROM runpod/stable-diffusion:web-automatic-1.5.16

SHELL ["/bin/bash", "-c"]

ENV PATH="${PATH}:/workspace/stable-diffusion-webui/venv/bin"

WORKDIR /src

RUN git clone https://github.com/TheLastBen/fast-stable-diffusion.git
RUN git clone --depth 1 --branch updt https://github.com/TheLastBen/diffusers

RUN pip install xformers==0.0.16
RUN pip install bitsandbytes==0.37.0
RUN pip install diffusers==0.12.1
RUN pip install torch==1.13.1 --extra-index-url=https://download.pytorch.org/whl/cu116
RUN pip install ftfy==6.1.1
RUN pip install scipy==1.9.3
RUN pip install transformers==4.25.1
RUN pip install accelerate==0.14.0
RUN pip install triton==2.0.0.dev20221120
RUN pip install https://github.com/runpod/runpod-python/archive/main.zip

ADD model_fetcher.py /src/
RUN python model_fetcher.py

ADD dreambooth.py /src/

ADD handler.py /src/
ADD start.sh /src/

ADD test_input.json /src/

RUN chmod +x /src/start.sh

# Run container infinitely
# CMD ["tail", "-f", "/dev/null"]

CMD ["/src/start.sh"]
