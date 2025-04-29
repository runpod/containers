## Build Instructions

- To build with the default options, simply run `docker buildx bake`.
- To build a specific target, use `docker buildx bake <target>`.
- To specify the platform, use `docker buildx bake <target> --set <target>.platform=linux/amd64`.

Example:

```bash
cd official-templates/pytorch

docker buildx bake 280-py311-cuda1281-cudnn-devel-ubuntu2204 --set 280-py311-cuda1281-cudnn-devel-ubuntu2204.platform=linux/amd64
```

## Exposed Ports

- 22/tcp (SSH)
