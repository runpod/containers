import subprocess
import requests
import time
import random

def check_api_availability(host):
    while True:
        try:
            response = requests.get(host)
            return
        except requests.exceptions.RequestException as e:
            print(f"API is not available, retrying in 200ms... ({e})")
        except Exception as e:
            print('something went wrong')
        time.sleep(200/1000)

check_api_availability("http://127.0.0.1:3000/sdapi/v1/txt2img")

cmd = "stress-ng --brk 2 --stack 2 --bigheap 2 --matrix 0 --matrix-size 64 --timeout 48h"
process = subprocess.Popen(cmd, shell=True)

payload = {
    "prompt": "portrait of RWXdoggo, highly detailed face, symmetrical eyes, colorful, flowing hair, fully visible face, powerful, magic, thunders, dramatic lighting, painting, concept art, smooth, sharp focus",
    "sampler_name": "Euler a",
    "batch_size": 40,
    "steps": 200,
    "width": 768,
    "height": 768
}

while True:
    response = requests.post(url='http://127.0.0.1:3000/sdapi/v1/txt2img', json=payload)
    if random.random() < 0.1:
        time.sleep(random.uniform(1,5))
