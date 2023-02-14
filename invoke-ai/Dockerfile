FROM ghcr.io/ebr/invokeai:latest-cuda

ENV PATH=${VIRTUAL_ENV}/bin:$PATH
ENV PYTHONUNBUFFERED=1

RUN pip install jupyterlab && \
pip install ipywidgets && \
jupyter nbextension enable --py widgetsnbextension

ADD start.sh /start.sh
RUN chmod a+x /start.sh
CMD [ "/start.sh" ]
