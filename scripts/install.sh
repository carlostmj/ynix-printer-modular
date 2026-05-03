#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"
LAUNCHER="$BIN_DIR/ynix-printer-modular"
ALT_LAUNCHER="$BIN_DIR/thermal-label-app"
DESKTOP_FILE="$APP_DIR/ynix-printer-modular.desktop"
ICON_FILE="$PROJECT_DIR/assets/icone.png"

python -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install -e "$PROJECT_DIR"

mkdir -p "$BIN_DIR" "$APP_DIR"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec "$VENV_DIR/bin/python" -m ynix_printer_modular "\$@"
EOF
chmod +x "$LAUNCHER"
ln -sf "$LAUNCHER" "$ALT_LAUNCHER"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Ynix Printer Modular
Comment=Open PDF and image files in Ynix Printer Modular
Exec=$LAUNCHER %F
Terminal=false
Icon=$ICON_FILE
Categories=Graphics;Office;Utility;
MimeType=application/pdf;image/jpeg;image/png;image/bmp;image/webp;image/tiff;
StartupNotify=true
EOF

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" || true

for mime in application/pdf image/jpeg image/png image/bmp image/webp image/tiff; do
    xdg-mime default "$(basename "$DESKTOP_FILE")" "$mime" >/dev/null 2>&1 || true
done

echo "Ynix Printer Modular installed."
echo "Command: ynix-printer-modular"
echo "Alias: thermal-label-app"
echo "Desktop entry: $DESKTOP_FILE"
