#!/usr/bin/env bash
set -euo pipefail

# Configurable defaults (override via ENV before calling)
: "${DB_NAME:=shopercenter}"
: "${DB_USER:=shopercenter}"
: "${DB_PASSWORD:=shopercenter}"
: "${DB_HOST:=}"
: "${DB_PORT:=5432}"

echo "[1/6] Ensuring PostgreSQL is installed and running..."
if ! command -v psql >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt install python3.12-venv -y
    sudo apt-get install -y postgresql postgresql-contrib postgresql-client
  else
    echo "apt-get not found. Please install PostgreSQL manually and re-run."
    exit 1
  fi
fi

start_pg() {
  # Try systemd
  if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl enable postgresql 2>/dev/null || true
    sudo systemctl start postgresql 2>/dev/null || true
  fi
  # Try SysV/service
  if command -v service >/dev/null 2>&1; then
    sudo service postgresql start 2>/dev/null || true
  fi
  # Try pg_ctlcluster (Debian/Ubuntu without systemd, e.g., WSL/containers)
  if command -v pg_ctlcluster >/dev/null 2>&1; then
    ver="$(ls /etc/postgresql 2>/dev/null | sort -Vr | head -n1)"
    if [ -n "$ver" ]; then
      sudo pg_ctlcluster "$ver" main start 2>/dev/null || {
        # Create cluster if missing
        sudo pg_createcluster "$ver" main 2>/dev/null || true
        sudo pg_ctlcluster "$ver" main start 2>/dev/null || true
      }
    fi
  fi
}

pg_ready() {
  if command -v pg_isready >/dev/null 2>&1; then
    if [ -n "${DB_HOST}" ]; then
      pg_isready -q -h "${DB_HOST}" -p "${DB_PORT}" && return 0
    else
      pg_isready -q && return 0
    fi
  fi
  # Fallback check for local socket
  [ -S "/var/run/postgresql/.s.PGSQL.${DB_PORT}" ] && return 0
  return 1
}

# Only start local PostgreSQL when targeting local host/socket
case "${DB_HOST:-}" in
  ""|"localhost"|"127.0.0.1")
    start_pg ;;
  *)
    echo "Skipping local PostgreSQL start (DB_HOST=${DB_HOST})." ;;
esac

# Wait a moment and verify readiness (max ~10s)
for i in $(seq 1 20); do
  if pg_ready; then
    break
  fi
  sleep 0.5
done

echo "[2/6] Creating PostgreSQL role and database if missing..."
if ! pg_ready; then
  echo "PostgreSQL is not running. Please start it manually (WSL tip: 'sudo pg_ctlcluster <ver> main start') and re-run."
  exit 1
fi

if [ -n "${DB_ADMIN_USER:-}" ]; then
  echo "Using remote admin to create role on ${DB_HOST:-local-socket}:${DB_PORT}..."
  PGPASSWORD="${DB_ADMIN_PASSWORD:-}" psql -h "${DB_HOST:-}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" -d postgres -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${DB_USER}', '${DB_PASSWORD}');
  END IF;
END
\$\$;
SQL
  # Create DB if missing (must be top-level, not inside DO)
  if ! PGPASSWORD="${DB_ADMIN_PASSWORD:-}" psql -h "${DB_HOST:-}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
    echo "Creating database ${DB_NAME} owned by ${DB_USER}..."
    PGPASSWORD="${DB_ADMIN_PASSWORD:-}" createdb -h "${DB_HOST:-}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" -O "${DB_USER}" "${DB_NAME}"
  else
    echo "Database ${DB_NAME} already exists."
  fi
else
  echo "Using local postgres superuser to create role/db (unix socket)."
  sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${DB_USER}', '${DB_PASSWORD}');
  END IF;
END
\$\$;
SQL
  # Create DB if missing using createdb
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
    echo "Creating database ${DB_NAME} owned by ${DB_USER}..."
    sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
  else
    echo "Database ${DB_NAME} already exists."
  fi
fi

echo "[3/6] Ensuring Python venv and requirements..."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "[4/6] Building frontend CSS (Tailwind + DaisyUI)..."

ensure_linux_node() {
  # Usuń windowsowego node/npm z PATH dla tej sesji
  if printf "%s" "$PATH" | grep -qi '/mnt/c/Program Files/nodejs'; then
    export PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -vi '/mnt/c/Program Files/nodejs' | paste -sd: -)"
  fi

  # Zainstaluj narzędzia do kompilacji natywnych modułów npm (@parcel/watcher)
  if ! dpkg -s build-essential >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y build-essential python3 make g++
  fi

  # Zapewnij Node.js LTS jeśli brak lub jeśli pochodzi z /mnt/c
  if ! command -v node >/dev/null 2>&1 || printf "%s" "$(command -v node)" | grep -qi '^/mnt/'; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
  fi

  # Ustaw cache npm w $HOME, żeby nie trafiał w ścieżki windowsowe
  export npm_config_cache="$HOME/.npm"
  export npm_config_update_notifier=false
}

if [ -f package.json ]; then
  ensure_linux_node
  echo "Using node: $(command -v node) | $(node -v)"
  echo "Using npm : $(command -v npm)  | $(npm -v)"
  if [ -f package-lock.json ]; then
    npm ci --no-audit --no-fund
  else
    npm install --no-audit --no-fund
  fi
  # Jeśli masz w package.json skrypt "build:css"
  npm run build:css || echo "Tailwind build failed; continuing (dev only)."
else
  echo "No package.json found. Skipping CSS build."
fi


echo "[5/6] Running migrations..."
export POSTGRES_DB="${DB_NAME}"
export POSTGRES_USER="${DB_USER}"
export POSTGRES_PASSWORD="${DB_PASSWORD}"
# Avoid local 'peer' auth by default; prefer TCP to localhost unless user provided DB_HOST
MIGRATION_DB_HOST="${DB_HOST:-127.0.0.1}"
export POSTGRES_HOST="${MIGRATION_DB_HOST}"
export POSTGRES_PORT="${DB_PORT}"

python manage.py migrate

# Optional: auto-create superuser if env provided
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  echo "Creating Django superuser ${DJANGO_SUPERUSER_USERNAME} if missing..."
  python manage.py createsuperuser --noinput \
    --username "$DJANGO_SUPERUSER_USERNAME" \
    ${DJANGO_SUPERUSER_EMAIL:+--email "$DJANGO_SUPERUSER_EMAIL"} || true
fi

# Ensure default admin/admin superuser exists (idempotent)
echo "[5b/6] Ensuring Django superuser admin/admin exists..."
python manage.py shell <<'PY'
from django.contrib.auth import get_user_model
User = get_user_model()
username = 'admin'
password = 'admin'
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, password=password, email='')
    print('Created superuser admin/admin')
else:
    print('Superuser admin already exists')
PY

echo "[6/6] Starting Django on 0.0.0.0:8000"
exec python manage.py runserver 0.0.0.0:8000
