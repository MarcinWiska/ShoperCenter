#!/usr/bin/env bash
set -euo pipefail

# ============================================
# ShoperCenter Startup Script
# ============================================

# Colors and formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Icons (using unicode)
ICON_CHECK="✓"
ICON_CROSS="✗"
ICON_ARROW="➜"
ICON_INFO="ℹ"
ICON_WARN="⚠"
ICON_ROCKET="🚀"
ICON_DB="🗄️"
ICON_PYTHON="🐍"
ICON_CSS="🎨"
ICON_MIGRATE="📦"
ICON_USER="👤"
ICON_SERVER="🌐"

# Print functions
print_header() {
    echo ""
    echo -e "${BOLD}${CYAN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${CYAN}║${NC}  ${ICON_ROCKET} ${BOLD}${WHITE}ShoperCenter - Starting Up${NC}                          ${BOLD}${CYAN}║${NC}"
    echo -e "${BOLD}${CYAN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    local step=$1
    local total=$2
    local icon=$3
    local message=$4
    echo -e "${BOLD}${BLUE}[${step}/${total}]${NC} ${icon}  ${BOLD}${message}${NC}"
}

print_success() {
    echo -e "  ${GREEN}${ICON_CHECK}${NC} ${GREEN}$1${NC}"
}

print_info() {
    echo -e "  ${CYAN}${ICON_INFO}${NC} ${GRAY}$1${NC}"
}

print_warning() {
    echo -e "  ${YELLOW}${ICON_WARN}${NC} ${YELLOW}$1${NC}"
}

print_error() {
    echo -e "  ${RED}${ICON_CROSS}${NC} ${RED}$1${NC}"
}

print_separator() {
    echo -e "${GRAY}  ────────────────────────────────────────────────────────${NC}"
}

# Configurable defaults (override via ENV before calling)
: "${DB_NAME:=shopercenter}"
: "${DB_USER:=shopercenter}"
: "${DB_PASSWORD:=shopercenter}"
: "${DB_HOST:=}"
: "${DB_PORT:=5432}"

# Print header
print_header

print_step "1" "8" "${ICON_DB}" "Ensuring PostgreSQL is installed and running..."
if ! command -v psql >/dev/null 2>&1; then
  print_warning "PostgreSQL not found. Installing..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y >/dev/null 2>&1
    sudo apt install python3.12-venv -y >/dev/null 2>&1
    sudo apt-get install -y postgresql postgresql-contrib postgresql-client >/dev/null 2>&1
    print_success "PostgreSQL installed successfully"
  else
    print_error "apt-get not found. Please install PostgreSQL manually and re-run."
    exit 1
  fi
else
  print_success "PostgreSQL is already installed"
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
    print_info "Starting local PostgreSQL service..."
    start_pg 
    print_success "PostgreSQL service started"
    ;;
  *)
    print_info "Using remote PostgreSQL at ${DB_HOST}" ;;
esac

# Wait a moment and verify readiness (max ~10s)
print_info "Waiting for PostgreSQL to be ready..."
for i in $(seq 1 20); do
  if pg_ready; then
    print_success "PostgreSQL is ready"
    break
  fi
  sleep 0.5
done

print_separator
print_step "2" "8" "${ICON_DB}" "Creating PostgreSQL role and database..."
if ! pg_ready; then
  print_error "PostgreSQL is not running!"
  print_info "WSL tip: sudo pg_ctlcluster <ver> main start"
  exit 1
fi

if [ -n "${DB_ADMIN_USER:-}" ]; then
  print_info "Using remote admin to create role on ${DB_HOST:-local-socket}:${DB_PORT}..."
  PGPASSWORD="${DB_ADMIN_PASSWORD:-}" psql -h "${DB_HOST:-}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" -d postgres -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${DB_USER}', '${DB_PASSWORD}');
  END IF;
END
\$\$;
SQL
  # Create DB if missing (must be top-level, not inside DO)
  if ! PGPASSWORD="${DB_ADMIN_PASSWORD:-}" psql -h "${DB_HOST:-}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" 2>/dev/null | grep -q 1; then
    print_info "Creating database ${DB_NAME}..."
    PGPASSWORD="${DB_ADMIN_PASSWORD:-}" createdb -h "${DB_HOST:-}" -p "${DB_PORT}" -U "${DB_ADMIN_USER}" -O "${DB_USER}" "${DB_NAME}" >/dev/null 2>&1
    print_success "Database ${DB_NAME} created"
  else
    print_success "Database ${DB_NAME} already exists"
  fi
  print_success "Role ${DB_USER} configured"
else
  print_info "Using local postgres superuser to create role/db"
  sudo -u postgres psql -v ON_ERROR_STOP=1 >/dev/null 2>&1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${DB_USER}', '${DB_PASSWORD}');
  END IF;
END
\$\$;
SQL
  # Create DB if missing using createdb
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" 2>/dev/null | grep -q 1; then
    print_info "Creating database ${DB_NAME}..."
    sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}" >/dev/null 2>&1
    print_success "Database ${DB_NAME} created"
  else
    print_success "Database ${DB_NAME} already exists"
  fi
  print_success "Role ${DB_USER} configured"
fi

print_separator
print_step "3" "8" "${ICON_PYTHON}" "Ensuring Python venv and requirements..."
if [ ! -d .venv ]; then
  print_info "Creating Python virtual environment..."
  python3 -m venv .venv >/dev/null 2>&1
  print_success "Virtual environment created"
else
  print_success "Virtual environment exists"
fi

print_info "Activating virtual environment..."
source .venv/bin/activate
print_success "Virtual environment activated"

print_info "Upgrading pip..."
python -m pip install --upgrade pip >/dev/null 2>&1
print_success "Pip upgraded"

print_info "Installing Python dependencies..."
pip install -r requirements.txt >/dev/null 2>&1
print_success "All dependencies installed"

print_separator
print_step "4" "8" "📁" "Creating necessary directories..."
# Utwórz katalog logs jeśli nie istnieje
if [ ! -d logs ]; then
  print_info "Creating logs directory..."
  mkdir -p logs
  print_success "Logs directory created"
else
  print_success "Logs directory exists"
fi

print_separator
print_step "5" "8" "${ICON_CSS}" "Building frontend CSS (Tailwind + DaisyUI)..."

ensure_linux_node() {
  # Usuń windowsowego node/npm z PATH dla tej sesji
  if printf "%s" "$PATH" | grep -qi '/mnt/c/Program Files/nodejs'; then
    export PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -vi '/mnt/c/Program Files/nodejs' | paste -sd: -)"
  fi

  # Zainstaluj narzędzia do kompilacji natywnych modułów npm (@parcel/watcher)
  if ! dpkg -s build-essential >/dev/null 2>&1; then
    sudo apt-get update -y >/dev/null 2>&1
    sudo apt-get install -y build-essential python3 make g++ >/dev/null 2>&1
  fi

  # Zapewnij Node.js LTS jeśli brak lub jeśli pochodzi z /mnt/c
  if ! command -v node >/dev/null 2>&1 || printf "%s" "$(command -v node)" | grep -qi '^/mnt/'; then
    curl -fsSL https://deb.nodesource.com/setup_20.x 2>/dev/null | sudo -E bash - >/dev/null 2>&1
    sudo apt-get install -y nodejs >/dev/null 2>&1
  fi

  # Ustaw cache npm w $HOME, żeby nie trafiał w ścieżki windowsowe
  export npm_config_cache="$HOME/.npm"
  export npm_config_update_notifier=false
}

if [ -f package.json ]; then
  print_info "Ensuring Linux Node.js environment..."
  ensure_linux_node >/dev/null 2>&1
  
  NODE_VERSION=$(node -v 2>/dev/null || echo "unknown")
  NPM_VERSION=$(npm -v 2>/dev/null || echo "unknown")
  print_success "Node.js ${NODE_VERSION} | npm ${NPM_VERSION}"
  
  print_info "Installing npm dependencies..."
  if [ -f package-lock.json ]; then
    npm ci --no-audit --no-fund >/dev/null 2>&1
  else
    npm install --no-audit --no-fund >/dev/null 2>&1
  fi
  print_success "npm dependencies installed"
  
  print_info "Building Tailwind CSS..."
  if npm run build:css >/dev/null 2>&1; then
    print_success "CSS build completed"
  else
    print_warning "CSS build failed (continuing anyway)"
  fi
else
  print_warning "No package.json found. Skipping CSS build."
fi

print_separator
print_step "6" "8" "${ICON_MIGRATE}" "Checking and running database migrations..."
export POSTGRES_DB="${DB_NAME}"
export POSTGRES_USER="${DB_USER}"
export POSTGRES_PASSWORD="${DB_PASSWORD}"
# Avoid local 'peer' auth by default; prefer TCP to localhost unless user provided DB_HOST
MIGRATION_DB_HOST="${DB_HOST:-127.0.0.1}"
export POSTGRES_HOST="${MIGRATION_DB_HOST}"
export POSTGRES_PORT="${DB_PORT}"

# Sprawdź czy są niewykonane migracje
print_info "Checking for unapplied migrations..."
if python manage.py showmigrations --plan 2>/dev/null | grep -q '\[ \]'; then
  print_warning "Found unapplied migrations"
  print_info "Running migrations..."
  python manage.py migrate 2>&1 | while read line; do
    if [[ "$line" =~ "Applying" ]]; then
      print_info "  $line"
    fi
  done
  print_success "All migrations applied"
else
  print_success "All migrations are up to date"
fi

# Sprawdź czy są nowe zmiany w modelach wymagające migracji
print_info "Checking for model changes..."
if python manage.py makemigrations --dry-run --check 2>&1 | grep -q 'No changes detected'; then
  print_success "No new model changes detected"
else
  print_warning "Detected model changes"
  print_info "Creating new migrations..."
  python manage.py makemigrations 2>&1 | tail -3
  print_info "Running new migrations..."
  python manage.py migrate 2>&1 | grep "Applying" || true
  print_success "New migrations completed"
fi

# Optional: auto-create superuser if env provided
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  print_info "Creating custom superuser ${DJANGO_SUPERUSER_USERNAME}..."
  python manage.py createsuperuser --noinput \
    --username "$DJANGO_SUPERUSER_USERNAME" \
    ${DJANGO_SUPERUSER_EMAIL:+--email "$DJANGO_SUPERUSER_EMAIL"} >/dev/null 2>&1 || true
  print_success "Custom superuser configured"
fi

# Ensure default admin/admin superuser exists (idempotent)
print_separator
print_step "7" "8" "${ICON_USER}" "Ensuring Django superuser exists..."
SUPERUSER_OUTPUT=$(python manage.py shell <<'PY'
from django.contrib.auth import get_user_model
User = get_user_model()
username = 'admin'
password = 'admin'
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, password=password, email='')
    print('created')
else:
    print('exists')
PY
)

if [[ "$SUPERUSER_OUTPUT" == *"created"* ]]; then
  print_success "Created superuser: admin/admin"
else
  print_success "Superuser admin already exists"
fi

print_separator
print_step "8" "8" "${ICON_SERVER}" "Starting Django development server..."
echo ""
print_success "ShoperCenter is ready!"
echo -e "${GRAY}  ────────────────────────────────────────────────────────${NC}"
echo -e "  ${CYAN}${ICON_INFO}${NC} ${WHITE}Server running at: ${BOLD}${GREEN}http://0.0.0.0:8000${NC}"
echo -e "  ${CYAN}${ICON_INFO}${NC} ${WHITE}Admin login: ${BOLD}${YELLOW}admin${NC} / ${BOLD}${YELLOW}admin${NC}"
echo -e "  ${CYAN}${ICON_INFO}${NC} ${GRAY}Press Ctrl+C to stop${NC}"
echo -e "${GRAY}  ────────────────────────────────────────────────────────${NC}"
echo ""

exec python manage.py runserver 0.0.0.0:8000
