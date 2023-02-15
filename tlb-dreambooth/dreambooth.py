'''
Trains DreamBooth image encoder then text encoder sequentially.
'''

import subprocess


def dump_only_textenc(trnonltxt, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR, PT, Seed, precision, Training_Steps):
    '''
    Train only the text encoder.
    '''
    subprocess.Popen([
        "accelerate", "launch", "/content/diffusers/examples/dreambooth/train_dreambooth.py",
        # Flags
        trnonltxt,
        "--use_8bit_adam",

        # Variables
        "--image_captions_filename",
        "--train_text_encoder",
        "--dump_only_text_encoder",
        f"--pretrained_model_name_or_path=\'{MODELT_NAME}\'",
        f"--instance_data_dir=\'{INSTANCE_DIR}\'",
        f"--output_dir=\'{OUTPUT_DIR}\'",
        f"--instance_prompt=\'{PT}\'",
        f"--seed=\'{Seed}\'",
        "--resolution=512",
        f"--mixed_precision=\'{precision}\'",
        "--train_batch_size=1",
        "--gradient_accumulation_steps=1",
        "--learning_rate='txlr'",
        "--lr_scheduler='linear'",
        "--lr_warmup_steps=0",
        f"- -max_train_steps=\'{Training_Steps}\'"
    ])


def train_only_unet(stpsv, stp, SESSION_DIR, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR, PT, Seed, Res, precision, Training_Steps):
    '''
    Train only the image encoder.
    '''
    subprocess.Popen([
        "accelerate", "launch", "/content/diffusers/examples/dreambooth/train_dreambooth.py",
        # Flags
        "--use_8bit_adam",

        "--stop_text_encoder_training=stpsv"
        f"--save_n_steps=\'{SESSION_DIR}\'",
        f"--pretrained_model_name_or_path=\'{MODELT_NAME}\'",
        f"--instance_data_dir=\'{INSTANCE_DIR}\'",
        f"--output_dir=\'{OUTPUT_DIR}\'",
        # f"--captions_dir=\'{CAPTIONS_DIR}\'",
        f"--instance_prompt=\'{PT}\'",
        "--seed=Res",
        f"--mixed_precision=\'{precision}\'",
        "--train_batch_size=1",
        "--gradient_accumulation_steps=1",
        "--lr_scheduler='linear'",
        "--lr_warmup_steps=0",
        f"--max_train_steps=\'{Training_Steps}\'"
    ])
