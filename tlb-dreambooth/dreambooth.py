'''
Trains DreamBooth image encoder then text encoder sequentially.
'''

import subprocess


# ---------------------------------------------------------------------------- #
#                                 Text Encoder                                 #
# ---------------------------------------------------------------------------- #
def dump_only_textenc(trnonltxt, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR, PT, Seed, precision, num_train_epochs, training_steps):
    '''
    Train only the text encoder.
    '''
    text_encoder = subprocess.Popen([
        "accelerate", "launch", "/diffusers/examples/dreambooth/train_dreambooth.py",

        f"--pretrained_model_name_or_path={MODELT_NAME}",
        # "--revision",
        # "--tokenizer_name",
        f"--instance_data_dir={INSTANCE_DIR}",
        # "--class_data_dir",
        f"--instance_prompt={PT}",
        # "--class_prompt",
        # "--with_prior_preservation",
        # "--prior_loss_weight",
        # "--num_class_images",
        f"--output_dir={OUTPUT_DIR}",
        f"--seed={Seed}",
        "--resolution=512",
        # "--center_crop",
        "--train_text_encoder",
        "--train_batch_size=1",
        # "--sample_batch_size",
        f"--num_train_epochs={num_train_epochs}",
        # f"--max_train_steps={training_steps}",
        # "--checkpointing_steps",
        # "--resume_from_checkpoint",
        "--gradient_accumulation_steps=1",
        "--gradient_checkpointing",  # ENABLED FOR TESTING
        "--learning_rate=1e-6",
        # "--scale_lr",
        "--lr_scheduler=linear",
        "--lr_warmup_steps=0",
        # "--lr_num_cycles",
        # "--lr_power",
        # "--use_8bit_adam",  # ENABLED FOR TESTING
        # "--dataloader_num_workers",
        # "--adam_beta1",
        # "--adam_beta2",
        # "--adam_weight_decay",
        # "--adam_epsilon",
        # "--max_grad_norm",
        # "--push_to_hub",
        # "--hub_token",
        # "--hub_model_id",
        # "--logging_dir",
        # "--allow_tf32",
        # "--report_to",
        f"--mixed_precision={precision}",
        # "--prior_generation_precision",
        # "--local_rank",
        # "--enable_xformers_memory_efficient_attention",
        # "--set_grads_to_none",

        "--image_captions_filename",
        "--dump_only_text_encoder",

        # trnonltxt,  # train_only_text_encoder
        # extrnlcptn,  # external_captions
    ])

    text_encoder.wait()


# ---------------------------------------------------------------------------- #
#                                     UNet                                     #
# ---------------------------------------------------------------------------- #
def train_only_unet(stpsv, stp, SESSION_DIR, MODELT_NAME, INSTANCE_DIR, OUTPUT_DIR, PT, Seed, Res, precision, Training_Steps):
    '''
    Train only the image encoder.
    '''
    unet = subprocess.Popen([
        "accelerate", "launch", "/diffusers/examples/dreambooth/train_dreambooth.py",

        f"--stop_text_encoder_training={stpsv}",
        f"--save_n_steps={stp}",

        f"--pretrained_model_name_or_path={MODELT_NAME}",
        f"--instance_data_dir={INSTANCE_DIR}",
        f"--output_dir={OUTPUT_DIR}",
        # f"--captions_dir=\'{CAPTIONS_DIR}\'",
        f"--instance_prompt={PT}",
        f"--seed={Seed}",
        f"--resolution={Res}",
        f"--mixed_precision={precision}",
        "--train_batch_size=1",
        "--gradient_accumulation_steps=1",
        "--learning_rate=2e-6",
        "--lr_scheduler='linear'",
        "--lr_warmup_steps=0",
        f"--max_train_steps={Training_Steps}",

        f"--Session_dir={SESSION_DIR}",
    ])

    unet.wait()
