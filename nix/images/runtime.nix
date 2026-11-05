# The runtime contract of official-templates/base, for an image with no
# distro underneath: container-template/start.sh as-is, the nginx proxy, the
# banner, and the /etc files that apt's postinst scripts would normally write.

{ pkgs, loaderEnv }:

let
  inherit (pkgs) nginx openssh pam;

  # start.sh runs `service nginx start` / `service ssh start`; there's no init
  # system here, so start the daemons directly. sshd must be started by
  # absolute path (OpenSSH re-execs sshd-session from it).
  service = pkgs.writeShellApplication {
    name = "service";
    text = ''
      case "$*" in
        "nginx start")
          mkdir -p /var/log/nginx
          exec ${nginx}/bin/nginx -c /etc/nginx/nginx.conf
          ;;
        "ssh start")
          mkdir -p /run/sshd
          exec ${openssh}/bin/sshd
          ;;
        *)
          echo "service: this image only supports 'nginx start' and 'ssh start'" >&2
          exit 1
          ;;
      esac
    '';
  };

  sshdConfig = pkgs.writeText "sshd_config" ''
    # Ubuntu's defaults, minus PAM: key-only root login.
    HostKey /etc/ssh/ssh_host_rsa_key
    HostKey /etc/ssh/ssh_host_ecdsa_key
    HostKey /etc/ssh/ssh_host_ed25519_key
    PermitRootLogin prohibit-password
    KbdInteractiveAuthentication no
    UsePAM no
    X11Forwarding yes
    PrintMotd no
    AcceptEnv LANG LC_*
    Subsystem sftp ${openssh}/libexec/sftp-server
    SetEnv ${builtins.concatStringsSep " " loaderEnv}
  '';

  sudoPam = pkgs.writeText "sudo" ''
    auth     sufficient ${pam}/lib/security/pam_rootok.so
    account  required   ${pam}/lib/security/pam_permit.so
    session  required   ${pam}/lib/security/pam_permit.so
  '';

  # Ubuntu's guard comes first: sshd runs ~/.bashrc for scp/sftp/rsync too,
  # and any output there breaks them.
  bashrc = pkgs.writeText "bashrc" ''
    [ -z "$PS1" ] && return

    cat /etc/runpod.txt
    cat <<'BANNER'

    For detailed documentation and guides, please visit:
    https://docs.runpod.io/
    and https://blog.runpod.io

    BANNER
  '';

  proxy = ../../container-template/proxy;
in
{
  # Store paths the image needs on PATH or by reference.
  contents = [
    service
    pkgs.nix-ld
    pkgs.sudo
  ];

  # Run from the image root by streamLayeredImage's fakeRootCommands, so
  # ownership and modes stick.
  rootCommands = ''
    # streamLayeredImage symlinks each package's top-level dirs (etc, etc/ssh,
    # ...) into the root. Make each dir we write to real, keeping what the
    # packages put there (e.g. openssh's moduli).
    realdir() {
      local path="" part
      for part in $(tr / ' ' <<<"$1"); do
        path="''${path:+$path/}$part"
        if [ -L "$path" ]; then
          local src
          src=$(readlink -f "$path")
          rm "$path"
          mkdir "$path"
          cp -rP "$src"/. "$path"/
          chmod -R u+w "$path"
        fi
        mkdir -p "$path"
      done
    }
    for d in etc/ssh etc/nginx etc/pam.d usr/share/nginx/html root run \
      var/log/nginx var/empty lib64 etc/ssl/certs; do
      realdir "$d"
    done
    install -m 1777 -d tmp
    # Files may also be symlinks into the store (e.g. openssh's sshd_config).
    rm -f etc/passwd etc/group etc/nsswitch.conf etc/ssh/sshd_config \
      etc/sudoers etc/pam.d/sudo etc/nginx/nginx.conf etc/runpod.txt \
      root/.bashrc start.sh

    cat > etc/passwd <<'EOF'
    root:x:0:0:root:/root:/bin/bash
    nobody:x:65534:65534:nobody:/var/empty:/bin/false
    sshd:x:74:74:sshd privsep:/var/empty:/bin/false
    EOF
    cat > etc/group <<'EOF'
    root:x:0:
    nogroup:x:65534:
    nobody:x:65534:
    sshd:x:74:
    EOF
    printf 'passwd: files\ngroup: files\nshadow: files\nhosts: files dns\n' > etc/nsswitch.conf

    cp ${sshdConfig} etc/ssh/sshd_config
    # OpenSSH 10 can't generate DSA keys, and start.sh would abort trying.
    # An empty placeholder makes it skip; sshd_config never loads it.
    touch etc/ssh/ssh_host_dsa_key

    echo 'root ALL=(ALL:ALL) ALL' > etc/sudoers
    chmod 0440 etc/sudoers
    cp ${sudoPam} etc/pam.d/sudo

    cp ${proxy}/nginx.conf etc/nginx/nginx.conf
    cp -r ${proxy}/snippets etc/nginx/snippets
    cp ${proxy}/readme.html usr/share/nginx/html/readme.html
    cp ${../../official-templates/base/README.md} usr/share/nginx/html/README.md

    cp ${../../container-template/runpod.txt} etc/runpod.txt
    cp ${bashrc} root/.bashrc

    install -m 0755 ${../../container-template/start.sh} start.sh

    ln -sf ${pkgs.nix-ld}/libexec/nix-ld lib64/ld-linux-x86-64.so.2

    # The distro CA bundle paths, for sessions without SSL_CERT_FILE (SSH).
    ln -sf ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt etc/ssl/certs/ca-certificates.crt
    ln -sf ${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt etc/ssl/certs/ca-bundle.crt
  '';
}
