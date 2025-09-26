#!/usr/bin/env bash
set -euo pipefail

# Update ~/.zshrc with a managed block of environment variables for this project.
# The script:
# - creates a timestamped backup of your existing ~/.zshrc
# - removes any previous managed block between markers
# - removes any stray exports for MSSQL_*, ODBC_DRIVER or LOG_SINK
# - writes a new managed block at the top of ~/.zshrc
#
# Usage: ./scripts/update_zsh_env.sh

ZSHRC="$HOME/.zshrc"
TS=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$HOME/.zshrc.bak.$TS"

if [ ! -f "$ZSHRC" ]; then
  echo "No $ZSHRC found; creating an empty one." >&2
  touch "$ZSHRC"
fi

echo "Creating backup: $BACKUP"
cp -p "$ZSHRC" "$BACKUP"

# Remove any existing managed block between markers and any exports we manage.
TMP=$(mktemp)
awk '
  BEGIN{inside=0}
  /# >>> PROJECT MANAGED ENV BEGIN >>>/ {inside=1; next}
  /# <<< PROJECT MANAGED ENV END <<</ {inside=0; next}
  { if(!inside) print }
' "$ZSHRC" | grep -v -E '^(export[[:space:]]+MSSQL_|export[[:space:]]+ODBC_DRIVER=|export[[:space:]]+LOG_SINK=)' > "$TMP" || true

cat > "$ZSHRC" <<ZSH
# >>> PROJECT MANAGED ENV BEGIN >>>
export MSSQL_HOST=154.12.226.108
export MSSQL_PORT=1433
export MSSQL_DB=vps_dude
export MSSQL_USER=sa
export MSSQL_PASSWORD='NewStrong!Passw0rd'
export MSSQL_ENCRYPT=true
export ODBC_DRIVER='ODBC Driver 18 for SQL Server'
export LOG_SINK=db
# <<< PROJECT MANAGED ENV END <<<

"# Additional content from previous $ZSHRC" 
ZSH

cat "$TMP" >> "$ZSHRC"
rm -f "$TMP"

echo "Updated $ZSHRC. Backup saved as $BACKUP"
echo "To apply changes in your current shell run: source $ZSHRC"
