### Runpod FileBrowser

**A web file manager for your pod's `/workspace`, powered by [FileBrowser Quantum](https://github.com/gtsteffaniak/filebrowser).**

Browse, upload, download, and edit files in your pod from the browser, with JupyterLab and SSH available alongside.

### What's included

- **FileBrowser Quantum** on port `80`, serving `/workspace`.
- **JupyterLab** on port `8888` (set `JUPYTER_PASSWORD` to enable).
- **SSH** access (set `PUBLIC_KEY`).
- **CUDA** base image, so GPU tooling is available if you need it.

### Getting started

1. Launch a pod with this template and expose HTTP port `80`.
2. Open the pod's `:80` proxy URL. Log in as `admin`.
3. Set `FILEBROWSER_ADMIN_PASSWORD` in the pod env to choose the admin password up front. Without it, FileBrowser prints a one-time password to `/filebrowser.log` on first boot; log in with it and FileBrowser prompts you to set a permanent password.

The admin user and settings persist in `/workspace/.filebrowser/filebrowser.db`, so they survive restarts on a network volume.

### Notes

- `trustProxyHeaders` is enabled so the session cookie is scoped to the proxy host, which is required for login to work behind the Runpod proxy.
- `FILEBROWSER_ADMIN_PASSWORD` only applies on first database initialization. To reset it later, remove `/workspace/.filebrowser/filebrowser.db` and restart.
- On the first login of a new pod, FileBrowser shows a "new database was created on startup" notice. This is expected (the database is created on the volume) and appears only once.

### Links

- [FileBrowser Quantum](https://github.com/gtsteffaniak/filebrowser)
- [Documentation](https://filebrowserquantum.com/)
