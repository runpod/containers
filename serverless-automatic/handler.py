import runpod
import subprocess
## Load models into VRAM here so they can be warm between requests
import requests
from threading import Thread

def start_server():
    subprocess.run(["python", "/workspace/stable-diffusion-webui/webui.py", "--port", "3000", "--xformers", "--ckpt", "/workspace/stable-diffusion-webui/v1-5-pruned-emaonly.ckpt", "--opt-split-attention", "--listen", "--api", "--nowebui"])

thread = Thread(target=start_server)

thread.start()

def handler(event):
    '''
    This is the handler function that will be called by the serverless.
    '''
    print(event)

    response = requests.post(url=f'http://127.0.0.1:3000/sdapi/v1/txt2img', json=event["input"])

    json = response.json()
    # do the things

    print(json)

    # return the output that you want to be returned like pre-signed URLs to output artifacts
    return json


runpod.serverless.start({"handler": handler})
