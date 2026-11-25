# shellcheck shell=sh
# Rust toolchain installed in /opt by the Burn image. Mirrors the Dockerfile ENV
# so login shells of non-root users find cargo and rustup's default toolchain.
export RUSTUP_HOME=/opt/rustup
export CARGO_HOME=/opt/cargo
case ":${PATH}:" in
    *:/opt/cargo/bin:*) ;;
    *) export PATH="/opt/cargo/bin:${PATH}" ;;
esac
