#!/usr/bin/env bash
# Copies the database and the issued invoices aside every night.
#
# sqlite3 .backup is used rather than cp: it takes a consistent copy even
# while the application is writing, which a plain file copy does not.
set -euo pipefail

DATA=/var/lib/invoicing
BACKUPS="$DATA/backups"
KEEP_DAYS=30
STAMP=$(date +%Y-%m-%d)

mkdir -p "$BACKUPS"
sqlite3 "$DATA/invoicing.db" ".backup '$BACKUPS/invoicing-$STAMP.db'"

if [ -d "$DATA/rechnungen" ]; then
  tar -czf "$BACKUPS/rechnungen-$STAMP.tar.gz" -C "$DATA" rechnungen
fi

find "$BACKUPS" -type f -mtime +"$KEEP_DAYS" -delete
