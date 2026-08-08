#!/usr/bin/env bash
# Sets up the application on a fresh Ubuntu server. Run once, as root.
#
#   INVOICING_DOMAIN=rechnungen.example.com bash deploy/install.sh
#
# Afterwards the application answers on that domain over HTTPS, restarts by
# itself, and backs its database up every night.
set -euo pipefail

DOMAIN="${INVOICING_DOMAIN:?set INVOICING_DOMAIN to the subdomain you pointed at this server}"
CODE=/opt/invoicing
DATA=/var/lib/invoicing
SERVICE_USER=invoicing

echo "==> System packages"
apt-get update
# The first four are what WeasyPrint needs to render text; without them it
# falls back to nothing and no invoice can be produced.
apt-get install -y --no-install-recommends \
  libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1 \
  sqlite3 curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https

echo "==> Caddy, for automatic HTTPS"
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
  apt-get install -y caddy
fi

echo "==> Account and folders"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$DATA/rechnungen" "$DATA/backups"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA"

echo "==> Python environment"
if [ ! -x "$CODE/.venv/bin/python" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi
cd "$CODE"
uv sync --no-dev --frozen
chown -R root:root "$CODE"
# scp from Windows arrives with 700 directories, which the service account
# cannot read; open them up without touching the execute bits of files.
chmod -R a+rX "$CODE"

echo "==> Services"
install -m 644 deploy/invoicing.service /etc/systemd/system/invoicing.service
install -m 644 deploy/invoicing-backup.service /etc/systemd/system/invoicing-backup.service
install -m 644 deploy/invoicing-backup.timer /etc/systemd/system/invoicing-backup.timer
install -m 755 deploy/backup.sh /usr/local/bin/invoicing-backup
sed "s/{{DOMAIN}}/$DOMAIN/" deploy/Caddyfile > /etc/caddy/Caddyfile

systemctl daemon-reload
systemctl enable --now invoicing.service
systemctl enable --now invoicing-backup.timer
systemctl restart caddy

echo
echo "Done. Set a password before you sign in:"
echo "  sudo -u $SERVICE_USER $CODE/.venv/bin/python $CODE/main.py set-password 'YOUR-PASSWORD' --database $DATA/invoicing.db"
echo "Then open https://$DOMAIN"
