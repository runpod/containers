import os
import time


def relaunch_process(launch_counter=0):
    '''

    '''
    while True:
        print('Relauncher: Launching...')
        if launch_counter > 0:
            print(f'\tRelaunch count: {launch_counter}')

        try:
            launch_string = "/workspace/stable-diffusion-webui/webui.sh -f"
            os.system(launch_string)
        except Exception as err:
            print(f"An error occurred: {err}")
        finally:
            print('Relauncher: Process is ending. Relaunching in 2s...')
            launch_counter += 1
            time.sleep(2)


if __name__ == "__main__":
    relaunch_process()
