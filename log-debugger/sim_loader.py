"""
Runs a long running loading bar to cause container log to hang.
"""

from tqdm import tqdm

# -------------------------------- Print Test -------------------------------- #
print("Test 1001 single line prints")

for index, _ in enumerate(range(1000000000)):
    print(f"Test print {index}")

# --------------------------------- tqdm Test -------------------------------- #
print("Test tqdm bar")

for iter in tqdm(range(1000000000)):
    pass

print("Done")

while True:
    pass
