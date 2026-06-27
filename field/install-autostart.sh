#!/usr/bin/env bash
# Auto-mode WITH on-screen preview, for a dedicated capture rig.
#
# On power-up the Pi boots to a console, auto-logs in on the ATTACHED SCREEN,
# shows the LIVE camera, and captures -- no keyboard needed. With no monitor
# (the field) it captures headlessly all the same. Manage it by SSH-ing in.
#
#   cd ~/Documents/sauron-pi-capture
#   ./field/install-autostart.sh
#   sudo reboot          # ~20-40s later the live camera appears on screen
#
# Undo:
#   sudo raspi-config nonint do_boot_behaviour B4   # back to desktop autologin
#   then delete the 'sauron autostart' block from ~/.profile
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"

echo "Repo : $REPO"
echo "User : $RUN_USER"
chmod +x "$REPO/field/run-capture.sh"

# 1. the single-access camera can't be shared: stop the headless service if set
sudo systemctl disable --now startracker.service 2>/dev/null || true

# 2. boot to console + autologin on the screen (no desktop compositor, so the
#    camera's DRM preview can own the display)
sudo raspi-config nonint do_boot_behaviour B2

# 3. camera group + boot config present
sudo usermod -aG video "$RUN_USER" || true
if [ -d /boot/firmware ]; then BOOTCFG=/boot/firmware/startracker.conf
else BOOTCFG=/boot/startracker.conf; fi
[ -f "$BOOTCFG" ] || sudo cp "$REPO/field/startracker.conf.example" "$BOOTCFG"

# 4. launch capture on the PHYSICAL console (tty1) only -- SSH logins unaffected,
#    so you can still SSH in to manage the rig while the screen shows the camera
PROFILE="$USER_HOME/.profile"
BEGIN="# >>> sauron autostart >>>"
END="# <<< sauron autostart <<<"
touch "$PROFILE"
sed -i "/$BEGIN/,/$END/d" "$PROFILE" 2>/dev/null || true
cat >> "$PROFILE" <<EOF
$BEGIN
# Live camera + capture on the physical screen (tty1), never over SSH.
if [ "\$(tty)" = "/dev/tty1" ]; then
  while true; do
    "$REPO/field/run-capture.sh"
    echo "[sauron] capture exited -- restarting in 30s (Ctrl-C for a shell)"
    sleep 30
  done
fi
$END
EOF
chown "$RUN_USER":"$RUN_USER" "$PROFILE" 2>/dev/null || true

cat <<EOF

Done. Test it:  sudo reboot

  ~20-40s after power-up the screen auto-logs in and shows the LIVE camera while
  it captures to $REPO/data/session_*. No monitor (field) -> still captures.
  SSH in to manage it (the console screen is busy showing the camera).

  Change settings : edit $BOOTCFG (or from a laptop on the SD boot partition)
  Undo            : sudo raspi-config nonint do_boot_behaviour B4
                    then remove the 'sauron autostart' block from ~/.profile
EOF
