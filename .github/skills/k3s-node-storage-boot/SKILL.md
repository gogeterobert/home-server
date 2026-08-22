---
name: k3s-node-storage-boot
description: How the external Seagate USB drive is mounted on the k3s node and why k3s waits for it at boot. Use when the node drops to emergency mode, when the drive is unmounted or missing, when k3s will not start, or when a workload's data looks empty or reverted.
---

# Node Storage and Boot Order

The node has two disks. Confusing them has already produced an apparently unbootable
machine and silent data divergence, so the layout is worth knowing before touching
anything storage-related.

| Device | Size | FS | Mount | Role |
| --- | --- | --- | --- | --- |
| `nvme0n1p2` | 237G | ext4 | `/` | OS, k3s, `local-path` PVCs |
| `nvme0n1p1` | 1G | vfat | `/boot/efi` | EFI system partition |
| `sda1` | 931G | **NTFS** | `/storage/seagate-1tb` | External USB, backs `manual` PVs |
| `sdb` | 20G | ext4 | CSI-managed | Longhorn |

`sda1` is a **USB-attached Seagate Basic**, UUID `4A104695104687C1`, mounted with
`ntfs-3g` — a FUSE userspace driver, so it shows as `fuseblk` in `mount` output, not
`ntfs`.

## What actually lives on the external drive

Three PVs, all `storageClassName: manual` with reclaim policy `Retain`:

| PV | Claim | Path |
| --- | --- | --- |
| `n8n-pv` | `ai/n8n-data` | `/storage/seagate-1tb/ai/n8n` |
| `plex-pv` | `plex/plex-pvc` | `/storage/seagate-1tb/plex` |
| `qbittorrent-downloads-pv` | `plex/qbittorrent-downloads-pvc` | `/storage/seagate-1tb/media` |

Plus two `hostPath` mounts straight in pod specs: `/storage/seagate-1tb/media` and
`/storage/seagate-1tb/plex-config`.

The drive also holds `jellyfin-config/`, `nextcloud-data/`, `postgres-nextcloud/` and
`qbittorrent-config/`. These back **no current PV** — treat them as stale until
proven otherwise, and re-check before assuming any of them is live:

```bash
ssh "$K3S_SSH_HOST" 'kubectl get pv -o custom-columns=NAME:.metadata.name,PATH:.spec.local.path --no-headers | grep seagate'
```

These are `local`/`hostPath` volumes, **not** Longhorn and not `local-path`. That is
exactly why mount ordering matters: a host path always "exists" even when nothing is
mounted on it.

## Boot order: k3s waits for the mount

`/etc/systemd/system/k3s.service.d/10-wait-for-seagate.conf`:

```ini
[Unit]
RequiresMountsFor=/storage/seagate-1tb
```

`RequiresMountsFor=` expands to both `Requires=` and `After=` on
`storage-seagate\x2d1tb.mount`, so k3s cannot start until the NTFS mount succeeds.

**Why this is necessary.** Without it, k3s starts once the network is up, which
regularly beat the USB drive's enumeration. kubelet then binds those host paths to
the *empty directory on the internal SSD* underneath the mount point. Workloads come
up against blank state; the drive mounts later and shadows the writes. Nothing
errors and `kubectl` reports every pod healthy. This was observed live — kubelet
mounted `n8n-pv` **28 minutes before** the drive was mounted.

The tell that it happened:

```
systemd[1]: storage-seagate\x2d1tb.mount: Directory /storage/seagate-1tb to mount
            over is not empty, mounting anyway.
```

Files were written to the mount point while it was unmounted. They are still on the
SSD, hidden beneath the mount — recoverable, not lost. To inspect them, bind-mount
the underlying root rather than unmounting the drive:

```bash
ssh -t "$K3S_SSH_HOST" 'sudo mkdir -p /mnt/underlay && sudo mount --bind / /mnt/underlay \
  && ls -la /mnt/underlay/storage/seagate-1tb'
ssh -t "$K3S_SSH_HOST" 'sudo umount /mnt/underlay'
```

**The trade-off.** If the drive is absent, dead, or fails to mount, **k3s will not
start at all** — including workloads unrelated to this disk. That is deliberate:
silent data divergence was judged worse than a loud outage.

To bring k3s up without the drive:

```bash
ssh -t "$K3S_SSH_HOST" 'sudo rm /etc/systemd/system/k3s.service.d/10-wait-for-seagate.conf \
  && sudo systemctl daemon-reload && sudo systemctl start k3s'
```

Expect the affected workloads to start against empty directories. Scale them to zero
first if their data matters.

## The fstab entry

```
UUID=4A104695104687C1 /storage/seagate-1tb ntfs-3g uid=1000,gid=1000,umask=022,nofail,x-systemd.device-timeout=15 0 0
```

Every option is load-bearing:

- `ntfs-3g` — the filesystem is NTFS. Declaring `ext4` fails the mount outright.
- `uid=1000,gid=1000,umask=022` — NTFS carries no Unix ownership, so it is assigned
  at mount time to the operator account.
- `nofail` — a missing drive must not fail `local-fs.target`. **Without this the node
  drops to emergency mode**, which has no networking, so the machine looks dead from
  the LAN.
- `x-systemd.device-timeout=15` — bounds the wait on a slow or absent USB device to
  15s instead of systemd's 90s default.

There must be **exactly one** line for this mount point (see emergency mode below).

Note `x-systemd.device-timeout` will **not** show up in the mount unit's `Options`
property — the generator consumes it itself to bound the device wait. That absence
is expected, not a sign the option was dropped.

### `findmnt --verify` warnings that are safe to ignore

```
[W] ntfs-3g seems unsupported by the current kernel
[W] ntfs-3g does not match with on-disk ntfs
```

Both are false positives. `ntfs-3g` is a FUSE driver dispatched through
`/sbin/mount.ntfs-3g`, so it never appears in `/proc/filesystems` — the only place
`findmnt` looks. The second is `ntfs` vs `ntfs-3g` spelling. What matters is
`0 parse errors, 0 errors`.

## Debugging: k3s will not start

Work down this list. The first three are specific to the mount dependency.

### 1. Is the drive mounted?

```bash
ssh "$K3S_SSH_HOST" 'findmnt /storage/seagate-1tb || echo "NOT MOUNTED"'
ssh "$K3S_SSH_HOST" 'lsblk -o NAME,SIZE,FSTYPE,UUID,MOUNTPOINT'
```

If `sda` is missing entirely the kernel never saw the disk — check the USB cable and
power, then `dmesg | grep -i usb`. If `sda1` exists but is unmounted, go to step 2.

### 2. Why did the mount fail?

```bash
ssh "$K3S_SSH_HOST" 'systemctl status "$(systemd-escape -p --suffix=mount /storage/seagate-1tb)" --no-pager'
ssh "$K3S_SSH_HOST" 'journalctl -b | grep -iE "seagate|sda1|ntfs|fstab"'
```

| Symptom in log | Cause |
| --- | --- |
| `EXT4-fs (sda1): VFS: Can't find ext4 filesystem` | fstab declares the wrong FS type |
| `Failed to create unit file ... Duplicate entry in '/etc/fstab'?` | two fstab lines for one mount point |
| `The disk contains an unclean file system` | NTFS dirty bit — Windows hibernation or unclean removal |
| `wrong fs type, bad option, bad superblock` | generic mount failure; read the lines just above it |

For the NTFS dirty bit, `sudo ntfsfix /dev/sda1` clears it, but the authoritative
repair is `chkdsk` on a Windows machine.

### 3. Is k3s blocked on the mount specifically?

```bash
ssh "$K3S_SSH_HOST" 'systemctl show k3s -p RequiresMountsFor -p DropInPaths'
ssh "$K3S_SSH_HOST" 'systemctl list-dependencies k3s --all | grep -i seagate'
ssh -t "$K3S_SSH_HOST" 'sudo systemctl status k3s --no-pager'
```

k3s `inactive (dead)` with the mount unit `failed` is the drop-in doing its job — fix
the mount, then `sudo systemctl start k3s`. Do **not** delete the drop-in as a first
response; that trades a visible outage for silent data corruption.

### 4. Ordinary k3s failures

If the mount is healthy, the drop-in is not your problem. See the
`k3s-troubleshooting` skill, and:

```bash
ssh -t "$K3S_SSH_HOST" 'sudo journalctl -u k3s -n 200 --no-pager'
```

## Debugging: the node is unreachable after a reboot

**Wait two full minutes before concluding anything.** A normal reboot here takes
longer than it feels; more than one "it's dead" has just been an early check. A brief
mid-session SSH timeout on an otherwise healthy node is usually a LAN blip — confirm
with `uptime -s`, which reveals whether it actually rebooted.

```powershell
Test-Connection -ComputerName <node-ip> -Count 1 -Quiet
```

If it stays down, the leading cause is **emergency mode**, which has no networking —
SSH and ping both fail and the machine looks bricked. It is not.

The historical trigger was a duplicate `/etc/fstab` entry:

```
UUID=...4A10 /storage/seagate-1tb ext4    defaults 0 2               ← bogus, no nofail
UUID=...4A10 /storage/seagate-1tb ntfs-3g uid=1000,...,nofail 0 0    ← correct
```

`systemd-fstab-generator` keeps the **first** line for a mount point and discards the
rest. It kept `ext4`, which cannot mount an NTFS volume and lacked `nofail`, so
`local-fs.target` failed and the boot ended in an emergency shell.

**This is not a BIOS boot-order problem, and the drive does not need to be unplugged
to boot.** Confirm from the journal after recovery — early USB enumeration in a
successful boot proves firmware booted the NVMe with the drive attached:

```bash
ssh "$K3S_SSH_HOST" 'journalctl -b -o short-monotonic | grep -iE "Seagate|sda: sda1"'
# [ 2.619] usb 5-3: new SuperSpeed USB device ... Manufacturer: Seagate
# [ 9.000] Mounted storage-seagate\x2d1tb.mount
```

Recovery requires **physical console access** — keyboard and monitor on the node:

```bash
mount -o remount,rw /          # the emergency shell mounts / read-only
nano /etc/fstab                # fix or comment the offending line
systemctl daemon-reload
reboot
```

`/etc/fstab.bak` on the node holds the pre-fix version.

### Verifying a clean boot

```bash
ssh "$K3S_SSH_HOST" 'systemctl is-active local-fs.target emergency.target'   # active, inactive
ssh "$K3S_SSH_HOST" 'systemctl --failed --no-pager'
ssh "$K3S_SSH_HOST" 'findmnt /storage/seagate-1tb'
ssh "$K3S_SSH_HOST" 'journalctl -b | grep -i "COMMAND=/usr/bin/mount" || echo "(mounted automatically)"'
```

The drive should mount **automatically** within ~10s of boot. If you ever find
yourself running `sudo mount -t ntfs-3g ... /dev/sda1 /storage/seagate-1tb` by hand,
fstab is wrong — fix fstab instead of repeating the manual mount, because every boot
spent unmounted is a boot where workloads may write to the wrong disk.

`netfilter-persistent.service` is in a failed state on this node. It is pre-existing
and unrelated to storage; do not treat it as a symptom of a mount problem.

## Editing fstab safely from PowerShell

PowerShell strips inner double quotes from native-command arguments, so
`ssh host 'sudo sed -i "s|a|b|" ...'` reaches bash with `|` as a **pipe** and
corrupts the command. Base64-encode the script instead:

```powershell
$script = @'
set -e
cp /etc/fstab /etc/fstab.bak
# ... edits ...
'@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($script -replace "`r`n","`n")))
ssh server ('echo ' + $b64 + ' | base64 -d > /tmp/fix.sh')
ssh -t server 'sudo bash /tmp/fix.sh'
```

The CRLF-to-LF replacement in that snippet is required: a CRLF-terminated `[Unit]`
line or fstab entry will not parse on the node.

Always dry-run fstab edits against a copy and `diff` them before touching the real
file — a bad fstab costs a physical trip to the machine:

```bash
cp /etc/fstab /tmp/fstab.test && sed -i '...' /tmp/fstab.test && diff /etc/fstab /tmp/fstab.test
```

Then validate with `findmnt --verify` and `systemctl daemon-reload` **before**
rebooting.
