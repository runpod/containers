#!/usr/bin/env python3

import subprocess
import re
from collections import defaultdict
from typing import List


def normalize_cuda(cuda_raw: str) -> str:
    if len(cuda_raw) == 3:  # e.g., '121' -> '12.1.0'
        return f"{cuda_raw[:2]}.{cuda_raw[2]}.0"
    elif len(cuda_raw) == 4:  # e.g., '1241' -> '12.4.1'
        return f"{cuda_raw[:2]}.{cuda_raw[2]}.{cuda_raw[3]}"
    else:
        return f"{cuda_raw[:2]}.{cuda_raw[2]}.{cuda_raw[3]}"


def normalize_torch(torch_code: str) -> str:
    if len(torch_code) == 3:
        return f"{torch_code[0]}.{torch_code[1]}.{torch_code[2]}"
    elif len(torch_code) == 2:
        return f"{torch_code[0]}.{torch_code[1]}"
    else:
        return torch_code


def normalize_ubuntu(ubuntu_code: str) -> str:
    return f"{ubuntu_code[:2]}.{ubuntu_code[2:]}" if len(ubuntu_code) == 4 else ubuntu_code


def get_image_tags() -> List[str]:
    result = subprocess.run(
        ["./bake.sh", "pytorch", "--print"],
        capture_output=True,
        text=True,
        check=True
    )
    
    jq_result = subprocess.run(
        ["jq", "-r", ".target[] | .tags[]"],
        input=result.stdout,
        capture_output=True,
        text=True,
        check=True
    )
    
    return [line.strip() for line in jq_result.stdout.splitlines() if line.strip()]


def generate_markdown(image_tags: List[str]) -> str:
    # Pattern 1: cu1241-torch240-ubuntu2004
    pattern1 = re.compile(r'cu(?P<cuda>\d+).*?torch(?P<torch>\d+).*?ubuntu(?P<ubuntu>\d+)')
    # Pattern 2: ubuntu2004-cu1241-torch240
    pattern2 = re.compile(r'ubuntu(?P<ubuntu>\d+).*?cu(?P<cuda>\d+).*?torch(?P<torch>\d+)')
    
    structure = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    
    for tag in image_tags:
        if match := (pattern1.search(tag) or pattern2.search(tag)):
            cuda = normalize_cuda(match.group("cuda"))
            torch = normalize_torch(match.group("torch"))
            ubuntu = normalize_ubuntu(match.group("ubuntu"))
            structure[cuda][torch][ubuntu].append(tag)
    
    lines = ["## Generated PyTorch Images"]
    
    def version_sort_key(version_str: str) -> List[int]:
        return [int(i) for i in version_str.split(".")]
    
    for cuda in sorted(structure, key=version_sort_key):
        lines.append(f"\n### CUDA {cuda}:")
        for torch in sorted(structure[cuda], key=version_sort_key):
            lines.append(f"- Torch {torch}:")
            for ubuntu in sorted(structure[cuda][torch], key=version_sort_key):
                lines.append(f"  - Ubuntu {ubuntu}:")
                for image in sorted(structure[cuda][torch][ubuntu]):
                    lines.append(f"    - `{image}`")
    
    return '<div class="base-images">\n\n' + "\n".join(lines) + '\n\n</div>'


tags = get_image_tags()
markdown = generate_markdown(tags)

with open("generated-pytorch-images.md", "w") as f:
    f.write(markdown)

