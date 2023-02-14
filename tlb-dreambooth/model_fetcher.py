'''
RunPod | serverless-ckpt-template | model_fetcher.py

Downloads the model from the URL passed in.
'''

import os
import shutil
import argparse

from diffusers import StableDiffusionPipeline
from diffusers.pipelines.stable_diffusion.safety_checker import (
    StableDiffusionSafetyChecker,
)


MODEL_ID = "runwayml/stable-diffusion-v1-5"
SAFETY_MODEL_ID = "CompVis/stable-diffusion-safety-checker"
MODEL_CACHE_DIR = "diffusers-cache"

# ---------------------------------------------------------------------------- #
#                                Parse Arguments                               #
# ---------------------------------------------------------------------------- #
argparser = argparse.ArgumentParser(description=__doc__)
argparser.add_argument("--model_url", type=str,
                       default="https://huggingface.co/stabilityai/stable-diffusion-2-1", help="URL of the model to download.")

args = argparser.parse_args()


if os.path.exists(MODEL_CACHE_DIR):
    shutil.rmtree(MODEL_CACHE_DIR)
os.makedirs(MODEL_CACHE_DIR, exist_ok=True)

saftey_checker = StableDiffusionSafetyChecker.from_pretrained(
    SAFETY_MODEL_ID,
    cache_dir=MODEL_CACHE_DIR,
)

pipe = StableDiffusionPipeline.from_pretrained(
    MODEL_ID,
    cache_dir=MODEL_CACHE_DIR,
)
