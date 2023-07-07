## 🚀 RunPod Automatic1111 Stable Diffusion Template

### 📝 General

⚠️ **Please note, this doesn't work out-of-the-box with encrypted volumes!**

This is a RunPod packaged template for stable diffusion using the Automatic1111 repository. RunPod does not maintain the code for this repo, we merely package it for easier use.

If you need help with settings, etc., feel free to ask us, but remember we're not stable diffusion experts! 😅 We'll do our best to assist, but the RunPod community or automatic/stable diffusion communities might be more effective in helping you.

🔵 **Please wait until the GPU Utilization % is 0 before attempting to connect. You'll likely encounter a 502 error if the pod is still getting ready for use.**

### ⚙️ Changing Launch Parameters

You might be used to altering a different file for your launch parameters. In our case, we use `relauncher.py` located in the `webui` directory to manage the launch flags like `--xformers`. Feel free to edit this file, and then restart your pod via the hamburger menu for the changes to take effect. `--xformers` and `--api` are commonly inquired about.

### 📥 Using Your Own Models

The best ways to introduce your models to your pod is by using [runpodctl](https://github.com/runpod/runpodctl/blob/main/README.md) or by uploading them to Google Drive or another cloud storage provider and downloading them to your pod from there.

### 🚚 Uploading to Google Drive

If you're finished with the pod and want to transfer things to Google Drive, [this colab](https://colab.research.google.com/drive/1ot8pODgystx1D6_zvsALDSvjACBF1cj6) can assist you using `runpodctl`. You can run `runpodctl` in a web terminal (found in the pod connect menu), or in a terminal on the desktop.

## 🔌 Template Ports

- **3001** | HTTP - This is the WebUI port that gets proxied to the internal 3000 port.
- **8888** | HTTP - This is the JupyterLab port that gets proxied to the internal 8888 port.
- **22** | TCP  - This is the SSH port that gets proxied to the internal 22 port.
