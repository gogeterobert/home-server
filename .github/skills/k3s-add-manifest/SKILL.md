---
name: k3s-add-manifest
description: Add a new workload manifest to this k3s repository, following the cluster's conventions for namespaces, storage classes, Traefik ingress and cert-manager TLS. Use when adding or modifying a service, deployment, statefulset, PVC or ingress.
---

# Adding a Manifest

New manifests go in `k3s-manifests/` as plain `.yaml`/`.yml`. Only use a `.j2`
template if the manifest must embed a secret value — see the `k3s-secrets` skill,
and prefer the non-templated approach for anything new.

## Checklist

1. **Set an explicit `namespace`** on every namespaced object. If the namespace is
   new, add it to `k3s-manifests/_namespace.yaml` in the same change.
2. **Set an explicit `storageClassName`** on every PVC (see below).
3. **Use `ingressClassName: traefik`** for anything web-facing.
4. **Request TLS via cert-manager** with the `letsencrypt-prod` ClusterIssuer.
5. **Set resource requests and limits.** This is a single node; an unbounded
   workload starves everything else.
6. **Validate with a server dry-run** before committing.
7. **Commit and push to `main`** — that is what actually deploys it.

## Storage

Available StorageClasses:

| Class | Provisioner | Notes |
| --- | --- | --- |
| `longhorn` | `driver.longhorn.io` | Replicated, supports volume expansion |
| `longhorn-seagate` | `driver.longhorn.io` | Separate disks; **no** expansion |
| `local-path` | `rancher.io/local-path` | Node-local, `WaitForFirstConsumer` |
| `manual` | *(none)* | Statically bound to a hand-written PV |

> **Gotcha: two classes are both flagged default** (`local-path` and `longhorn`). A
> PVC that omits `storageClassName` gets a non-deterministic class, silently changing
> its durability. **Always set it explicitly.**

For a host-path volume, use the `manual` pattern — a `PersistentVolume` with
`storageClassName: manual`, `persistentVolumeReclaimPolicy: Retain`, and a matching
PVC. Keep `Retain` so a deleted PVC never destroys data.

## Ingress + TLS pattern

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp
  namespace: <ns>
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - myapp.example.com
      secretName: myapp-tls
  rules:
    - host: myapp.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: myapp
                port:
                  number: 8080
```

Test against `letsencrypt-staging` first if you expect to iterate — the production
ACME endpoint has strict rate limits that are easy to exhaust.

### Internal-only services

To restrict a route to the LAN, attach a Traefik `Middleware` and reference it from
the ingress. The annotation value is `<namespace>-<middleware-name>@kubernetescrd`:

```yaml
apiVersion: traefik.io/v1alpha1
kind: Middleware
metadata:
  name: myapp-local-allowlist
  namespace: <ns>
spec:
  ipWhiteList:
    sourceRange:
      - "10.0.0.0/8"
      - "172.16.0.0/12"
      - "192.168.0.0/16"
      - "127.0.0.1/32"
```

```yaml
    traefik.ingress.kubernetes.io/router.middlewares: <ns>-myapp-local-allowlist@kubernetescrd
```

### Internal DNS

Hostnames that must resolve on the LAN are served by CoreDNS via
`k3s-manifests/coredns-custom.yaml`. Add both the IPv4 and IPv6 entries when adding a
new hostname, or it will resolve only from outside.

## Image tags

Several existing manifests use `:latest` with `imagePullPolicy: Always`. **Do not
copy that pattern.** It makes deploys non-reproducible and lets a workload silently
jump major versions on any pod recreation — this has already caused a multi-week
outage in this cluster. Pin an explicit tag.

## Validate before committing

```bash
# Schema + admission check against the live API server. Changes nothing.
ssh "$K3S_SSH_HOST" 'kubectl apply --dry-run=server -f -' < k3s-manifests/<file>.yml

# Show exactly what would change on the cluster.
ssh "$K3S_SSH_HOST" 'kubectl diff -f -' < k3s-manifests/<file>.yml
```

From PowerShell, pipe instead of redirecting:

```powershell
Get-Content k3s-manifests\<file>.yml | ssh $env:K3S_SSH_HOST 'kubectl apply --dry-run=server -f -'
```

Empty `kubectl diff` output means the file already matches the cluster.

## Deploying

The `Deploy K3s manifests with Ansible` workflow runs on push to `main` and renders
and applies everything.

> **The workflow currently fails.** The node's SSH port is reachable only from the
> LAN, so the GitHub-hosted runner cannot connect. Until that changes, commit the
> manifest **and** apply it yourself from a machine on the local network:
>
> ```bash
> ssh "$K3S_SSH_HOST" 'kubectl apply -f -' < k3s-manifests/<file>.yml
> ```
>
> Hand-applying is safe here because the deploy no longer uses `--prune`. Still
> commit the manifest — otherwise the cluster gains a resource with no record of
> where it came from, which is exactly how this repo drifted before.
