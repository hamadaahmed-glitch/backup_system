### `README.md`

```markdown
# Linux Partition Backup System

A resilient, modular backup system engineered for Ubuntu Linux. It orchestrates the synchronization of an `ext4` partition (~170 GB) from a **Laptop** to a **Desktop** over local network infrastructure using **Python**, **OpenSSH**, and native **rsync**.

---

## Architecture Highlights

```
                 LAPTOP (Client Node)
           ┌──────────────────────────────┐
           │     Python Orchestrator      │
           │  (lsblk, validator, rsync)   │
           └──────────────┬───────────────┘
                          │
                          │ OpenSSH (Port 22)
                          ▼
                 DESKTOP (Storage Node)
           ┌──────────────────────────────┐
           │      OpenSSH + rsync         │
           │              │               │
           │              ▼               │
           │     Storage Hierarchy        │
           │  (Atomic .partial Promotion) │
           │              │               │
           │              ▼               │
           │     Desktop Manager CLI      │
           │   (SQLite Catalog/Pruning)   │
           └──────────────────────────────┘
```

* **Zero Custom Protocol Overhead:** Python acts strictly as the controller and progress observer. File I/O and delta transfers are handed off directly to native `rsync` running over system `OpenSSH`.
* **Metadata Preservation:** Retains Linux POSIX ACLs (`-A`), extended attributes (`-X`), hard links (`-H`), sparse files (`-S`), symlinks, and numeric UIDs/GIDs (`--numeric-ids`).
* **Resumable Transfers:** Employs hidden `.partial-dir` containers and directory-level `.partial` staging. If power fails or the network drops at 80%, restarting immediately resumes where it stopped.
* **Pre-Flight Safety Gates:** Validates network reachability, verifies SSH key trust, and checks available destination capacity (including a **10% safety margin**) prior to data transmission.
* **Storage Atomicity:** Jobs transfer into `<Backup-ID>.partial/`. Only after verification passes is the directory atomically renamed to `<Backup-ID>/` and cataloged in SQLite.

---

## Directory Structure

```text
backup-system/
├── client/                     # Laptop application (CLI / TUI orchestration)
│   ├── main.py                 # Primary entry point
│   ├── core/                   # Detection, validation, rsync controller, verifier
│   └── ui/                     # Terminal presentation layers (Standard CLI & Rich TUI)
│
├── desktop/                    # Desktop application (Cataloging & maintenance)
│   ├── manager.py              # CLI for history, audits, and pruning
│   ├── core/                   # SQLite engine, storage lifecycle, retention
│   └── schemas/database.sql    # SQLite catalog schema
│
├── common/                     # Shared models, exceptions, constants, and logging
├── scripts/                    # Automated setup and network benchmarking tools
├── storage/                    # Storage repository layout on Desktop
├── tests/                      # Unit and integration test suites
└── docs/                       # Technical architecture, restore guide, troubleshooting
```

---

## Quick Start Guide

### Step 1: Provision the Desktop (Destination)
On your **Desktop**, run the automated provisioning script with `sudo` to create the isolated `backup-user`, setup the directory `/srv/backups`, and verify OpenSSH:

```bash
sudo bash scripts/setup_desktop_user.sh
```

### Step 2: Configure Passwordless SSH from Laptop
On your **Laptop**, generate an Ed25519 key pair and deploy it to the Desktop:

```bash
bash scripts/setup_ssh_keys.sh
```

### Step 3: Benchmark Network Performance (Recommended)
Measure physical throughput between the machines to verify connection speeds:

```bash
bash scripts/test_network_limits.sh
```
* **Gigabit Ethernet:** ~105–115 MB/s (170 GB takes ~25 minutes).
* **Wi-Fi 5/6:** ~30–65 MB/s (170 GB takes ~1 to 2 hours).

---

## Usage

### 1. Inspect Local Partitions
Discover local block devices, mountpoints, and used space on the Laptop:

```bash
python3 client/main.py --list-partitions
```

### 2. Execute a Backup
Synchronize an ext4 partition to the Desktop:

```bash
python3 client/main.py \
  --source /home \
  --desktop-host 192.168.1.50 \
  --desktop-user backup-user \
  --desktop-path /srv/backups
```

#### Optional Flags:
* `--tui`: Launches the multi-panel interactive terminal dashboard (requires `pip install rich`).
* `--dry-run`: Simulates the transfer without writing remote files.
* `--compress` (`-z`): Enables rsync compression (recommended for slow Wi-Fi; keep disabled on Gigabit Ethernet).

```bash
# Example with TUI dashboard enabled:
python3 client/main.py --source /home --desktop-host 192.168.1.50 --tui
```

---

## Desktop Management & Operations

Manage stored backups locally on the Desktop using `desktop/manager.py`:

```bash
# View backup run history from the SQLite catalog
python3 desktop/manager.py history

# Filter history by client hostname
python3 desktop/manager.py history --client HP-EliteBook

# Run an integrity audit on a stored archive
python3 desktop/manager.py verify /srv/backups/HP-EliteBook/HP-EliteBook-2026-09-19-213000

# Retain only the last 3 completed backups (Prunes older archives)
python3 desktop/manager.py prune --client HP-EliteBook --keep-last 3

# Prune backups older than 30 days
python3 desktop/manager.py prune --client HP-EliteBook --max-days 30
```

---

## Running Test Suites

Execute all automated unit and integration tests using Python's built-in `unittest` runner:

```bash
python3 -m unittest discover tests/
```

---

## Documentation

* [Technical Architecture & Lifecycle](docs/architecture.md): Deep-dive into design, flags, process pipelines, and storage atomicity.
* [Partition & Data Restore Guide](docs/restore_guide.md): Step-by-step procedures for single-file and full-disk partition restores via Live USB.
* [Troubleshooting & Recovery Runbook](docs/troubleshooting.md): Recovery steps for network disconnections, stale locks, and rsync exit codes.

---

## License

This project is licensed under the MIT License.
```


### How to Run

1. **Interactive Menu (Default):**
   ```bash
   python3 main.py
   ```
   *Displays the interactive menu on either computer, allowing you to select your role (1 for Sender, 2 for Receiver), test the network, or inspect local partitions.*

2. **Command-Line Direct (Sender / Laptop):**
   ```bash
   python3 main.py send --source /home --desktop-host 192.168.1.50 --tui
   ```

3. **Command-Line Direct (Receiver / Desktop):**
   ```bash
   python3 main.py receive
   ```

4. **Run Benchmark Directly:**
   ```bash
   python3 main.py benchmark
   ```

5. **Run Test Suites Directly:**
   ```bash
   python3 main.py test
   ```