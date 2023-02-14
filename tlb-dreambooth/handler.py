import runpod
import subprocess
import requests
import time
import subprocess

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

print('run handler')

def run_inference(job):
    response = requests.post(url=f'http://127.0.0.1:3000/sdapi/v1/txt2img', json=job)
    json = response.json()
    return json

def handler(event):
    '''
    This is the handler function that will be called by the serverless.
    '''
    print('got event')
    print(event)
    subprocess.Popen(["python", "/workspace/stable-diffusion-webui/webui.py","--port", "3000", "--nowebui", "--api", "--xformers", "--ckpt", "/workspace/v1-5-pruned-emaonly.ckpt"])
    
    time.sleep(15)

    check_api_availability("http://127.0.0.1:3000/sdapi/v1/txt2img")

    inference_jobs = event['input']['inference_jobs']

    inference_results = map(run_inference, inference_jobs)

    # do the things

    print(inference_results)

    # return the output that you want to be returned like pre-signed URLs to output artifacts
    return {
        "inference_results": list(inference_results)
    }


runpod.serverless.start({"handler": handler})
