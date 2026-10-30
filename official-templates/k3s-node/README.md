### Runpod K8S cluster node (k3s agent)

**Not a template to deploy yourself.** Every pod of a Runpod K8S cluster runs this image, and the Runpod host starts it under the `sysbox-runc` runtime. It joins the pod to the cluster's control plane as a Kubernetes node.

### What's included
- **k3s agent** with containerd, flannel and the CNI plugins it bundles.
- **runc 1.4.3**, in place of the 1.4.2 that this k3s release bundles.
- **NVIDIA Container Toolkit**, so pods on a GPU node get the GPUs the Runpod pod rents (through CDI). k3s adds the `nvidia` RuntimeClass on its own.
- **WireGuard tools**: the node reaches the control plane through a tunnel.
- **amd64 and arm64** (GB10/Grace hosts) in one image.

### How it starts
The entrypoint, `k3s-node`, wraps `k3s agent`:
- It sets the kubelet's `system-reserved` to the part of the host the Runpod pod does not rent, read from the pod's cgroup limits.
- It works on cgroup v1 and v2 hosts. On v1 it adds the kubelet flags `fail-cgroupv1=false` and `cpu-cfs-quota=false`: under sysbox the node cannot see its CPU quota, so k8s CPU limits are not enforced per pod there.
- Without `K3S_TOKEN` and `WG_ENDPOINT` it waits: a cluster's pods start before its control plane exists.
- It derives the WireGuard keys and the node password from `K3S_TOKEN` and `NODE_RANK`, so a recreated node pod joins as the same node.

### What's deliberately absent
No SSH server, no nginx and no Jupyter. Reach the cluster with `kubectl` through its kubeconfig.
