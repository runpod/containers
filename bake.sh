#!/bin/bash

if [ "$#" -lt 1 ]; then
    echo "Usage: ./bake.sh <template> ...arguments"
    exit 1
fi

TEMPLATE=$1
shift

if [ ! -f "official-templates/$TEMPLATE/docker-bake.hcl" ]; then
    echo "Bake file not found for template $TEMPLATE"
    exit 1
fi

docker buildx bake -f official-templates/shared/versions.hcl -f "official-templates/$TEMPLATE/docker-bake.hcl" "$@"
