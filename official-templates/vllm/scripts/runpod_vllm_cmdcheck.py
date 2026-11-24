"""Exit 3 if the start command sets vLLM's own --api-key, as vLLM reads it.

Parses the arguments with the `vllm serve` parser itself, so --api_key,
abbreviations such as --api-ke, and --config files count too. Exits 0 on
anything else, including arguments vLLM rejects: `vllm serve` reports those.
Prints nothing, since the arguments may hold a key.
"""

import contextlib
import io
import sys

API_KEY_SET = 3


def api_key_set(argv: list[str]) -> bool:
    from vllm import platforms
    from vllm.entrypoints.cli.serve import ServeSubcommand
    from vllm.utils.argparse_utils import FlexibleArgumentParser

    # Parsing infers a device; without a GPU that raises. Only the parse
    # result matters here, as `vllm bench` does the same.
    if platforms.current_platform.is_unspecified():
        from vllm.platforms.cpu import CpuPlatform

        platforms.current_platform = CpuPlatform()

    parser = FlexibleArgumentParser()
    subparsers = parser.add_subparsers(dest="subparser")
    ServeSubcommand().subparser_init(subparsers)
    args = parser.parse_args(["serve", *argv])
    return bool(getattr(args, "api_key", None))


def main(argv: list[str]) -> int:
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            found = api_key_set(argv)
    except BaseException:  # argparse exits with SystemExit on bad arguments
        return 0
    return API_KEY_SET if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
