'''
RunPod | Endpoint | Dreambooth

This is the handler for the DreamBooth serverless worker.
'''

import io
import os
import time
import base64
import requests
import subprocess

from PIL import Image

import runpod
from runpod.serverless.utils import rp_download, rp_upload
from runpod.serverless.utils.rp_validator import validate
from dreambooth import dump_only_textenc, train_only_unet

# ---------------------------------------------------------------------------- #
#                                    Schemas                                   #
# ---------------------------------------------------------------------------- #
TRAIN_SCHEMA = {
    'data_url': {
        'type': str,
        'required': True
    },
    'concept_name': {
        'type': str,
        'required': False,
        'default': None
    },
    # Text Encoder Training Parameters
    'text_steps': {
        'type': int,
        'required': False,
        'default': 350
    },
    'text_seed': {
        'type': int,
        'required': False,
        'default': 555
    },
    'text_learning_rate': {
        'type': float,
        'required': False,
        'default': 1e-6
    },
    'text_lr_scheduler': {
        'type': str,
        'required': False,
        'default': 'linear',
        'constraints': lambda scheduler: scheduler in ['linear', 'cosine', 'cosine_with_restarts', 'polynomial', 'constant', 'constant_with_warmup']
    },
    # UNet Training Parameters
    'unet_seed': {
        'type': int,
        'required': False,
        'default': 555
    },
    'unet_resolution': {
        'type': int,
        'required': False,
        'default': 256
    },
    'unet_epochs': {
        'type': int,
        'required': False,
        'default': 150
    },
    'unet_learning_rate': {
        'type': float,
        'required': False,
        'default': 2e-6
    },
    'unet_lr_scheduler': {
        'type': str,
        'required': False,
        'default': 'linear',
        'constraints': lambda scheduler: scheduler in ['linear', 'cosine', 'cosine_with_restarts', 'polynomial', 'constant', 'constant_with_warmup']
    },
}

INFERENCE_SCHEMA = {
    'enable_hr': {
        'type': bool,
        'required': False,
        'default': False
    },
    'denoising_strength': {
        'type': int,
        'required': False,
        'default': 0
    },
    'firstphase_width': {
        'type': int,
        'required': False,
        'default': 0
    },
    'firstphase_height': {
        'type': int,
        'required': False,
        'default': 0
    },
    'hr_scale': {
        'type': int,
        'required': False,
        'default': 2
    },
    'hr_upscaler': {
        'type': str,
        'required': False,
        'default': 'string'
    },
    'hr_second_pass_steps': {
        'type': int,
        'required': False,
        'default': 0
    },
    'hr_resize_x': {
        'type': int,
        'required': False,
        'default': 0
    },
    'hr_resize_y': {
        'type': int,
        'required': False,
        'default': 0
    },
    'prompt': {
        'type': str,
        'required': True
    },
    'styles': {
        'type': list,
        'required': False,
        'default': []
    },
    'seed': {
        'type': int,
        'required': False,
        'default': -1
    },
    'subseed': {
        'type': int,
        'required': False,
        'default': -1
    },
    'subseed_strength': {
        'type': int,
        'required': False,
        'default': 0
    },
    'seed_resize_from_h': {
        'type': int,
        'required': False,
        'default': -1
    },
    'seed_resize_from_w': {
        'type': int,
        'required': False,
        'default': -1
    },
    'sampler_name': {
        'type': str,
        'required': False,
        'default': 'string'
    },
    'batch_size': {
        'type': int,
        'required': False,
        'default': 1
    },
    'n_iter': {
        'type': int,
        'required': False,
        'default': 1
    },
    'steps': {
        'type': int,
        'required': False,
        'default': 50
    },
    'cfg_scale': {
        'type': int,
        'required': False,
        'default': 7
    },
    'width': {
        'type': int,
        'required': False,
        'default': 512
    },
    'height': {
        'type': int,
        'required': False,
        'default': 512
    },
    'restore_faces': {
        'type': bool,
        'required': False,
        'default': False
    },
    'tiling': {
        'type': bool,
        'required': False,
        'default': False
    },
    'negative_prompt': {
        'type': str,
        'required': False,
        'default': None
    },
    'eta': {
        'type': int,
        'required': False,
        'default': 0
    },
    's_churn': {
        'type': int,
        'required': False,
        'default': 0
    },
    's_tmax': {
        'type': int,
        'required': False,
        'default': 0
    },
    's_tmin': {
        'type': int,
        'required': False,
        'default': 0
    },
    's_noise': {
        'type': int,
        'required': False,
        'default': 0
    },
    'sampler_index': {
        'type': str,
        'required': False,
        'default': 'Euler',
    },
    'script_name': {
        'type': str,
        'required': False,
        'default': None
    },
    'passback': {
        'type': str,
        'required': False,
        'default': None
    }
}

S3_SCHEMA = {
    'accessId': {
        'type': str,
        'required': True
    },
    'accessSecret': {
        'type': str,
        'required': True
    },
    'bucketName': {
        'type': str,
        'required': True
    },
    'endpointUrl': {
        'type': str,
        'required': True
    }
}


# ---------------------------------------------------------------------------- #
#                              Automatic Functions                             #
# ---------------------------------------------------------------------------- #
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
        time.sleep(1)


def run_inference(inference_request):
    '''
    Run inference on a request.
    '''
    response = requests.post(url='http://127.0.0.1:3000/sdapi/v1/txt2img',
                             json=inference_request, timeout=10)
    return response.json()


# ---------------------------------------------------------------------------- #
#                                    Handler                                   #
# ---------------------------------------------------------------------------- #
def handler(job):
    '''
    This is the handler function that will be called on every job.
    '''
    job_input = job['input']

    job_output = {}
    job_output['train'] = {}

    # -------------------------------- Validation -------------------------------- #
    # Validate the training input
    if 'train' not in job_input:
        return {"error": "Missing training input."}
    train_input = job_input['train']

    validated_train_input = validate(job_input['train'], TRAIN_SCHEMA)
    if 'errors' in validated_train_input:
        return {"error": validated_train_input['errors']}
    train_input = validated_train_input['validated_input']

    # Validate the inference input
    if 's3Config' not in job and 'inference' not in job_input:
        return {"error": "Please provide either an inference input or an S3 config."}
    if 'inference' in job_input:
        for index, inference_input in enumerate(job_input['inference']):
            validated_inf_input = validate(inference_input, INFERENCE_SCHEMA)
            if 'errors' in validated_inf_input:
                return {"error": validated_inf_input['errors']}
            job_input['inference'][index] = validated_inf_input['validated_input']

    # Validate the S3 config, if provided
    s3_config = None
    if 's3Config' in job:
        validated_s3_config = validate(job['s3Config'], S3_SCHEMA)
        if 'errors' in validated_s3_config:
            return {"error": validated_s3_config['errors']}
        s3_config = validated_s3_config['validated_input']

    # -------------------------- Download Training Data -------------------------- #
    downloaded_input = rp_download.file(train_input['data_url'])

    # Rename the files to the concept name, if provided.
    if train_input['concept_name'] is not None:
        concept_images = os.listdir(downloaded_input)
        for index, image in enumerate(concept_images):
            file_type = image.split(".")[-1]
            os.rename(
                os.path.join(downloaded_input, image),
                os.path.join(downloaded_input,
                             f"{train_input['concept_name']} ({index}).{file_type}")
            )

    os.makedirs(f"job_files/{job['id']}", exist_ok=True)
    os.makedirs(f"job_files/{job['id']}/model", exist_ok=True)

    # ----------------------------------- Train ---------------------------------- #
    dump_only_textenc(
        model_name="runwayml/stable-diffusion-v1-5",
        concept_dir=downloaded_input['extracted_path'],
        ouput_dir=f"job_files/{job['id']}/model",
        training_steps=train_input['text_steps'],
        PT="",
        seed=train_input['text_seed'],
        precision="fp16",
        learning_rate=train_input['text_learning_rate'],
        lr_scheduler=train_input['text_lr_scheduler']
    )

    train_only_unet(
        stp=500,
        SESSION_DIR="TEST_OUTPUT",
        MODELT_NAME="runwayml/stable-diffusion-v1-5",
        INSTANCE_DIR=downloaded_input['extracted_path'],
        OUTPUT_DIR=f"job_files/{job['id']}/model",
        PT="",
        seed=train_input['unet_seed'],
        resolution=train_input['unet_resolution'],
        precision="fp16",
        num_train_epochs=train_input['unet_epochs'],
        learning_rate=train_input['unet_learning_rate'],
        lr_scheduler=train_input['unet_lr_scheduler'],
    )

    # Convert to CKPT
    diffusers_to_ckpt = subprocess.Popen([
        "python", "/src/diffusers/scripts/convertosdv2.py",
        "--fp16",
        f"/src/job_files/{job['id']}/model",
        f"/src/job_files/{job['id']}/{job['id']}.ckpt"
    ])
    diffusers_to_ckpt.wait()

    trained_ckpt = f"/src/job_files/{job['id']}/{job['id']}.ckpt"

    # --------------------------------- Inference -------------------------------- #
    if 'inference' in job_input:
        os.makedirs(f"job_files/{job['id']}/inference_output", exist_ok=True)

        os.environ["install_dir"] = "/workspace"
        os.environ["COMMANDLINE_ARGS"] = f"--port 3000 --nowebui --api --xformers --ckpt {trained_ckpt}"
        subprocess.Popen(["/workspace/stable-diffusion-webui/webui.sh", "-f"])

        check_api_availability("http://127.0.0.1:3000/sdapi/v1/txt2img")

        # inference_results = list(map(run_inference, job_input['inference']))

        inference_results = []
        print("HERE")
        for inference in job_input['inference']:
            print(inference)
            passback = inference['passback']
            inference = inference.pop('passback')
            print("HERE2")
            print(inference)
            inference = run_inference(inference)
            inference['passback'] = passback
            inference_results.append(inference)

        for top_index, results in enumerate(inference_results):
            for index, image in enumerate(results['images']):
                image = Image.open(io.BytesIO(base64.b64decode(image.split(",", 1)[0])))
                image.save(f"job_files/{job['id']}/inference_output/{top_index}-{index}.png")

                inference_results[top_index]['images'][index] = rp_upload.upload_image(
                    job['id'], f"job_files/{job['id']}/inference_output/{top_index}-{index}.png")

        job_output['inference'] = inference_results

    # ------------------------------- Upload Files ------------------------------- #
    if 's3Config' in job:
        # Upload the checkpoint file
        ckpt_url = rp_upload.file(f"{job['id']}.ckpt", trained_ckpt, s3_config)
        job_output['train']['checkpoint_url'] = ckpt_url

    job_output['refresh_worker'] = True  # Refresh the worker after the job is done
    return job_output


runpod.serverless.start({"handler": handler})
