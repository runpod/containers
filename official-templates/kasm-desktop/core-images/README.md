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
