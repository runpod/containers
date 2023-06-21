## RunPod Automatic1111 Stable Diffusion Template

### General

**Note that this does not work out of the box with encrypted volumes!**

This is a RunPod packaged template for stable diffusion using the Automatic1111 repo.

Runpod does not maintain the code for this repo, we just package it so that it's easier for you to use.

If you need help with settings, etc. You can feel free to ask us, but just keep in mind that we're not experts at stable diffusion! We'll try our best to help, but the RP community or automatic/stable diffusion communities may be better at helping you :)

**Please wait until the GPU Utilization % is 0 before attempting to connect. You will likely get a 502 error before that as the pod is still getting ready to be used.**

### Changing launch parameters

You may be used to changing a different file for your launch parameters. We use relauncher.py, which is located in the webui directory to manage the launch flags like --xformers. You can feel free to edit this file, and then restart your pod via the hamburger menu to get them to go into effect. --xformers and --api are ones that are commonly asked about.

### Using your own models

The best ways to get your models onto your pod is by using [runpodctl](https://github.com/runpod/runpodctl/blob/main/README.md) or by uploading them to google drive or other cloud storage and downloading them to your pod from there.

### Uploading to google drive

If you're done with the pod and would like to send things to google drive, you can use [this colab](https://colab.research.google.com/drive/1ot8pODgystx1D6_zvsALDSvjACBF1cj6) to do it using runpodctl. You run the runpodctl either in a web terminal (found in the pod connect menu), or in a terminal on the desktop
