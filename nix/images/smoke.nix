# `nix run .#image-smoke -- <image>`: load a Nix image into Docker, start it
# the way a pod does (PUBLIC_KEY, JUPYTER_PASSWORD), and check the runtime
# contract from outside and over SSH. Needs Docker and network access.

{ pkgs }:

pkgs.writeShellApplication {
  name = "image-smoke";
  runtimeInputs = with pkgs; [
    coreutils
    curl
    gnugrep
    openssh
  ];
  # The checks are single-quoted commands that `check` evals, so the helpers
  # they call look unused and their `$` look unexpanded.
  excludeShellChecks = [
    "SC2016"
    "SC2329"
  ];
  text = ''
    image=''${1:?usage: image-smoke <image>}
    work=$(mktemp -d)
    name="nix-smoke-$$"
    bare="nix-smoke-bare-$$"
    cleanup() {
      docker rm -f "$name" "$bare" >/dev/null 2>&1 || true
      rm -rf "$work"
    }
    trap cleanup EXIT

    "$(nix build --no-link --print-out-paths ".#$image")" 2>/dev/null | docker load >/dev/null
    tag=$(nix eval --raw ".#$image.imageName"):$(nix eval --raw ".#$image.imageTag")

    ssh-keygen -q -t ed25519 -N "" -f "$work/key"
    docker run -d --name "$name" \
      -e PUBLIC_KEY="$(cat "$work/key.pub")" -e JUPYTER_PASSWORD=smoke \
      -p 127.0.0.1::22 -p 127.0.0.1::8888 -p 127.0.0.1::7270 "$tag" >/dev/null
    # And one with neither, which must leave sshd and Jupyter off (#175).
    docker run -d --name "$bare" "$tag" >/dev/null
    for c in "$name" "$bare"; do
      for _ in $(seq 60); do
        docker logs "$c" 2>&1 | grep -q "Pod is ready" && break
        sleep 1
      done
    done

    port() { docker port "$name" "$1" | head -1 | cut -d: -f2; }
    auth=(-i "$work/key" -o BatchMode=yes -o LogLevel=ERROR -o IdentityAgent=none
      -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)
    on_pod() { ssh "''${auth[@]}" -p "$(port 22)" root@127.0.0.1 "$@"; }
    sftp_ls() { echo "ls $1" | sftp "''${auth[@]}" -P "$(port 22)" -b - root@127.0.0.1; }
    http() { curl -s -o /dev/null -w '%{http_code} %{content_type}' "http://127.0.0.1:$(port "$1")$2"; }

    failed=0
    # check <description> <command> <expected: grep -E pattern on the output>
    check() {
      local out
      if out=$(eval "$2" 2>&1) && grep -qE "$3" <<<"$out"; then
        echo "PASS  $1"
      else
        echo "FAIL  $1: expected /$3/, got: $(tail -3 <<<"$out")"
        failed=1
      fi
    }

    check "start.sh reaches ready" 'docker logs "$name"' 'Pod is ready to use'
    check "SSH login as root" 'on_pod whoami' '^root$'
    check "sftp works (quiet non-interactive .bashrc)" 'sftp_ls /etc/runpod.txt' '/etc/runpod.txt'
    check "JupyterLab serves static assets (#168)" 'http 8888 /static/favicons/favicon.ico' '^200 image/'
    check "nginx proxy is up" 'http 7270 /' '^200 '
    check "TLS from an SSH session" 'on_pod curl -sI https://pypi.org' '^HTTP/2 200'
    check "pip wheels find libstdc++" \
      'on_pod "pip install -q --target /tmp/w numpy && PYTHONPATH=/tmp/w python -c \"import numpy; print(numpy.__name__)\""' \
      '^numpy$'
    check "uv-managed (non-Nix) Python runs via nix-ld" \
      'on_pod "uv run -q --no-project --python 3.12 python -c \"print(6 * 7)\""' \
      '^42$'
    check "no PUBLIC_KEY: start.sh says so" 'docker logs "$bare"' 'PUBLIC_KEY is not set'
    check "no PUBLIC_KEY: sshd stays off" \
      'docker exec "$bare" pgrep -x sshd || echo no-sshd' \
      '^no-sshd$'
    check "no JUPYTER_PASSWORD: Jupyter stays off" \
      'docker exec "$bare" pgrep -f jupyter-lab || echo no-jupyter' \
      '^no-jupyter$'

    exit "$failed"
  '';
}
