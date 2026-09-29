#!/bin/sh
# Install Chiral for the current user: `chiral` command + app launcher entry. Nothing needs sudo.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$ICONS"
cp "$HERE/data/org.chiral.Chiral.svg" "$ICONS/org.chiral.Chiral.svg"
# the file name matches the app id, so the dock shows this icon for the Chiral window
rm -f "$HOME/.local/share/applications/chiral.desktop"
ln -sf "$HERE/bin/chiral" "$HOME/.local/bin/chiral"

cat > "$HOME/.local/share/applications/org.chiral.Chiral.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Chiral Terminal
Comment=Terminal with floating sub-terminals, file tree, hex viewer and Claude
Exec=$HERE/bin/chiral --new-window
Icon=org.chiral.Chiral
Terminal=false
Categories=System;TerminalEmulator;Development;
StartupWMClass=chiral
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -t -f "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo "Installed: $HOME/.local/bin/chiral"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "Note: add ~/.local/bin to your PATH (e.g. in ~/.profile) to run 'chiral' from any shell." ;;
esac
echo "Open it: type 'chiral', or press Super and search for Chiral."
echo "Optional shortcut: Settings > Keyboard Shortcuts > + , command: $HERE/bin/chiral"
