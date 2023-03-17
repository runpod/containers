from IPython.display import clear_output
from subprocess import call, getoutput, Popen
from IPython.display import display
import ipywidgets as widgets
import io
from PIL import Image, ImageDraw
import fileinput
import time
import os
from os import listdir
from os.path import isfile
import random
import sys
from io import BytesIO
import requests
from collections import defaultdict
from math import log, sqrt
import numpy as np
import sys
import fileinput



def Deps(force_reinstall):

    if not force_reinstall and os.path.exists('/usr/local/lib/python3.10/dist-packages/safetensors'):
        ntbks()
        print('[1;32mModules and notebooks updated, dependencies already installed')

    else:
        print('[1;33mInstalling the dependencies...')
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
        clear_output()

        done()

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

def done():
    done = widgets.Button(
        description='Done!',
        disabled=True,
        button_style='success',
        tooltip='',
        icon='check'
    )
    display(done)

    
def mdlv1():

   os.chdir('/workspace')
   clear_output()
   print('[1;33mDownlading the V1.5 model...')
   call("mkdir stable-diffusion-v1-5", shell=True)
   os.chdir("stable-diffusion-v1-5")
   call('git init', shell=True)
   call('git lfs install --system --skip-repo', shell=True)
   call('git remote add -f origin https://huggingface.co/runwayml/stable-diffusion-v1-5', shell=True)
   call("git config core.sparsecheckout true", shell=True)
   call('echo -e "\nscheduler\ntext_encoder\ntokenizer\nunet\nmodel_index.json\n!*.safetensors" > .git/info/sparse-checkout', shell=True)      
   call("git pull origin main", shell=True)
   if os.path.exists('unet/diffusion_pytorch_model.bin'):
     call('git clone --depth 1 https://huggingface.co/stabilityai/sd-vae-ft-mse vae', shell=True)
     call('wget -q -O model_index.json https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/Dreambooth/model_index.json', shell=True)
     clear_output()
   if os.path.exists('.git'):
     call('rm -r .git', shell=True)
   os.chdir('/workspace')
    
   while not os.path.exists('/workspace/stable-diffusion-v1-5/unet/diffusion_pytorch_model.bin'):
         print('[1;31mSomething went wrong, try again')
         os.chdir('/workspace')
         time.sleep(5)


def downloadmodel_hf(Path_to_HuggingFace):

  import wget
  os.chdir('/workspace')
  if os.path.exists('stable-diffusion-custom'):
    call("rm -r stable-diffusion-custom", shell=True)
  clear_output()
  
  if os.path.exists('Fast-Dreambooth/token.txt'):
    with open("Fast-Dreambooth/token.txt") as f:
       token = f.read()
    authe=f'https://USER:{token}@'
  else:
    authe="https://"  

  clear_output()
  call("mkdir stable-diffusion-custom", shell=True)
  os.chdir("stable-diffusion-custom")
  call("git init", shell=True)
  call("git lfs install --system --skip-repo", shell=True)
  call('git remote add -f origin '+authe+'huggingface.co/'+Path_to_HuggingFace, shell=True)
  call("git config core.sparsecheckout true", shell=True)
  call('echo -e "\nscheduler\ntext_encoder\ntokenizer\nunet\nvae\nmodel_index.json\n!*.safetensors" > .git/info/sparse-checkout', shell=True)
  call("git pull origin main", shell=True)
  if os.path.exists('stable-diffusion-custom/unet/diffusion_pytorch_model.bin'):
    call("rm -r stable-diffusion-custom/.git", shell=True)
    call("rm -r stable-diffusion-custom/model_index.json", shell=True)
    wget.download('https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/Dreambooth/model_index.json')
    os.chdir('/workspace')
    clear_output()
    done()

  while not os.path.exists('/workspace/stable-diffusion-custom/unet/diffusion_pytorch_model.bin'):
        print('[1;31mCheck the link you provided')
        os.chdir('/workspace')
        time.sleep(5)



def downloadmodel_pth(CKPT_Path):

  import wget
  os.chdir('/workspace')
  clear_output() 
  if os.path.exists(str(CKPT_Path)):
    wget.download('https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dreambooth/refmdlz')
    call('unzip -o -q refmdlz', shell=True)
    call('rm -f refmdlz', shell=True)
    wget.download('https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/Dreambooth/convertodiffv1.py')
    clear_output()
    call('python convertodiffv1.py '+CKPT_Path+' stable-diffusion-custom --v1', shell=True)
    call('rm convertodiffv1.py', shell=True)
    call('rm -r refmdl', shell=True)
    if os.path.exists('stable-diffusion-custom/unet/diffusion_pytorch_model.bin'):
      clear_output()
      done()
    while not os.path.exists('/workspace/stable-diffusion-custom/unet/diffusion_pytorch_model.bin'):
      print('[1;31mConversion error')
      time.sleep(5)
      
  else:
    while not os.path.exists(str(CKPT_Path)):
       print('[1;31mWrong path, use the file explorer to copy the path')
       time.sleep(5)
       

def downloadmodel_lnk(CKPT_Link):

    import wget
    os.chdir('/workspace')
    call("gdown --fuzzy " +CKPT_Link+ " -O model.ckpt", shell=True)
    
    if os.path.exists('model.ckpt'):
      if os.path.getsize("model.ckpt") > 1810671599:
        wget.download('https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dreambooth/refmdlz')
        call('unzip -o -q refmdlz', shell=True)
        call('rm -f refmdlz', shell=True)
        wget.download('https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/Dreambooth/convertodiffv1.py')
        clear_output()
        call('python convertodiffv1.py model.ckpt stable-diffusion-custom --v1', shell=True)
        call('rm convertodiffv1.py', shell=True)
        call('rm -r refmdl', shell=True)
        if os.path.exists('stable-diffusion-custom/unet/diffusion_pytorch_model.bin'):
          call('rm model.ckpt', shell=True)
          clear_output()
          done()
        else:
          while not os.path.exists('/workspace/stable-diffusion-custom/unet/diffusion_pytorch_model.bin'):
            print('[1;31mConversion error')
            time.sleep(5)
      else:
        while os.path.getsize('model.ckpt') < 1810671599:
           print('[1;31mWrong link, check that the link is valid')
           time.sleep(5)

           
def dl(Path_to_HuggingFace, CKPT_Path, CKPT_Link):

    if Path_to_HuggingFace != "":
      downloadmodel_hf(Path_to_HuggingFace)
      MODEL_NAME="/workspace/stable-diffusion-custom"
    elif CKPT_Path !="":
      downloadmodel_pth(CKPT_Path)
      MODEL_NAME="/workspace/stable-diffusion-custom"
    elif CKPT_Link !="":
      downloadmodel_lnk(CKPT_Link)
      MODEL_NAME="/workspace/stable-diffusion-custom"
    else:
      if not os.path.exists('/workspace/stable-diffusion-v1-5'):
        mdlv1()
      MODEL_NAME="/workspace/stable-diffusion-v1-5"
      print('[1;32mUsing the original V1.5 model')

    call("sed -i 's@\"sample_size\": 256,@\"sample_size\": 512,@g' "+MODEL_NAME+"/vae/config.json", shell=True)
    return MODEL_NAME



def sess(Session_Name, Session_Link_optional, MODEL_NAME):

    import wget, gdown
    
    os.chdir('/workspace')
    PT=""
    while Session_Name=="":
      print('[1;31mInput the Session Name:') 
      Session_Name=input("")
    Session_Name=Session_Name.replace(" ","_")

    WORKSPACE='/workspace/Fast-Dreambooth'

    if Session_Link_optional !="":
      print('[1;33mDownloading session...')

      if Session_Link_optional != "":
        if not os.path.exists(str(WORKSPACE+'/Sessions')):
          call("mkdir -p " +WORKSPACE+ "/Sessions", shell=True)
          time.sleep(1)
        os.chdir(WORKSPACE+'/Sessions')
        gdown.download_folder(url=Session_Link_optional, output=Session_Name, quiet=True, remaining_ok=True, use_cookies=False)
        os.chdir(Session_Name)
        call("rm -r " +instance_images, shell=True)
        call("unzip " +instance_images.zip, shell=True, stdout=open('/dev/null', 'w'))
        call("rm -r " +concept_images, shell=True)
        call("unzip " +concept_images.zip, shell=True, stdout=open('/dev/null', 'w'))
        call("rm -r " +captions, shell=True)
        call("unzip " +captions.zip, shell=True, stdout=open('/dev/null', 'w'))
        os.chdir('/workspace')
        clear_output()

    INSTANCE_NAME=Session_Name
    OUTPUT_DIR="/workspace/models/"+Session_Name
    SESSION_DIR=WORKSPACE+"/Sessions/"+Session_Name
    CONCEPT_DIR=SESSION_DIR+"/concept_images"
    INSTANCE_DIR=SESSION_DIR+"/instance_images"
    CAPTIONS_DIR=SESSION_DIR+'/captions'
    MDLPTH=str(SESSION_DIR+"/"+Session_Name+'.ckpt')
    resume=False
    
    if os.path.exists(str(SESSION_DIR)):
      mdls=[ckpt for ckpt in listdir(SESSION_DIR) if ckpt.split(".")[-1]=="ckpt"]
      if not os.path.exists(MDLPTH) and '.ckpt' in str(mdls):  
        
        def f(n):
          k=0
          for i in mdls:
            if k==n:
              call('mv '+SESSION_DIR+'/'+i+' '+MDLPTH, shell=True)
            k=k+1

        k=0
        print('[1;33mNo final checkpoint model found, select which intermediary checkpoint to use, enter only the number, (000 to skip):\n[1;34m')

        for i in mdls:
          print(str(k)+'- '+i)
          k=k+1
        n=input()
        while int(n)>k-1:
          n=input()
        if n!="000":
          f(int(n))
          print('[1;32mUsing the model '+ mdls[int(n)]+" ...")
          time.sleep(4)
          clear_output()
        else:
          print('[1;32mSkipping the intermediary checkpoints.')


    if os.path.exists(str(SESSION_DIR)) and not os.path.exists(MDLPTH):
      print('[1;32mLoading session with no previous model, using the original model or the custom downloaded model')
      if MODEL_NAME=="":
        print('[1;31mNo model found, use the "Model Download" cell to download a model.')
      else:
        print('[1;32mSession Loaded, proceed to uploading instance images')

    elif os.path.exists(MDLPTH):
      print('[1;32mSession found, loading the trained model ...')
      wget.download('https://github.com/TheLastBen/fast-stable-diffusion/raw/main/Dreambooth/refmdlz')
      call('unzip -o -q refmdlz', shell=True, stdout=open('/dev/null', 'w'))
      call('rm -f refmdlz', shell=True, stdout=open('/dev/null', 'w'))
      wget.download('https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/Dreambooth/convertodiffv1.py')
      call('python convertodiffv1.py '+MDLPTH+' '+OUTPUT_DIR+' --v1', shell=True)
      call('rm convertodiffv1.py', shell=True)
      call('rm -r refmdl', shell=True)

       
      if os.path.exists(OUTPUT_DIR+'/unet/diffusion_pytorch_model.bin'):
        resume=True
        clear_output()
        print('[1;32mSession loaded.')
      else:     
        print('[1;31mConversion error, if the error persists, remove the CKPT file from the current session folder')

    elif not os.path.exists(str(SESSION_DIR)):
        call('mkdir -p '+INSTANCE_DIR, shell=True)
        print('[1;32mCreating session...')
        if MODEL_NAME=="":
          print('[1;31mNo model found, use the "Model Download" cell to download a model.')
        else:
          print('[1;32mSession created, proceed to uploading instance images')

    return PT, WORKSPACE, Session_Name, INSTANCE_NAME, OUTPUT_DIR, SESSION_DIR, CONCEPT_DIR, INSTANCE_DIR, CAPTIONS_DIR, MDLPTH, MODEL_NAME, resume



def uplder(Remove_existing_instance_images, Crop_images, Crop_size, IMAGES_FOLDER_OPTIONAL, INSTANCE_DIR, CAPTIONS_DIR, ren):

    if os.path.exists(INSTANCE_DIR+"/.ipynb_checkpoints"):
      call('rm -r '+INSTANCE_DIR+'/.ipynb_checkpoints', shell=True)

    uploader = widgets.FileUpload(description="Choose images",accept='image/*', multiple=True)
    Upload = widgets.Button(
        description='Upload',
        disabled=False,
        button_style='info', 
        tooltip='Click to upload the chosen instance images',
        icon=''
    )


    def up(Upload):
        with out: 
            uploader.close()
            Upload.close()
            upld(Remove_existing_instance_images, Crop_images, Crop_size, IMAGES_FOLDER_OPTIONAL, INSTANCE_DIR, CAPTIONS_DIR, uploader, ren)
            done()
    out=widgets.Output()
    
    if IMAGES_FOLDER_OPTIONAL=="":
      Upload.on_click(up)
      display(uploader, Upload, out)
    else:
       upld(Remove_existing_instance_images, Crop_images, Crop_size, IMAGES_FOLDER_OPTIONAL, INSTANCE_DIR, CAPTIONS_DIR, uploader, ren)
       done()
    
    

def upld(Remove_existing_instance_images, Crop_images, Crop_size, IMAGES_FOLDER_OPTIONAL, INSTANCE_DIR, CAPTIONS_DIR, uploader, ren):

    from tqdm import tqdm
    if Remove_existing_instance_images:
        if os.path.exists(str(INSTANCE_DIR)):
            call("rm -r " +INSTANCE_DIR, shell=True)
        if os.path.exists(str(CAPTIONS_DIR)):
            call("rm -r " +CAPTIONS_DIR, shell=True)            


    if not os.path.exists(str(INSTANCE_DIR)):
        call("mkdir -p " +INSTANCE_DIR, shell=True)
    if not os.path.exists(str(CAPTIONS_DIR)):
        call("mkdir -p " +CAPTIONS_DIR, shell=True)        


    if IMAGES_FOLDER_OPTIONAL !="":
        if any(file.endswith('.{}'.format('txt')) for file in os.listdir(IMAGES_FOLDER_OPTIONAL)):
            call('mv '+IMAGES_FOLDER_OPTIONAL+'/*.txt '+CAPTIONS_DIR, shell=True)
        if Crop_images:   
            os.chdir(str(IMAGES_FOLDER_OPTIONAL))
            call('find . -name "* *" -type f | rename ' "'s/ /-/g'", shell=True)
            os.chdir('/workspace')    
            for filename in tqdm(os.listdir(IMAGES_FOLDER_OPTIONAL), bar_format='  |{bar:15}| {n_fmt}/{total_fmt} Uploaded'):
                extension = filename.split(".")[-1]
                identifier=filename.split(".")[0]
                new_path_with_file = os.path.join(INSTANCE_DIR, filename)
                file = Image.open(IMAGES_FOLDER_OPTIONAL+"/"+filename)
                width, height = file.size
                image = file                
                if file.size !=(Crop_size, Crop_size):
                    image=crop_image(file, Crop_size)
                    if (extension.upper() == "JPG" or "jpg"):
                        image[0].save(new_path_with_file, format="JPEG", quality = 100)
                    else:
                        image[0].save(new_path_with_file, format=extension.upper())
                        
                else:
                   call("cp \'"+IMAGES_FOLDER_OPTIONAL+"/"+filename+"\' "+INSTANCE_DIR, shell=True)                        

        else:
            for filename in tqdm(os.listdir(IMAGES_FOLDER_OPTIONAL), bar_format='  |{bar:15}| {n_fmt}/{total_fmt} Uploaded'):
                call("cp -r " +IMAGES_FOLDER_OPTIONAL+"/. " +INSTANCE_DIR, shell=True)

    elif IMAGES_FOLDER_OPTIONAL =="":
        up=""  
        for file in uploader.value:
          filename = file['name']
          if filename.split(".")[-1]=="txt":
            with open(CAPTIONS_DIR+'/'+filename, 'w') as f:
                f.write(file['content'].decode())            
          up=[file for file in uploader.value if filename.split(".")[-1]!="txt"]
        if Crop_images:
            for file in tqdm(up, bar_format='  |{bar:15}| {n_fmt}/{total_fmt} Uploaded'):
                filename = file['name']
                img = Image.open(io.BytesIO(file['content']))
                extension = filename.split(".")[-1]
                identifier=filename.split(".")[0]

                if (extension.upper() == "JPG" or "jpg"):
                    img.save(INSTANCE_DIR+"/"+filename, format="JPEG", quality = 100) 
                else:
                    img.save(INSTANCE_DIR+"/"+filename, format=extension.upper())                
                
                new_path_with_file = os.path.join(INSTANCE_DIR, filename)
                file = Image.open(new_path_with_file)
                width, height = file.size
                image = img          
                if file.size !=(Crop_size, Crop_size):
                    image=crop_image(file, Crop_size)
                    if (extension.upper() == "JPG" or "jpg"):
                        image[0].save(new_path_with_file, format="JPEG", quality = 100) 
                    else:
                        image[0].save(new_path_with_file, format=extension.upper())

        else:
            for file in tqdm(uploader.value, bar_format='  |{bar:15}| {n_fmt}/{total_fmt} Uploaded'):
                filename = file['name']
                img = Image.open(io.BytesIO(file['content']))
                
                extension = filename.split(".")[-1]
                identifier=filename.split(".")[0]   
                
                if (extension.upper() == "JPG" or "jpg"):
                    img.save(INSTANCE_DIR+"/"+filename, format="JPEG", quality = 100) 
                else:
                    img.save(INSTANCE_DIR+"/"+filename, format=extension.upper())                  
   

    if ren:
        i=0
        for filename in tqdm(os.listdir(INSTANCE_DIR), bar_format='  |{bar:15}| {n_fmt}/{total_fmt} Renamed'):
          extension = filename.split(".")[-1]
          identifier=filename.split(".")[0]
          new_path_with_file = os.path.join(INSTANCE_DIR, "conceptimagedb"+str(i)+"."+extension)
          call('mv "'+os.path.join(INSTANCE_DIR,filename)+'" "'+new_path_with_file+'"', shell=True)
          i=i+1

    os.chdir(INSTANCE_DIR)
    call('find . -name "* *" -type f | rename ' "'s/ /-/g'", shell=True)
    os.chdir(CAPTIONS_DIR)
    call('find . -name "* *" -type f | rename ' "'s/ /-/g'", shell=True)    
    os.chdir('/workspace')



def caption(CAPTIONS_DIR, INSTANCE_DIR):
   
  paths=""
  out=""
  widgets_l=""
  clear_output()
  def Caption(path):
      if path!="Select an instance image to caption":
        
        name = os.path.splitext(os.path.basename(path))[0]
        ext=os.path.splitext(os.path.basename(path))[-1][1:]
        if ext=="jpg" or "JPG":
          ext="JPEG"        

        if os.path.exists(CAPTIONS_DIR+"/"+name + '.txt'):
          with open(CAPTIONS_DIR+"/"+name + '.txt', 'r') as f:
              text = f.read()
        else:
          with open(CAPTIONS_DIR+"/"+name + '.txt', 'w') as f:
              f.write("")
              with open(CAPTIONS_DIR+"/"+name + '.txt', 'r') as f:
                  text = f.read()   

        img=Image.open(os.path.join(INSTANCE_DIR,path))
        img=img.resize((420, 420))
        image_bytes = BytesIO()
        img.save(image_bytes, format=ext, qualiy=10)
        image_bytes.seek(0)
        image_data = image_bytes.read()
        img= image_data  
        image = widgets.Image(
            value=img,
            width=420,
            height=420
        )
        text_area = widgets.Textarea(value=text, description='', disabled=False, layout={'width': '300px', 'height': '120px'})
        

        def update_text(text):
            with open(CAPTIONS_DIR+"/"+name + '.txt', 'w') as f:
                f.write(text)

        button = widgets.Button(description='Save', button_style='success')
        button.on_click(lambda b: update_text(text_area.value))

        return widgets.VBox([widgets.HBox([image, text_area, button])])


  paths = os.listdir(INSTANCE_DIR)
  widgets_l = widgets.Select(options=["Select an instance image to caption"]+paths, rows=25)


  out = widgets.Output()

  def click(change):
      with out:
          out.clear_output()
          display(Caption(change.new))

  widgets_l.observe(click, names='value')
  display(widgets.HBox([widgets_l, out]))



def dbtrain(Resume_Training, UNet_Training_Steps, UNet_Learning_Rate, Text_Encoder_Training_Steps, Text_Encoder_Concept_Training_Steps, Text_Encoder_Learning_Rate, Style_Training, Resolution, MODEL_NAME, SESSION_DIR, INSTANCE_DIR, CONCEPT_DIR, CAPTIONS_DIR, External_Captions,  INSTANCE_NAME, Session_Name, OUTPUT_DIR, PT, resume, Save_Checkpoint_Every_n_Steps, Start_saving_from_the_step, Save_Checkpoint_Every):

    if os.path.exists(INSTANCE_DIR+"/.ipynb_checkpoints"):
      call('rm -r '+INSTANCE_DIR+'/.ipynb_checkpoints', shell=True)
    if os.path.exists(CONCEPT_DIR+"/.ipynb_checkpoints"):
      call('rm -r '+CONCEPT_DIR+'/.ipynb_checkpoints', shell=True)
    if os.path.exists(CAPTIONS_DIR+"/.ipynb_checkpoints"):
      call('rm -r '+CAPTIONS_DIR+'/.ipynb_checkpoints', shell=True)

    if resume and not Resume_Training:
      print('[1;31mOverwrite your previously trained model ?, answering "yes" will train a new model, answering "no" will resume the training of the previous model?  yes or no ?[0m')
      while True:
        ansres=input('')
        if ansres=='no':
          Resume_Training = True
          break
        elif ansres=='yes':
          Resume_Training = False
          resume= False
          break

    while not Resume_Training and not os.path.exists(MODEL_NAME+'/unet/diffusion_pytorch_model.bin'):
        print('[1;31mNo model found, use the "Model Download" cell to download a model.')
        time.sleep(5) 

    MODELT_NAME=MODEL_NAME

    Seed=random.randint(1, 999999)
    
    Style=""
    if Style_Training:
      Style="--Style"
      
    extrnlcptn=""
    if External_Captions:
      extrnlcptn="--external_captions"      

    precision="fp16"
    
    GCUNET="--gradient_checkpointing"
    if Resolution<=640:
      GCUNET=""

    resuming=""
    if Resume_Training and os.path.exists(OUTPUT_DIR+'/unet/diffusion_pytorch_model.bin'):
      MODELT_NAME=OUTPUT_DIR
      print('[1;32mResuming Training...[0m')
      resuming="Yes"
    elif Resume_Training and not os.path.exists(OUTPUT_DIR+'/unet/diffusion_pytorch_model.bin'):
      print('[1;31mPrevious model not found, training a new model...[0m') 
      MODELT_NAME=MODEL_NAME
      while MODEL_NAME=="":
        print('[1;31mNo model found, use the "Model Download" cell to download a model.')
        time.sleep(5)


    trnonltxt=""
    if UNet_Training_Steps==0:
       trnonltxt="--train_only_text_encoder"      
      
    Enable_text_encoder_training= True
    Enable_Text_Encoder_Concept_Training= True
    

    if Text_Encoder_Training_Steps==0:
       Enable_text_encoder_training= False
    else:
      stptxt=Text_Encoder_Training_Steps
      
    if Text_Encoder_Concept_Training_Steps==0:
       Enable_Text_Encoder_Concept_Training= False
    else:
      stptxtc=Text_Encoder_Concept_Training_Steps
      
      
    if Save_Checkpoint_Every==None:
      Save_Checkpoint_Every=1
    stp=0
    if Start_saving_from_the_step==None:
      Start_saving_from_the_step=0
    if (Start_saving_from_the_step < 200):
      Start_saving_from_the_step=Save_Checkpoint_Every
    stpsv=Start_saving_from_the_step
    if Save_Checkpoint_Every_n_Steps:
      stp=Save_Checkpoint_Every


    def dump_only_textenc(trnonltxt, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR, PT, Seed, precision, Training_Steps):
        call('accelerate launch /workspace/diffusers/examples/dreambooth/train_dreambooth_rnpd.py \
        '+trnonltxt+' \
        '+extrnlcptn+' \
        --train_text_encoder \
        --image_captions_filename \
        --dump_only_text_encoder \
        --pretrained_model_name_or_path='+MODELT_NAME+' \
        --instance_data_dir='+INSTANCE_DIR+' \
        --output_dir='+OUTPUT_DIR+' \
        --instance_prompt='+PT+' \
        --seed='+str(Seed)+' \
        --resolution=512 \
        --mixed_precision='+str(precision)+' \
        --train_batch_size=1 \
        --gradient_accumulation_steps=1 --gradient_checkpointing \
        --use_8bit_adam \
        --learning_rate='+str(Text_Encoder_Learning_Rate)+' \
        --lr_scheduler="linear" \
        --lr_warmup_steps=0 \
        --max_train_steps='+str(Training_Steps), shell=True)
        
    def train_only_unet(stp, stpsv, SESSION_DIR, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR, Text_Encoder_Training_Steps, PT, Seed, Resolution, Style, extrnlcptn, precision, Training_Steps):
        clear_output()
        if resuming=="Yes":
          print('[1;32mResuming Training...[0m')
        print('[1;33mTraining the UNet...[0m')
        call('accelerate launch /workspace/diffusers/examples/dreambooth/train_dreambooth_rnpd.py \
        '+Style+' \
        '+extrnlcptn+' \
        --image_captions_filename \
        --train_only_unet \
        --Session_dir='+SESSION_DIR+' \
        --save_starting_step='+str(stpsv)+' \
        --save_n_steps='+str(stp)+' \
        --pretrained_model_name_or_path='+MODELT_NAME+' \
        --instance_data_dir='+INSTANCE_DIR+' \
        --output_dir='+OUTPUT_DIR+' \
        --instance_prompt='+PT+' \
        --seed='+str(Seed)+' \
        --resolution='+str(Resolution)+' \
        --mixed_precision='+str(precision)+' \
        --train_batch_size=1 \
        --gradient_accumulation_steps=1 '+GCUNET+' \
        --use_8bit_adam \
        --learning_rate='+str(UNet_Learning_Rate)+' \
        --lr_scheduler="linear" \
        --lr_warmup_steps=0 \
        --max_train_steps='+str(Training_Steps), shell=True)

    if Enable_text_encoder_training :
      print('[1;33mTraining the text encoder...[0m')
      if os.path.exists(OUTPUT_DIR+'/'+'text_encoder_trained'):
        call('rm -r '+OUTPUT_DIR+'/text_encoder_trained', shell=True)
      dump_only_textenc(trnonltxt, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR, PT, Seed, precision, Training_Steps=stptxt)
      
    if Enable_Text_Encoder_Concept_Training:
      if os.path.exists(CONCEPT_DIR):
        if os.listdir(CONCEPT_DIR)!=[]:
          clear_output()
          if resuming=="Yes":
            print('[1;32mResuming Training...[0m')    
          print('[1;33mTraining the text encoder on the concept...[0m')
          dump_only_textenc(trnonltxt, MODELT_NAME, CONCEPT_DIR, OUTPUT_DIR, PT, Seed, precision, Training_Steps=stptxtc)
        else:
          clear_output()
          if resuming=="Yes":
            print('[1;32mResuming Training...[0m')      
          print('[1;31mNo concept images found, skipping concept training...')
          Text_Encoder_Concept_Training_Steps=0
          time.sleep(8)
      else:
          clear_output()
          if resuming=="Yes":
            print('[1;32mResuming Training...[0m')
          print('[1;31mNo concept images found, skipping concept training...')
          Text_Encoder_Concept_Training_Steps=0
          time.sleep(8)
      
    if UNet_Training_Steps!=0:
      train_only_unet(stp, stpsv, SESSION_DIR, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR, Text_Encoder_Training_Steps, PT, Seed, Resolution, Style, extrnlcptn, precision, Training_Steps=UNet_Training_Steps)

    if UNet_Training_Steps==0 and Text_Encoder_Concept_Training_Steps==0 and Text_Encoder_Training_Steps==0 :
      print('[1;32mNothing to do')
    else:
        if os.path.exists(OUTPUT_DIR+'/unet/diffusion_pytorch_model.bin'):
        
          call('python /workspace/diffusers/scripts/convertosdv2.py --fp16 '+OUTPUT_DIR+' '+SESSION_DIR+'/'+Session_Name+'.ckpt', shell=True)
          clear_output()
          if os.path.exists(SESSION_DIR+"/"+INSTANCE_NAME+'.ckpt'):
            clear_output()
            print("[1;32mDONE, the CKPT model is in the session's folder")
          else:
            print("[1;31mSomething went wrong")    
            
        else:
          print("[1;31mSomething went wrong")

    return resume



def test(Custom_Path, Previous_Session_Name, Session_Name, User, Password, Huggingface_token_optional, restored):

    from slugify import slugify
    from huggingface_hub import HfApi, CommitOperationAdd, create_repo
    import gradio
    
    gradio.close_all()

    if Previous_Session_Name!="":
      print("[1;32mLoading a previous session model")
      mdldir='/workspace/Fast-Dreambooth/Sessions/'+Previous_Session_Name
      path_to_trained_model=mdldir+"/"+Previous_Session_Name+'.ckpt'

            
      while not os.path.exists(path_to_trained_model):
         print("[1;31mThere is no trained model in the previous session")
         time.sleep(5)
          
    elif Custom_Path!="":
      print("[1;32mLoading model from a custom path")
      path_to_trained_model=Custom_Path

       
      while not os.path.exists(path_to_trained_model):
         print("[1;31mWrong Path")
         time.sleep(5)
           
    else:
        print("[1;32mLoading the trained model")
        mdldir='/workspace/Fast-Dreambooth/Sessions/'+Session_Name
        path_to_trained_model=mdldir+"/"+Session_Name+'.ckpt'


        while not os.path.exists(path_to_trained_model):
           print("[1;31mThere is no trained model in this session")
           time.sleep(5)


    auth=f"--gradio-auth {User}:{Password}"
    if User =="" or Password=="":
      auth=""


    if restored:
        Huggingface_token_optional=""

    if Huggingface_token_optional!="":
       username = HfApi().whoami(Huggingface_token_optional)["name"]
       backup=f"https://USER:{Huggingface_token_optional}@huggingface.co/datasets/{username}/fast-stable-diffusion/resolve/main/sd_backup_rnpd.tar.zst"
       response = requests.head(backup)
       if response.status_code == 302:
          restored=True
          print('[1;33mRestoring the SD folder...')
          open('/workspace/sd_backup_rnpd.tar.zst', 'wb').write(requests.get(backup).content)
          call('tar --zstd -xf sd_backup_rnpd.tar.zst', shell=True)
          call('rm sd_backup_rnpd.tar.zst', shell=True)
       else:
          print('[1;33mBackup not found, using a fresh/existing repo...')
          time.sleep(2)
          if not os.path.exists('/workspace/sd/stablediffusion'):
             call('wget -q -O sd_rep.tar.zst https://huggingface.co/TheLastBen/dependencies/resolve/main/sd_rep.tar.zst', shell=True)
             call('tar --zstd -xf sd_rep.tar.zst', shell=True)
             call('rm sd_rep.tar.zst', shell=True)        
          os.chdir('/workspace/sd')
          if not os.path.exists('stable-diffusion-webui'):
              call('git clone -q --depth 1 --branch master https://github.com/AUTOMATIC1111/stable-diffusion-webui', shell=True)            
        
    else:
        print('[1;33mInstalling/Updating the repo...')
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
    print('[1;32m')
    call('git pull', shell=True)
    os.chdir('/workspace')


    call('wget -q -O /usr/local/lib/python3.10/dist-packages/gradio/blocks.py https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/AUTOMATIC1111_files/blocks.py', shell=True)
   
    os.chdir('/workspace/sd/stable-diffusion-webui/modules')
    call('wget -q -O paths.py https://raw.githubusercontent.com/TheLastBen/fast-stable-diffusion/main/AUTOMATIC1111_files/paths.py', shell=True)
    #call("sed -i 's@ui.create_ui().*@ui.create_ui();shared.demo.queue(concurrency_count=999999,status_update_rate=0.1)@' /workspace/sd/stable-diffusion-webui/webui.py", shell=True)
    call("sed -i 's@/content/gdrive/MyDrive/sd/stablediffusion@/workspace/sd/stablediffusion@' /workspace/sd/stable-diffusion-webui/modules/paths.py", shell=True)   
    os.chdir('/workspace/sd/stable-diffusion-webui')
    clear_output()

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


    configf="--disable-console-progressbars --no-half-vae --disable-safe-unpickle --api --xformers --enable-insecure-extension-access --no-download-sd-model  --skip-version-check  --listen --port 3000 --ckpt "+path_to_trained_model+" "+auth
    
    
    return configf, restored
    
    
    
def hf(Name_of_your_concept, hf_token_write, INSTANCE_NAME, OUTPUT_DIR, Session_Name, MDLPTH):

    from slugify import slugify
    from huggingface_hub import HfApi, HfFolder, CommitOperationAdd
    from huggingface_hub import create_repo
    from IPython.display import display_markdown


    if(Name_of_your_concept == ""):
      Name_of_your_concept = Session_Name
    Name_of_your_concept=Name_of_your_concept.replace(" ","-")  
      
    if hf_token_write =="":
      print('[1;32mYour Hugging Face write access token : ')
      hf_token_write=input()

    hf_token = hf_token_write

    api = HfApi()
    your_username = api.whoami(token=hf_token)["name"]

    repo_id = f"{your_username}/{slugify(Name_of_your_concept)}"
    output_dir = f'/workspace/models/'+INSTANCE_NAME

    def bar(prg):
        clear_output()
        br="[1;33mUploading to HuggingFace : " '[0m|'+'█' * prg + ' ' * (25-prg)+'| ' +str(prg*4)+ "%"
        return br

    print("[1;33mLoading...")

    os.chdir(OUTPUT_DIR)
    call('rm -r safety_checker feature_extractor .git', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
    call('rm model_index.json', shell=True)
    call('git init', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
    call('git lfs install --system --skip-repo', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
    call('git remote add -f origin https://huggingface.co/runwayml/stable-diffusion-v1-5', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
    call('git config core.sparsecheckout true', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
    call('echo -e "\nfeature_extractor\nsafety_checker\nmodel_index.json\n!*.safetensors" > .git/info/sparse-checkout', shell=True)
    call('git pull origin main', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
    call('rm -r .git', shell=True, stdout=open('/dev/null', 'w'), stderr=open('/dev/null', 'w'))
    os.chdir('/workspace')

    print(bar(1))
       
    readme_text = f'''---
    license: creativeml-openrail-m
    tags:
    - text-to-image
    - stable-diffusion
    ---
    ### {Name_of_your_concept} Dreambooth model trained by {api.whoami(token=hf_token)["name"]} with TheLastBen's fast-DreamBooth notebook

    '''
    #Save the readme to a file
    readme_file = open("README.md", "w")
    readme_file.write(readme_text)
    readme_file.close()

    operations = [
      CommitOperationAdd(path_in_repo="README.md", path_or_fileobj="README.md"),
      CommitOperationAdd(path_in_repo=f"{Session_Name}.ckpt",path_or_fileobj=MDLPTH)

    ]
    create_repo(repo_id,private=True, token=hf_token)

    api.create_commit(
      repo_id=repo_id,
      operations=operations,
      commit_message=f"Upload the concept {Name_of_your_concept} embeds and token",
      token=hf_token
    )

    api.upload_folder(
      folder_path=OUTPUT_DIR+"/feature_extractor",
      path_in_repo="feature_extractor",
      repo_id=repo_id,
      token=hf_token
    )

    print(bar(4))

    api.upload_folder(
      folder_path=OUTPUT_DIR+"/safety_checker",
      path_in_repo="safety_checker",
      repo_id=repo_id,
      token=hf_token
    )

    print(bar(8))

    api.upload_folder(
      folder_path=OUTPUT_DIR+"/scheduler",
      path_in_repo="scheduler",
      repo_id=repo_id,
      token=hf_token
    )

    print(bar(9))

    api.upload_folder(
      folder_path=OUTPUT_DIR+"/text_encoder",
      path_in_repo="text_encoder",
      repo_id=repo_id,
      token=hf_token
    )

    print(bar(12))

    api.upload_folder(
      folder_path=OUTPUT_DIR+"/tokenizer",
      path_in_repo="tokenizer",
      repo_id=repo_id,
      token=hf_token
    )

    print(bar(13))

    api.upload_folder(
      folder_path=OUTPUT_DIR+"/unet",
      path_in_repo="unet",
      repo_id=repo_id,
      token=hf_token
    )

    print(bar(21))

    api.upload_folder(
      folder_path=OUTPUT_DIR+"/vae",
      path_in_repo="vae",
      repo_id=repo_id,
      token=hf_token
    )

    print(bar(23))

    api.upload_file(
      path_or_fileobj=OUTPUT_DIR+"/model_index.json",
      path_in_repo="model_index.json",
      repo_id=repo_id,
      token=hf_token
    )

    print(bar(25))

    print("[1;32mYour concept was saved successfully at https://huggingface.co/"+repo_id)
    done()


def clean():
    
    Sessions=os.listdir("/workspace/Fast-Dreambooth/Sessions")

    s = widgets.Select(
        options=Sessions,
        rows=5,
        description='',
        disabled=False
    )

    out=widgets.Output()

    d = widgets.Button(
        description='Remove',
        disabled=False,
        button_style='warning',
        tooltip='Removet the selected session',
        icon='warning'
    )

    def rem(d):
        with out:
            if s.value is not None:
                clear_output()
                print("[1;33mTHE SESSION [1;31m"+s.value+" [1;33mHAS BEEN REMOVED FROM THE STORAGE")
                call('rm -r /workspace/Fast-Dreambooth/Sessions/'+s.value, shell=True)
                if os.path.exists('/workspace/models/'+s.value):
                  call('rm -r /workspace/models/'+s.value, shell=True)
                s.options=os.listdir("/workspace/Fast-Dreambooth/Sessions")       


            else:
                d.close()
                s.close()
                clear_output()
                print("[1;32mNOTHING TO REMOVE")

    d.on_click(rem)
    if s.value is not None:
        display(s,d,out)
    else:
        print("[1;32mNOTHING TO REMOVE")



def crop_image(im, size):

  import cv2

  GREEN = "#0F0"
  BLUE = "#00F"
  RED = "#F00"    

  def focal_point(im, settings):
      corner_points = image_corner_points(im, settings) if settings.corner_points_weight > 0 else []
      entropy_points = image_entropy_points(im, settings) if settings.entropy_points_weight > 0 else []
      face_points = image_face_points(im, settings) if settings.face_points_weight > 0 else []

      pois = []

      weight_pref_total = 0
      if len(corner_points) > 0:
        weight_pref_total += settings.corner_points_weight
      if len(entropy_points) > 0:
        weight_pref_total += settings.entropy_points_weight
      if len(face_points) > 0:
        weight_pref_total += settings.face_points_weight

      corner_centroid = None
      if len(corner_points) > 0:
        corner_centroid = centroid(corner_points)
        corner_centroid.weight = settings.corner_points_weight / weight_pref_total 
        pois.append(corner_centroid)

      entropy_centroid = None
      if len(entropy_points) > 0:
        entropy_centroid = centroid(entropy_points)
        entropy_centroid.weight = settings.entropy_points_weight / weight_pref_total
        pois.append(entropy_centroid)

      face_centroid = None
      if len(face_points) > 0:
        face_centroid = centroid(face_points)
        face_centroid.weight = settings.face_points_weight / weight_pref_total 
        pois.append(face_centroid)

      average_point = poi_average(pois, settings)
      
      return average_point


  def image_face_points(im, settings):

      np_im = np.array(im)
      gray = cv2.cvtColor(np_im, cv2.COLOR_BGR2GRAY)

      tries = [
        [ f'{cv2.data.haarcascades}haarcascade_eye.xml', 0.01 ],
        [ f'{cv2.data.haarcascades}haarcascade_frontalface_default.xml', 0.05 ],
        [ f'{cv2.data.haarcascades}haarcascade_profileface.xml', 0.05 ],
        [ f'{cv2.data.haarcascades}haarcascade_frontalface_alt.xml', 0.05 ],
        [ f'{cv2.data.haarcascades}haarcascade_frontalface_alt2.xml', 0.05 ],
        [ f'{cv2.data.haarcascades}haarcascade_frontalface_alt_tree.xml', 0.05 ],
        [ f'{cv2.data.haarcascades}haarcascade_eye_tree_eyeglasses.xml', 0.05 ],
        [ f'{cv2.data.haarcascades}haarcascade_upperbody.xml', 0.05 ]
      ]
      for t in tries:
        classifier = cv2.CascadeClassifier(t[0])
        minsize = int(min(im.width, im.height) * t[1]) # at least N percent of the smallest side
        try:
          faces = classifier.detectMultiScale(gray, scaleFactor=1.1,
            minNeighbors=7, minSize=(minsize, minsize), flags=cv2.CASCADE_SCALE_IMAGE)
        except:
          continue

        if len(faces) > 0:
          rects = [[f[0], f[1], f[0] + f[2], f[1] + f[3]] for f in faces]
          return [PointOfInterest((r[0] +r[2]) // 2, (r[1] + r[3]) // 2, size=abs(r[0]-r[2]), weight=1/len(rects)) for r in rects]
      return []


  def image_corner_points(im, settings):
      grayscale = im.convert("L")

      # naive attempt at preventing focal points from collecting at watermarks near the bottom
      gd = ImageDraw.Draw(grayscale)
      gd.rectangle([0, im.height*.9, im.width, im.height], fill="#999")

      np_im = np.array(grayscale)

      points = cv2.goodFeaturesToTrack(
          np_im,
          maxCorners=100,
          qualityLevel=0.04,
          minDistance=min(grayscale.width, grayscale.height)*0.06,
          useHarrisDetector=False,
      )

      if points is None:
          return []

      focal_points = []
      for point in points:
        x, y = point.ravel()
        focal_points.append(PointOfInterest(x, y, size=4, weight=1/len(points)))

      return focal_points


  def image_entropy_points(im, settings):
      landscape = im.height < im.width
      portrait = im.height > im.width
      if landscape:
        move_idx = [0, 2]
        move_max = im.size[0]
      elif portrait:
        move_idx = [1, 3]
        move_max = im.size[1]
      else:
        return []

      e_max = 0
      crop_current = [0, 0, settings.crop_width, settings.crop_height]
      crop_best = crop_current
      while crop_current[move_idx[1]] < move_max:
          crop = im.crop(tuple(crop_current))
          e = image_entropy(crop)

          if (e > e_max):
            e_max = e
            crop_best = list(crop_current)

          crop_current[move_idx[0]] += 4
          crop_current[move_idx[1]] += 4

      x_mid = int(crop_best[0] + settings.crop_width/2)
      y_mid = int(crop_best[1] + settings.crop_height/2)

      return [PointOfInterest(x_mid, y_mid, size=25, weight=1.0)]


  def image_entropy(im):
      # greyscale image entropy
      # band = np.asarray(im.convert("L"))
      band = np.asarray(im.convert("1"), dtype=np.uint8)
      hist, _ = np.histogram(band, bins=range(0, 256))
      hist = hist[hist > 0]
      return -np.log2(hist / hist.sum()).sum()

  def centroid(pois):
    x = [poi.x for poi in pois]
    y = [poi.y for poi in pois]
    return PointOfInterest(sum(x)/len(pois), sum(y)/len(pois))


  def poi_average(pois, settings):
      weight = 0.0
      x = 0.0
      y = 0.0
      for poi in pois:
          weight += poi.weight
          x += poi.x * poi.weight
          y += poi.y * poi.weight
      avg_x = round(weight and x / weight)
      avg_y = round(weight and y / weight)

      return PointOfInterest(avg_x, avg_y)


  def is_landscape(w, h):
    return w > h


  def is_portrait(w, h):
    return h > w


  def is_square(w, h):
    return w == h


  class PointOfInterest:
    def __init__(self, x, y, weight=1.0, size=10):
      self.x = x
      self.y = y
      self.weight = weight
      self.size = size

    def bounding(self, size):
      return [
        self.x - size//2,
        self.y - size//2,
        self.x + size//2,
        self.y + size//2
      ]

  class Settings:
    def __init__(self, crop_width=512, crop_height=512, corner_points_weight=0.5, entropy_points_weight=0.5, face_points_weight=0.5):
      self.crop_width = crop_width
      self.crop_height = crop_height
      self.corner_points_weight = corner_points_weight
      self.entropy_points_weight = entropy_points_weight
      self.face_points_weight = face_points_weight

  settings = Settings(
      crop_width = size,
      crop_height = size,
      face_points_weight = 0.9,
      entropy_points_weight = 0.15,
      corner_points_weight = 0.5,
  )        

  scale_by = 1
  if is_landscape(im.width, im.height):
    scale_by = settings.crop_height / im.height
  elif is_portrait(im.width, im.height):
    scale_by = settings.crop_width / im.width
  elif is_square(im.width, im.height):
    if is_square(settings.crop_width, settings.crop_height):
      scale_by = settings.crop_width / im.width
    elif is_landscape(settings.crop_width, settings.crop_height):
      scale_by = settings.crop_width / im.width
    elif is_portrait(settings.crop_width, settings.crop_height):
      scale_by = settings.crop_height / im.height

  im = im.resize((int(im.width * scale_by), int(im.height * scale_by)))
  im_debug = im.copy()

  focus = focal_point(im_debug, settings)

  # take the focal point and turn it into crop coordinates that try to center over the focal
  # point but then get adjusted back into the frame
  y_half = int(settings.crop_height / 2)
  x_half = int(settings.crop_width / 2)

  x1 = focus.x - x_half
  if x1 < 0:
      x1 = 0
  elif x1 + settings.crop_width > im.width:
      x1 = im.width - settings.crop_width

  y1 = focus.y - y_half
  if y1 < 0:
      y1 = 0
  elif y1 + settings.crop_height > im.height:
      y1 = im.height - settings.crop_height

  x2 = x1 + settings.crop_width
  y2 = y1 + settings.crop_height

  crop = [x1, y1, x2, y2]

  results = []

  results.append(im.crop(tuple(crop)))

  return results