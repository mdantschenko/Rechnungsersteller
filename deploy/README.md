# Running this on a server

The application is a program that has to keep running, so it needs a machine
that stays on. What follows sets it up on a fresh Ubuntu server and leaves it
reachable at a subdomain over HTTPS, restarting by itself and backing itself
up every night.

Everything below is done from your own computer unless it says otherwise.

## 1. Create the server

At IONOS, order a **VPS with Ubuntu 24.04**. The smallest one is enough. Note
down its **IPv4 address** and the root password.

## 2. Point a subdomain at it

In the IONOS customer area, under the domain, add a record:

| Type | Name | Value |
|---|---|---|
| A | `rechnungen` | the server's IPv4 address |

This only adds a name and leaves your MX records, and therefore your email,
untouched. Give it a few minutes to spread.

## 3. Upload the code

```powershell
.\deploy\upload.ps1 -Server root@THE.SERVER.IP
```

## 4. Set it up

Log in and run the installer once:

```bash
ssh root@THE.SERVER.IP
cd /opt/invoicing
INVOICING_DOMAIN=rechnungen.deine-domain.de bash deploy/install.sh
```

It installs what WeasyPrint needs, sets up Caddy for HTTPS, creates a service
account, starts the application and enables the nightly backup.

## 5. Choose a password

```bash
sudo -u invoicing /opt/invoicing/.venv/bin/python /opt/invoicing/main.py \
  set-password 'YOUR-PASSWORD' --database /var/lib/invoicing/invoicing.db
```

Then open `https://rechnungen.deine-domain.de` in Safari on your phone and add
it to the home screen.

## Bringing your existing invoices along

If you want the imported history on the server, copy the database up before
setting a password:

```powershell
scp data/invoicing.db root@THE.SERVER.IP:/var/lib/invoicing/invoicing.db
ssh root@THE.SERVER.IP "chown invoicing:invoicing /var/lib/invoicing/invoicing.db"
```

## Updating later

```powershell
.\deploy\upload.ps1 -Server root@THE.SERVER.IP
ssh root@THE.SERVER.IP "cd /opt/invoicing && uv sync --no-dev --frozen && systemctl restart invoicing"
```

Schema changes are applied by the application itself when it starts.

## Where things live

| | |
|---|---|
| Code | `/opt/invoicing` |
| Database | `/var/lib/invoicing/invoicing.db` |
| Issued invoices | `/var/lib/invoicing/rechnungen/<year>/` |
| Backups, 30 days | `/var/lib/invoicing/backups` |
| Application log | `journalctl -u invoicing -f` |
| Web server log | `/var/log/caddy/invoicing.log` |

Set the invoice folder to `/var/lib/invoicing/rechnungen` on the settings
screen after the first sign-in.

## Rendering

On Linux the PDF is produced by WeasyPrint, which the installer provides the
system libraries for. Playwright and its browser are not installed there; they
exist only for Windows, where WeasyPrint cannot run. The application picks
whichever is available on its own.
