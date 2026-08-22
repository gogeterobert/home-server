---
name: k3s-repo-structure
description: Explains how this k3s repository is laid out, which manifest maps to which namespace, and how a change reaches the cluster via Ansible and GitHub Actions. Use when orienting in the repo, locating the manifest behind a running workload, or reasoning about deploys and drift.
---

# Repository Structure

This repository is the intended source of truth for a single-node k3s cluster.

```
.
├── main.yml                     # imports install-k3s.yml + install-cockpit.yml
├── install-k3s.yml              # installs k3s via get.k3s.io if absent
├── install-cockpit.yml          # installs the Cockpit web console
├── deploy-manifests.yml         # THE deploy playbook: renders + applies everything
├── ansible.cfg
├── k3s-manifests/               # all cluster manifests (.yaml/.yml and .j2 templates)
└── .github/
    ├── workflows/               # deploy + rollout-restart pipelines
    └── skills/                  # these skills
```

## Manifest → namespace map

| Namespace | Manifests |
| --- | --- |
| `ai` | `librechat.yml.j2`, `openwebui.yml.j2`, `ollama.yml`, `n8n.yml`, `reddit-mcp-server.yaml`, `registry-image-creds-ai.yaml.j2` |
| `nostalgiagame` | `keycloak.yml`, `nostalgiaservice.yml.j2`, `registry-image-creds.yaml.j2` |
| `monitoring` | `prometheus.yaml`, `prometheus-rbac.yaml`, `grafana.yaml`, `node-exporter.yml` |
| `registry` | `registry.yml`, `registry-ui.yaml`, `registry-auth-secret.yaml.j2` |
| `plex` | `plex.yml`, `jellyfin.yml`, `qbittorrent.yml` |
| `kube-system` | `coredns-custom.yaml`, `kube-state-metrics.yaml` |
| `satisfactory` | `statefulset-satisfactory.yaml` |
| `default` | `statefulset-minecraft.yaml` (declares no namespace) |
| cluster-scoped | `_namespace.yaml`, `letsencrypt-issuer.yaml`, `secret-cf-api-key.yaml.j2` |

Third-party components are **not** vendored; `deploy-manifests.yml` downloads them at
deploy time:

- **cert-manager** — tracks the `latest` release (unpinned).
- **Longhorn** — pinned to `v1.6.2`.

## Deploy flow

```
push to main
  └─ .github/workflows/deploy_manifests.yml
       └─ ansible-playbook deploy-manifests.yml
            ├─ download cert-manager + Longhorn manifests
            ├─ copy k3s-manifests/ into a temp dir on the node
            ├─ render every *.j2 with secrets from environment variables
            ├─ kubectl apply cert-manager, wait for its webhook (120s)
            ├─ kubectl apply Longhorn, wait for longhorn-manager (300s)
            └─ kubectl apply -f <tmpdir>/
```

> **This pipeline does not currently work.** The node's SSH port is not reachable
> from the public internet — only from the LAN — so the GitHub-hosted runner cannot
> connect and the workflow fails. Until that changes, pushing to `main` does **not**
> deploy anything, and changes must be applied from a machine on the local network
> (see the `k3s-cluster-access` skill). Treat a green `main` as "committed", never as
> "deployed".

The workflow builds an Ansible inventory on the fly from repository secrets
(`SERVER_IP`, `SERVER_USER`, `SERVER_PASSWORD`) and connects over SSH with
`become`. The other workflows (`rollout_restart_keycloak.yml`,
`rollout_restart_nostalgiaservice.yml`) are `workflow_dispatch`-only and use the same
pattern to run a single `kubectl rollout restart`.

## Consequences you must respect

### Never run `kubectl apply -f k3s-manifests/` directly

It does **not** error — it *silently succeeds on a partial set*. `kubectl` only reads
`.yaml`, `.yml`, and `.json` files from a directory, so every `.j2` template is
skipped without a warning. You would apply the plain manifests while omitting all
templated Secrets and credentials. Only the Ansible playbook can apply this tree
correctly.

To sanity-check a single **plain** manifest, pipe just that file:

```bash
ssh "$K3S_SSH_HOST" 'kubectl apply --dry-run=server -f -' < k3s-manifests/<file>.yml
```

### Deleting a manifest does not delete the resource

The deploy intentionally does **not** use `--prune`. Pruning was removed because it
deletes every cluster resource absent from the applied set — including Secrets
created directly in the cluster and workloads that have never had a manifest here.

The trade-off: removing a manifest from `k3s-manifests/` leaves the resource running
on the cluster. Delete it explicitly:

```bash
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> delete <kind> <name>'
```

Do not reintroduce `--prune` without first auditing for resources that exist only in
the cluster.

## Drift: the cluster can be ahead of the repo

Because it is possible to apply manifests directly on the node, the live cluster has
at times been *more* correct than this repository. Ad-hoc manifest copies live in the
operator's home directory on the node.

Before assuming a committed manifest is correct, diff it against live:

```bash
# Empty output and exit code 0 means the repo matches the cluster.
ssh "$K3S_SSH_HOST" 'kubectl diff -f -' < k3s-manifests/<file>.yml
```

`kubectl diff` is the reliable check. A server dry-run may report `configured` purely
because of field-manager attribution even when nothing meaningful differs.

When the repo and cluster disagree, **ask the operator which side is authoritative**
before overwriting either. Do not assume the committed file wins.

## Known gaps

- Some workloads running in the cluster have no manifest here (they were applied by
  hand from the node). Treat `kubectl get deploy,statefulset -A` as the real
  inventory, not this directory alone.
- `nostalgiaservice.yml.j2` has **no render task** in `deploy-manifests.yml`. Since
  `kubectl` skips `.j2` files, it is never applied — the file is currently dead
  weight. Its workloads (`keycloak`, `postgres` in `nostalgiagame`) sit at 0
  replicas, so this appears deliberate.
- Several manifests use `:latest` with `imagePullPolicy: Always`. That makes deploys
  non-reproducible and lets a workload jump major versions on any pod recreation;
  it has already caused a multi-week outage here.
- **Node-level configuration is not in this repo.** `/etc/fstab` and the
  `k3s.service` drop-in that makes k3s wait for the external drive live only on the
  node. This repo describes the cluster, not the host. See `k3s-node-storage-boot`
  for what that host state is and why it matters.
