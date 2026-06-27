#!/usr/bin/env bash
# One-time installer (run on the Pi, at home, on network).
# Installs + enables a systemd service that auto-starts capture on every boot.
#
#   cd ~/sauron-pi-capture
#   ./field/install-service.sh
#
# After this, the Pi captures automatically whenever it gets power -- no screen,
# no login needed. Disable later with:  sudo systemctl disable --now startracker
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
UNIT=/etc/systemd/system/startracker.service

echo "Repo : $REPO"
echo "User : $RUN_USER"

chmod +x "$REPO/field/run-capture.sh"

# capture.py (picamera2) needs the 'video' group; default Pi user already has it.
sudo usermod -aG video "$RUN_USER" || true

# Seed config onto the boot partition (editable from any laptop) if not present.
if [ -d /boot/firmware ]; then BOOTCFG=/boot/firmware/startracker.conf
else BOOTCFG=/boot/startracker.conf; fi
if [ ! -f "$BOOTCFG" ]; then
  sudo cp "$REPO/field/startracker.conf.example" "$BOOTCFG"
  echo "Seeded config: $BOOTCFG"
else
  echo "Config already present: $BOOTCFG (left as-is)"
fi

# Write the unit (paths/user baked in).
# Make boot logs survive a power cycle, so field failures are debuggable with
# `journalctl -u startracker -b -1` after a reboot.
sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald || true

sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Sauron-1 star tracker field capture (auto-start on boot)
# NOTE: do NOT use After=multi-user.target here -- combined with
# WantedBy=multi-user.target it forms an ordering cycle and systemd silently
# drops this service at boot (it still runs manually). local-fs.target just
# guarantees the filesystems are mounted; the camera wait lives in run-capture.sh.
After=local-fs.target
StartLimitIntervalSec=120
StartLimitBurst=10

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$REPO
ExecStart=$REPO/field/run-capture.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable startracker.service

echo
echo -n "is-enabled: "; systemctl is-enabled startracker.service || true
echo "Verify there is NO ordering cycle at next boot:"
echo "  sudo reboot   # then:  journalctl -u startracker -b   (should show capture starting)"

cat <<EOF

Installed and ENABLED. Capture now starts automatically on every power-on.

  Test it right now : sudo systemctl start startracker
  Watch it live     : journalctl -u startracker -f
  Stop this run     : sudo systemctl stop startracker
  Turn off auto-boot: sudo systemctl disable --now startracker
  Change settings   : edit $BOOTCFG  (or edit it from a laptop on the SD card), then reboot

Each power-on writes a NEW timestamped folder under $REPO/data, so power
cycling never overwrites previous data.
EOF
