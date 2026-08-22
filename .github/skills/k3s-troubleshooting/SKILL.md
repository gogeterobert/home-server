---
name: k3s-troubleshooting
description: Diagnose failures in this single-node k3s cluster - crashlooping or pending pods, TLS certificates not issuing, Longhorn storage problems, Traefik ingress errors, and failed deploy workflows. Use when something in the cluster is broken or a deploy has failed.
---

# Troubleshooting

All commands assume the SSH wrapper from the `k3s-cluster-access` skill.

## Start here

```bash
# Unhealthy pods only.
# Do NOT use --field-selector=status.phase!=Running for this: a CrashLoopBackOff
# pod still reports phase "Running", so that selector hides the single most common
# failure while listing completed installer Jobs as noise.
ssh "$K3S_SSH_HOST" 'kubectl get pods -A --no-headers | awk '\''{split($3,a,"/"); if ($4=="Completed") next; if ($4!="Running" || a[1]!=a[2]) print}'\'''

ssh "$K3S_SSH_HOST" 'kubectl get events -A --sort-by=.lastTimestamp | tail -40'
```

## Investigate without breaking things

Read logs from the current and the previous container:

```bash
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> logs <pod> --tail=100'
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> logs <pod> --previous --tail=100'
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> describe pod <pod>'
```

If a container crashes too fast to `exec` into, **do not** modify the real workload
to keep it alive. Instead run a temporary pod that mounts the same PVC
**`readOnly: true`** and inspect from there. Always delete the temporary pod when
finished.

## Pod not starting

Map the `STATUS` column to a cause:

| Status | Cause | Next step |
| --- | --- | --- |
| `ImagePullBackOff` | Registry auth | Check `imagePullSecrets` and that the matching `registry-image-creds*` Secret exists **in that namespace** |
| `CrashLoopBackOff` | App-level failure | `kubectl logs --previous` |
| `Pending` | No capacity, or unbound PVC | `kubectl describe pod` — single node, so nothing can reschedule |
| `ContainerCreating` (stuck) | Volume attach | See Storage below |

### A container restart is not a pod restart

This distinction has cost real downtime here. CrashLoopBackOff restarts the
*container* inside the existing pod. Deleting the pod creates a **new** pod, which
re-resolves its environment from Secrets and re-pulls its image. A workload can stay
broken through thousands of container restarts and then start cleanly on pod
recreation.

So when a pod has been crashlooping for a long time and the configuration looks
correct, recreating it is a legitimate and usually safe fix:

```bash
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> delete pod <pod>'      # controller recreates it
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> rollout restart deploy/<name>'
```

Deleting a pod does **not** touch its data: state lives on the PVC/PV, which stay
bound. The genuine risks are (a) the volume is `emptyDir`, or (b) the new pod pulls a
newer image and runs **irreversible schema migrations** — likely wherever a manifest
uses `:latest`. Check the image tag and back up the data volume first.

## TLS certificate not issuing

`letsencrypt-issuer.yaml` defines `letsencrypt-staging` and `letsencrypt-prod`, both
solving HTTP-01 through the `traefik` ingress class.

```bash
ssh "$K3S_SSH_HOST" 'kubectl get clusterissuer'
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> get certificate,certificaterequest,order,challenge'
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> describe challenge <challenge>'
ssh "$K3S_SSH_HOST" 'kubectl -n cert-manager logs deploy/cert-manager --tail=100'
```

A stuck HTTP-01 challenge is usually the ingress not routing `/.well-known/...`, or
DNS not resolving to the node. Iterate against `letsencrypt-staging`; the production
endpoint's rate limits are easy to exhaust.

## Storage / Longhorn

```bash
ssh "$K3S_SSH_HOST" 'kubectl get pvc -A'
ssh "$K3S_SSH_HOST" 'kubectl -n longhorn-system get volumes.longhorn.io'
ssh "$K3S_SSH_HOST" 'kubectl -n longhorn-system get pods'
```

- Two StorageClasses are both marked default (`local-path`, `longhorn`), so a PVC
  without an explicit `storageClassName` may have landed on the wrong one.
- `longhorn-seagate` does not allow volume expansion.
- A PVC stuck `Pending` with `WaitForFirstConsumer` is normal until a pod schedules.
- A third class of volume exists: `storageClassName: manual` PVs on host paths under
  `/storage/seagate-1tb` (`n8n-pv`, `plex-pv`, `qbittorrent-downloads-pv`). These are
  neither Longhorn nor `local-path`. If one of these workloads starts with empty or
  stale data, the disk was probably not mounted — see `k3s-node-storage-boot`.

**Never delete a PVC or Longhorn volume to "reset" a stuck workload without explicit
operator confirmation.** Game saves and application databases live on them, and
several PVs use `Retain` precisely to prevent accidental loss.

## Ingress not reachable

k3s ships **Traefik** as the ingress controller.

```bash
ssh "$K3S_SSH_HOST" 'kubectl get ingress -A'
ssh "$K3S_SSH_HOST" 'kubectl -n kube-system logs deploy/traefik --tail=100'
```

Check in order:

1. Does the Ingress host match what the client requests?
2. Is a `router.middlewares` annotation applying an IP allowlist that excludes the
   caller?
3. Does the hostname resolve? LAN names come from `coredns-custom.yaml` in
   `kube-system` — a name added for IPv4 but not IPv6 (or vice versa) resolves
   inconsistently.
4. Does the Service have endpoints? `kubectl -n <ns> get endpoints <svc>` — empty
   means the selector matches no ready pods.

## Deploy workflow failed

1. Failure at `Validate Secrets` → a repository secret is missing or empty.
2. Failure in a `template` task → a `lookup('env', ...)` resolved empty; the secret
   is not wired into the workflow `env:` block.
3. Failure at `Apply K3s Manifests` → a real manifest error. Reproduce with
   `kubectl apply --dry-run=server`.
4. Timeout waiting on `cert-manager-webhook` (120s) or `longhorn-manager` (300s) →
   usually node resource pressure, not a manifest bug.

## Node-level checks

These need root, so hand them to the operator:

```bash
ssh -t "$K3S_SSH_HOST" 'sudo systemctl status k3s'
ssh -t "$K3S_SSH_HOST" 'sudo journalctl -u k3s -n 200 --no-pager'
```

### k3s itself will not start

Check the storage dependency **first**. k3s has a `RequiresMountsFor=` drop-in on
`/storage/seagate-1tb`, so if that external USB drive is missing or fails to mount,
k3s stays `inactive (dead)` on purpose and every workload is down — including ones
unrelated to that disk.

```bash
ssh "$K3S_SSH_HOST" 'findmnt /storage/seagate-1tb || echo "NOT MOUNTED"'
```

If the node is unreachable entirely after a reboot, suspect emergency mode (no
networking) rather than a dead machine. Both cases, and the recovery steps, are in
the **`k3s-node-storage-boot`** skill.

Disk pressure affects everything on a single node:

```bash
ssh "$K3S_SSH_HOST" 'df -h; kubectl top nodes; kubectl top pods -A --sort-by=memory | head -15'
```
