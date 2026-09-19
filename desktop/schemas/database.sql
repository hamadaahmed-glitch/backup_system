-- SQLite Schema for Backup Catalog and Integrity Audits

CREATE TABLE IF NOT EXISTS backups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_id TEXT UNIQUE NOT NULL,
    client_hostname TEXT NOT NULL,
    source_partition TEXT NOT NULL,
    source_mountpoint TEXT,
    filesystem_type TEXT,
    bytes_transferred INTEGER DEFAULT 0,
    status TEXT CHECK(status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED', 'INTERRUPTED', 'PRUNED')) NOT NULL,
    storage_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS integrity_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backup_id TEXT NOT NULL,
    audit_timestamp TEXT NOT NULL,
    total_files INTEGER NOT NULL,
    total_bytes INTEGER NOT NULL,
    sample_files_checked INTEGER DEFAULT 0,
    is_valid INTEGER CHECK(is_valid IN (0, 1)) NOT NULL,
    audit_summary TEXT,
    FOREIGN KEY(backup_id) REFERENCES backups(backup_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_backups_client ON backups(client_hostname);
CREATE INDEX IF NOT EXISTS idx_backups_status ON backups(status);
CREATE INDEX IF NOT EXISTS idx_backups_started_at ON backups(started_at);
CREATE INDEX IF NOT EXISTS idx_audits_backup_id ON integrity_audits(backup_id);