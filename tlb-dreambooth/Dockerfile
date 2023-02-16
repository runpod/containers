FROM runpod/stable-diffusion:web-automatic-1.5.16

SHELL ["/bin/bash", "-c"]

ENV PATH="${PATH}:/workspace/stable-diffusion-webui/venv/bin"

WORKDIR /

RUN git clone https://github.com/TheLastBen/fast-stable-diffusion.git
RUN git clone --depth 1 --branch updt https://github.com/TheLastBen/diffusers


RUN pip install https://github.com/runpod/runpod-python/archive/main.zip

RUN pip install -U xformers
RUN pip3 install diffusers==0.12.1
RUN pip3 install torch==1.13.1 --extra-index-url=https://download.pytorch.org/whl/cu116
RUN pip3 install ftfy==6.1.1
RUN pip3 install scipy==1.9.3
RUN pip3 install transformers==4.25.1
RUN pip3 install accelerate==0.14.0
# RUN pip3 install xformers==0.0.16
RUN pip3 install triton==2.0.0.dev20221120


COPY . /

RUN python model_fetcher.py

ADD handler.py .
ADD start.sh /start.sh
RUN chmod +x /start.sh

CMD [ "/start.sh" ]
