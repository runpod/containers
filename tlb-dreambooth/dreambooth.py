'''
Trains DreamBooth image encoder then text encoder sequentially.
'''

import subprocess


# ---------------------------------------------------------------------------- #
#                                 Text Encoder                                 #
# ---------------------------------------------------------------------------- #
def dump_only_textenc(
        model_name, concept_dir, ouput_dir, PT, seed,
        precision, training_steps, learning_rate, lr_scheduler, enable_adam):
    '''
    Train the text encoder first.
    '''
    text_options = [
        "accelerate", "launch", "/src/diffusers/examples/dreambooth/train_dreambooth.py",
        "--train_text_encoder",
        "--dump_only_text_encoder",
        f"--pretrained_model_name_or_path={model_name}",
        f"--instance_data_dir={concept_dir}",
        f"--instance_prompt={PT}",
        f"--output_dir={ouput_dir}",
        f"--seed={seed}",
        "--resolution=512",
        "--train_batch_size=1",
        f"--max_train_steps={training_steps}",
        "--gradient_accumulation_steps=1",
        # "--gradient_checkpointing",
        f"--learning_rate={learning_rate}",
        f"--lr_scheduler={lr_scheduler}",
        "--lr_warmup_steps=0",
        f"--mixed_precision={precision}",
        "--image_captions_filename"
    ]

    if enable_adam:
        text_options.append("--use_8bit_adam")

    text_encoder = subprocess.Popen(text_options)

    text_encoder.wait()


# ---------------------------------------------------------------------------- #
#                                     UNet                                     #
# ---------------------------------------------------------------------------- #
def train_only_unet(
        stp, SESSION_DIR, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR,
        PT, seed, resolution, precision, num_train_epochs, learning_rate, lr_scheduler, enable_adam):
    '''
    Train only the image encoder.
    '''
    unet_options = [
        "accelerate", "launch", "/src/diffusers/examples/dreambooth/train_dreambooth.py",
        "--image_captions_filename",
        "--train_only_unet",
        f"--save_n_steps={stp}",

        f"--pretrained_model_name_or_path={MODELT_NAME}",
        f"--instance_data_dir={INSTANCE_DIR}",
        f"--output_dir={OUTPUT_DIR}",
        f"--instance_prompt={PT}",
        f"--seed={seed}",
        f"--resolution={resolution}",
        f"--mixed_precision={precision}",
        "--train_batch_size=1",
        "--gradient_accumulation_steps=1",
        f"--learning_rate={learning_rate}",
        f"--lr_scheduler={lr_scheduler}",
        "--lr_warmup_steps=0",

        f"--num_train_epochs={num_train_epochs}",

        f"--Session_dir={SESSION_DIR}"
    ]

    if enable_adam:
        unet_options.append("--use_8bit_adam")

    unet = subprocess.Popen(unet_options)

    unet.wait()
