#!/usr/bin/env python

import runpod


def handler(event):
    print(event)

    # do the things

    return "Hello World"


runpod.serverless.start({
    "handler": handler
})
