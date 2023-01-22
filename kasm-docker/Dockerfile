FROM kasmweb/ubuntu-focal-dind-rootless:1.12.0
USER root
RUN apt-get update \
    && apt-get install -y sudo \
    && echo 'kasm-user ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers \
    && rm -rf /var/lib/apt/list/*
RUN sed -i.bak 's/-sslOnly//' /dockerstartup/vnc_startup.sh
RUN sed -i '/^\s*pem_key:/a \ \ \ \ require_ssl: false' /etc/kasmvnc/kasmvnc.yaml
USER 1000
