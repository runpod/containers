from python:3.11.1-buster

WORKDIR /

RUN pip install runpod

ADD handler.py .
RUN chmod a+x /handler.py

CMD [ "/handler.py" ]