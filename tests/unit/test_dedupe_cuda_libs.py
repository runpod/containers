"""dedupe-cuda-libs.py swaps torch's pip CUDA libraries for symlinks.

A wrong swap does not fail the build: torch loads whatever the symlink points
at, so a version or CUDA-major mix-up only shows on a GPU. These pin the rules
that decide what may switch.
"""

import contextlib
import importlib.util
import io
import os
import pathlib
import tempfile
import unittest
from unittest import mock

SCRIPT = (pathlib.Path(__file__).resolve().parents[2]
          / "official-templates" / "pytorch" / "dedupe-cuda-libs.py")
_spec = importlib.util.spec_from_file_location("dedupe_cuda_libs", SCRIPT)
dedupe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dedupe)


class _File:
    def __init__(self, path):
        self._path = path

    def locate(self):
        return self._path


class _Dist:
    """The parts of importlib.metadata.Distribution the script reads."""

    def __init__(self, name, version, paths):
        self.metadata = {"Name": name}
        self.version = version
        self.files = [_File(p) for p in paths]


class _Tree:
    """A temp system lib dir and pip dir with real files and soname links."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # The script resolves its dirs; macOS temp dirs sit behind /var -> /private/var.
        self.root = pathlib.Path(tmp.name).resolve()
        self.sys_dir = self.root / "sys"
        self.pip_dir = self.root / "pip"
        self.sys_dir.mkdir()
        self.pip_dir.mkdir()

    def system(self, soname, version):
        real = self.sys_dir / f"{soname}.{version}"
        real.write_bytes(b"system")
        (self.sys_dir / soname).symlink_to(real.name)
        return real

    def pip(self, name, version, sonames):
        paths = []
        for soname in sonames:
            path = self.pip_dir / f"{name}-{soname}"
            path.mkdir()
            lib = path / soname
            lib.write_bytes(b"pip" * 100)
            paths.append(lib)
        return _Dist(name, version, paths)

    def system_libs(self):
        with mock.patch.object(dedupe, "SYSTEM_DIRS", (str(self.sys_dir),)):
            return dedupe.system_libs()


class Versions(unittest.TestCase):
    def test_same_minor_with_equal_or_newer_patch_switches(self):
        self.assertIsNone(dedupe.mismatch((12, 8, 4, 1), (12, 8, 3, 14)))
        # The fourth component is ignored.
        self.assertIsNone(dedupe.mismatch((12, 8, 4, 1), (12, 8, 4, 9)))

    def test_older_system_copy_stays(self):
        self.assertEqual(dedupe.mismatch((9, 8, 0), (9, 10, 2, 21)), "older than")
        self.assertEqual(dedupe.mismatch((12, 8, 3), (12, 8, 4, 1)), "older than")

    def test_newer_minor_stays(self):
        # torch 2.6.0 pins cuDNN 9.5.1; the 12.8.1 image has 9.8.0, which ran
        # fp32 conv 8% slower on an RTX 4090.
        self.assertEqual(dedupe.mismatch((9, 8, 0), (9, 5, 1, 17)),
                         "a newer minor release than")
        self.assertEqual(dedupe.mismatch((12, 8, 4, 1), (12, 6, 4, 1)),
                         "a newer minor release than")

    def test_shorter_system_version(self):
        # libcudnn.so.9.12.0 against pip's 9.13.0.50
        self.assertEqual(dedupe.mismatch((9, 12, 0), (9, 13, 0, 50)), "older than")
        self.assertIsNone(dedupe.mismatch((9, 13, 0), (9, 13, 0, 50)))


class SystemLibs(_Tree, unittest.TestCase):
    def test_links_to_the_soname_symlink(self):
        # apt repoints the soname link on upgrade; a link to the versioned
        # file would dangle after `apt-get upgrade`.
        self.system("libcublas.so.12", "9.0.13")
        found = self.system_libs()
        link, version = found["libcublas.so.12"]
        self.assertEqual(link, str(self.sys_dir / "libcublas.so.12"))
        self.assertEqual(version, (12, 9, 0, 13))

    def test_ignores_a_file_the_soname_does_not_point_at(self):
        (self.sys_dir / "libcufft.so.11.4.0.6").write_bytes(b"old")
        self.system("libcufft.so.11", "4.1.4")
        found = self.system_libs()
        self.assertEqual(found["libcufft.so.11"][1], (11, 4, 1, 4))

    def test_ignores_a_file_without_a_soname_link(self):
        (self.sys_dir / "libcurand.so.10.3.9.90").write_bytes(b"x")
        self.assertNotIn("libcurand.so.10", self.system_libs())


class PlanPackage(_Tree, unittest.TestCase):
    def test_switches_when_the_system_copy_is_a_newer_patch(self):
        self.system("libcublas.so.12", "8.4.1")
        dist = self.pip("nvidia-cublas-cu12", "12.8.3.14", ["libcublas.so.12"])
        plan, why = dedupe.plan_package(dist, self.system_libs())
        self.assertIsNone(why)
        self.assertEqual([p[1] for p in plan],
                         [str(self.sys_dir / "libcublas.so.12")])

    def test_keeps_pip_when_the_system_copy_is_a_newer_minor(self):
        self.system("libcudnn.so.9", "8.0")
        dist = self.pip("nvidia-cudnn-cu12", "9.5.1.17", ["libcudnn.so.9"])
        plan, why = dedupe.plan_package(dist, self.system_libs())
        self.assertEqual(plan, [])
        self.assertIn("is a newer minor release than pip 9.5.1.17", why)

    def test_keeps_pip_when_the_system_copy_is_older(self):
        self.system("libcudnn.so.9", "8.0")
        dist = self.pip("nvidia-cudnn-cu12", "9.10.2.21", ["libcudnn.so.9"])
        plan, why = dedupe.plan_package(dist, self.system_libs())
        self.assertEqual(plan, [])
        self.assertIn("older than pip 9.10.2.21", why)

    def test_a_lib_the_system_lacks_stays_but_does_not_block(self):
        # e.g. libnvrtc.alt.so.13 ships in the wheel only
        self.system("libnvrtc.so.13", "0.48")
        dist = self.pip("nvidia-cuda-nvrtc", "13.0.48",
                        ["libnvrtc.so.13", "libnvrtc.alt.so.13"])
        plan, why = dedupe.plan_package(dist, self.system_libs())
        self.assertIsNone(why)
        self.assertEqual([os.path.basename(p[0]) for p in plan],
                         ["libnvrtc.so.13"])

    def test_no_system_copy_at_all(self):
        dist = self.pip("nvidia-cufile-cu12", "1.13.1.3", ["libcufile.so.0"])
        plan, why = dedupe.plan_package(dist, self.system_libs())
        self.assertEqual((plan, why), ([], "no system copy"))


class Decide(_Tree, unittest.TestCase):
    def test_toolkit_switches_all_or_nothing(self):
        self.system("libcublas.so.12", "8.4.1")
        self.system("libcufft.so.11", "3.3.83")
        self.system("libcudnn.so.9", "10.2")
        packages = {
            "cublas": self.pip("nvidia-cublas-cu12", "12.8.4.1", ["libcublas.so.12"]),
            "cufft": self.pip("nvidia-cufft-cu12", "11.4.1.4", ["libcufft.so.11"]),
            "cudnn": self.pip("nvidia-cudnn-cu12", "9.10.2.21", ["libcudnn.so.9"]),
        }
        result = {d.metadata["Name"]: (plan, why)
                  for d, plan, why in dedupe.decide(packages, self.system_libs())}
        self.assertIn("older than pip", result["nvidia-cufft-cu12"][1])
        self.assertEqual(result["nvidia-cublas-cu12"][1],
                         "another CUDA toolkit library can not switch")
        # cuDNN is standalone: the toolkit staying does not hold it back.
        self.assertIsNone(result["nvidia-cudnn-cu12"][1])

    def test_ignores_packages_outside_both_groups(self):
        packages = {"nvtx": self.pip("nvidia-nvtx-cu12", "12.8.90",
                                     ["libnvToolsExt.so.1"])}
        self.assertEqual(list(dedupe.decide(packages, self.system_libs())), [])


class NvidiaPackages(unittest.TestCase):
    def test_keys_drop_the_prefix_and_cuda_suffix(self):
        dists = [_Dist(n, "1", []) for n in
                 ("nvidia-cublas-cu12", "nvidia_cuda_runtime", "nvidia-nccl-cu13",
                  "torch")]
        with mock.patch.object(dedupe.md, "distributions", return_value=dists):
            self.assertEqual(sorted(dedupe.nvidia_packages()),
                             ["cublas", "cuda-runtime", "nccl"])


class Main(_Tree, unittest.TestCase):
    def run_main(self, packages, image_major, *argv):
        out = io.StringIO()
        with mock.patch.object(dedupe, "SYSTEM_DIRS", (str(self.sys_dir),)), \
                mock.patch.object(dedupe, "nvidia_packages", return_value=packages), \
                mock.patch.object(dedupe, "image_cuda_major", return_value=image_major), \
                mock.patch.object(dedupe.sys, "argv", ["dedupe", *argv]), \
                contextlib.redirect_stdout(out):
            dedupe.main()
        return out.getvalue()

    def cu12_wheels(self):
        self.system("libnccl.so.2", "27.7")
        return {
            "cuda-runtime": self.pip("nvidia-cuda-runtime-cu12", "12.8.90",
                                     ["libcudart.so.12"]),
            "nccl": self.pip("nvidia-nccl-cu12", "2.27.5", ["libnccl.so.2"]),
        }

    def test_replaces_pip_files_with_symlinks(self):
        packages = self.cu12_wheels()
        lib = pathlib.Path(packages["nccl"].files[0].locate())
        out = self.run_main(packages, 12)
        self.assertTrue(lib.is_symlink())
        self.assertEqual(os.readlink(lib), str(self.sys_dir / "libnccl.so.2"))
        self.assertIn("link  nvidia-nccl-cu12", out)

    def test_dry_run_changes_nothing(self):
        packages = self.cu12_wheels()
        lib = pathlib.Path(packages["nccl"].files[0].locate())
        self.run_main(packages, 12, "--dry-run")
        self.assertFalse(lib.is_symlink())

    def test_wheel_for_another_cuda_major_keeps_everything(self):
        # cuDNN and NCCL keep their soname across CUDA majors: without this
        # check a cu12 torch would load the CUDA 13 libnccl.so.2.
        packages = self.cu12_wheels()
        lib = pathlib.Path(packages["nccl"].files[0].locate())
        out = self.run_main(packages, 13)
        self.assertFalse(lib.is_symlink())
        self.assertIn("keep  everything: wheel CUDA 12, image CUDA 13", out)

    def test_unknown_image_cuda_keeps_everything(self):
        packages = self.cu12_wheels()
        out = self.run_main(packages, None)
        self.assertIn("keep  everything", out)


if __name__ == "__main__":
    unittest.main()
