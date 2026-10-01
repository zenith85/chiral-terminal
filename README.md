# Chiral Terminal

A plain terminal with four hidden edges. By default it's just your shell, full screen.

| Key | What appears |
|---|---|
| **Shift+↑** | command bar: commands, `@file`, `#ask the AI agent`, `1`–`9` window, or any shell command |
| **Shift+←** | closes a terminal column: the focused one, otherwise the rightmost (the main terminal is never closed) |
| **Ctrl+Shift+F** (or mouse at the left edge) | file tree: enter open · `x` hex · `o` Nautilus · `t` shell here |
| **Shift+↓** (or mouse at the bottom edge) | window bar: every sub-terminal, `1`–`9` jump, `t` tile, `h` hide all |
| **Shift+→** | a new terminal column on the right, in the folder you are in; every press adds another. Columns share the width; the focused one has the bigger font. `exit` or **Ctrl+Shift+W** closes a column |

- Sub-terminals and AI agent windows **float above everything**: the file tree, the main terminal and all
  columns.
- **Ctrl+Shift+T** opens a sub-terminal: a small terminal window inside the main one. Drag its title to
  move it, drag its corner to resize it, double-click the title to fill the screen. Its font follows its
  width (aiming for 80 columns); **Ctrl + / − / 0** pins or resets it. **Ctrl+Shift+W** closes it.
- Typing `nano`, `vim`, `less`, `man`, `htop`… in the **main** terminal opens it in a sub-terminal and
  gives the prompt straight back. `$EDITOR` waits for its window, so `git commit` works. Use
  `command nano file` to run it in place. In a sub-terminal, programs run where you type them.
- **Smart Shift+arrows:** while nano/vim/etc. run in the focused terminal, Shift+arrows go to them (text
  selection). **Ctrl+Shift+arrows** always reach Chiral.
- **Images** (png, jpg, gif, svg, webp, …) open in a window with two tabs: **image** (the picture, fitted,
  with its size and format) and **hex**. Click the tabs in the title bar or press **Ctrl+Tab**.
- **Videos and audio** (mp4, mkv, webm, mov, avi, mp3, wav, ogg, flac, …) play inside a window with two
  tabs: **video** / **audio** (a player: play/pause, seek bar, time, mute) and **hex**. In the player:
  **Space** play/pause, **← / →** 5 s back/forward, **m** mute. The tree's preview shows the first frame,
  paused and silent. Uses GStreamer (installed on Ubuntu desktops).
- Binary files open in the hex viewer (`g` go to offset, `/` find bytes or `"text"`, `n` next, `q` quit).
- **AI agents:** Shift+↑ → `AI agent` (or `AI agent: claude` / `AI agent: codex`) opens the agent, already
  running, in a floating window in the folder you are in (`default_agent` under `[claude]` picks which).
  Agents start through bash, so tools installed with nvm are found. It watches your terminals: Chiral logs each finished command (and the output of failed ones) to a context
  file the agent reads. With `claude.watch = "auto"` a failed command is explained automatically by the
  agent you used last (never while you type in it). `#question` in the command bar or **Ctrl+Shift+E**
  go to that agent. Open as many agents as you like.
- **Ctrl+←/→** moves focus: file tree → main terminal → floating windows → columns. The focused
  terminal's border lights up in the accent color; others have a gray border.
- **Ctrl+Shift+C / V** copy / paste.

## Team sessions

In **Settings → Team**, add the people who may join you (name + IP address) and tell them your address.
- **N** (top bar) turns sharing on for the folder you are in (e.g. `cd ~/work`, then N). Your team gets a
  **locked team terminal** there (a violet column): it sees only that folder and its sub-folders, never
  your home, keys, history or other programs (a bubblewrap sandbox with a clean environment; system
  tools are read-only). Your own terminals are not shared. `N · 2` shows how many are watching.
  Settings → Team → "What your team can reach" → "My own terminals" shares your real terminals instead
  (trusted people only).
- **NC** lists everyone on your list: ● sharing (with their terminals) or ○ not. Click a terminal to
  open it in a floating window: live, in colour, and what you type goes to them.
- **Buzz:** in a teammate's terminal window, click the bell in its title bar (or **Ctrl+Shift+B**): their
  Chiral shakes, the borders flash, the bell rings, and they get a notification if Chiral is not in front.
  At most one buzz per person every 2 seconds.
- Both sides must have each other on their lists. The traffic is **not encrypted**: use a trusted
  network or Tailscale. A firewall may need the port (default 47800) opened for your teammates.

## Command line

```
chiral .                  open here (reuses the running window)
chiral notes.txt          open a file in a sub-terminal ($EDITOR, binaries in hex)
chiral -f "make watch"    run a command in a new sub-terminal
chiral -x fw.bin          hex viewer
chiral open [PATH]        show in Nautilus
chiral settings           edit settings
```

## Settings

Shift+↑ → `settings` (or `settings: appearance`, `settings: font`, …, or `chiral settings`) opens the settings window: theme cards with
live previews, accent colours, strands and animations, fonts and auto-sizing, tree and top-bar options,
AI agents and key behaviour. Every change applies at once and is saved to `~/.config/chiral/chiral.toml`
(still editable by hand: "Open settings file").

Themes: Chiral Dark, Nord, Catppuccin Mocha, Tokyo Night, Everforest, Rosé Pine, Kanagawa, Gruvbox Dark,
Solarized Dark, High Contrast, and light: Chiral Light, Catppuccin Latte, Gruvbox Light, Solarized Light.
Each brings its own accent (accent "theme"), or pick one.

## Install

```
./install.sh
```

Needs Python 3.8+, GTK 3 and VTE 2.91 (`gir1.2-vte-2.91`, preinstalled on Ubuntu desktops) and, for
the Claude panel, the `claude` CLI.
