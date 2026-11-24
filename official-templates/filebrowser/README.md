### Runpod FileBrowser

**A web file manager for your pod's `/workspace`, powered by [FileBrowser Quantum](https://github.com/gtsteffaniak/filebrowser).**

Browse, upload, download, and edit files in your pod from the browser, with JupyterLab and SSH available alongside.

### What's included

- **FileBrowser Quantum** on port `80`, serving `/workspace`.
- **JupyterLab** on port `8888` (set `JUPYTER_PASSWORD` to enable).
- **SSH** access (set `PUBLIC_KEY`).
- **CPU and CUDA** images. FileBrowser itself does not use the GPU; pick the CUDA image when you want GPU tooling alongside the file browser.

### Getting started

1. Launch a pod with this template and expose HTTP port `80`.
2. Open the pod's `:80` proxy URL. Log in as `admin`.
3. Set `FILEBROWSER_ADMIN_PASSWORD` in the pod env to set the admin password. Without it, FileBrowser generates a one-time password on first boot and prints it to the pod's **Logs** tab (and `/filebrowser.log`); log in with it and FileBrowser prompts you to set a permanent password.

The admin user and settings persist in `/workspace/.filebrowser/filebrowser.db`, so they survive restarts on a network volume.

### Notes

- `trustProxyHeaders` is enabled so the session cookie is scoped to the proxy host, which is required for login to work behind the Runpod proxy.
- `FILEBROWSER_ADMIN_PASSWORD` is re-applied on every start, not just first boot: it overwrites the admin password each time the pod restarts, so a password you change in the UI is reverted. To change it, update or remove the env var (no need to delete the database, which would also drop users, shares and settings).
- On the first login of a new pod, FileBrowser shows a "new database was created on startup" notice. This is expected (the database is created on the volume) and appears only once.

### Links

- [FileBrowser Quantum](https://github.com/gtsteffaniak/filebrowser)
- [Documentation](https://filebrowserquantum.com/)
