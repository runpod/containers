# Runtime contract for the prod Nix images: a Nix-adapted /start.sh plus the
# staged nginx proxy config + banner. The upstream container-template/start.sh
# uses Debian `service nginx|ssh start`, which a Nix image has no sysvinit for;
# this reproduces the same behavior by invoking the daemons directly, preserving
# the env-var gating ($PUBLIC_KEY -> sshd, $JUPYTER_PASSWORD -> jupyter) and the
# /etc/rp_environment export.
#
# Returns a derivation that stages /start.sh, /etc/nginx/*, and
# /usr/share/nginx/html/* into the image root.

{ pkgs }:

let
  # Adapted entrypoint. Runs from the image where the userland (nginx, sshd,
  # ssh-keygen, python) is on PATH via /bin.
  startScript = pkgs.writeShellScript "start.sh" ''
    set -e

    start_nginx() {
      echo "Starting Nginx service..."
      # Nix has no `service`; run nginx directly. Prefix = /etc/nginx so the
      # relative `include snippets/...` and temp dirs resolve; keep pid/logs in
      # writable /run + /var/log (container fs is writable at runtime).
      mkdir -p /run/nginx /var/log/nginx \
        /etc/nginx/client_body_temp /etc/nginx/proxy_temp \
        /etc/nginx/fastcgi_temp /etc/nginx/uwsgi_temp /etc/nginx/scgi_temp
      nginx -p /etc/nginx -c /etc/nginx/nginx.conf \
        -g 'daemon on; pid /run/nginx/nginx.pid; error_log /var/log/nginx/error.log;'
    }

    execute_script() {
      local script_path=$1 script_msg=$2
      if [[ -f $script_path ]]; then
        echo "$script_msg"
        bash "$script_path"
      fi
    }

    setup_ssh() {
      if [[ $PUBLIC_KEY ]]; then
        echo "Setting up SSH..."
        mkdir -p ~/.ssh
        echo "$PUBLIC_KEY" >> ~/.ssh/authorized_keys
        chmod 700 -R ~/.ssh
        mkdir -p /etc/ssh /run/sshd

        local t
        for t in rsa ecdsa ed25519; do
          if [[ ! -f /etc/ssh/ssh_host_''${t}_key ]]; then
            ssh-keygen -t "$t" -f "/etc/ssh/ssh_host_''${t}_key" -q -N ""
          fi
        done

        # Direct daemon instead of `service ssh start`.
        sshd \
          -o PermitRootLogin=yes \
          -o AuthorizedKeysFile=/root/.ssh/authorized_keys \
          -o PidFile=/run/sshd/sshd.pid \
          -o UsePAM=no

        echo "SSH host keys:"
        for key in /etc/ssh/*.pub; do
          echo "Key: $key"
          ssh-keygen -lf "$key"
        done
      fi
    }

    export_env_vars() {
      echo "Exporting environment variables..."
      printenv | grep -E '^[A-Z_][A-Z0-9_]*=' | grep -v '^PUBLIC_KEY' \
        | awk -F = '{ val = $0; sub(/^[^=]*=/, "", val); print "export " $1 "=\"" val "\"" }' > /etc/rp_environment
      if ! grep -q 'source /etc/rp_environment' ~/.bashrc 2>/dev/null; then
        echo 'source /etc/rp_environment' >> ~/.bashrc
      fi
    }

    start_jupyter() {
      if [[ $JUPYTER_PASSWORD ]]; then
        echo "Starting Jupyter Lab..."
        mkdir -p /workspace
        cd /
        nohup python -m jupyter lab --allow-root --no-browser --port=8888 --ip=* \
          --FileContentsManager.delete_to_trash=False \
          --ServerApp.terminado_settings='{"shell_command":["/bin/bash"]}' \
          --IdentityProvider.token="$JUPYTER_PASSWORD" \
          --ServerApp.allow_origin=* --ServerApp.preferred_dir=/workspace &> /jupyter.log &
        local pid=$!
        sleep 2
        if kill -0 "$pid" 2>/dev/null; then
          echo "Jupyter Lab started (pid=$pid)"
        else
          echo "Jupyter Lab FAILED to start. /jupyter.log:" >&2
          cat /jupyter.log >&2
          return 1
        fi
      fi
    }

    start_nginx
    execute_script "/pre_start.sh" "Running pre-start script..."
    echo "Pod Started"
    setup_ssh
    start_jupyter
    export_env_vars
    echo "Start script(s) finished, Pod is ready to use."
    execute_script "/post_start.sh" "Running post-start script..."
    sleep infinity
  '';

  proxy = ../../container-template/proxy;
in
pkgs.runCommand "runpod-prod-runtime" { } ''
  mkdir -p "$out/etc/nginx/snippets" "$out/usr/share/nginx/html"
  cp ${startScript} "$out/start.sh"
  chmod +x "$out/start.sh"

  cp ${proxy}/nginx.conf "$out/etc/nginx/nginx.conf"
  cp ${proxy}/snippets/*.conf "$out/etc/nginx/snippets/"
  cp ${proxy}/readme.html "$out/usr/share/nginx/html/readme.html"
  cp ${../../README.md} "$out/usr/share/nginx/html/README.md"
''
