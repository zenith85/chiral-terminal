"""A locked shell for team sessions: it can only see one folder.

Uses bubblewrap (bwrap), the sandbox Flatpak uses. Inside:
  - the shared folder, readable and writable, at its real path;
  - system programs (/usr, /etc, ...) read-only, so git, python, nano ... work;
  - an empty /home, a private /tmp, no /run (no desktop, D-Bus or other users' sockets);
  - its own process list (the host's programs are invisible).
Everything else of the host's disk does not exist for it: `cd ..` ends at the folder.
"""
import os
import shutil


def available():
    return shutil.which('bwrap') is not None


def argv(folder, rc):
    """bwrap command running an interactive bash confined to `folder`. `rc` is bound read-only."""
    folder = os.path.realpath(folder)
    a = ['bwrap',
         '--ro-bind', '/usr', '/usr',
         '--ro-bind', '/etc', '/etc',
         '--proc', '/proc', '--dev', '/dev',
         '--tmpfs', '/tmp', '--tmpfs', '/home', '--tmpfs', '/run',
         # no --die-with-parent: VTE starts children from a helper thread, whose end would kill the shell
         # no --new-session: this pty belongs to the sandbox alone, and job control needs it
         '--unshare-pid', '--unshare-ipc']
    for name in ('bin', 'lib', 'lib64', 'lib32', 'sbin'):         # usually symlinks into /usr
        path = '/' + name
        if os.path.islink(path):
            a += ['--symlink', os.readlink(path), path]
        elif os.path.isdir(path):
            a += ['--ro-bind', path, path]
    for opt in ('/opt', '/snap', '/var/lib/snapd/snap'):
        if os.path.isdir(opt):
            a += ['--ro-bind', opt, opt]
    if os.path.isdir('/run/systemd/resolve'):                     # name lookups (DNS) keep working
        a += ['--ro-bind', '/run/systemd/resolve', '/run/systemd/resolve']
    a += ['--bind', folder, folder,
          '--ro-bind', rc, rc,
          '--chdir', folder,
          '--setenv', 'HOME', folder,
          '--setenv', 'CHIRAL_TEAM_FOLDER', folder,
          '/bin/bash', '--rcfile', rc, '-i']
    return a
