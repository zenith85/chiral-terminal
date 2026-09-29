#!/bin/sh
# Install Forge for the current user: `forge` command + app launcher entry. Nothing needs sudo.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$ICONS"
cp "$HERE/data/org.forge.Forge.svg" "$ICONS/org.forge.Forge.svg"
# the file name matches the app id, so the dock shows this icon for the Forge window
rm -f "$HOME/.local/share/applications/forge.desktop"
ln -sf "$HERE/bin/forge" "$HOME/.local/bin/forge"

cat > "$HOME/.local/share/applications/org.forge.Forge.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Forge
Comment=Terminal with floating sub-terminals, file tree, hex viewer and Claude
Exec=$HERE/bin/forge --new-window
Icon=org.forge.Forge
Terminal=false
Categories=System;TerminalEmulator;Development;
StartupWMClass=forge
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Installed: $HOME/.local/bin/forge"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "Note: add ~/.local/bin to your PATH (e.g. in ~/.profile) to run 'forge' from any shell." ;;
esac
echo "Open it: type 'forge', or press Super and search for Forge."
echo "Optional shortcut: Settings > Keyboard Shortcuts > + , command: $HERE/bin/forge"
