from python:3.11.1-buster

WORKDIR /

RUN pip install git+https://github.com/runpod/runpod-python.git

ADD handler.py .

CMD [ "python", "-u", "/handler.py" ]
