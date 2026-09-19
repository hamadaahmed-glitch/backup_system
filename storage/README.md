# Backup Storage Repository Hierarchy

This directory serves as the root destination for all incoming client backups on the Desktop server.

---

## 1. Directory Structure

For each client machine (identified by its hostname), the storage manager maintains an isolated namespace:

```text
storage/
├── backup_catalog.db                      # Global SQLite catalog database
│
└── <Client-Hostname>/                     # e.g., HP-EliteBook/
    ├── .backup.lock                       # Ephemeral lockfile (Active during transfers)
    │
    ├── metadata/                          # Historical archive of run manifests
    │   ├── 2026-09-19-run.json
    │   └── 2026-09-20-run.json
    │
    ├── <Backup-ID>.partial/               # Active / in-progress resumable transfer
    │   ├── .rsync-partial/                # Chunked incomplete files for fast resume
    │   └── ... (files being transferred)
    │
    └── <Backup-ID>/                       # Atomic, fully completed & verified backup
        ├── backup_metadata.json           # Snapshot of this specific backup run
        └── ... (full partition filesystem tree)