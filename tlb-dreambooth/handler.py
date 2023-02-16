
import subprocess
import requests
import time
import subprocess

from dreambooth import dump_only_textenc, train_only_unet

import runpod
from runpod.serverless.utils import rp_download

# ---------------------------------------------------------------------------- #
#                                    Schemas                                   #
# ---------------------------------------------------------------------------- #
TRAIN_SCHEMA = {
    ''
}


def check_api_availability(host):
    '''
    Check if the API is available, if not, retry in 200ms
    '''
    time.sleep(15)  # Buffered time for the API to start up

    while True:
        try:
            requests.get(host, timeout=1)
            return
        except requests.exceptions.RequestException as err:
            print(f"API is not available, retrying in 200ms... ({err})")
        except Exception:
            print('something went wrong')
        time.sleep(200/1000)


def run_inference(inference_request):
    '''
    Run inference on a request.
    '''
    response = requests.post(url='http://127.0.0.1:3000/sdapi/v1/txt2img',
                             json=inference_request, timeout=10)
    return response.json()


def handler(job):
    '''
    This is the handler function that will be called on every job.
    '''
    job_input = job['input']
    train_input = job_input['train']

    # -------------------------- Download Training Data -------------------------- #
    downloaded_input = rp_download.file(train_input['data_url'])

    # ----------------------------------- Train ---------------------------------- #
    dump_only_textenc(
        trnonltxt="",
        MODELT_NAME="runwayml/stable-diffusion-v1-5",
        INSTANCE_DIR=downloaded_input['file_path'],
        OUTPUT_DIR="TEST_OUTPUT",
        PT="",
        Seed=555,
        precision="fp16",
        Training_Steps=0
    )

    train_only_unet(
        stpsv=500,
        stp=500,
        SESSION_DIR="TEST_OUTPUT",
        MODELT_NAME="runwayml/stable-diffusion-v1-5",
        INSTANCE_DIR=downloaded_input['file_path'],
        OUTPUT_DIR="TEST_OUTPUT",
        PT="",
        Seed=555,
        Res=256,
        precision="fp16",
        Training_Steps=500
    )

    # --------------------------------- Inference -------------------------------- #
    # subprocess.Popen([
    #     "python", "/workspace/stable-diffusion-webui/webui.py",
    #     "--port", "3000",
    #     "--nowebui", "--api", "--xformers",
    #     "--ckpt", "/workspace/v1-5-pruned-emaonly.ckpt"
    # ])

    # check_api_availability("http://127.0.0.1:3000/sdapi/v1/txt2img")

    # inference_results = map(run_inference, job_input['inference_jobs'])

    # print(inference_results)

    # return the output that you want to be returned like pre-signed URLs to output artifacts
    # return {
    #     "inference_results": list(inference_results)
    # }

    return {"test": "test"}


runpod.serverless.start({"handler": handler})
