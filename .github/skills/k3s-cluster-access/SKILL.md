---
name: k3s-cluster-access
description: Connect to the k3s cluster this repository manages and run kubectl against it over SSH. Use when you need to inspect or change live cluster state, or when kubectl fails with a kubeconfig permission error.
---

# k3s Cluster Access

The cluster is a **single-node k3s** install. There is no kubeconfig in this
repository and no direct API access from a workstation. You reach it by running
`kubectl` **on the node, over SSH**.

## The one command shape

```bash
ssh "$K3S_SSH_HOST" 'kubectl get nodes -o wide'
```

Everything in the other k3s skills assumes this wrapper.

## Resolving the SSH target

The host alias is operator-specific and deliberately **not** committed. Resolve it
in this order:

1. The `K3S_SSH_HOST` environment variable, if set.
2. An entry in the operator's `~/.ssh/config` (commonly aliased `server`).
3. Ask the operator.

Do not add a hostname, IP, or username for the SSH target to tracked files.

> **LAN only.** The node's SSH port is not exposed to the public internet. You must
> be on the local network to connect — which is also why the GitHub Actions deploy
> workflow cannot reach it and currently fails. Applying manifests is a local
> operation, not something a push to `main` performs.

## Rules

- **Never use `sudo k3s kubectl ...`.** `sudo` on the node prompts for a password,
  which cannot be supplied by a non-interactive SSH command. It will hang or fail
  with `sudo: a password is required`. Plain `kubectl` is all you need.
- **Quote the remote command in single quotes** so the local shell does not expand
  `$` before it reaches the node.
- **Scope every command with `-n <namespace>`.** This cluster runs many unrelated
  workloads.
- **Prefer read-only verbs** (`get`, `describe`, `logs`, `diff`,
  `--dry-run=server`) and confirm anything destructive with the operator first.

## Verifying access

```bash
ssh "$K3S_SSH_HOST" 'kubectl get nodes -o wide'
```

Expected: one node, role `control-plane,master`, status `Ready`.

## One-time node setup

If `kubectl` over SSH fails with:

```
error loading config file "/etc/rancher/k3s/k3s.yaml": permission denied
```

the node has not been prepared. k3s writes its kubeconfig to
`/etc/rancher/k3s/k3s.yaml` as `root:root 0600`, and the k3s `kubectl` shim defaults
to that path. The fix is a user-owned copy.

The **operator must run this once, interactively** — it needs a sudo password, so
`-t` is required to allocate a TTY:

```bash
ssh -t "$K3S_SSH_HOST" 'mkdir -p ~/.kube \
  && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config \
  && sudo chown "$(id -u):$(id -g)" ~/.kube/config \
  && chmod 600 ~/.kube/config'
```

Then export `KUBECONFIG` so plain `kubectl` finds it:

```bash
ssh "$K3S_SSH_HOST" 'grep -q KUBECONFIG ~/.bashrc \
  || sed -i "1i export KUBECONFIG=\$HOME/.kube/config" ~/.bashrc'
```

The export **must go at line 1** of `~/.bashrc`, above the standard
`case $- in *i*) ;; *) return;; esac` guard. Below that guard it applies only to
interactive logins, and every non-interactive `ssh host 'kubectl ...'` would still
fail.

> **Security note:** this kubeconfig is cluster-admin. Anything running as that user
> on the node has full control of the cluster. If narrower access is wanted, create a
> dedicated ServiceAccount with a scoped Role and generate a kubeconfig for it
> instead.

## Running from a PowerShell client

PowerShell needs two adjustments:

- Escape any `$` meant for the **remote** shell as `` `$ ``.
- PowerShell has no `<` input-redirection operator. Pipe files instead:

```powershell
Get-Content k3s-manifests\ollama.yml | ssh $env:K3S_SSH_HOST 'kubectl apply --dry-run=server -f -'
```

## Reading logs and events

```bash
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> logs deploy/<name> --tail=200'
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> logs <pod> --previous --tail=200'
ssh "$K3S_SSH_HOST" 'kubectl get events -A --sort-by=.lastTimestamp | tail -40'
```

Checking the k3s service itself does need root, so hand it to the operator:

```bash
ssh -t "$K3S_SSH_HOST" 'sudo journalctl -u k3s -n 200 --no-pager'
```
