### 1. `docs/architecture.md`

```markdown
# Technical Architecture & System Design

## 1. System Overview

This backup system coordinates the transfer of an entire storage partition (ext4 or NTFS up to 170+ GB) from an Ubuntu Laptop to an Ubuntu Desktop across a local network.

The architecture decouples the responsibilities cleanly:
1. **Python Orchestrator (Laptop):** Control plane, discovery, pre-flight safety gates, process lifecycle, progress stream decoding, and verification.
2. **OpenSSH:** Secure encrypted transport, mutual authentication, and remote command execution.
3. **rsync (Native Engine):** Data plane, delta transfer algorithm, preservation of filesystem attributes, and resume logic.
4. **Desktop Storage Manager:** Atomic directory promotion (`.partial` -> clean), SQLite cataloging, and retention pruning.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           LAPTOP (Client Node)                          │
│                                                                         │
│   ┌───────────────────────┐             ┌───────────────────────────┐   │
│   │    SystemDetector     │             │      SystemValidator      │   │
│   │ (Auto-mount, lsblk)   │             │ (Socket, SSH, Disk Quota) │   │
│   └──────────┬────────────┘             └─────────────┬─────────────┘   │
│              │                                        │                 │
│              ▼                                        ▼                 │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                 RsyncRunner / Controller Process                │   │
│   │   - Flags: -aHAXS (ext4) or -rltD (NTFS)                        │   │
│   │   - Stream Parser: regex on \r stdout                           │   │
│   │   - Signal Manager: forwards SIGINT/SIGTERM gracefully         │   │
│   └───────────────────────────────┬─────────────────────────────────┘   │
└───────────────────────────────────┼─────────────────────────────────────┘
                                    │
                                    │ OpenSSH Tunnel (Port 22)
                                    │
┌───────────────────────────────────┼─────────────────────────────────────┐
│                                   ▼                                     │
│                         DESKTOP (Storage Node)                          │
│                                                                         │
│   ┌───────────────────────┐             ┌───────────────────────────┐   │
│   │    OpenSSH Daemon     ├────────────►│       rsync (Server)      │   │
│   └───────────────────────┘             └─────────────┬─────────────┘   │
│                                                       │                 │
│                                                       ▼                 │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                     Storage File Hierarchy                      │   │
│   │   1. Lock:     .backup.lock                                     │   │
│   │   2. Write:    <Backup-ID>.partial/ + .rsync-partial/           │   │
│   │   3. Promote:  os.replace() ➔ <Backup-ID>/                      │   │
│   │   4. Catalog:  SQLite metadata insertion                        │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. End-to-End Execution Lifecycle

Every backup operation proceeds through six distinct stages:

```text
[1. Discover] ➔ [2. Validate] ➔ [3. Lock] ➔ [4. Transfer] ➔ [5. Verify] ➔ [6. Promote & Catalog]
```

### Stage 1: Discovery (`SystemDetector`)
* Executes `lsblk -e 7` to filter out virtual snap loop devices (`squashfs`).
* Identifies physical devices (e.g. `/dev/nvme0n1p2`, `/dev/nvme0n1p4`), filesystem type (`ext4`, `ntfs`), and used space.
* **Auto-Mount:** If an unmounted partition is selected, it mounts it read-only via `udisksctl` or `/mnt/backup_source` and cleans it up when done.

### Stage 2: Pre-Flight Validation (`SystemValidator`)
Before spawning rsync, four safety gates must clear:
1. **Network Reachability:** Raw TCP socket check against the Desktop IP and SSH port (`22`).
2. **SSH Authentication:** Passwordless public-key check with batch options (`BatchMode=yes`).
3. **Remote Binaries:** Validates that `rsync` is installed and executable on the Desktop.
4. **Capacity Thresholds:** Computes required storage:
   $$\text{Required Bytes} = \text{Source Used Bytes} \times (1.0 + \text{Safety Margin})$$
   Default safety margin is **10%**. If Desktop storage lacks this capacity, execution aborts immediately.

### Stage 3: Mutual Exclusion Locking (`StorageManager`)
* The storage manager creates `<Client-Dir>/.backup.lock` containing the active PID.
* Prevents data corruption caused by overlapping backup jobs targeting the same client directory.

### Stage 4: Transfer Execution (`RsyncRunner`)
rsync is invoked with flags tailored to the filesystem:
* **ext4 (Linux Native):** `-aHAXS --numeric-ids` (preserves ACLs, extended attributes, hard links, sparse files, and numeric UIDs/GIDs).
* **NTFS (Windows Data):** `-rltD` (safely drops Linux POSIX ACLs/xattrs that are unsupported on Windows NTFS).
* **Resume Support:** `--partial-dir=.rsync-partial` saves incomplete file chunks in a hidden directory. If disconnected at 80%, restarting will instantly resume where it stopped.
* **Live Progress:** `--info=progress2` streams whole-job metrics over `stdout` via `\r`.

### Stage 5: Verification & Atomic Promotion (`Verifier`, `StorageManager`)
1. Translates rsync exit codes (Code `0` = Success; Code `24` = Non-fatal vanished source files).
2. Verifies file counts between source and destination top-level trees.
3. Atomically promotes the directory:
   ```bash
   mv /storage/Host/Host-2026-09-19.partial /storage/Host/Host-2026-09-19
   ```
4. Writes `backup_metadata.json` inside the archive.
5. Inserts job summary into SQLite (`backup_catalog.db`).
6. Releases `.backup.lock`.

---

## 3. Performance & Bottleneck Analysis

| Subsystem | Theoretical Max | Real-World Throughput | Bottleneck Factor |
| :--- | :--- | :--- | :--- |
| **Gigabit Ethernet** | 125 MB/s | **105 – 115 MB/s** | Physical wire speed limit |
| **Wi-Fi 5 / Wi-Fi 6** | 50 – 100 MB/s | **25 – 65 MB/s** | Wireless interference, packet loss |
| **NVMe SSD Read** | 2000+ MB/s | > 1000 MB/s | Not a bottleneck |
| **SSH Crypto (ChaCha20)** | 400+ MB/s | ~300 MB/s | Minimal CPU overhead |

### Transfer Time Estimates for 160–170 GB
* **Gigabit Ethernet (~110 MB/s):**
  $$\text{Time} = \frac{170 \times 1024 \text{ MB}}{110 \text{ MB/s}} \approx 1582 \text{ seconds} \approx \mathbf{26 \text{ minutes}}$$
* **Fast Wi-Fi (~45 MB/s):**
  $$\text{Time} = \frac{170 \times 1024 \text{ MB}}{45 \text{ MB/s}} \approx 3868 \text{ seconds} \approx \mathbf{1 \text{ hour } 4 \text{ minutes}}$$
```

---

### 2. `docs/restore_guide.md`

```markdown
# Partition & Data Restore Guide

This guide details how to restore backed-up data from the Desktop storage node back to the Laptop.

---

## 1. Safety Rules Prior to Restoring

1. **Verify Mount State:** Never restore files into an active, mounted root system (`/`). If recovering an entire OS partition, use an Ubuntu Live USB session.
2. **Perform a Dry Run First:** Always run `rsync` with `--dry-run` to inspect files before writing data.
3. **Preserve Ownerships:** Execute restoration using `sudo` to ensure root-owned system files, numeric UID/GIDs, and ACLs are restored cleanly.

---

## 2. Scenario A: Restoring Specific Files or Folders

Use this scenario if you want to recover a specific folder (e.g. `Documents/` or `Projects/`).

### Step 1: Identify the Target Backup on Desktop
On the Desktop, run:
```bash
python3 main.py
# Choose [2] RECEIVER -> [1] View Backup History
```
Locate the directory path of the desired backup:
`/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/`

### Step 2: Test with Dry-Run from Laptop
```bash
rsync -aHAXSv --numeric-ids --dry-run \
  -e "ssh -i ~/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/Projects/ \
  /home/hamada/Projects/
```

### Step 3: Execute the Real Restore
Remove the `--dry-run` flag:
```bash
rsync -aHAXSv --numeric-ids \
  -e "ssh -i ~/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/Projects/ \
  /home/hamada/Projects/
```

---

## 3. Scenario B: Full Partition Restoration (Live USB)

Use this scenario if your hard drive was replaced or formatted and you need to restore all ~160 GB of data.

### Step 1: Boot from an Ubuntu Live USB
Boot the laptop into a live desktop session and open a Terminal.

### Step 2: Format and Mount Target Partition
```bash
# Verify disk layout
lsblk

# Format destination partition (Example: ext4 on /dev/nvme0n1p4)
sudo mkfs.ext4 -L "LinuxData" /dev/nvme0n1p4

# Mount to /mnt/target
sudo mkdir -p /mnt/target
sudo mount /dev/nvme0n1p4 /mnt/target
```

### Step 3: Configure SSH Access in Live Environment
```bash
mkdir -p ~/.ssh
# Place your private key into ~/.ssh/id_ed25519_backup
chmod 600 ~/.ssh/id_ed25519_backup
```

### Step 4: Execute Full Partition Restore
Run rsync with full preservation flags:
```bash
sudo rsync -aHAXS --numeric-ids --info=progress2 \
  -e "ssh -i ~/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/ \
  /mnt/target/
```

---

## 4. Scenario C: Updating `/etc/fstab` (If Filesystem UUID Changed)

Formatting a partition assigns a new UUID. If this partition mounts automatically at boot, `/etc/fstab` must be updated:

1. Identify the new UUID:
   ```bash
   sudo blkid /dev/nvme0n1p4
   ```
   *Example:* `UUID="69c82c3f-519f-44d5-8a21-f818f20355a0"`

2. Update the target mount table:
   ```bash
   sudo nano /mnt/target/etc/fstab
   ```
3. Update the matching line:
   ```text
   UUID=69c82c3f-519f-44d5-8a21-f818f20355a0  /  ext4  defaults,noatime  0  1
   ```
4. Unmount cleanly:
   ```bash
   sudo umount /mnt/target
   sudo reboot
   ```
```

---

### 3. `docs/troubleshooting.md`

```markdown
# Troubleshooting & Operational Recovery Runbook

This runbook covers edge cases, network drops, stale locks, and rsync error resolutions.

---

## 1. Network Disconnection Mid-Transfer

### Problem
Transfer drops out (e.g. at 80% completion) due to an Ethernet cable unplugging, Wi-Fi dropping, or a machine rebooting.

### Recovery Procedure
The system was designed specifically for this scenario:
1. Re-establish network connectivity (confirm via `ping <Desktop-IP>`).
2. Re-run:
   ```bash
   python3 main.py
   # Choose [1] SENDER and select the partition again
   ```
3. **What happens under the hood:**
   * rsync inspects existing files in `<Backup-ID>.partial/`.
   * Files that were already transferred and verified are skipped.
   * Incomplete files stored in `.rsync-partial/` resume transferring remaining byte ranges.
   * **Zero previously transferred data is duplicated.**

---

## 2. Stale Lock Error (`LockAcquisitionError`)

### Problem
The client displays:
`[ERROR] Job already locked for client HP-EliteBook by PID: 45316`
This happens if the computer crashed or had power cut without running clean shutdown handlers.

### Recovery Procedure
1. On the **Desktop**, verify if an active rsync process is still running:
   ```bash
   ps aux | grep rsync
   ```
2. If no active rsync process is running for that client, remove the stale `.backup.lock`:
   ```bash
   rm /srv/backups/HP-EliteBook/.backup.lock
   # Or if using local storage:
   rm storage/HP-EliteBook/.backup.lock
   ```
3. Re-run the transfer.

---

## 3. Permission Denied on `/srv/backups`

### Problem
`PermissionError: [Errno 13] Permission denied: '/srv/backups'`

### Cause
`/srv` is a root-owned directory. If you haven't run the provisioning script, regular users cannot create folders in `/srv`.

### Fix
* **Option A (Recommended):** Run this once with `sudo` on the Desktop:
  ```bash
  sudo mkdir -p /srv/backups && sudo chown -R $USER:$USER /srv/backups
  ```
* **Option B (User-space storage):** In `main.py`, select the default auto-fallback to `./storage` or `~/Backups`, which requires zero root permissions.

---

## 4. Rsync Exit Codes Dictionary

| Exit Code | Meaning | Remediation Action |
| :---: | :--- | :--- |
| **0** | Success | Everything completed cleanly. |
| **1** | Syntax or usage error | Check rsync options or arguments in configuration. |
| **11** | File I/O Error | Check disk health on source or destination via `dmesg \| grep -i ext4` or `smartctl`. |
| **12** | Error in rsync protocol stream | Network connection dropped or remote SSH daemon terminated. |
| **23** | Partial transfer due to error | Specific files were unreadable (e.g. permission denied). Run with `sudo` if copying root-owned files. |
| **24** | Vanished source files | **Non-fatal warning.** Files (like browser cache or temp sockets) were deleted while rsync was reading. Backup is completely valid. |
| **30** | Timeout in data send/receive | Increase network timeout settings in `client_config.json`. |

---

## 5. Destination Disk Full (`DestinationDiskFullError`)

### Problem
`[FAIL] Insufficient disk space on Desktop. Source requires: 161.55 GB (+10% margin: 177.70 GB). Available on remote: 42.10 GB.`

### Recovery Procedure
Run the retention manager on the **Desktop** to purge old archives:

1. Launch receiver menu:
   ```bash
   python3 main.py
   # Choose [2] RECEIVER -> [3] Prune Old Backups
   ```
2. Enter your client hostname and keep only the last **1** or **2** backups.
3. Once old archives are deleted, rerun the backup.

---

## 6. SSH Authentication Failure

### Problem
`[FAIL] SSH authentication check failed: Permission denied (publickey).`

### Checklist:
1. **Permissions on Desktop:** OpenSSH will silently ignore authorized keys if the permissions are too open.
   Fix on Desktop:
   ```bash
   chmod 700 ~/.ssh
   chmod 600 ~/.ssh/authorized_keys
   chmod 755 ~
   ```
2. **Key File Location:** Ensure the client points to the correct key:
   ```bash
   ssh -i ~/.ssh/id_ed25519_backup -p 22 backup-user@<Desktop-IP>
   ```
3. **Firewall:** Verify port 22 is open:
   ```bash
   sudo ufw status
   sudo ss -tulpn | grep :22
   ```
```