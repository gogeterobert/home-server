---
name: k3s-secrets
description: How secrets reach the k3s cluster in this repository - the current Jinja2 template plus Ansible env-lookup flow, and the target state of managing Secrets directly in the cluster. Use when adding, rotating, or migrating a secret, or when a workload fails because a credential is missing or wrong.
---

# Secrets

## Current flow (what exists today)

Secrets are **not** stored in this repository. They are injected at deploy time:

```
GitHub repository secret
  └─ env: block in .github/workflows/deploy_manifests.yml
       └─ lookup('env', 'NAME') in a deploy-manifests.yml template task
            └─ k3s-manifests/<thing>.yml.j2   →  rendered on the node
                 └─ kubectl apply
```

Every remaining `.j2` file in `k3s-manifests/` exists solely to interpolate a secret:
`librechat.yml.j2`, `openwebui.yml.j2`, `nostalgiaservice.yml.j2`,
`registry-auth-secret.yaml.j2`, `registry-image-creds.yaml.j2`,
`registry-image-creds-ai.yaml.j2`, and `secret-cf-api-key.yaml.j2`.

A template embeds the value like this:

```yaml
stringData:
  SOME_KEY: {{ some_var | quote }}
```

### Adding a secret under the current flow

All four steps are required, or the value renders empty:

1. Add the placeholder to the `.j2` manifest.
2. Add a `template` task in `deploy-manifests.yml` with
   `vars: { my_var: "{{ lookup('env', 'MY_SECRET') }}" }`.
3. Add `MY_SECRET: ${{ secrets.MY_SECRET }}` to the `env:` block in
   `.github/workflows/deploy_manifests.yml`.
4. Create the repository secret in GitHub.

A missing step 3 or 4 is the most common cause of a workload starting with an empty
credential — Ansible's `lookup('env', ...)` returns an empty string rather than
failing.

**Prefer not to add a new `.j2` template.** For anything new, create the Secret
in-cluster and reference it by name — see the target state below.

## Target state (direction of travel)

The intent is to **retire the `.j2` templates** and manage Secrets directly in the
cluster, so manifests become plain YAML that merely *reference* a Secret by name.
An earlier iteration built manifests in GitHub Actions; the direction is away from
build-time interpolation entirely.

Under the target state:

- A Secret is created once, in-cluster, and lives there.
- Manifests reference it with `secretKeyRef` / `envFrom` and contain no values.
- `deploy-manifests.yml` loses its `template` tasks, and the workflow loses most of
  its `env:` block.

### n8n is the reference example — already migrated

`n8n.yml` is plain YAML. It declares no Secret and reads the key with a
`secretKeyRef` pointing at `n8n-secrets`, which exists only in the cluster
(created with `kubectl create secret`). Copy this shape for the rest.

When migrating, remember the migration is **three** deletions, not one. Leaving any
behind breaks the deploy:

1. the `.j2` file,
2. its `template` task in `deploy-manifests.yml` — a task whose `src` points at a
   deleted file fails the whole playbook,
3. the now-unused variable in the workflow `env:` block.

### Secrets that live only in the cluster

Some Secrets were created directly with `kubectl create secret` and have **no**
`.j2` template backing them. At the time of writing that includes `n8n-secrets` and
`azure-mcp-secrets` in `ai`.

These are load-bearing and unrecoverable: `n8n-secrets` holds the key n8n's stored
credentials are encrypted with, and it is *not* the value in the corresponding
GitHub repository secret. If a `.j2` template were added that re-renders one of
these, the deploy would overwrite the working key and break the app.

The deploy previously ran `kubectl apply --prune --all`, which would have **deleted**
these Secrets outright. Pruning has since been removed for exactly this reason. Do
not reintroduce it without auditing what exists only in-cluster:

```bash
ssh "$K3S_SSH_HOST" 'kubectl -n <ns> get secret <name> \
  -o jsonpath="{.metadata.managedFields[*].manager}{\"\n\"}"'
```

A manager of `kubectl-create` means the Secret was made by hand and has no
representation in this repository.

### Migrating off `.j2`

Because pruning is gone, an in-cluster Secret survives deploys on its own. The
migration for a given secret is therefore:

1. Confirm the in-cluster Secret already holds the correct value (compare hashes).
2. Delete the `.j2` template and its `template` task in `deploy-manifests.yml`.
3. Drop the now-unused entry from the workflow `env:` block.
4. Leave the manifest referencing the Secret by name via `secretKeyRef`.

Options for keeping a record of the values, in rough order of effort:

| Option | Trade-off |
| --- | --- |
| `kubectl create secret` once, by hand | Simplest; undocumented in git, no recovery if lost |
| Sealed Secrets | Encrypted secret *is* committable; needs a controller + key backup |
| SOPS + age | Encrypted values in git; needs key distribution to the deploy path |
| External Secrets Operator | Best for many secrets; heaviest to run on a single node |

Whichever is chosen, keep an out-of-band backup of every secret value before
deleting the `.j2` path — several of these values are unrecoverable and their loss is
destructive (see below).

## Rules

- **Never commit a real secret value.** `.j2` files must contain only placeholders.
- **Never print a secret.** Do not `kubectl get secret -o yaml`, decode `data`
  fields, or echo rendered template output into logs or chat.
- To compare a secret against another value **without revealing it**, compare
  hashes:

  ```bash
  ssh "$K3S_SSH_HOST" 'kubectl -n <ns> get secret <name> \
    -o jsonpath="{.data.<KEY>}" | base64 -d | sha256sum'
  ```

- Secrets are namespaced. A credential needed in two namespaces needs **two**
  Secret objects — this is why `registry-image-creds` exists separately for `ai` and
  `nostalgiagame`.

## Encryption keys are not rotatable

Some values are not credentials but **encryption keys** that data is encrypted
*with*. Changing one does not "reset" the app — it makes existing data
undecryptable. In this repository that includes at least:

- `N8N_ENCRYPTION_KEY` — n8n refuses to start if it disagrees with the key recorded
  in `/home/node/.n8n/config` on its volume, and stored credentials become
  unreadable if it is replaced.
- `LIBRECHAT_CREDS_KEY` / `LIBRECHAT_CREDS_IV`
- `N8N_ENCRYPTION_KEY`'s equivalent in any future stateful app.

Before changing one of these, back up the app's data volume and confirm with the
operator. When an app reports an encryption-key mismatch, **compare hashes first** —
the key is usually correct and the real fault lies elsewhere.
