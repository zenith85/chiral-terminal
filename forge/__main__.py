import sys

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Vte', '2.91')
gi.require_version('PangoCairo', '1.0')


def main():
    args = sys.argv[1:]
    before_dashdash = args[:args.index('--')] if '--' in args else args
    from .app import USAGE, ForgeApp
    if '-h' in before_dashdash or '--help' in before_dashdash:
        print(USAGE)
        return 0
    from gi.repository import GLib
    GLib.set_prgname('forge')
    GLib.set_application_name('Forge')
    from gi.repository import Gtk
    Gtk.Window.set_default_icon_name('org.forge.Forge')
    return ForgeApp().run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())
