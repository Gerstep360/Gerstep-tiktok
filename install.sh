#!/usr/bin/env bash
set -euo pipefail
umask 027
SOURCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR=/opt/gerstep-interactive
NGINX_SITE="${1:-}"
SERVICE_PORT="${GERSTEP_PORT:-9081}"
if [[ ${EUID} -ne 0 ]]; then echo "Use: sudo bash vps/install.sh [/etc/nginx/sites-available/your-existing-https-site]"; exit 1; fi
command -v nginx >/dev/null || { echo 'Install Nginx first; no existing server will be replaced.'; exit 1; }
command -v python3 >/dev/null || { echo 'Python 3.10+ is required.'; exit 1; }
command -v systemctl >/dev/null || { echo 'This installer requires a Linux system with systemd.'; exit 1; }
command -v useradd >/dev/null || { echo 'The useradd command is required for the dedicated service account.'; exit 1; }
if [[ -f /etc/gerstep-interactive.env ]]; then
    SERVICE_PORT="$(python3 -c "from pathlib import Path; print(next((line.partition('=')[2] for line in Path('/etc/gerstep-interactive.env').read_text().splitlines() if line.startswith('GERSTEP_PORT=')), '9081'))")"
fi
[[ "$SERVICE_PORT" =~ ^[0-9]+$ ]] && (( SERVICE_PORT >= 1024 && SERVICE_PORT <= 65535 )) || { echo 'Select a port between 1024 and 65535.'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required"'
[[ -f "$SOURCE_ROOT/vps/frontend/dist/index.html" ]] || { echo 'Build the frontend before uploading: cd vps/frontend && npm ci && npm run build'; exit 1; }
[[ "$SOURCE_ROOT" != "$APP_DIR" ]] || { echo 'Run the installer from the uploaded source folder, outside /opt/gerstep-interactive.'; exit 1; }
if ! systemctl is-active --quiet gerstep-interactive; then
    python3 - "$SERVICE_PORT" <<'PY'
import socket,sys
with socket.socket() as listener:
    try: listener.bind(('127.0.0.1',int(sys.argv[1])))
    except OSError: raise SystemExit('Selected port is occupied. No service was stopped. Rerun with sudo GERSTEP_PORT=9082 bash vps/install.sh ... for a new installation.')
PY
fi
for target in /etc/nginx/snippets/gerstep-interactive.conf /etc/nginx/conf.d/gerstep-interactive-limits.conf /etc/systemd/system/gerstep-interactive.service; do
    if [[ -f "$target" ]] && ! head -n 1 "$target" | grep -q '^# Managed: Gerstep Interactive'; then
        echo "Refusing to overwrite an unrelated file: $target"; exit 1
    fi
done
id gerstep-interactive >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin gerstep-interactive
install -d -m 755 "$APP_DIR" /etc/nginx/snippets
tar -C "$SOURCE_ROOT" --exclude='node_modules' --exclude='__pycache__' --exclude='.env' --exclude='*.sqlite3*' -cf - vps gerstep_live | tar -C "$APP_DIR" -xf -
python3 -m venv "$APP_DIR/.venv" || { echo 'Install your distribution python3-venv package, then rerun.'; exit 1; }
"$APP_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -r "$APP_DIR/vps/backend/requirements.txt"
install -d -m 700 -o gerstep-interactive -g gerstep-interactive "$APP_DIR/data"
if [[ ! -e /etc/gerstep-interactive.env ]]; then
    (umask 077; "$APP_DIR/.venv/bin/python" - "$SERVICE_PORT" <<'PY' > /etc/gerstep-interactive.env
import secrets,sys
print('GERSTEP_ORIGIN=https://167.86.106.105\nGERSTEP_PORT='+sys.argv[1]+'\nGERSTEP_DB=/opt/gerstep-interactive/data/interactive.sqlite3')
for name in ('SESSION_SECRET','BRIDGE_TOKEN','ADMIN_TOKEN'): print('GERSTEP_'+name+'='+secrets.token_urlsafe(48))
print('GERSTEP_COLLECT_TIKTOK=0\nGERSTEP_TIKTOK_USERNAME=gerstep_official')
PY
    )
fi
chmod 600 /etc/gerstep-interactive.env
install -m 644 "$APP_DIR/vps/deploy/nginx-location.conf" /etc/nginx/snippets/gerstep-interactive.conf
python3 - "$SERVICE_PORT" <<'PY'
from pathlib import Path
import sys
path=Path('/etc/nginx/snippets/gerstep-interactive.conf')
path.write_text(path.read_text().replace('127.0.0.1:9081','127.0.0.1:'+sys.argv[1]))
PY
install -m 644 "$APP_DIR/vps/deploy/nginx-limits.conf" /etc/nginx/conf.d/gerstep-interactive-limits.conf
install -m 644 "$APP_DIR/vps/deploy/gerstep-interactive.service" /etc/systemd/system/gerstep-interactive.service
if [[ -n "$NGINX_SITE" ]]; then python3 "$APP_DIR/vps/deploy/attach_nginx.py" "$NGINX_SITE"; fi
nginx -t
systemctl daemon-reload
systemctl enable --now gerstep-interactive
systemctl restart gerstep-interactive
if [[ -n "$NGINX_SITE" ]]; then systemctl reload nginx; else
    echo 'Add this line inside your existing HTTPS server block, then run nginx -t and reload:'
    echo '    include /etc/nginx/snippets/gerstep-interactive.conf;'
fi
echo "Backend installed on 127.0.0.1:$SERVICE_PORT. Frontend: https://167.86.106.105/Gerstep/"
echo 'Independent credentials are in /etc/gerstep-interactive.env (root only). No tokens are printed.'
echo 'HTTPS uses your existing certificate. See vps/README.md for trusted IP certificates and renewal.'
