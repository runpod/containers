
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
    "data_url": {
        'type': str,
        'required': True
    },
    "steps": {
        'type': int,
        'required': False,
        'default': 4000
    },
    "learning_rate": {
        'type': float,
        'required': False,
        'default': 2e-6,
        'constraints': lambda learning_rate: 0 < learning_rate < 1
    }
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
    {
        "enable_hr": false,
        "denoising_strength": 0,
        "firstphase_width": 0,
        "firstphase_height": 0,
        "hr_scale": 2,
        "hr_upscaler": "string",
        "hr_second_pass_steps": 0,
        "hr_resize_x": 0,
        "hr_resize_y": 0,
        "prompt": "",
        "styles": [
            "A beautiful anime girl"
        ],
        "seed": -1,
        "subseed": -1,
        "subseed_strength": 0,
        "seed_resize_from_h": -1,
        "seed_resize_from_w": -1,
        "sampler_name": "string",
        "batch_size": 1,
        "n_iter": 1,
        "steps": 50,
        "cfg_scale": 7,
        "width": 512,
        "height": 512,
        "restore_faces": false,
        "tiling": false,
        "negative_prompt": "string",
        "eta": 0,
        "s_churn": 0,
        "s_tmax": 0,
        "s_tmin": 0,
        "s_noise": 1,
        "override_settings": {},
        "override_settings_restore_afterwards": true,
        "script_args": [],
        "sampler_index": "Euler",
        "script_name": "string"
        }
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
        MODELT_NAME="runwayml/stable-diffusion-v1-5",
        INSTANCE_DIR=downloaded_input['extracted_path'],
        OUTPUT_DIR="TEST_OUTPUT",
        PT="",
        Seed=555,
        precision="fp16",
        training_steps=350
    )

    train_only_unet(
        stp=500,
        SESSION_DIR="TEST_OUTPUT",
        MODELT_NAME="runwayml/stable-diffusion-v1-5",
        INSTANCE_DIR=downloaded_input['extracted_path'],
        OUTPUT_DIR="TEST_OUTPUT",
        PT="",
        Seed=555,
        Res=256,
        precision="fp16",
        num_train_epochs=150
    )

    # Convert to CKPT
    diffusers_to_ckpt = subprocess.Popen([
        "python", "/src/diffusers/scripts/convertosdv2.py",
        "--fp16",
        "/src/TEST_OUTPUT",
        "/src/TEST_OUTPUT/converted.ckpt"
    ])
    diffusers_to_ckpt.wait()

    # --------------------------------- Inference -------------------------------- #
    subprocess.Popen([
        "python", "/workspace/stable-diffusion-webui/webui.py",
        "--port", "3000",
        "--nowebui", "--api", "--xformers",
        "--ckpt", "/src/TEST_OUTPUT/converted.ckpt"
    ])

    check_api_availability("http://127.0.0.1:3000/sdapi/v1/txt2img")

    inference_results = map(run_inference, job_input['inference'])

    print(inference_results)

    print("Training done")
    while True:
        time.sleep(1000)

    return {"test": "test"}


runpod.serverless.start({"handler": handler})
