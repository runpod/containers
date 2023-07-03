#!/bin/bash

# Use FD model list
export DISCOART_MODELS_YAML='/models.yaml'

# Start DiscroArt service
cd /discoart-ui
yarn start &
