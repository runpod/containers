FROM entmike/discoart:preload

# Set bash as default shell, non-interactive
ENV DEBIAN_FRONTEND noninteractive\
    SHELL=/bin/bash

# Create workspace working directory
WORKDIR /workspace

# Build with some basic utilities
RUN apt-get update && apt-get install -y \
    python3-pip \
    apt-utils \
    git wget curl openssh-server zip unzip &&\
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    echo "en_US.UTF-8 UTF-8" > /etc/locale.gen

# Node
RUN curl -sL https://deb.nodesource.com/setup_16.x -o /tmp/nodesource_setup.sh
RUN bash /tmp/nodesource_setup.sh

# alias python='python3'
RUN ln -s /usr/bin/python3 /usr/bin/python

RUN pip install \
    numpy \
    pip install torch==1.11.0+cu113 torchvision==0.12.0+cu113 torchaudio==0.11.0 --extra-index-url https://download.pytorch.org/whl/cu113 \
    jupyterlab ipywidgets jupyter-archive

RUN jupyter nbextension enable --py widgetsnbextension


ADD start.sh /start.sh
RUN chmod +x start.sh

ADD welcome-banner.txt /root/welcome-banner.txt
COPY examples /examples
ADD welcome.ipynb /root/welcome.ipynb

RUN echo 'cat ~/welcome-banner.txt' >> ~/.bashrc &&\
    echo 'cd /workspace' >> ~/.bashrc

# opt-out from cloud backup
ENV DISCOART_OPTOUT_CLOUD_BACKUP='1'

# use a custom output directory for all images and results
ENV DISCOART_OUTPUT_DIR='/workspace/out'

WORKDIR /
RUN pip install discoart==0.12.0
RUN git clone https://github.com/Run-Pod/discoart-ui.git
WORKDIR /discoart-ui
RUN apt install nodejs
RUN npm install --global yarn
RUN yarn && yarn build
RUN yarn global add pm2

RUN rm -Rf /root/.cache && mkdir -p /models/.cache && ln -s /models/.cache /root
CMD [ "/start.sh" ]