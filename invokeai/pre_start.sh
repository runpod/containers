#! #!/bin/bash

echo "syncing stable diffusion to workspace, please wait"
rsync -au --remove-source-files /invokeai/* /workspace/invokeai
