'''
RunPod | Endpoint | Dreambooth

This is the handler for the DreamBooth serverless worker.
'''

import io
import os
import base64
import requests
import subprocess
from requests.adapters import HTTPAdapter, Retry

from PIL import Image

import runpod
from runpod.serverless.utils import rp_download, rp_upload
from runpod.serverless.utils.rp_validator import validate
from dreambooth import dump_only_textenc, train_only_unet

automatic_session = requests.Session()
retries = Retry(total=6, backoff_factor=10, status_forcelist=[502, 503, 504])
automatic_session.mount('http://', HTTPAdapter(max_retries=retries))

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
    'text_8_bit_adam': {
        'type': bool,
        'required': False,
        'default': False
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
    'unet_8_bit_adam': {
        'type': bool,
        'required': False,
        'default': False
    }
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
        'default': None
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
        'default': 'Euler'
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
        'type': float,
        'required': False,
        'default': 7.0
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
        'default': None
    },
    's_churn': {
        'type': int,
        'required': False,
        'default': 0
    },
    's_tmax': {
        'type': int,
        'required': False,
        'default': None
    },
    's_tmin': {
        'type': int,
        'required': False,
        'default': 0
    },
    's_noise': {
        'type': int,
        'required': False,
        'default': 1
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
def run_inference(inference_request):
    '''
    Run inference on a request.
    '''
    response = automatic_session.post(url='http://127.0.0.1:3000/sdapi/v1/txt2img',
                                      json=inference_request, timeout=600)
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
        concept_images = os.listdir(downloaded_input['extracted_path'])
        for index, image in enumerate(concept_images):
            file_type = image.split(".")[-1]
            os.rename(
                os.path.join(downloaded_input['extracted_path'], image),
                os.path.join(downloaded_input['extracted_path'],
                             f"{train_input['concept_name']} ({index}).{file_type}")
            )

    os.makedirs(f"job_files/{job['id']}", exist_ok=True)
    os.makedirs(f"job_files/{job['id']}/model", exist_ok=True)

    # ----------------------------------- Train ---------------------------------- #
    dump_only_textenc(
        model_name="/src/stable-diffusion-v1-5",
        concept_dir=downloaded_input['extracted_path'],
        ouput_dir=f"job_files/{job['id']}/model",
        training_steps=train_input['text_steps'],
        PT="",
        seed=train_input['text_seed'],
        precision="fp16",
        learning_rate=train_input['text_learning_rate'],
        lr_scheduler=train_input['text_lr_scheduler'],
        enable_adam=train_input['text_8_bit_adam'],
    )

    train_only_unet(
        stp=500,
        SESSION_DIR="TEST_OUTPUT",
        MODELT_NAME="/src/stable-diffusion-v1-5",
        INSTANCE_DIR=downloaded_input['extracted_path'],
        OUTPUT_DIR=f"job_files/{job['id']}/model",
        PT="",
        seed=train_input['unet_seed'],
        resolution=train_input['unet_resolution'],
        precision="fp16",
        num_train_epochs=train_input['unet_epochs'],
        learning_rate=train_input['unet_learning_rate'],
        lr_scheduler=train_input['unet_lr_scheduler'],
        enable_adam=train_input['unet_8_bit_adam'],
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

        subprocess.Popen([
            "python", "/workspace/sd/stable-diffusion-webui/webui.py",
            "--port", "3000",
            "--nowebui", "--api", "--xformers",
            "--ckpt", f"{trained_ckpt}"
        ])

        inference_results = []
        for inference in job_input['inference']:
            passback = inference['passback']
            inference.pop('passback')

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
