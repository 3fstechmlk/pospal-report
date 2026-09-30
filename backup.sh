#!/bin/bash
# Nightly backup for pospal-report, installed via cron at 22:00 MYT.
#
#   data/   full every night — merchants + appKeys + sync state + member cache.
#           Small (≈5 MB gzipped) and irreplaceable: nothing else holds the appKeys.
#   cache/  incremental — the tree is ~41G on a separate volume, far too large to
#           copy nightly.  The daily sync only ever rewrites yesterday and the day
#           before, so a 3-day mtime window captures everything new plus one day of
#           slack in case a run is missed.
#
# Backups land outside the project directory so a deploy (which untars over
# /opt/pospal-report) can never overwrite them.
set -uo pipefail

SRC=/opt/pospal-report
DEST=/opt/pospal-backups
RETENTION_DAYS=30
REMOTE=mega:pospal-backups
LOG="$DEST/backup.log"
TS=$(date +%Y%m%d_%H%M%S)

mkdir -p "$DEST"
log() { echo "$(date '+%F %T') $*" >> "$LOG"; }

log "--- backup start ---"

# ── 1. data/ — full ───────────────────────────────────────────────────────────
DATA_FILE="$DEST/pospal_data_${TS}.tar.gz"
if tar -czf "$DATA_FILE" -C "$SRC" data; then
  log "OK   data    $(du -h "$DATA_FILE" | cut -f1)"
else
  log "FAIL data    tar exit=$?"
  rm -f "$DATA_FILE"
fi

# ── 2. cache/ — files changed in the last 3 days ──────────────────────────────
# cache is a symlink to the volume; cd into the real path so archive members are
# stored relative (./<merchant-id>/<date>.json) and restore is a plain -C extract.
CACHE_FILE="$DEST/pospal_cache_${TS}.tar.gz"
CACHE_DIR=$(readlink -f "$SRC/cache")
if [ -d "$CACHE_DIR" ]; then
  if (cd "$CACHE_DIR" && find . -name '*.json' -type f -mtime -3 -print0 \
        | tar -czf "$CACHE_FILE" --null -T -); then
    log "OK   cache   $(du -h "$CACHE_FILE" | cut -f1)"
  else
    log "FAIL cache   tar exit=$?"
    rm -f "$CACHE_FILE"
  fi
else
  log "FAIL cache   $CACHE_DIR not a directory"
fi

# ── 3. Off-site copy to Mega (non-fatal) ──────────────────────────────────────
if command -v rclone >/dev/null 2>&1; then
  for f in "$DATA_FILE" "$CACHE_FILE"; do
    [ -f "$f" ] || continue
    if rclone copyto "$f" "$REMOTE/$(basename "$f")" 2>>"$LOG"; then
      log "OK   offsite $(basename "$f")"
    else
      log "WARN offsite failed for $(basename "$f")"
    fi
  done
  rclone delete "$REMOTE" --min-age "${RETENTION_DAYS}d" 2>>"$LOG" \
    || log "WARN offsite retention sweep failed"
else
  log "WARN rclone not installed — local copy only"
fi

# ── 4. Local retention ────────────────────────────────────────────────────────
find "$DEST" -name 'pospal_*.tar.gz' -mtime "+$RETENTION_DAYS" -delete
log "--- backup done, $(find "$DEST" -name 'pospal_*.tar.gz' | wc -l) archives kept, $(du -sh "$DEST" | cut -f1) total ---"
