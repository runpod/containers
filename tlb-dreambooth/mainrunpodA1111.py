import os
from subprocess import call, getoutput, Popen
import time
import ipywidgets as widgets
import requests
import sys
import fileinput
from torch.hub import download_url_to_file
from urllib.parse import urlparse


def Deps(force_reinstall):

    if not force_reinstall and os.path.exists('/usr/local/lib/python3.10/dist-packages/safetensors'):
        ntbks()
        print('[1;32mModules and notebooks updated, dependencies already installed')

    else:
        print('[1;33mInstalling the dependencies...')
        call('pip install --root-user-action=ignore --disable-pip-version-check --no-deps -qq gdown numpy==1.23.5 accelerate==0.12.0 --force-reinstall', shell=True, stdout=open('/dev/null', 'w'))
        ntbks()
        if os.path.exists('deps'):
            call("rm -r deps", shell=True)
        if os.path.exists('diffusers'):
            call("rm -r diffusers", shell=True)            
        call('mkdir deps', shell=True)
        if not os.path.exists('cache'):
            call('mkdir cache', shell=True)
        os.chdir('deps')
        call('wget -q -i https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dependencies/rnpd_deps.txt', shell=True, stdout=open('/dev/null', 'w'))
        call('dpkg -i *.deb', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
        call('tar -C / --zstd -xf rnpd-310.tar.zst', shell=True, stdout=open('/dev/null', 'w'))
        call('apt-get install libfontconfig1 libgles2-mesa-dev -q=2 --no-install-recommends', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
        call("sed -i 's@~/.cache@/workspace/cache@' /usr/local/lib/python3.10/dist-packages/transformers/utils/hub.py", shell=True)
        os.chdir('/workspace')
        call("git clone --depth 1 -q --branch updt https://github.com/TheLastBen/diffusers", shell=True, stdout=open('/dev/null', 'w'))
        call("rm -r deps", shell=True)
        os.chdir('/workspace')

def ntbks():

    os.chdir('/workspace')
    if not os.path.exists('Latest_Notebooks'):
        call('mkdir Latest_Notebooks', shell=True)
    else:
        call('rm -r Latest_Notebooks', shell=True)
        call('mkdir Latest_Notebooks', shell=True)
    os.chdir('/workspace/Latest_Notebooks')
    call('wget -q -i https://huggingface.co/datasets/TheLastBen/RNPD/raw/main/Notebooks.txt', shell=True)
    call('rm Notebooks.txt', shell=True)
    os.chdir('/workspace')


def repo(Huggingface_token_optional):
    
    from slugify import slugify
    from huggingface_hub import HfApi, CommitOperationAdd, create_repo
    
    os.chdir('/workspace')
    if Huggingface_token_optional!="":
       username = HfApi().whoami(Huggingface_token_optional)["name"]
       backup=f"https://USER:{Huggingface_token_optional}@huggingface.co/datasets/{username}/fast-stable-diffusion/resolve/main/sd_backup_rnpd.tar.zst"
       response = requests.head(backup)
       if response.status_code == 302:
          print('[1;33mRestoring the SD folder...')
          open('/workspace/sd_backup_rnpd.tar.zst', 'wb').write(requests.get(backup).content)
          call('tar --zstd -xf sd_backup_rnpd.tar.zst', shell=True)
          call('rm sd_backup_rnpd.tar.zst', shell=True)
       else:
          print('[1;33mBackup not found, using a fresh/existing repo...')
          time.sleep(2)
          if not os.path.exists('/workspace/sd/stablediffusion'):
             call('wget -q -O sd_rep.tar.zst https://huggingface.co/TheLastBen/dependencies/resolve/main/sd_rep.tar.zst', shell=True)
             call('tar --zstd -xf sd_rep.tar.zst', shell=True)
             call('rm sd_rep.tar.zst', shell=True)        
          os.chdir('/workspace/sd')
          if not os.path.exists('stable-diffusion-webui'):
              call('git clone -q --depth 1 --branch master https://github.com/AUTOMATIC1111/stable-diffusion-webui', shell=True)            
        
    else:
        print('[1;33mInstalling/Updating the repo...')
        os.chdir('/workspace')
        if not os.path.exists('/workspace/sd/stablediffusion'):
           call('wget -q -O sd_rep.tar.zst https://huggingface.co/TheLastBen/dependencies/resolve/main/sd_rep.tar.zst', shell=True)
           call('tar --zstd -xf sd_rep.tar.zst', shell=True)
           call('rm sd_rep.tar.zst', shell=True)        

        os.chdir('/workspace/sd')
        if not os.path.exists('stable-diffusion-webui'):
            call('git clone -q --depth 1 --branch master https://github.com/AUTOMATIC1111/stable-diffusion-webui', shell=True)


    os.chdir('/workspace/sd/stable-diffusion-webui/')
    call('git reset --hard', shell=True)
    print('[1;32m')
    call('git pull', shell=True)
    os.chdir('/workspace')



def mdl(Original_Model_Version, Path_to_MODEL, MODEL_LINK, safetensors, Redownload_the_original_model):

    import gdown
    
    if os.path.exists('/workspace/auto-models/SDv1-5.ckpt'):
        call('mv /workspace/auto-models/* /workspace/sd/stable-diffusion-webui/models/Stable-diffusion', shell=True)
        call('rm -r /workspace/auto-models', shell=True)

    if Path_to_MODEL !='':
      if os.path.exists(str(Path_to_MODEL)):
        print('[1;32mUsing the trained model.')
        model=Path_to_MODEL
      else:
          print('[1;31mWrong path, check that the path to the model is correct')

    elif MODEL_LINK != "":
      modelname="model.safetensors" if safetensors else "model.ckpt"
      model=f'/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/{modelname}'
      if os.path.exists(model):
        call('rm '+model, shell=True)
      gdown.download(url=MODEL_LINK, output=model, quiet=False, fuzzy=True)

      if os.path.exists(model) and os.path.getsize(model) > 1810671599:
        print('[1;32mModel downloaded, using the trained model.')
      else:
        print('[1;31mWrong link, check that the link is valid')

    else:
        if Original_Model_Version == "v1.5":
           model="/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv1-5.ckpt"
           print('[1;32mUsing the original V1.5 model')
        elif Original_Model_Version == "v2-512":
           if not os.path.exists('/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv2-512.ckpt'):
              print('[1;33mDownlading the V2-512 model...')
              model='/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv2-512.ckpt'
              call('gdown -O '+model+' https://huggingface.co/stabilityai/stable-diffusion-2-1-base/resolve/main/v2-1_512-nonema-pruned.ckpt', shell=True)
              print('[1;32mUsing the original V2-512 model')
           else:
              print('[1;32mUsing the original V2-512 model')
              model='/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv2-512.ckpt'
        elif Original_Model_Version == "v2-768":
           model="/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv2-768.ckpt"
           print('[1;32mUsing the original V2-768 model')
        else:
            model="/workspace/sd/stable-diffusion-webui/models/Stable-diffusion"
            print('[1;31mWrong model version, try again')
    try:
        model
    except:
        model="/workspace/sd/stable-diffusion-webui/models/Stable-diffusion"

    return model


def mdls(Original_Model_Version, Path_to_MODEL, MODEL_LINK, safetensors):

    import gdown
    
    if os.path.exists('/workspace/auto-models/SDv1-5.ckpt'):
        call('mv /workspace/auto-models/* /workspace/sd/stable-diffusion-webui/models/Stable-diffusion', shell=True)
        call('rm -r /workspace/auto-models', shell=True)

    if Path_to_MODEL !='':
      if os.path.exists(str(Path_to_MODEL)):
        print('[1;32mUsing the trained model.')
        model=Path_to_MODEL
      else:
          print('[1;31mWrong path, check that the path to the model is correct')

    elif MODEL_LINK != "":
      modelname="model.safetensors" if safetensors else "model.ckpt"
      model=f'/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/{modelname}'
      if os.path.exists(model):
        call('rm '+model, shell=True)
      gdown.download(url=MODEL_LINK, output=model, quiet=False, fuzzy=True)

      if os.path.exists(model) and os.path.getsize(model) > 1810671599:
        print('[1;32mModel downloaded, using the trained model.')
      else:
        print('[1;31mWrong link, check that the link is valid')

    else:
        if Original_Model_Version == "v1.5":
           model="/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv1-5.ckpt"
           print('[1;32mUsing the original V1.5 model')
        elif Original_Model_Version == "v2-512":
           if not os.path.exists('/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv2-512.ckpt'):
              print('[1;33mDownlading the V2-512 model...')
              model='/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv2-512.ckpt'
              call('gdown -O '+model+' https://huggingface.co/stabilityai/stable-diffusion-2-1-base/resolve/main/v2-1_512-nonema-pruned.ckpt', shell=True)
              print('[1;32mUsing the original V2-512 model')
           else:
              print('[1;32mUsing the original V2-512 model')
              model='/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv2-512.ckpt'
        elif Original_Model_Version == "v2-768":
           model="/workspace/sd/stable-diffusion-webui/models/Stable-diffusion/SDv2-768.ckpt"
           print('[1;32mUsing the original V2-768 model')
        else:
            model="/workspace/sd/stable-diffusion-webui/models/Stable-diffusion"
            print('[1;31mWrong model version, try again')
    try:
        model
    except:
        model="/workspace/sd/stable-diffusion-webui/models/Stable-diffusion"

    return model


def CN(ControlNet_Model):
    
    def download(url, model_dir):

        filename = os.path.basename(urlparse(url).path)
        pth = os.path.abspath(os.path.join(model_dir, filename))
        if not os.path.exists(pth):
            print('Downloading: '+os.path.basename(url))
            download_url_to_file(url, pth, hash_prefix=None, progress=True)
        else:
          print(f"[1;32mThe model {filename} already exists[0m")    


    os.chdir('/workspace/sd/stable-diffusion-webui/extensions')
    if not os.path.exists("sd-webui-controlnet"):
      call('git clone https://github.com/Mikubill/sd-webui-controlnet.git', shell=True)
      os.chdir('/workspace')
    else:
      os.chdir('sd-webui-controlnet')
      call('git reset --hard', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
      call('git pull', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
      os.chdir('/workspace')
        
    mdldir="/workspace/sd/stable-diffusion-webui/extensions/sd-webui-controlnet/models"

    call('wget -q -O CN_models.txt https://github.com/TheLastBen/fast-stable-diffusion/raw/main/AUTOMATIC1111_files/CN_models.txt', shell=True)
    with open("CN_models.txt", 'r') as f:
        mdllnk = f.read().splitlines()
    call('rm CN_models.txt', shell=True)

    if ControlNet_Model == "All":     
      for lnk in mdllnk:
          download(url=lnk, model_dir=mdldir)
      
    else:
      download(mdllnk[int(ControlNet_Model)-1], mdldir)



def sd(User, Password, model):

    import gradio
    
    gradio.close_all()
    
    auth=f"--gradio-auth {User}:{Password}"
    if User =="" or Password=="":
      auth=""

    call('wget -q -O /usr/local/lib/python3.10/dist-packages/gradio/blocks.py https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/AUTOMATIC1111_files/blocks.py', shell=True)
   
    os.chdir('/workspace/sd/stable-diffusion-webui/modules')
    call('wget -q -O paths.py https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/AUTOMATIC1111_files/paths.py', shell=True)
    #call("sed -i 's@ui.create_ui().*@ui.create_ui();shared.demo.queue(concurrency_count=999999,status_update_rate=0.1)@' /workspace/sd/stable-diffusion-webui/webui.py", shell=True)
    call("sed -i 's@/content/gdrive/MyDrive/sd/stablediffusion@/workspace/sd/stablediffusion@' /workspace/sd/stable-diffusion-webui/modules/paths.py", shell=True)   
    os.chdir('/workspace/sd/stable-diffusion-webui')

    podid=os.environ.get('RUNPOD_POD_ID')
    localurl=f"{podid}-3000.proxy.runpod.net"

    for line in fileinput.input('/usr/local/lib/python3.10/dist-packages/gradio/blocks.py', inplace=True):
      if line.strip().startswith('self.server_name ='):
          line = f'            self.server_name = "{localurl}"\n'
      if line.strip().startswith('self.protocol = "https"'):
          line = '            self.protocol = "https"\n'
      if line.strip().startswith('if self.local_url.startswith("https") or self.is_colab'):
          line = ''
      if line.strip().startswith('else "http"'):
          line = ''
      sys.stdout.write(line)
      
    
    if os.path.isfile(model):
        mdlpth="--ckpt "+model
    else:
        mdlpth="--ckpt-dir "+model

    configf="--disable-console-progressbars --no-half-vae --disable-safe-unpickle --api --no-download-sd-model --xformers --enable-insecure-extension-access  --skip-version-check --listen --port 3000 "+auth+" "+mdlpth

    return configf


def save(Huggingface_Write_token):
    
    from slugify import slugify
    from huggingface_hub import HfApi, CommitOperationAdd, create_repo
    
    if Huggingface_Write_token=="":
        print('[1;31mA huggingface write token is required')
        
    else:
        os.chdir('/workspace')
        
        if os.path.exists('sd'):
        
            call('tar --exclude="stable-diffusion-webui/models/*/*" --exclude="sd-webui-controlnet/models/*" --zstd -cf sd_backup_rnpd.tar.zst sd', shell=True)
            api = HfApi()
            username = api.whoami(token=Huggingface_Write_token)["name"]

            repo_id = f"{username}/{slugify('fast-stable-diffusion')}"

            print("[1;32mBacking up...")

            operations = [CommitOperationAdd(path_in_repo="sd_backup_rnpd.tar.zst", path_or_fileobj="/workspace/sd_backup_rnpd.tar.zst")]

            create_repo(repo_id,private=True, token=Huggingface_Write_token, exist_ok=True, repo_type="dataset")

            api.create_commit(
              repo_id=repo_id,
              repo_type="dataset",
              operations=operations,
              commit_message="SD folder Backup",
              token=Huggingface_Write_token
            )

            call('rm sd_backup_rnpd.tar.zst', shell=True)
     
        else:
            print('[1;33mNothing to backup')
        
