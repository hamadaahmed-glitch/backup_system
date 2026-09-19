# `docs/restore_guide.md`

```markdown
# Partition & Data Restore Guide

This guide provides authoritative, step-by-step procedures for restoring backed-up partitions and files from your Desktop storage node back to your Laptop.

---

## 1. Safety Principles Before Restoring

1. **Never Restore into an Active Root Mount:** If you are restoring the operating system (`/`), never restore over a running OS. Always boot from an **Ubuntu Live USB** to restore to an unmounted or dedicated mount target (`/mnt/target`).
2. **Always Run a Dry-Run First:** Always test your rsync restore command with `--dry-run` (`-n`) first. Inspect the output to verify files will land in the exact target directory without unintended overwrites.
3. **Preserve Permissions with Sudo:** Always execute full restores with `sudo`. This guarantees that root-owned files, user UIDs/GIDs, POSIX ACLs, and extended attributes are accurately recreated.

---

## 2. Locating Your Backup on the Desktop

Before restoring, identify the exact backup archive path on your Desktop.

Run this on your Desktop:
```bash
python3 main.py
# Select [2] RECEIVER -> [1] View Backup History
```

Or query the storage directory directly:
```bash
ls -ld /srv/backups/HP-EliteBook/*
```

*Example Path Found:*
`/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/`

---

## 3. Scenario A: Restoring Specific Files or Directories

Use this scenario if you accidentally deleted or corrupted specific files while working in Ubuntu.

### Step 1: Test with Dry-Run
Run from your **Laptop** terminal (replace with your Desktop IP):
```bash
rsync -av --dry-run \
  -e "ssh -i ~/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/Projects/ \
  /home/hamada/Projects/
```

### Step 2: Execute the Real Restore
Remove the `--dry-run` flag:
```bash
rsync -av \
  -e "ssh -i ~/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/Projects/ \
  /home/hamada/Projects/
```

---

## 4. Scenario B: Restoring the 161.55 GB NTFS Partition (`/dev/nvme0n1p2`)

Use this scenario to restore your entire Windows or NTFS data partition.

### Step 1: Mount the NTFS Partition
Ensure the target partition is mounted on your Laptop:
```bash
# Check if mounted
lsblk -f /dev/nvme0n1p2

# If not mounted, mount via udisksctl or manual mount:
udisksctl mount -b /dev/nvme0n1p2
# Or manually:
sudo mkdir -p /mnt/ntfs_target
sudo mount -t ntfs-3g /dev/nvme0n1p2 /mnt/ntfs_target
```
*Assume mountpoint is `/mnt/ntfs_target`.*

### Step 2: Run Restore with NTFS-Safe Flags
Because NTFS does not use Linux POSIX ACLs or Linux UID/GID structures, use `-rltD` to prevent permission errors:

```bash
sudo rsync -rltDv --info=progress2 \
  -e "ssh -i ~/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/ \
  /mnt/ntfs_target/
```

### Step 3: Unmount Safely
```bash
sudo umount /mnt/ntfs_target
```

---

## 5. Scenario C: Disaster Recovery of Ubuntu Root Partition (`/dev/nvme0n1p4`)

Use this procedure if your Linux drive failed, had a corrupted filesystem, or needs to be completely reinstalled.

### Step 1: Boot into an Ubuntu Live USB
1. Insert your Ubuntu Live USB into the Laptop.
2. Boot into the "Try Ubuntu" live session.
3. Open a Terminal (`Ctrl+Alt+T`).

### Step 2: Prepare the Target Disk
Identify and format the target ext4 partition:
```bash
# Check drive layout
sudo lsblk

# (Optional) Format target partition fresh
sudo mkfs.ext4 -L "UbuntuRoot" /dev/nvme0n1p4

# Mount to /mnt/target
sudo mkdir -p /mnt/target
sudo mount /dev/nvme0n1p4 /mnt/target
```

### Step 3: Configure Network and SSH in the Live Session
Ensure the Live environment has your SSH key to reach the Desktop:
```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh

# Copy your private key onto the Live USB or copy from a USB drive:
cp /path/to/backup/id_ed25519_backup ~/.ssh/id_ed25519_backup
chmod 600 ~/.ssh/id_ed25519_backup

# Verify connection to Desktop
ssh -i ~/.ssh/id_ed25519_backup -p 22 backup-user@192.168.1.50 "echo 'Connected successfully'"
```

### Step 4: Execute Full System Restore
Run rsync with complete Linux metadata preservation (`-aHAXS --numeric-ids`):

```bash
sudo rsync -aHAXS --numeric-ids --info=progress2 \
  -e "ssh -i /home/ubuntu/.ssh/id_ed25519_backup -p 22" \
  backup-user@192.168.1.50:/srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000/ \
  /mnt/target/
```

---

## 6. Scenario D: Post-Restore Boot Configuration (GRUB & UUIDs)

If you formatted the partition during a disaster recovery, its **UUID changed**. You must update `/etc/fstab` and reinstall GRUB so the machine boots properly.

### Step 1: Get the New UUID
```bash
sudo blkid /dev/nvme0n1p4
```
*Example Output:*
`/dev/nvme0n1p4: UUID="69c82c3f-519f-44d5-8a21-f818f20355a0" TYPE="ext4"`

### Step 2: Update `/mnt/target/etc/fstab`
```bash
sudo nano /mnt/target/etc/fstab
```
Find the root entry (`/`) and update the `UUID=` string:
```text
# Root mount
UUID=69c82c3f-519f-44d5-8a21-f818f20355a0  /  ext4  errors=remount-ro  0  1
```
Save with `Ctrl+O` and exit with `Ctrl+X`.

### Step 3: Reinstall and Update GRUB
Bind-mount the system files from the live environment to enter the restored system:
```bash
sudo mount --bind /dev /mnt/target/dev
sudo mount --bind /proc /mnt/target/proc
sudo mount --bind /sys /mnt/target/sys
sudo mount /dev/nvme0n1p1 /mnt/target/boot/efi   # Mount EFI partition

# Enter chroot
sudo chroot /mnt/target

# Update bootloader
update-grub
grub-install /dev/nvme0n1

# Exit chroot
exit
```

### Step 4: Reboot
```bash
sudo umount -R /mnt/target
sudo reboot
```
Remove the Live USB. Your system will boot into the restored state.

---

## 7. Post-Restore Verification Checklist

After completing any restore operation, run these validation steps:

1. **Verify File Counts:**
   ```bash
   find /path/to/restored_target -mindepth 1 -maxdepth 1 | wc -l
   ```
2. **Verify Storage Usage:**
   ```bash
   df -h /path/to/restored_target
   ```
3. **Verify Readability:**
   Run a sample checksum test across user files:
   ```bash
   head -n 20 < /path/to/restored_target/some_important_file.txt
   ```
```