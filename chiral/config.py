"""Settings: ~/.config/chiral/chiral.toml (a small TOML subset, no dependencies)."""
import copy
import os
import re

CONFIG_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'chiral')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'chiral.toml')

DEFAULTS = {
    'theme': 'chiral-dark',
    'accent': 'theme',
    'animations': 'normal',
    'background': 'strands',
    'editor': '',
    'awareness': True,
    'popout': ['nano', 'vim', 'vi', 'nvim', 'less', 'man', 'htop', 'top'],
    'font': {
        'family': 'Monospace',
        'size': 12,
        'auto': True,
        'auto_min': 7,
        'auto_max': 16,
        'auto_columns': 80,
        'line_height': 1.0,
        'main_auto': True,
        'unfocused_drop': 3,
    },
    'tree': {'hover': True, 'show_hidden': False, 'preview': True},
    'claude': {'command': 'claude', 'codex_command': 'codex', 'default_agent': 'claude', 'watch': 'auto',
               'local_model': ''},
    'keys': {'shift_arrows': 'smart', 'ctrl_arrows': 'smart'},
    'sharing': {'name': '', 'port': 47800, 'allow_input': True, 'peers': [], 'mode': 'folder'},
}

DEFAULT_FILE = '''# Chiral settings. Save the file and changes apply immediately.

theme = "chiral-dark"        # chiral-dark, nord, catppuccin-mocha, tokyo-night, everforest, rose-pine, kanagawa, gruvbox,
                            # solarized-dark, high-contrast, chiral-light, catppuccin-latte, gruvbox-light, solarized-light
accent = "theme"            # theme (the theme's own), amber, teal, blue, sky, sage, rose, coral, violet, lavender, or "#rrggbb"
animations = "normal"       # normal (120 ms), fast (60 ms), off
background = "strands"      # strands: faint moving strands behind the text; off: plain
editor = ""                 # empty: $EDITOR, then nano
awareness = true            # top bar showing git, H (binary files), py/node/docker/make of the current folder
popout = ["nano", "vim", "vi", "nvim", "less", "man", "htop", "top"]   # open in a sub-terminal when typed in the main shell

[font]
family = "Monospace"
size = 12                   # main terminal, in points
auto = true                 # sub-terminals choose their size from their width
auto_min = 7
auto_max = 16
auto_columns = 80           # aim for this many columns
line_height = 1.0
main_auto = true            # main terminal shrinks its font when the side panels squeeze it
unfocused_drop = 3          # with Shift+→ columns: unfocused ones are this many points smaller

[tree]
hover = true                # show the tree when the mouse touches the left edge
show_hidden = false
preview = true              # moving through the tree shows the selected item in a floating window

[claude]
command = "claude"
codex_command = "codex"
default_agent = "claude"   # what Shift+↑ → "AI agent" opens: claude or codex
watch = "auto"              # auto: explain failed commands, notify: only show them, off

[keys]
shift_arrows = "smart"      # smart: nano, vim etc. keep Shift+arrows; always: Chiral always takes them
ctrl_arrows = "smart"       # Ctrl+←/→ move focus: tree, main, sub-terminals, Claude. smart: nano etc. keep them; off
'''


def _strip_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch == '#':
            return line[:i]
    return line


def _split_list(inner):
    parts, cur, quote = [], '', None
    for ch in inner:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
            cur += ch
        elif ch == ',':
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    parts.append(cur)
    return [p for p in parts if p.strip()]


def _value(raw):
    s = raw.strip()
    if s.startswith('['):
        return [_value(p) for p in _split_list(s[1:s.rindex(']')])]
    if s[:1] in '"\'':
        return s[1:s.index(s[0], 1)]
    if s in ('true', 'false'):
        return s == 'true'
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            pass
    raise ValueError('cannot read value: %s' % s)


def parse(text):
    data, errors = {}, []
    section = data
    for n, line in enumerate(text.splitlines(), 1):
        line = _strip_comment(line).strip()
        if not line:
            continue
        m = re.match(r'^\[([A-Za-z0-9_.-]+)\]$', line)
        if m:
            section = data.setdefault(m.group(1), {})
            continue
        if '=' not in line:
            errors.append('line %d: expected key = value' % n)
            continue
        key, raw = line.split('=', 1)
        try:
            value = _value(raw)
        except (ValueError, IndexError) as e:
            errors.append('line %d: %s' % (n, e))
            continue
        target = section
        parts = key.strip().split('.')
        for p in parts[:-1]:
            target = target.setdefault(p, {})
        target[parts[-1]] = value
    return data, errors


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


OLD_CONFIG_PATH = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'),
                               'forge', 'forge.toml')


def load():
    cfg = copy.deepcopy(DEFAULTS)
    if not os.path.exists(CONFIG_PATH) and os.path.exists(OLD_CONFIG_PATH):
        os.makedirs(CONFIG_DIR, exist_ok=True)       # carry settings over from before the rename
        with open(OLD_CONFIG_PATH) as src, open(CONFIG_PATH, 'w') as dst:
            dst.write(src.read())
    if not os.path.exists(CONFIG_PATH):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, 'w') as f:
            f.write(DEFAULT_FILE)
    try:
        with open(CONFIG_PATH) as f:
            data, errors = parse(f.read())
    except OSError as e:
        return cfg, [str(e)]
    _merge(cfg, data)
    return cfg, errors


def set_top_level_raw(key, raw):
    """Persist a top-level setting whose value is written as-is (true/false, numbers)."""
    try:
        with open(CONFIG_PATH) as f:
            text = f.read()
    except OSError:
        text = DEFAULT_FILE
    pattern = re.compile(r'^%s\s*=\s*\S+' % re.escape(key), re.M)
    line = '%s = %s' % (key, raw)
    text = pattern.sub(line, text, count=1) if pattern.search(text) else line + '\n' + text
    with open(CONFIG_PATH, 'w') as f:
        f.write(text)


def set_top_level(key, value):
    """Persist a top-level string setting (theme, accent, animations) in place."""
    try:
        with open(CONFIG_PATH) as f:
            text = f.read()
    except OSError:
        text = DEFAULT_FILE
    line = '%s = "%s"' % (key, value)
    pattern = re.compile(r'^%s\s*=\s*"[^"]*"' % re.escape(key), re.M)
    if pattern.search(text):
        text = pattern.sub(line, text, count=1)
    else:
        text = line + '\n' + text
    with open(CONFIG_PATH, 'w') as f:
        f.write(text)


# ---- writing the whole file (used by the settings window) ----
LAYOUT = [
    (None, [('theme', 'the colour theme'), ('accent', 'theme = the theme\'s own accent, a name, or "#rrggbb"'),
            ('animations', 'normal (120 ms), fast (60 ms), off'),
            ('background', 'strands: faint moving strands behind the text; off: plain'),
            ('awareness', 'top bar: git, H (binary files), py/node/docker/make of the current folder'),
            ('editor', 'empty: $EDITOR, then nano'),
            ('popout', 'open in a sub-terminal when typed in the main shell')]),
    ('font', [('family', ''), ('size', 'main terminal, in points'),
              ('auto', 'sub-terminals choose their size from their width'), ('auto_min', ''), ('auto_max', ''),
              ('auto_columns', 'aim for this many columns'), ('line_height', ''),
              ('main_auto', 'main terminal shrinks its font when a side panel squeezes it'),
              ('unfocused_drop', 'with Shift+→ columns: unfocused ones are this many points smaller')]),
    ('tree', [('hover', 'show the tree when the mouse touches the left edge'), ('show_hidden', ''),
              ('preview', 'moving through the tree shows the selected item in a floating window')]),
    ('claude', [('command', 'Claude Code command'), ('codex_command', 'Codex command'),
                ('default_agent', 'what Shift+↑ → "AI agent" opens: claude, codex or local'),
                ('local_model', 'the Ollama model Local AI runs (chosen when you set it up)'),
                ('watch', 'auto: explain failed commands, notify: only show them, off')]),
    ('sharing', [('name', 'how others see you; empty: user@computer'),
                 ('port', 'the port N listens on (same for everyone in the team)'),
                 ('mode', 'folder: a locked team terminal that sees only the shared folder; full: your own terminals'),
                 ('allow_input', 'people watching you may type into your terminal'),
                 ('peers', 'who may join you and whom NC lists: "Name=IP"')]),
    ('keys', [('shift_arrows', 'smart: nano, vim etc. keep Shift+arrows; always: Chiral always takes them'),
              ('ctrl_arrows', 'Ctrl+←/→ move focus. smart: nano etc. keep them; off')]),
]


def _fmt(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(_fmt(x) for x in v) + ']'
    return '"%s"' % str(v).replace('\\', '\\\\').replace('"', '\\"')


def render(cfg):
    out = ['# Chiral settings. Change them in the settings window (Shift+↑ → settings) or here; saving applies them.', '']
    for section, keys in LAYOUT:
        values = cfg if section is None else cfg.get(section, {})
        if section is not None:
            out += ['', '[%s]' % section]
        for key, comment in keys:
            if key not in values:
                continue
            line = '%s = %s' % (key, _fmt(values[key]))
            if comment:
                line = line.ljust(28) + '# ' + comment
            out.append(line)
    return '\n'.join(out) + '\n'


def save(cfg):
    text = render(cfg)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + '.tmp'
    with open(tmp, 'w') as f:
        f.write(text)
    os.replace(tmp, CONFIG_PATH)
    return text
