#!/usr/bin/env bash
set -euo pipefail

# install.sh - Automated installer for Raspberry Pi Security Camera
# Usage: ./install.sh <git-repo-url> [install-dir]
# Example: ./install.sh https://github.com/yourname/security-camera.git /home/pi/security-camera

REPO_URL=${1:-}
INSTALL_DIR=${2:-/home/pi/security-camera}
SERVICE_NAME=security-camera.service
SYSTEMD_PATH=/etc/systemd/system/${SERVICE_NAME}

info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
err() { echo "[ERROR] $*" >&2; }

if [[ -z "$REPO_URL" ]]; then
  err "Repository URL required as first argument. Example: https://github.com/yourname/security-camera.git"
  exit 1
fi

# detect user to run service as
if [[ -n "${SUDO_USER-}" ]]; then
  RUN_USER=${SUDO_USER}
else
  RUN_USER=$(whoami)
fi

info "Installing to: $INSTALL_DIR"
info "Repository: $REPO_URL"
info "Service will run as user: $RUN_USER"

# Update apt and install OS packages
info "Updating apt and installing OS packages (may prompt for sudo password)"
sudo apt update

# Some packages (especially optimized BLAS like libatlas-base-dev) may not be available on all releases.
# Detect available packages and install what apt knows about.
PACKAGES=(python3-venv python3-pip python3-dev build-essential libatlas-base-dev libjpeg-dev ffmpeg v4l-utils pkg-config libffi-dev)
AVAILABLE=()
MISSING=()
for pkg in "${PACKAGES[@]}"; do
  if apt-cache show "$pkg" >/dev/null 2>&1; then
    AVAILABLE+=("$pkg")
  else
    MISSING+=("$pkg")
  fi
done

if [ "${#AVAILABLE[@]}" -gt 0 ]; then
  info "Installing packages: ${AVAILABLE[*]}"
  sudo apt install -y "${AVAILABLE[@]}"
fi

if [ "${#MISSING[@]}" -gt 0 ]; then
  warn "Some packages are not available in apt: ${MISSING[*]}"
  warn "This is OK on newer distributions like Trixie. If libatlas-base-dev is missing, you can install python3-opencv via apt (sudo apt install -y python3-opencv) or omit BLAS dev packages and rely on pip wheels or system numpy."
fi

# Clone or update repo
if [[ -d "$INSTALL_DIR/.git" ]]; then
  info "Existing git repo found in $INSTALL_DIR, pulling latest"
  git -C "$INSTALL_DIR" pull --rebase || true
else
  info "Cloning repository into $INSTALL_DIR"
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# Create virtualenv and install Python dependencies
cd "$INSTALL_DIR"
if [[ ! -d venv ]]; then
  info "Creating Python virtualenv"
  python3 -m venv venv
fi

info "Activating venv and installing Python packages"
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
if [[ -f requirements.txt ]]; then
  pip install -r requirements.txt || {
    warn "pip install -r requirements.txt failed. On Pi Zero 2 W, opencv-python-headless may be unavailable from pip."
    warn "Try installing python3-opencv via apt: sudo apt install -y python3-opencv"
  }
fi

# Ensure config exists
if [[ ! -f config.json ]] && [[ -f config.example.json ]]; then
  info "Creating config.json from example (edit config.json to set webhook and device)"
  cp config.example.json config.json
  chmod 600 config.json || true
fi

# Install systemd unit (customize paths)
if [[ "$USER" == "root" ]] || [[ -n "${SUDO_USER-}" ]]; then
  SKIP_SYSTEMD=${SKIP_SYSTEMD:-0}
  if [[ "$SKIP_SYSTEMD" -eq 0 ]]; then
    info "Installing systemd unit to $SYSTEMD_PATH (requires sudo)"
    # Build ExecStart path
    PYTHON_BIN="$INSTALL_DIR/venv/bin/python"
    APP_PY="$INSTALL_DIR/app.py"

    if [[ ! -f "$PYTHON_BIN" ]]; then
      warn "Virtualenv python not found at $PYTHON_BIN, skipping systemd unit installation"
    else
      sudo bash -c "cat > $SYSTEMD_PATH <<'SERVICE'
[Unit]
Description=Raspberry Pi Security Camera
After=network.target

[Service]
User=${RUN_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON_BIN} ${APP_PY}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE"
      sudo systemctl daemon-reload
      sudo systemctl enable ${SERVICE_NAME} || true
      sudo systemctl restart ${SERVICE_NAME} || true
      info "Installed and started systemd service ${SERVICE_NAME}"
    fi
  fi
else
  warn "Not running as sudo/root - skipping systemd install. Rerun with sudo to install the service."
fi

# Fix ownership
info "Setting ownership of $INSTALL_DIR to $RUN_USER"
sudo chown -R ${RUN_USER}:${RUN_USER} "$INSTALL_DIR" || true

info "Installation complete."

cat <<EOF
Next steps:
- If the service was installed, check status: sudo systemctl status ${SERVICE_NAME}
- View logs: journalctl -u ${SERVICE_NAME} -f
- Open the web UI: http://<raspberry-pi-ip>:8080/
- Edit config.json to set camera device (/dev/video0) and Discord webhook if desired. Do not commit config.json.
EOF
