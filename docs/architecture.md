### 1. `docs/architecture.md`

```markdown
# Technical Architecture & System Design

## 1. System Overview

This backup system coordinates the transfer of an ext4 filesystem partition (~170 GB) from an Ubuntu Laptop to an Ubuntu Desktop across a local network.

The architecture decouples the responsibilities cleanly:
1. **Python Client (Laptop):** Control plane, validation, process management, progress stream decoding, and verification.
2. **OpenSSH:** Secure channel, authentication, and encrypted data pipeline.
3. **rsync (Native Engine):** Data plane, delta transfer algorithm, preservation of Linux metadata, and resume support.
4. **Desktop Storage Manager:** Storage lifecycle, atomic promotions, SQLite cataloging, and retention pruning.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           LAPTOP (Client Node)                          │
│                                                                         │
│   ┌───────────────────────┐             ┌───────────────────────────┐   │
│   │    SystemDetector     │             │      SystemValidator      │   │
│   │  (lsblk, findmnt, df) │             │ (Socket, SSH, Disk Quota) │   │
│   └──────────┬────────────┘             └─────────────┬─────────────┘   │
│              │                                        │                 │
│              ▼                                        ▼                 │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                 RsyncRunner / Controller Process                │   │
│   │   - Flags: -aHAXS --numeric-ids --info=progress2                │   │
│   │   - Stream Parser: regex on \r stdout                           │   │
│   │   - Signal Manager: forwards SIGINT/SIGTERM gracefully         │   │
│   └───────────────────────────────┬─────────────────────────────────┘   │
└───────────────────────────────────┼─────────────────────────────────────┘
                                    │
                                    │ OpenSSH Tunnel (Encrypted TCP)
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
│   │   1. Acquire:  .backup.lock                                     │   │
│   │   2. Write:    <Backup-ID>.partial/ + .rsync-partial/           │   │
│   │   3. Promote:  os.replace() ➔ <Backup-ID>/                      │   │
│   │   4. Catalog:  SQLite metadata insertion                        │   │
│   └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. End-to-End Execution Lifecycle

Every backup operation proceeds through six distinct stages:

```
[1. Discover] ➔ [2. Validate] ➔ [3. Lock] ➔ [4. Transfer] ➔ [5. Verify] ➔ [6. Promote & Catalog]
```

### Stage 1: Discovery (`SystemDetector`)
* Executes `lsblk --json --bytes -o NAME,PATH,MOUNTPOINT,FSTYPE,UUID,SIZE`.
* Identifies the physical device (e.g., `/dev/nvme0n1p3`), mountpoint (e.g., `/home`), and filesystem type (`ext4`).
* Extracts precise used byte statistics via `shutil.disk_usage` / `statvfs`.

### Stage 2: Pre-Flight Validation (`SystemValidator`)
Before spawning transfer processes, four gates must clear:
1. **Network Connectivity:** Raw TCP socket check against the Desktop IP and SSH port (`22`).
2. **SSH Authentication:** Passwordless public-key check with batch options (`BatchMode=yes`).
3. **Remote Binaries:** Validates that `rsync` is installed and executable on the Desktop.
4. **Capacity Thresholds:** Computes required storage:
   $$\text{Required Bytes} = \text{Source Used Bytes} \times (1.0 + \text{Safety Margin})$$
   Default safety margin is **10%**. If the Desktop filesystem lacks this capacity, execution aborts immediately.

### Stage 3: Mutual Exclusion Locking (`StorageManager`)
* The storage manager creates `<Client-Dir>/.backup.lock` containing the active PID.
* Prevents data corruption caused by overlapping backup schedules.

### Stage 4: Transfer Execution (`RsyncRunner`)
rsync is invoked with filesystem-preserving flags:
* `-a` (Archive): Recurses directories, copies symlinks, preserves permissions, modification times, group, owner, and device nodes.
* `-H`: Preserves hard links (crucial for Linux root or development trees).
* `-A`: Preserves POSIX Access Control Lists (ACLs).
* `-X`: Preserves Extended Attributes (`xattrs`).
* `-S`: Handles sparse files efficiently (avoids allocating empty blocks).
* `--numeric-ids`: Prevents mapping client UID/GIDs to Desktop users.
* `--info=progress2`: Computes aggregate job-level statistics instead of per-file spam.
* `--partial-dir=.rsync-partial`: Holds interrupted file chunks in a hidden directory to enable instant resumption.

### Stage 5: Output Parsing (`ProgressParser`)
* rsync communicates progress over `stdout` delimited by carriage returns (`\r`).
* The stream reader intercepts these chunks without blocking line-buffered pipes.
* Real-time metrics are extracted using regular expressions:
  ```regex
  ^\s*([\d,]+)\s+(\d+)%\s+([\d.]+[a-zA-Z]+/s)\s+([\d:]+)
  ```
* Dispatches structured `TransferProgress` objects to the CLI progress bar or Rich TUI dashboard.

### Stage 6: Verification & Atomic Promotion (`Verifier`, `StorageManager`, `DatabaseManager`)
1. Translates the rsync exit code (Code `0` = Success; Code `24` = Non-fatal vanished source files).
2. Verifies file counts between source and destination top-level trees.
3. Atomically promotes the directory:
   ```bash
   mv /storage/Host/Host-2026-09-19.partial /storage/Host/Host-2026-09-19
   ```
4. Stores `backup_metadata.json` inside the archive.
5. Inserts job summary into SQLite (`backup_catalog.db`).
6. Releases `.backup.lock`.

---

## 3. Performance & Bottleneck Analysis

| Subsystem | Theoretical Max | Real-World Throughput | Bottleneck Factor |
| :--- | :--- | :--- | :--- |
| **Gigabit Ethernet** | 125 MB/s | **105 – 115 MB/s** | Physical wire speed limit |
| **Wi-Fi 5 / Wi-Fi 6** | 50 – 100 MB/s | **25 – 65 MB/s** | Wireless interference, packet loss |
| **NVMe SSD Read** | 2000+ MB/s | > 1000 MB/s | Not a bottleneck |
| **SSH Crypto (ChaCha20)** | 400+ MB/s | ~300 MB/s | Minimal CPU overhead on Ryzen 5 |

### Transfer Time Estimates for 170 GB
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

1. **Verify Mount State:** Never restore files to a mounted, active partition if you are recovering the root system (`/`). Use an Ubuntu Live USB environment for full operating system restores.
2. **Perform a Dry Run First:** Always run `rsync` with `--dry-run` to inspect changes before writing data.
3. **Preserve Ownerships:** Execute restoration using `sudo` to ensure that root-owned system files, UID/GIDs, and ACLs are properly restored.

---

## 2. Scenario A: Restoring Specific Files or Folders

Use this scenario if you accidentally deleted a subfolder (e.g., `/home/hamada/Documents/`).

### Step 1: Identify the Latest Verified Backup
On the Desktop, run:
```bash
python3 desktop/manager.py history --client HP-EliteBook
```
Locate the path of the desired backup:
`/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/`

### Step 2: Test the Restore with Dry-Run
Run this from your **Laptop**:
```bash
rsync -aHAXSv --numeric-ids --dry-run \
  -e "ssh -i ~/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/hamada/Documents/ \
  /home/hamada/Documents/
```

### Step 3: Execute the Real Restore
Remove the `--dry-run` flag:
```bash
rsync -aHAXSv --numeric-ids \
  -e "ssh -i ~/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/hamada/Documents/ \
  /home/hamada/Documents/
```

---

## 3. Scenario B: Full Partition Restoration

Use this scenario if your hard drive failed or you formatted a partition and need to restore all 170 GB of data.

### Step 1: Boot from an Ubuntu Live USB
Boot the laptop into a live desktop session and open a Terminal.

### Step 2: Format and Mount Target Partition
Prepare the target ext4 partition:
```bash
# Verify disk layout
lsblk

# Format destination partition (Example: /dev/nvme0n1p3)
sudo mkfs.ext4 -L "HomeData" /dev/nvme0n1p3

# Mount to /mnt/target
sudo mkdir -p /mnt/target
sudo mount /dev/nvme0n1p3 /mnt/target
```

### Step 3: Setup SSH Keys on Live USB
Ensure the Live USB environment can access the Desktop:
```bash
mkdir -p ~/.ssh
# Copy or import your private key, or authenticate using your password
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

Formatting a partition assigns a new UUID. If this partition is mounted automatically during boot, `/etc/fstab` must be updated.

1. Find the new UUID of the partition:
   ```bash
   sudo blkid /dev/nvme0n1p3
   ```
   *Output Example:*
   `/dev/nvme0n1p3: UUID="e4d2a1b0-9c8e-4f7a-8b1d-0e3f2a1b4c5d" TYPE="ext4"`

2. Update the target mount configuration:
   ```bash
   sudo nano /mnt/target/etc/fstab
   ```
3. Replace the old UUID with the newly generated UUID string:
   ```text
   UUID=e4d2a1b0-9c8e-4f7a-8b1d-0e3f2a1b4c5d  /home  ext4  defaults,noatime  0  2
   ```
4. Unmount cleanly before rebooting:
   ```bash
   sudo umount /mnt/target
   sudo reboot
   ```
```

---

### 3. `docs/troubleshooting.md`

```markdown
# Troubleshooting & Operational Recovery Runbook

This runbook covers edge cases, network dropouts, stale lock removals, and rsync error resolutions.

---

## 1. Network Disconnection Mid-Transfer

### Problem
Transfer of 170 GB drops out (e.g., at 80% completion) due to an Ethernet cable unplugging, Wi-Fi interruption, or host reboot.

### Recovery Procedure
The system was designed specifically for this scenario:
1. Re-establish network connectivity (confirm via `ping <Desktop-IP>`).
2. Re-run the backup command:
   ```bash
   python3 client/main.py --source /home --target-dir /srv/backups
   ```
3. **What happens under the hood:**
   * `RsyncRunner` detects the existing target directory `<Backup-ID>.partial/`.
   * rsync inspects existing files, verifies timestamps and sizes, checks `.rsync-partial/` for interrupted large files, and resumes sending remaining bytes.
   * **Zero bytes of previously transferred data are duplicated.**

---

## 2. Stale Lock Error (`LockAcquisitionError`)

### Problem
The client displays:
`[ERROR] Job already locked for client HP-EliteBook by PID: 28412`
This occurs if the Laptop crashed, panicked, or had power cut without running clean shutdown handlers.

### Recovery Procedure
1. On the **Desktop**, verify if the old PID is still running:
   ```bash
   ssh backup-user@<Desktop-IP>
   ps aux | grep rsync
   ```
2. If no active rsync process is running for that client, remove the stale `.backup.lock`:
   ```bash
   rm /srv/backups/HP-EliteBook/.backup.lock
   ```
3. Re-run the client application.

---

## 3. Rsync Exit Codes Dictionary

| Exit Code | Meaning | Remediation Action |
| :---: | :--- | :--- |
| **0** | Success | Everything completed cleanly. |
| **1** | Syntax or usage error | Check rsync options or arguments in configuration. |
| **11** | File I/O Error | Check disk health on source or destination via `dmesg \| grep -i ext4` or `smartctl`. |
| **12** | Error in rsync protocol stream | Network connection dropped or remote SSH daemon terminated. Check SSH service logs. |
| **23** | Partial transfer due to error | Specific files were unreadable (e.g., permission denied). Run client with `sudo` if copying root files. |
| **24** | Vanished source files | **Non-fatal warning.** Files (like socket files or browser cache) were deleted while rsync was reading. Directory integrity remains valid. |
| **30** | Timeout in data send/receive | Increase network timeout settings in `client_config.json`. |

---

## 4. Destination Disk Full (`DestinationDiskFullError`)

### Problem
The pre-flight validator rejects execution:
`[FAIL] Insufficient disk space on Desktop. Source requires: 170.30 GB (+10% margin: 187.33 GB). Available on remote: 42.10 GB.`

### Recovery Procedure
Run the retention manager on the **Desktop** to purge old archives:

1. **Option A: Keep only the last 2 backups:**
   ```bash
   python3 desktop/manager.py prune --client HP-EliteBook --keep-last 2
   ```

2. **Option B: Prune backups older than 14 days:**
   ```bash
   python3 desktop/manager.py prune --client HP-EliteBook --max-days 14
   ```

3. Check new free space:
   ```bash
   df -h /srv/backups
   ```
4. Restart the client transfer.

---

## 5. SSH Authentication & Key Rejection

### Problem
`[FAIL] SSH authentication check failed: Permission denied (publickey).`

### Checklist:
1. **Permissions on Desktop:** OpenSSH will silently ignore authorized keys if the permissions are open.
   Fix on Desktop:
   ```bash
   chmod 700 ~/.ssh
   chmod 600 ~/.ssh/authorized_keys
   chmod 755 ~
   ```
2. **Key File Location:** Ensure the client knows which key to use:
   ```bash
   ssh -i ~/.ssh/id_ed25519_backup -p 22 backup-user@<Desktop-IP>
   ```
3. **Firewall:** Verify port 22 is listening:
   ```bash
   sudo ufw status
   sudo ss -tulpn | grep :22
   ```

---

## 6. Preserving File Permissions (Root vs Non-Root)

### Problem
Restored files have lost their original ownership (e.g., files originally owned by user ID 1000 now belong to root, or vice-versa).

### Solution
Always ensure the `--numeric-ids` flag is present during backup and restore. When backing up full partitions that contain system files or multiple user homes:
```bash
sudo python3 client/main.py --source /home --target-dir /srv/backups
```
Running the client with `sudo` allows reading all root-restricted metadata, extended attributes, and POSIX ACLs.
```