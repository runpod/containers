import time
import subprocess


def relaunch_process():
    """Relaunches the web UI process in a loop"""
    while True:
        print("Relauncher: Launching...")
        try:
            webui_path = "/workspace/stable-diffusion-webui/webui.sh"
            subprocess.run(f"bash {webui_path} -f", shell=True, check=True)
        except Exception as err:
            print(f"An error occurred: {err}")
        print("Relauncher: Process is ending. Relaunching in 2s...")
        time.sleep(2)


if __name__ == "__main__":
    relaunch_process()
