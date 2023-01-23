FROM kasmweb/blender:1.12.0
USER root
RUN apt-get update \
    && apt-get install -y sudo build-essential gcc-multilib dkms \
    && echo 'kasm-user ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers \
    && rm -rf /var/lib/apt/list/*
RUN sed -i.bak 's/-sslOnly//' /dockerstartup/vnc_startup.sh
RUN sed -i '/^\s*pem_key:/a \ \ \ \ require_ssl: false' /etc/kasmvnc/kasmvnc.yaml

RUN wget https://www.nvidia.com/content/DriverDownloads/confirmation.php?url=/XFree86/Linux-x86_64/525.85.05/NVIDIA-Linux-x86_64-525.85.05.run -O nvidia-driver.run

RUN chmod a+x nvidia-driver.run
RUN sudo ./nvidia-driver.run -s

USER 1000
