"""
Runs a long running loading bar to cause container log to hang.
"""

from tqdm import tqdm

for iter in tqdm(range(1000000000)):
    pass

print("Done")

while True:
    pass
