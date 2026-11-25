"""Color themes: one palette colors the terminals and Chiral's own panels.

Each theme has: bg / fg (terminal), pane / hdr / line / dim (Chiral's panels, title bars, borders),
the 16 ANSI colors, its own matching accent, and whether it is dark or light.
The presets are well-known palettes made for long sessions (Nord, Catppuccin, Tokyo Night, ...).
"""

THEMES = {
    'chiral-dark': {
        'label': 'Chiral Dark', 'dark': True, 'accent': '#e8ae55',
        'bg': '#0c0d0f', 'fg': '#d6d3ca', 'pane': '#121316', 'hdr': '#1c1e22', 'line': '#2e3137', 'dim': '#6b6e76',
        'palette': ['#1b1d21', '#e27d6f', '#8fcf7a', '#e8ae55', '#7fa8e0', '#b79be0', '#6cc3ae', '#d8d6cf',
                    '#4a4d55', '#f0a498', '#b6e0a6', '#f3c47a', '#a8c4ec', '#cdb8ee', '#8fdcc9', '#ffffff'],
    },
    'nord': {
        'label': 'Nord', 'dark': True, 'accent': '#88c0d0',
        'bg': '#2e3440', 'fg': '#d8dee9', 'pane': '#292e39', 'hdr': '#3b4252', 'line': '#434c5e', 'dim': '#6d7a93',
        'palette': ['#3b4252', '#bf616a', '#a3be8c', '#ebcb8b', '#81a1c1', '#b48ead', '#88c0d0', '#e5e9f0',
                    '#4c566a', '#bf616a', '#a3be8c', '#ebcb8b', '#81a1c1', '#b48ead', '#8fbcbb', '#eceff4'],
    },
    'catppuccin-mocha': {
        'label': 'Catppuccin Mocha', 'dark': True, 'accent': '#cba6f7',
        'bg': '#1e1e2e', 'fg': '#cdd6f4', 'pane': '#181825', 'hdr': '#313244', 'line': '#45475a', 'dim': '#6c7086',
        'palette': ['#45475a', '#f38ba8', '#a6e3a1', '#f9e2af', '#89b4fa', '#f5c2e7', '#94e2d5', '#bac2de',
                    '#585b70', '#f38ba8', '#a6e3a1', '#f9e2af', '#89b4fa', '#f5c2e7', '#94e2d5', '#a6adc8'],
    },
    'tokyo-night': {
        'label': 'Tokyo Night', 'dark': True, 'accent': '#7aa2f7',
        'bg': '#1a1b26', 'fg': '#c0caf5', 'pane': '#16161e', 'hdr': '#24283b', 'line': '#2f3549', 'dim': '#565f89',
        'palette': ['#15161e', '#f7768e', '#9ece6a', '#e0af68', '#7aa2f7', '#bb9af7', '#7dcfff', '#a9b1d6',
                    '#414868', '#f7768e', '#9ece6a', '#e0af68', '#7aa2f7', '#bb9af7', '#7dcfff', '#c0caf5'],
    },
    'everforest': {
        'label': 'Everforest', 'dark': True, 'accent': '#a7c080',
        'bg': '#2d353b', 'fg': '#d3c6aa', 'pane': '#232a2e', 'hdr': '#343f44', 'line': '#475258', 'dim': '#859289',
        'palette': ['#343f44', '#e67e80', '#a7c080', '#dbbc7f', '#7fbbb3', '#d699b6', '#83c092', '#d3c6aa',
                    '#5c6a72', '#e67e80', '#a7c080', '#dbbc7f', '#7fbbb3', '#d699b6', '#83c092', '#fdf6e3'],
    },
    'rose-pine': {
        'label': 'Rosé Pine', 'dark': True, 'accent': '#ebbcba',
        'bg': '#191724', 'fg': '#e0def4', 'pane': '#1f1d2e', 'hdr': '#26233a', 'line': '#393552', 'dim': '#6e6a86',
        'palette': ['#26233a', '#eb6f92', '#31748f', '#f6c177', '#9ccfd8', '#c4a7e7', '#ebbcba', '#e0def4',
                    '#6e6a86', '#eb6f92', '#31748f', '#f6c177', '#9ccfd8', '#c4a7e7', '#ebbcba', '#e0def4'],
    },
    'kanagawa': {
        'label': 'Kanagawa', 'dark': True, 'accent': '#7e9cd8',
        'bg': '#1f1f28', 'fg': '#dcd7ba', 'pane': '#16161d', 'hdr': '#2a2a37', 'line': '#363646', 'dim': '#727169',
        'palette': ['#16161d', '#c34043', '#76946a', '#c0a36e', '#7e9cd8', '#957fb8', '#6a9589', '#c8c093',
                    '#727169', '#e82424', '#98bb6c', '#e6c384', '#7fb4ca', '#938aa9', '#7aa89f', '#dcd7ba'],
    },
    'gruvbox': {
        'label': 'Gruvbox Dark', 'dark': True, 'accent': '#fabd2f',
        'bg': '#1d2021', 'fg': '#ebdbb2', 'pane': '#232627', 'hdr': '#32302f', 'line': '#45403d', 'dim': '#928374',
        'palette': ['#282828', '#cc241d', '#98971a', '#d79921', '#458588', '#b16286', '#689d6a', '#a89984',
                    '#928374', '#fb4934', '#b8bb26', '#fabd2f', '#83a598', '#d3869b', '#8ec07c', '#ebdbb2'],
    },
    'solarized-dark': {
        'label': 'Solarized Dark', 'dark': True, 'accent': '#2aa198',
        'bg': '#002b36', 'fg': '#d3cbb7', 'pane': '#04313c', 'hdr': '#0a3d4a', 'line': '#1f4f5c', 'dim': '#839496',
        'palette': ['#073642', '#dc322f', '#859900', '#b58900', '#268bd2', '#d33682', '#2aa198', '#eee8d5',
                    '#586e75', '#cb4b16', '#93a1a1', '#b58900', '#839496', '#6c71c4', '#93a1a1', '#fdf6e3'],
    },
    'high-contrast': {
        'label': 'High Contrast', 'dark': True, 'accent': '#ffd24a',
        'bg': '#000000', 'fg': '#ffffff', 'pane': '#000000', 'hdr': '#1a1a1a', 'line': '#8a8a8a', 'dim': '#b0b0b0',
        'palette': ['#000000', '#ff6b6b', '#b8ff6e', '#ffd24a', '#7cc4ff', '#ff9cf2', '#6effd1', '#ffffff',
                    '#6b6b6b', '#ff9a9a', '#d4ff9e', '#ffe38a', '#aad8ff', '#ffc2f7', '#a8ffe5', '#ffffff'],
    },
    # picture-tube themes: letters fade in, moving lines leave a short ghost, scanlines (see crt.py).
    # Each is one phosphor colour; the ANSI colours are shades of it, with red kept apart for errors.
    'crt': {                                            # P1 green (the name stays 'crt' for saved settings)
        'label': 'CRT Green', 'dark': True, 'accent': '#5cff8a', 'crt': True,
        'bg': '#030904', 'fg': '#6dfa8e', 'pane': '#050d07', 'hdr': '#0b1a0f', 'line': '#17351f', 'dim': '#3d7a4d',
        'palette': ['#0c1f12', '#ff6a4d', '#5cff8a', '#d8ff6a', '#4fd6a0', '#9ef2b4', '#3fffc8', '#9cffb3',
                    '#2c5c3a', '#ff8f75', '#8dffad', '#e8ff9a', '#7ff0c2', '#c4ffd5', '#8affe0', '#e6ffec'],
    },
    'crt-amber': {                                      # P3 amber
        'label': 'CRT Amber', 'dark': True, 'accent': '#ffb000', 'crt': True,
        'bg': '#0b0700', 'fg': '#ffb43a', 'pane': '#0f0a02', 'hdr': '#1f1505', 'line': '#3d2a0c', 'dim': '#8a6224',
        'palette': ['#1f1505', '#ff5a36', '#e6c34a', '#ffcc33', '#e08a2e', '#ff9e5e', '#ffd98a', '#ffc46b',
                    '#5a3f12', '#ff8060', '#f2d56e', '#ffe066', '#f0a552', '#ffbb88', '#ffe8b0', '#fff0d6'],
    },
    'crt-white': {                                      # P4 white, slightly blue like a monochrome monitor
        'label': 'CRT White', 'dark': True, 'accent': '#d9e6ff', 'crt': True,
        'bg': '#06070a', 'fg': '#d7dde8', 'pane': '#090a0e', 'hdr': '#14161c', 'line': '#2a2e38', 'dim': '#6c7282',
        'palette': ['#14161c', '#ff7a6e', '#c8f0c8', '#f2e6b8', '#a9c1ff', '#d9c4f2', '#b8e8ef', '#c9ced8',
                    '#4a4f5c', '#ff9d94', '#e0ffe0', '#fff4cc', '#c8d7ff', '#ead9ff', '#d4f6fa', '#ffffff'],
    },
    'crt-cyan': {                                       # P7 radar blue-white
        'label': 'CRT Cyan', 'dark': True, 'accent': '#44e0ff', 'crt': True,
        'bg': '#01070b', 'fg': '#7fe6ff', 'pane': '#030b10', 'hdr': '#08171f', 'line': '#12313f', 'dim': '#3a7488',
        'palette': ['#08171f', '#ff6f7d', '#5cf2d0', '#c8f07a', '#4fa8ff', '#a89bff', '#44e0ff', '#a8eeff',
                    '#24505f', '#ff96a0', '#8af7de', '#dcf7a2', '#80c2ff', '#c4bcff', '#88ecff', '#e6faff'],
    },
    'crt-plasma': {                                     # gas-plasma orange-red, like early portable computers
        'label': 'CRT Plasma', 'dark': True, 'accent': '#ff6a1a', 'crt': True,
        'bg': '#0c0301', 'fg': '#ff7a2e', 'pane': '#100502', 'hdr': '#220b04', 'line': '#44170a', 'dim': '#8f3f1c',
        'palette': ['#220b04', '#ff3b3b', '#ffb03a', '#ffd04a', '#ff8a52', '#ff6f8a', '#ffb98a', '#ff9a5c',
                    '#5e200c', '#ff6b6b', '#ffc870', '#ffe080', '#ffaa7f', '#ff9aae', '#ffd2b0', '#ffe9d9'],
    },
    'chiral-light': {
        'label': 'Chiral Light', 'dark': False, 'accent': '#a4610c',
        'bg': '#faf8f3', 'fg': '#23211d', 'pane': '#f1ede4', 'hdr': '#e2dccd', 'line': '#cfc8b8', 'dim': '#8a8475',
        'palette': ['#23211d', '#b3372a', '#4c7a2a', '#a4610c', '#2a5fa8', '#7a3fb8', '#1f7a66', '#ddd7ca',
                    '#5e5a52', '#d0493a', '#5f9535', '#c27612', '#3a75c4', '#9150d4', '#289681', '#faf8f3'],
    },
    'catppuccin-latte': {
        'label': 'Catppuccin Latte', 'dark': False, 'accent': '#8839ef',
        'bg': '#eff1f5', 'fg': '#4c4f69', 'pane': '#e6e9ef', 'hdr': '#ccd0da', 'line': '#bcc0cc', 'dim': '#8c8fa1',
        'palette': ['#5c5f77', '#d20f39', '#40a02b', '#df8e1d', '#1e66f5', '#ea76cb', '#179299', '#acb0be',
                    '#6c6f85', '#d20f39', '#40a02b', '#df8e1d', '#1e66f5', '#ea76cb', '#179299', '#bcc0cc'],
    },
    'gruvbox-light': {
        'label': 'Gruvbox Light', 'dark': False, 'accent': '#b57614',
        'bg': '#fbf1c7', 'fg': '#3c3836', 'pane': '#f2e5bc', 'hdr': '#ebdbb2', 'line': '#d5c4a1', 'dim': '#928374',
        'palette': ['#3c3836', '#cc241d', '#98971a', '#d79921', '#458588', '#b16286', '#689d6a', '#7c6f64',
                    '#928374', '#9d0006', '#79740e', '#b57614', '#076678', '#8f3f71', '#427b58', '#282828'],
    },
    'solarized-light': {
        'label': 'Solarized Light', 'dark': False, 'accent': '#268bd2',
        'bg': '#fdf6e3', 'fg': '#586e75', 'pane': '#eee8d5', 'hdr': '#e4ddc8', 'line': '#d6cfb9', 'dim': '#93a1a1',
        'palette': ['#073642', '#dc322f', '#859900', '#b58900', '#268bd2', '#d33682', '#2aa198', '#eee8d5',
                    '#586e75', '#cb4b16', '#93a1a1', '#b58900', '#839496', '#6c71c4', '#93a1a1', '#002b36'],
    },
}

# 'theme' uses the accent that comes with the chosen theme
ACCENTS = {
    'theme': None,
    'amber': '#e8ae55',
    'teal': '#6cc3ae',
    'blue': '#7fa8e0',
    'sky': '#89b4fa',
    'sage': '#a7c080',
    'rose': '#ebbcba',
    'coral': '#e27d6f',
    'violet': '#b79be0',
    'lavender': '#b4befe',
}

ANIMATION_MS = {'normal': 120, 'fast': 60, 'off': 0}


def get(cfg):
    name = str(cfg.get('theme') or '')
    if name.startswith('forge-'):                      # themes from before the rename
        name = 'chiral-' + name[len('forge-'):]
    theme = THEMES.get(name, THEMES['chiral-dark'])
    name = cfg.get('accent', 'theme')
    if isinstance(name, str) and name.startswith('#'):
        accent = name
    else:
        accent = ACCENTS.get(name) or theme['accent']
    return theme, accent
