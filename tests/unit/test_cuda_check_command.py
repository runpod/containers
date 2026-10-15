"""The GPU check is a Python program embedded in a string.

Nothing compiles it before it reaches a pod, so a typo looks like a broken
image twenty minutes into a matrix run. This is its only pre-flight.
"""

import unittest

from runpod_smoke.checks import cuda_check_command


PYTORCH_IMAGE = "runpod/pytorch:1.4.0-cu1320-torch2130-ubuntu2404"


def _python_body(image: str, torch_packages: bool = False) -> str:
    """The program between the heredoc markers."""
    command = cuda_check_command(image, torch_packages)
    return command.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]


class TorchCheckProgram(unittest.TestCase):
    def test_compiles_with_and_without_the_package_checks(self):
        for torch_packages in (False, True):
            with self.subTest(torch_packages=torch_packages):
                compile(_python_body(PYTORCH_IMAGE, torch_packages),
                        "<cuda-check>", "exec")

    def test_packages_are_opt_in(self):
        # Not every image matching the torch regex ships them — NGC
        # nvidia-pytorch and runpod/base -pytorch251 tags carry torch alone.
        body = _python_body(PYTORCH_IMAGE)
        for package in ("torchvision", "torchaudio", "torchcodec"):
            self.assertNotIn(package, body)

    def test_opted_in_groups_require_the_packages(self):
        # No probe-and-skip: a package missing where it belongs must fail.
        body = _python_body(PYTORCH_IMAGE, torch_packages=True)
        self.assertIn("import torchvision", body)
        self.assertIn("import torchaudio", body)
        self.assertIn("import torchcodec", body)
        self.assertNotIn("find_spec", body)

    def test_rocm_images_do_not_take_the_torch_path(self):
        command = cuda_check_command("runpod/base:1.0.0-rocm644-ubuntu2404")
        self.assertIn("rocm-smi", command)
        self.assertNotIn("import torch", command)
