"""Video and audio files in a floating window: a "video" tab (a player) and a "hex" tab.

Plays with GStreamer (playbin + gtksink) inside the window. Controls: play/pause, a seek bar, the time
and mute. Keys in the player: Space play/pause, ← / → 5 seconds back / forward, m mute.
Opening a file plays it; the tree's live preview shows the first frame, paused and silent.
"""
import os

import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gdk, Gio, GLib, Gst, Gtk  # noqa: E402

Gst.init(None)

VIDEO_EXT = {'.mp4', '.m4v', '.mkv', '.webm', '.mov', '.avi', '.mpg', '.mpeg', '.ogv', '.3gp', '.flv', '.wmv'}
AUDIO_EXT = {'.mp3', '.wav', '.ogg', '.oga', '.flac', '.m4a', '.aac', '.opus', '.wma'}
SEEK_S = 5


def media_kind(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return 'video'
    if ext in AUDIO_EXT:
        return 'audio'
    return None


def available():
    return all(Gst.ElementFactory.find(n) for n in ('playbin', 'gtksink'))


def _clock(ns):
    if ns is None or ns < 0:
        return '0:00'
    s = int(ns // Gst.SECOND)
    return '%d:%02d:%02d' % (s // 3600, s // 60 % 60, s % 60) if s >= 3600 else '%d:%02d' % (s // 60, s % 60)


class MediaView(Gtk.EventBox):
    def __init__(self, win, path, autoplay=True):
        super().__init__()
        self.win = win
        self.path = path
        self.duration = None
        self._updating = False
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.get_style_context().add_class('chiral-media')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)

        self.player = Gst.ElementFactory.make('playbin', None)
        sink = Gst.ElementFactory.make('gtksink', None)
        self.player.set_property('video-sink', sink)
        self.player.set_property('uri', Gio.File.new_for_path(path).get_uri())
        video = sink.props.widget
        video.set_hexpand(True)
        video.set_vexpand(True)
        box.pack_start(video, True, True, 0)

        bar = Gtk.Box(spacing=6)
        for side in ('start', 'end', 'top', 'bottom'):
            getattr(bar, 'set_margin_' + side)(3)
        self.play_btn = self._button('media-playback-start-symbolic', 'play / pause (space)', self.toggle)
        self.pos = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.1)
        self.pos.set_draw_value(False)
        self.pos.set_can_focus(False)
        self.pos.connect('value-changed', self._seek_bar)
        self.time = Gtk.Label(label='0:00 / 0:00')
        self.time.get_style_context().add_class('chiral-dim')
        self.mute_btn = self._button('audio-volume-high-symbolic', 'mute (m)', self.toggle_mute)
        bar.pack_start(self.play_btn, False, False, 0)
        bar.pack_start(self.pos, True, True, 0)
        bar.pack_start(self.time, False, False, 0)
        bar.pack_start(self.mute_btn, False, False, 0)
        box.pack_start(bar, False, False, 0)

        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect('message::eos', lambda *_: self._ended())
        bus.connect('message::error', self._error)
        self.connect('key-press-event', self._key)
        self.connect('button-press-event', lambda *_: (self.grab_focus(), False)[1])
        video.connect('button-press-event', lambda *_: (self.grab_focus(), self.toggle(), True)[2])
        self.connect('destroy', lambda *_: self.stop())
        self._tick_source = GLib.timeout_add(250, self._tick)
        self.autoplay = autoplay
        self._started = False
        if not autoplay:
            self.player.set_property('mute', True)   # preview: silent
        # start only once we are inside Chiral's window: gtksink otherwise opens a window of its own
        # and moves the player into it
        self.connect('realize', lambda *_: self._start())
        self._mark(False)

    def _start(self):
        if self._started or self.player is None:
            return
        self._started = True
        if self.autoplay:
            self.play()
        else:
            self.player.set_state(Gst.State.PAUSED)   # preview: shows the first frame

    def _button(self, icon, tip, cb):
        b = Gtk.Button()
        b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_can_focus(False)
        b.set_tooltip_text(tip)
        b.connect('clicked', lambda *_: cb())
        return b

    # --- control ---
    def playing(self):
        return self.player.get_state(0)[1] == Gst.State.PLAYING

    def play(self):
        self.player.set_state(Gst.State.PLAYING)
        self._mark(True)

    def pause(self):
        self.player.set_state(Gst.State.PAUSED)
        self._mark(False)

    def toggle(self):
        self.pause() if self.playing() else self.play()

    def toggle_mute(self):
        self.player.set_property('mute', not self.player.get_property('mute'))
        self._mark()

    def seek_by(self, seconds):
        ok, now = self.player.query_position(Gst.Format.TIME)
        if ok:
            target = max(0, now + seconds * Gst.SECOND)
            if self.duration:
                target = min(target, self.duration - Gst.SECOND // 10)
            self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, target)

    def stop(self):
        if self._tick_source:
            GLib.source_remove(self._tick_source)
            self._tick_source = 0
        if self.player is not None:
            self.player.set_state(Gst.State.NULL)          # frees the decoder and the audio device
            self.player.get_bus().remove_signal_watch()
            self.player = None

    # --- display ---
    def _mark(self, playing=None):
        if self.player is None:
            return
        playing = self.playing() if playing is None else playing
        self.play_btn.get_image().set_from_icon_name(
            'media-playback-pause-symbolic' if playing else 'media-playback-start-symbolic', Gtk.IconSize.MENU)
        self.mute_btn.get_image().set_from_icon_name(
            'audio-volume-muted-symbolic' if self.player.get_property('mute') else 'audio-volume-high-symbolic',
            Gtk.IconSize.MENU)

    def _tick(self):
        if self.player is None:
            return False
        if not self.duration:
            ok, d = self.player.query_duration(Gst.Format.TIME)
            if ok and d > 0:
                self.duration = d
                self._updating = True
                self.pos.set_range(0, d / Gst.SECOND)
                self._updating = False
        ok, now = self.player.query_position(Gst.Format.TIME)
        if ok:
            self._updating = True
            self.pos.set_value(now / Gst.SECOND)
            self._updating = False
            self.time.set_text('%s / %s' % (_clock(now), _clock(self.duration)))
        return True

    def _seek_bar(self, scale):
        if self._updating or self.player is None:
            return
        self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                                int(scale.get_value() * Gst.SECOND))

    def _ended(self):
        self.pause()
        self.player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH, 0)

    def _error(self, _bus, msg):
        err, _debug = msg.parse_error()
        self.time.set_text('cannot play: %s · see the hex tab' % err.message)
        self._mark(False)

    def _key(self, _w, ev):
        if ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.MOD1_MASK):
            return False                        # Chiral's own shortcuts keep working
        if ev.keyval == Gdk.KEY_space:
            self.toggle()
        elif ev.keyval == Gdk.KEY_Left:
            self.seek_by(-SEEK_S)
        elif ev.keyval == Gdk.KEY_Right:
            self.seek_by(SEEK_S)
        elif ev.keyval in (Gdk.KEY_m, Gdk.KEY_M):
            self.toggle_mute()
        else:
            return False
        return True
