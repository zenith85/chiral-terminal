"""Which AI agents are installed, logged in and how much of their usage limit is left.

Nothing here talks to a remote service. Usage is read from the files the tools keep themselves:
  Claude Code  ~/.claude/dem-rate-limits.json            (5-hour and 7-day used %, reset times)
  Codex        ~/.codex/sessions/**/rollout-*.jsonl      (the last "rate_limits" it recorded)
  Ollama       http://localhost:11434/api/tags           (local: no limit; which models exist)
Tools are looked up through an interactive bash, so ones installed with nvm are found too.
"""
import glob
import json
import os
import subprocess
import time
import urllib.request

HOME = os.path.expanduser('~')
OLLAMA_URL = 'http://127.0.0.1:11434'

SPECS = {
    'claude': {
        'label': 'Claude', 'tool': 'claude',
        'install': 'npm install -g @anthropic-ai/claude-code',
        'login': 'claude',                    # its first run walks you through signing in
        'login_note': 'Claude Code opens and walks you through signing in.',
    },
    'codex': {
        'label': 'Codex', 'tool': 'codex',
        'install': 'npm install -g @openai/codex',
        'login': 'codex login',
        'login_note': 'Codex opens its sign-in page.',
    },
    'local': {
        'label': 'Local', 'tool': 'ollama',
        'install': 'curl -fsSL https://ollama.com/install.sh | sh',
        'login': None,                        # no account: start the server and download a model instead
        'login_note': 'Starts the Ollama server and downloads a model to run on this computer.',
    },
}

LOCAL_MODELS = [
    ('llama3.2:3b', 'Llama 3.2 3B · 2 GB · fast, general'),
    ('qwen2.5-coder:7b', 'Qwen 2.5 Coder 7B · 4.7 GB · code'),
    ('gemma3:4b', 'Gemma 3 4B · 3.3 GB · general'),
    ('deepseek-r1:7b', 'DeepSeek R1 7B · 4.7 GB · reasoning'),
]


def find_tools():
    """{tool: path or None}, using the user's interactive shell (nvm, ~/.local/bin, ...)."""
    tools = [s['tool'] for s in SPECS.values()]
    script = '; '.join('printf "%s=%%s\\n" "$(command -v %s)"' % (t, t) for t in tools)
    try:
        out = subprocess.run(['/bin/bash', '-ic', script], capture_output=True, text=True, timeout=8,
                             stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        out = ''
    found = {t: None for t in tools}
    for line in out.splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            if k in found and v.strip():
                found[k] = v.strip()
    return found


def _claude_logged_in():
    if os.environ.get('ANTHROPIC_API_KEY') or os.path.exists(os.path.join(HOME, '.claude', '.credentials.json')):
        return True
    try:
        with open(os.path.join(HOME, '.claude.json')) as f:
            return bool(json.load(f).get('oauthAccount'))
    except (OSError, ValueError):
        return False


def _codex_logged_in():
    if os.environ.get('OPENAI_API_KEY'):
        return True
    try:
        with open(os.path.join(HOME, '.codex', 'auth.json')) as f:
            d = json.load(f)
        return bool(d.get('tokens') or d.get('OPENAI_API_KEY'))
    except (OSError, ValueError):
        return False


def _window(used, resets_at, minutes=None):
    left = max(0.0, 100.0 - float(used))
    if resets_at:
        t = resets_at / 1000 if resets_at > 1e11 else resets_at
        if t < time.time():                  # the window has reset since the tool last recorded it
            return {'left': 100.0, 'resets_at': None, 'minutes': minutes, 'stale': True}
    return {'left': left, 'resets_at': resets_at, 'minutes': minutes}


def _claude_usage():
    try:
        with open(os.path.join(HOME, '.claude', 'dem-rate-limits.json')) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    rl = d.get('rate_limits') or {}
    out = {'captured': (d.get('capturedAt') or 0) / (1000 if (d.get('capturedAt') or 0) > 1e11 else 1)}
    if 'five_hour' in rl:
        out['short'] = _window(rl['five_hour'].get('used_percentage', 0), rl['five_hour'].get('resets_at'), 300)
    if 'seven_day' in rl:
        out['long'] = _window(rl['seven_day'].get('used_percentage', 0), rl['seven_day'].get('resets_at'), 10080)
    return out if len(out) > 1 else None


def _codex_usage():
    files = glob.glob(os.path.join(HOME, '.codex', 'sessions', '**', 'rollout-*.jsonl'), recursive=True)
    for path in sorted(files, key=os.path.getmtime, reverse=True)[:5]:
        try:
            with open(path, 'rb') as f:
                f.seek(max(0, os.path.getsize(path) - 400000))
                tail = f.read().decode('utf-8', 'ignore')
        except OSError:
            continue
        for line in reversed(tail.splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            rl = _find_key(d, 'rate_limits')
            if not rl:
                continue
            out = {'captured': os.path.getmtime(path)}
            for key, name in (('primary', 'short'), ('secondary', 'long')):
                w = rl.get(key)
                if isinstance(w, dict) and 'used_percent' in w:
                    out[name] = _window(w['used_percent'], w.get('resets_at'), w.get('window_minutes'))
            if len(out) > 1:
                return out
    return None


def _find_key(obj, key):
    if isinstance(obj, dict):
        if isinstance(obj.get(key), dict):
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r:
                return r
    return None


def ollama_models():
    """Names of downloaded models, or None when the server is not running."""
    try:
        with urllib.request.urlopen(OLLAMA_URL + '/api/tags', timeout=1.5) as r:
            return [m.get('name') for m in json.load(r).get('models', [])]
    except (OSError, ValueError):
        return None


def status(tools, local_model=''):
    """Everything the top bar shows, for each agent. `tools` comes from find_tools()."""
    out = {}
    # Claude
    s = {'installed': bool(tools.get('claude'))}
    s['ready'] = s['installed'] and _claude_logged_in()
    s['usage'] = _claude_usage() if s['ready'] else None
    out['claude'] = s
    # Codex
    s = {'installed': bool(tools.get('codex'))}
    s['ready'] = s['installed'] and _codex_logged_in()
    s['usage'] = _codex_usage() if s['ready'] else None
    out['codex'] = s
    # Local (Ollama)
    s = {'installed': bool(tools.get('ollama'))}
    models = ollama_models() if s['installed'] else None
    s['server'] = models is not None
    s['models'] = models or []
    s['model'] = local_model if local_model in s['models'] else (s['models'][0] if s['models'] else '')
    s['ready'] = s['installed'] and s['server'] and bool(s['models'])
    s['usage'] = {'unlimited': True} if s['ready'] else None
    out['local'] = s
    return out


def describe_window(w, name):
    text = '%s: %d%% left' % (name, round(w['left']))
    if w.get('stale'):
        return text + ' (reset since last use)'
    if w.get('resets_at'):
        t = w['resets_at']
        t = t / 1000 if t > 1e11 else t
        fmt = '%H:%M' if t - time.time() < 86400 else '%a %H:%M'
        text += ', resets %s' % time.strftime(fmt, time.localtime(t))
    return text
