![Logo][logo]
# Workspaces Core Images
This repository contains the base or **"Core"** images from which all other Workspaces images are derived.
These images are based off popular linux distributions and contain the wiring necessary to work within the Kasm platform.

While these images are primarily built to run inside the Kasm platform, they can also be executed manually.  Please note that certain functionality, such as audio, uploads, downloads, and microphone passthrough are only available within the Kasm platform.

The container is now accessible via a browser : `https://<IP>:6901`

 - **User** : `kasm_user`
 - **Password**: `password`

 ### How to build:
CUDA 11.8
 ```docker buildx build -f dockerfile-kasm-core-11 -t runpod/kasm-docker:cuda11 --build-arg START_XFCE4=1 --build-arg START_PULSEAUDIO=1 .```


# Kasmweb VNC - Ubuntu Remote Desktop CUDA 11.8

## KasmVNC - Linux Web Remote Desktop

This template allows you to access a temporary Ubuntu desktop thanks to usage of KasmVNC

**Default username: kasm_user**

**Default password: password (Unless you change VNC_PW)**

As we run it on runpod.io you get GPU acceleration access that allows you to run programs like you can do on normal linux PC. This image is customized to allow user to access to sudo command for full root access.

## Setup process

1. Edit Environment Variable VNC_PW the default value is password (Make sure to edit it to secure your container)
2. After pod starts go to connect page
3. You will see window asking for username and password (Input username kasm_user and password you set in VNC_PW)
4. If you followed guide you should be able to see your linux desktop!
5. The volume storage is mounted at /workspace

### Know issues:

- Dark Reader extension might cause web ui to not load
- There is no audio support
