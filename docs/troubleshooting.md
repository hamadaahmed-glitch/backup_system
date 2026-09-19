# `docs/troubleshooting.md`

```markdown
# Operational Troubleshooting & Recovery Runbook

This runbook provides actionable solutions for network dropouts, stale lock collisions, storage permission errors, NTFS mount conflicts, and rsync exit codes.

---

## Quick Diagnostic Checklist

If a transfer or management command fails, run this diagnostic sequence first:

```bash
# 1. Test ping reachability between Laptop and Desktop
ping -c 3 192.168.1.50

# 2. Test passwordless SSH connectivity
ssh -i ~/.ssh/id_ed25519_backup -p 22 backup-user@192.168.1.50 "echo 'SSH is functional'"

# 3. Check disk space on Desktop storage target
ssh -i ~/.ssh/id_ed25519_backup -p 22 backup-user@192.168.1.50 "df -h /srv/backups"

# 4. Check whether rsync is currently running on the Desktop
ssh -i ~/.ssh/id_ed25519_backup -p 22 backup-user@192.168.1.50 "pgrep -a rsync"
```

---

## 1. Network Disconnection Mid-Transfer (160+ GB Resume)

### Symptom
Transfer drops out (e.g. at 75% or 80% completion) due to an Ethernet cable unplugging, Wi-Fi latency spike, or computer reboot.

### Solution & Recovery
The system uses `--partial-dir=.rsync-partial` and staging directories (`.partial/`) specifically to handle this:
1. Re-establish physical network connectivity (verify with `ping`).
2. Re-run the transfer:
   ```bash
   python3 main.py
   # Choose [1] SENDER and re-select your partition
   ```
3. **What happens automatically:**
   * rsync inspects existing files in `<Backup-ID>.partial/`.
   * Files that are already fully transferred are verified and skipped.
   * Large files that were cut off mid-way resume transferring only the missing bytes from `.rsync-partial/`.
   * **No duplicate data is transferred.**

---

## 2. Permission Denied on `/srv/backups`

### Symptom
```text
PermissionError: [Errno 13] Permission denied: '/srv/backups'
```

### Cause
In Linux, `/srv` is owned by `root`. A non-root user (`hamada`) cannot create subdirectories in `/srv` unless write permissions have been granted.

### Solution

#### Option A: Grant Permissions to Your User (Recommended)
Run this once with `sudo` on your **Desktop**:
```bash
sudo mkdir -p /srv/backups
sudo chown -R $USER:$USER /srv/backups
sudo chmod -R 750 /srv/backups
```

#### Option B: Use User-Space Storage
The system automatically detects permission failures and falls back to:
```text
./storage
# or
~/Backups
```
Both of these paths require zero `sudo` permissions.

---

## 3. Stale Lock Error (`LockAcquisitionError`)

### Symptom
```text
[ERROR] Job already locked for client HP-EliteBook by PID: 45316
```

### Cause
Occurs when the Laptop or Desktop crashed, lost power, or was terminated forcefully (`SIGKILL`) without allowing Python to run its clean exit handlers.

### Solution

1. **Verify if the old PID is still alive on the Desktop:**
   ```bash
   ssh backup-user@192.168.1.50 "ps -p 45316"
   ```
2. **If no process exists with that PID, remove the stale lockfile:**
   ```bash
   # On the Desktop:
   rm /srv/backups/HP-EliteBook/.backup.lock

   # Or if using local storage:
   rm storage/HP-EliteBook/.backup.lock
   ```
3. Restart your backup job.

---

## 4. NTFS Partition Fails to Mount (`/dev/nvme0n1p2`)

### Symptom A: Windows Hibernation / Fast Startup Lock
```text
The disk contains an unclean file system (0, 0).
Metadata keeps Windows Paging File. ... Windows is hibernated, refused to mount.
```

### Cause
Windows was shut down using "Fast Startup" (hybrid hibernation), leaving the NTFS partition locked.

### Solution
1. Boot into Windows on the Laptop.
2. Open Command Prompt as Administrator and run:
   ```cmd
   powercfg /h off
   ```
3. Shut down Windows completely (do not use "Sleep" or "Hibernate").
4. Boot into Ubuntu; the partition can now be mounted cleanly.
5. **Temporary read-only mount alternative:**
   ```bash
   sudo mkdir -p /mnt/backup_source
   sudo mount -t ntfs-3g -o ro,remove_hiberfile /dev/nvme0n1p2 /mnt/backup_source
   ```

---

### Symptom B: Partition Device Busy
```text
mount: /mnt/backup_source: /dev/nvme0n1p2 already mounted or mount point busy.
```

### Solution
Find where it is already mounted:
```bash
findmnt /dev/nvme0n1p2
```
If mounted at `/run/media/hamada/2E66791E6678E7CB`, you can pass that mountpoint directly as the source or unmount it:
```bash
udisksctl unmount -b /dev/nvme0n1p2
```

---

## 5. SSH Authentication Rejections

### Symptom
```text
[FAIL] SSH authentication check failed: Permission denied (publickey).
```

### Checklist & Fixes:

1. **Strict Permissions on Desktop (Most Common Cause):**
   OpenSSH disables key authentication if the `.ssh` folder or home directory has group-write permissions.
   Run on the **Desktop**:
   ```bash
   chmod 700 ~/.ssh
   chmod 600 ~/.ssh/authorized_keys
   chmod 755 ~
   ```
2. **Verify Correct Key Is Used on Laptop:**
   ```bash
   ssh -i ~/.ssh/id_ed25519_backup -p 22 backup-user@192.168.1.50
   ```
3. **Firewall Blocking Port 22:**
   Check UFW status on the Desktop:
   ```bash
   sudo ufw status
   # Allow SSH if blocked:
   sudo ufw allow 22/tcp
   sudo ufw reload
   ```

---

## 6. Destination Disk Full (`DestinationDiskFullError`)

### Symptom
```text
[FAIL] Insufficient disk space on Desktop. 
Source requires: 161.55 GB (+10% margin: 177.70 GB). 
Available on remote: 82.10 GB.
```

### Solution
Free up space by pruning older backups using the Desktop Manager:

1. On the **Desktop**, run:
   ```bash
   python3 main.py
   # Select [2] RECEIVER -> [3] Prune Old Backups
   ```
2. Enter the client hostname (e.g. `HP-EliteBook`).
3. Set retention:
   * Keep only the last **1** or **2** backups:
   ```bash
   # Or directly from CLI:
   python3 desktop/manager.py prune --client HP-EliteBook --keep-last 1
   ```
4. Check available storage:
   ```bash
   df -h /srv/backups
   ```
5. Restart the Laptop backup once space is freed.

---

## 7. Rsync Exit Codes Dictionary

| Exit Code | Classification | Cause & Meaning | Actionable Fix |
| :---: | :---: | :--- | :--- |
| **0** | Success | Transfer completed cleanly and verified. | None needed. |
| **1** | Fatal | Syntax or usage command-line error. | Verify arguments in `config/client_config.json`. |
| **10** | Error | Error in socket I/O. | Network link went down. Check Ethernet cable or Wi-Fi. |
| **11** | Fatal | Error in file I/O. | Disk bad sectors or filesystem corruption. Check `dmesg \| grep -i ext4` or `smartctl`. |
| **12** | Fatal | Error in rsync protocol data stream. | Remote SSH daemon crashed or connection timed out. |
| **20** | Signal | Process received `SIGINT` or `SIGTERM`. | Transfer stopped cleanly by user pressing `Ctrl+C`. Re-run to resume. |
| **23** | Partial | Partial transfer due to error (e.g. unreadable root files). | Run with `sudo` if copying files owned by other users or `root`. |
| **24** | **Warning** | Vanished source files. | **Non-fatal.** Ephemeral files (browser cache, temp files) were deleted while copying. The backup is valid. |
| **30** | Error | Timeout in data send/receive. | Network congested. Increase timeout in `client_config.json`. |

---

## 8. Cleaning Up Abandoned Temporary Mounts

If the Python script was forcefully killed (`kill -9`) while backing up an unmounted partition, the temporary mount might remain active.

To clean it up manually:

```bash
# Check if /mnt/backup_source or /run/media/... is still mounted:
mount | grep nvme0n1p2

# Unmount cleanly:
sudo umount /mnt/backup_source
# Or via udisksctl:
udisksctl unmount -b /dev/nvme0n1p2
```
```