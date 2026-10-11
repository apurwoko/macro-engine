#!/usr/bin/env bash
# deploy/sudo_steps.sh
#
# SATU skrip untuk SEMUA langkah yang butuh sudo pada setup "pakai MySQL host yang sudah ada"
# (lihat deploy/VPS_UBUNTU.md § "Memakai MySQL yang sudah ada" dan docs/SETUP_LOG.md).
#
# Jalankan SEKALI, dari root proyek, sebagai root:
#   sudo bash deploy/sudo_steps.sh
#
# Idempoten: aman dijalankan ulang (tidak akan menduplikasi data atau menimpa password tanpa alasan).
# TIDAK ADA output skrip ini yang mencetak password/API key — nilai diambil dari .env/file kredensial
# lokal dan langsung dipakai, tidak di-echo.
#
# Apa yang dilakukan:
#   1. Database `macro` + user `macro`@'172.%' (password dari .env: MYSQL_PASSWORD), GRANT hanya ke macro.*
#   2. Muat skema db/init/001_schema.sql ke database `macro` (CREATE TABLE IF NOT EXISTS -> aman diulang)
#   3. Database `macro_test` + user `macro_test`@'172.%' SEKALI PAKAI untuk tes integrasi
#      (password acak disimpan di deploy/.test_db_credentials, chmod 600, di .gitignore)
#   4. bind-address MySQL: tambahkan 172.18.0.1 (gateway network docker compose `macro-engine_default`)
#      di samping 127.0.0.1 yang sudah ada, lalu restart service mysql. Nilai LAMA dicatat di
#      deploy/bind_address.rollback untuk pemulihan manual (lihat komentar di akhir skrip).
#
# TIDAK melakukan: DROP/DELETE/TRUNCATE apa pun, tidak menyentuh database lain, tidak membuka port
# ke 0.0.0.0, tidak mengubah ufw (ufw tidak terpasang di mesin ini -> dicatat, bukan diubah).

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Jalankan dengan sudo: sudo bash deploy/sudo_steps.sh" >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -f .env ]]; then
  echo ".env tidak ditemukan di $PROJECT_ROOT" >&2
  exit 1
fi

# --- muat MYSQL_DATABASE / MYSQL_USER / MYSQL_PASSWORD dari .env tanpa mencetaknya ---
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${MYSQL_DATABASE:?MYSQL_DATABASE kosong di .env}"
: "${MYSQL_USER:?MYSQL_USER kosong di .env}"
: "${MYSQL_PASSWORD:?MYSQL_PASSWORD kosong di .env}"

# .env berisi MYSQL_HOST=host.docker.internal (dipakai container, lihat KEPUTUSAN #3) dan `mysql` CLI
# membaca MYSQL_HOST/MYSQL_PORT sebagai env var resmi -> tanpa unset ini, perintah admin di bawah akan
# mencoba connect ke host.docker.internal lewat TCP alih-alih socket lokal sebagai root. Admin DB di
# skrip ini SELALU lewat socket lokal (auth_socket root), jadi env itu tidak relevan di sini.
unset MYSQL_HOST MYSQL_PORT MYSQL_TCP_PORT 2>/dev/null || true

MYSQL_HOST_PATTERN="172.%"    # cocok semua subnet docker 172.x (docker0 + network compose apa pun), lihat KEPUTUSAN #2
MYSQLD_CNF="/etc/mysql/mysql.conf.d/mysqld.cnf"
BIND_ROLLBACK_FILE="$PROJECT_ROOT/deploy/bind_address.rollback"
TEST_DB_NAME="macro_test"
TEST_DB_USER="macro_test"
TEST_CREDS_FILE="$PROJECT_ROOT/deploy/.test_db_credentials"
# "host.docker.internal:host-gateway" (extra_hosts di docker-compose.override.yml) di Docker/Linux SELALU
# resolve ke gateway bridge DEFAULT docker0 -- bukan ke gateway network compose project ini -- ditemukan
# empiris saat setup (lihat docs/SETUP_LOG.md). Karena itu bind-address MySQL dibuka ke gateway docker0,
# bukan ke gateway network `macro-engine_default`.
GATEWAY_IP="$(ip -4 addr show docker0 2>/dev/null | grep -oP 'inet \K[\d.]+' | head -1)"
if [[ -z "$GATEWAY_IP" ]]; then
  echo "Tidak bisa menemukan alamat IPv4 docker0; cek manual dengan 'ip -4 addr show docker0'" >&2
  exit 1
fi

echo "== 1/4  Database '${MYSQL_DATABASE}' + user '${MYSQL_USER}'@'${MYSQL_HOST_PATTERN}' =="
mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`${MYSQL_DATABASE}\`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'${MYSQL_HOST_PATTERN}' IDENTIFIED BY '${MYSQL_PASSWORD}';
ALTER USER '${MYSQL_USER}'@'${MYSQL_HOST_PATTERN}' IDENTIFIED BY '${MYSQL_PASSWORD}';

GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'${MYSQL_HOST_PATTERN}';
FLUSH PRIVILEGES;
SQL
echo "   OK (idempoten: aman diulang)"

echo "== 2/4  Muat skema db/init/001_schema.sql ke '${MYSQL_DATABASE}' =="
mysql -u root "${MYSQL_DATABASE}" < "$PROJECT_ROOT/db/init/001_schema.sql"
TABLE_COUNT=$(mysql -u root -N -B -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${MYSQL_DATABASE}';")
echo "   OK - ${TABLE_COUNT} tabel ada di '${MYSQL_DATABASE}' (harus 13)"

echo "== 3/4  Database '${TEST_DB_NAME}' sekali pakai untuk tes integrasi =="
if [[ -f "$TEST_CREDS_FILE" ]]; then
  echo "   kredensial tes sudah ada ($TEST_CREDS_FILE) -> dipakai ulang (idempoten)"
  # shellcheck disable=SC1090
  source "$TEST_CREDS_FILE"
else
  MACRO_TEST_DB_PASSWORD="$(openssl rand -hex 16)"
  umask 077
  cat > "$TEST_CREDS_FILE" <<EOF
# Dibuat otomatis oleh deploy/sudo_steps.sh - JANGAN commit (sudah di .gitignore).
# Dipakai HANYA untuk tes integrasi (MACRO_INTEGRATION_DB=1), database sekali pakai.
MACRO_TEST_DB_NAME=${TEST_DB_NAME}
MACRO_TEST_DB_USER=${TEST_DB_USER}
MACRO_TEST_DB_PASSWORD=${MACRO_TEST_DB_PASSWORD}
EOF
  chmod 600 "$TEST_CREDS_FILE"
  chown "${SUDO_USER:-$USER}":"${SUDO_USER:-$USER}" "$TEST_CREDS_FILE" 2>/dev/null || true
  echo "   kredensial baru ditulis ke $TEST_CREDS_FILE (chmod 600, tidak dicetak)"
fi
mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`${TEST_DB_NAME}\`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS '${TEST_DB_USER}'@'${MYSQL_HOST_PATTERN}' IDENTIFIED BY '${MACRO_TEST_DB_PASSWORD}';
ALTER USER '${TEST_DB_USER}'@'${MYSQL_HOST_PATTERN}' IDENTIFIED BY '${MACRO_TEST_DB_PASSWORD}';

GRANT ALL PRIVILEGES ON \`${TEST_DB_NAME}\`.* TO '${TEST_DB_USER}'@'${MYSQL_HOST_PATTERN}';
FLUSH PRIVILEGES;
SQL
# Test runner (tests/test_integration_db.py) mengasumsikan tabel SUDAH ADA (kosong) -- ia tidak
# membuat skema sendiri, hanya mengisi/membaca. Muat skema yang sama dengan database produksi.
mysql -u root "${TEST_DB_NAME}" < "$PROJECT_ROOT/db/init/001_schema.sql"
echo "   OK (idempoten: aman diulang; skema db/init/001_schema.sql dimuat ke '${TEST_DB_NAME}')"

echo "== 4/4  bind-address MySQL: pastikan 127.0.0.1 + ${GATEWAY_IP} (gateway docker0) =="
CURRENT_BIND="$(grep -E '^\s*bind-address' "$MYSQLD_CNF" | head -1 | sed -E 's/^\s*bind-address\s*=\s*//')"
DESIRED_BIND="127.0.0.1,${GATEWAY_IP}"
if [[ "$CURRENT_BIND" == "$DESIRED_BIND" ]]; then
  echo "   bind-address sudah '${DESIRED_BIND}' -> tidak diubah"
else
  if [[ ! -f "$BIND_ROLLBACK_FILE" ]]; then
    echo "bind-address lama (sebelum skrip ini): ${CURRENT_BIND}" > "$BIND_ROLLBACK_FILE"
    echo "   nilai lama '${CURRENT_BIND}' dicatat ke $BIND_ROLLBACK_FILE"
  else
    echo "   $BIND_ROLLBACK_FILE sudah ada -> tidak ditimpa (nilai lama asli tetap tersimpan)"
  fi
  cp "$MYSQLD_CNF" "${MYSQLD_CNF}.bak.$(date +%Y%m%d%H%M%S)"
  sed -i -E "s/^(\s*bind-address\s*=\s*).*/\1${DESIRED_BIND}/" "$MYSQLD_CNF"
  echo "   bind-address -> ${DESIRED_BIND} (cadangan file lama disimpan di ${MYSQLD_CNF}.bak.*)"
  systemctl restart mysql
  sleep 2
  systemctl is-active --quiet mysql && echo "   mysql restart OK, service aktif" || { echo "   GAGAL: mysql tidak aktif setelah restart" >&2; exit 1; }
fi

echo
echo "SELESAI. Verifikasi dari luar skrip ini (tanpa sudo):"
echo "  mysql -h 127.0.0.1 -u root -e \"SELECT user,host FROM mysql.user WHERE user IN ('${MYSQL_USER}','${TEST_DB_USER}');\""
echo "  docker compose run --rm api python -c \"from app import db; print(db.scalar('SELECT @@session.time_zone'))\""

# ---------------------------------------------------------------------------
# ROLLBACK MANUAL (bila perlu mengembalikan bind-address ke kondisi semula):
#   1. Baca nilai lama:      cat deploy/bind_address.rollback
#   2. Edit kembali:         sudo sed -i -E 's/^(\s*bind-address\s*=\s*).*/\1<NILAI_LAMA>/' /etc/mysql/mysql.conf.d/mysqld.cnf
#      (atau pulihkan dari cadangan: sudo cp /etc/mysql/mysql.conf.d/mysqld.cnf.bak.<timestamp> /etc/mysql/mysql.conf.d/mysqld.cnf)
#   3. Restart:              sudo systemctl restart mysql
#
# Untuk mencabut akses (tidak dijalankan otomatis -- lakukan manual bila perlu):
#   sudo mysql -u root -e "DROP USER IF EXISTS 'macro_test'@'172.%'; DROP DATABASE IF EXISTS macro_test;"
# ---------------------------------------------------------------------------
