<div style="text-align: center;">

<h1> Fast Stable Diffusion </h1>

</div>

## 📖 About

This is a packaged template for Fast Stable Diffusion, RunPod does not maintain the code for this repo, we just package it so that it's easier for you to use.

If you need help with settings, etc. You can feel free to ask us, but just keep in mind that we're not experts at stable diffusion! We'll try our best to help, but the RP community or automatic/stable diffusion communities may be better at helping you.

**Note: This does not work out of the box with encrypted volumes!**

## 🚀 Usage

Start by connecting to jupyter lab. From there you will have the option to run the automatic1111 notebook, which will launch the UI for automatic, or you can directly train dreambooth using one of the dreambooth notebooks.

### Changing launch parameters

There is a "Start Stable-Diffusion" cell in the RNPD-A1111.ipynb notebook. You can feel free to change the launch params by changing this line `!python /workspace/sd/stable-diffusion-webui/webui.py $configf`.

### Using your own models

The best ways to get your models onto your pod is by using [runpodctl](https://github.com/runpod/runpodctl/blob/main/README.md) or by uploading them to google drive or other cloud storage and downloading them to your pod from there. You should put models that you want to use with auto in the /workspace/auto-models directory.

### Uploading to google drive

If you're done with the pod and would like to send things to google drive, you can use [this colab](https://colab.research.google.com/drive/1ot8pODgystx1D6_zvsALDSvjACBF1cj6) to do it using runpodctl. You run the runpodctl either in a web terminal (found in the pod connect menu), or in a terminal on the desktop

## 🔌 Template Ports

- **3001** | HTTP - This is the interface port that gets proxied to the internal 3000 port.
- **8888** | HTTP - This is the JupyterLab port that gets proxied to the internal 8888 port.
- **22** | TCP  - This is the SSH port that gets proxied to the internal 22 port.
