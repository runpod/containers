import runpod

def handler(event):
    '''
    This is the handler function that will be called by the serverless.
    '''
    print(event)

    return "hi"


runpod.serverless.start({"handler": handler})
