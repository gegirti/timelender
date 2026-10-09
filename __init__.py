bl_info = {
    "name": "TimeLender (Alpha)",
    "author": "TimeLender",
    "version": (0, 2, 0),
    "blender": (4, 0, 0),
    "location": "Status Bar / Topbar / Sidebar (TimeLender tab)",
    "description": "Project session timer (Alpha Version - Work in Progress)",
    "category": "System",
}

import csv
import datetime
import os
import time
import traceback

import bpy
from bpy.app.handlers import persistent
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper

ADDON_ID = __package__ or __name__

TICK = 1.0                # seconds between timer ticks
LOAD_GRACE = 2.0          # ignore UI/depsgraph churn right after a file load
BUSY_GAP = 3.0            # a tick this late means the main loop was blocked (or the machine slept)
BUSY_CPU_RATIO = 0.25     # CPU/wall ratio over a gap that counts as "Blender was working"
LOG_DISPLAY_LIMIT = 50    # newest entries drawn in the sidebar
JOB_TYPES = ('RENDER', 'OBJECT_BAKE', 'COMPOSITE')


# ─────────────────────────────────────────────
#  Runtime state
# ─────────────────────────────────────────────
#
# Live state is kept in plain Python, not in RNA properties. Writing a bpy.props
# property tags the owning ID for a depsgraph update and broadcasts an NC_WINDOW
# notifier (= every region of every window redraws), so doing that once per
# second was a constant drag on Blender. The .blend file is only written to in
# save_pre.

class _State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.ready = False
        self.elapsed = 0.0             # project seconds
        self.session = 0.0             # seconds counted since the file was opened
        self.running = False
        self.idle_paused = False       # paused by the inactivity detector (not by the user)
        self.pending_auto_start = False
        self.activity = False          # activity seen since the last tick
        self.last_activity = time.monotonic()
        self.idle_counted = 0.0        # seconds counted since the last activity
        self.last_tick = time.monotonic()
        self.last_cpu = time.process_time()
        self.ignore_until = 0.0
        self.snapshot = None
        self.window_keys = None
        self.shown_second = -1
        self.log = []                  # [(timestamp, event, elapsed_seconds)]


_S = _State()

# Header regions (status bar / topbar) the widget was last drawn in, per window.
# Python can't enumerate a window's global areas (window.screen.areas excludes
# them), so the draw callbacks record the region they draw into.
_HEADER_REGIONS = {}


class _DefaultPrefs:
    location = 'STATUSBAR'
    auto_start = True
    auto_pause = True
    auto_resume = True
    inactivity_minutes = 7
    count_jobs = True
    log_sessions = True


def _prefs():
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    return addon.preferences if addon and addon.preferences else _DefaultPrefs


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _fmt(seconds) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _log(event: str):
    if not _prefs().log_sessions:
        return
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _S.log.append((stamp, event, int(_S.elapsed)))


def _status_text():
    if _S.running:
        return "Running"
    if _S.idle_paused:
        return "Idle (auto-paused)"
    if _S.pending_auto_start:
        return "Waiting for activity"
    return "Paused"


def _start(event, now=None):
    _S.running = True
    _S.idle_paused = False
    _S.pending_auto_start = False
    _S.idle_counted = 0.0
    _S.last_activity = time.monotonic() if now is None else now
    _log(event)


def _pause(event, idle=False):
    _S.running = False
    _S.idle_paused = idle
    _S.pending_auto_start = False
    _log(event)


def _touch(now=None):
    """Record user (or Blender job) activity."""
    _S.last_activity = time.monotonic() if now is None else now
    _S.idle_counted = 0.0
    _S.activity = True


def _animation_playing(wm):
    return any(win.screen and win.screen.is_animation_playing for win in wm.windows)


def _jobs_running():
    return any(bpy.app.is_job_running(job) for job in JOB_TYPES)


def _ui_snapshot(wm):
    """Hash of UI state that changes when the user navigates or works.

    Covers what the depsgraph handler misses: viewport orbit/pan/zoom, 2D view
    panning in other editors, text editing, workspace/editor switches and newly
    executed operators. Mouse hovering alone is deliberately not activity.
    """
    h = []
    ops = wm.operators
    if len(ops):
        h += (len(ops), ops[-1].as_pointer())
    for win in wm.windows:
        screen = win.screen
        if screen is None:
            continue
        h.append(screen.as_pointer())
        for area in screen.areas:
            h.append(area.ui_type)
            space = area.spaces.active
            if area.type == 'VIEW_3D':
                r3d = getattr(space, "region_3d", None)
                if r3d is not None:
                    h.extend(v for row in r3d.view_matrix for v in row)
            elif area.type == 'TEXT_EDITOR':
                text = space.text
                if text is not None:
                    h += (text.as_pointer(), text.current_line_index, text.current_character, space.top)
            else:
                for region in area.regions:
                    if region.type == 'WINDOW':
                        v2d = region.view2d
                        h.extend(v2d.region_to_view(0, 0))
                        h.extend(v2d.region_to_view(region.width, region.height))
    return hash(tuple(h))


def _tag_widget_regions(wm):
    keys = frozenset(win.as_pointer() for win in wm.windows)
    if keys != _S.window_keys:
        # A window was opened/closed: drop cached regions, the next draw re-caches them.
        _S.window_keys = keys
        _HEADER_REGIONS.clear()
    for regions in _HEADER_REGIONS.values():
        for region in regions.values():
            region.tag_redraw()
    for win in wm.windows:
        if win.screen is None:
            continue
        for area in win.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()


# ─────────────────────────────────────────────
#  Clock
# ─────────────────────────────────────────────

def _step(now, cpu):
    """Advance the clock. Separated from the timer callback so it can be tested."""
    dt = now - _S.last_tick
    dcpu = cpu - _S.last_cpu
    _S.last_tick, _S.last_cpu = now, cpu
    if not _S.ready:
        return

    wm = bpy.context.window_manager
    p = _prefs()
    in_grace = now < _S.ignore_until

    if wm is not None:
        snap = _ui_snapshot(wm)
        if (not in_grace and _S.snapshot is not None and snap != _S.snapshot
                and not _animation_playing(wm)):
            _touch(now)
        _S.snapshot = snap

    if not in_grace and p.count_jobs and _jobs_running():
        _touch(now)

    if dt > BUSY_GAP:
        if dcpu >= dt * BUSY_CPU_RATIO:
            if not in_grace:
                _touch(now)    # main loop blocked by real work (bake, heavy modifier, ...)
        else:
            dt = TICK          # machine slept or the app was suspended: don't bill the gap

    if _S.activity:
        _S.activity = False
        if _S.pending_auto_start:
            _start("Timer auto-started on first activity", now)
        elif _S.idle_paused and p.auto_resume:
            _start("Timer resumed on activity", now)

    if _S.running:
        _S.elapsed += dt
        _S.session += dt
        _S.idle_counted += dt
        if p.auto_pause and now - _S.last_activity > p.inactivity_minutes * 60:
            # Everything counted since the last activity was idle time: give it back.
            _S.elapsed = max(0.0, _S.elapsed - _S.idle_counted)
            _S.session = max(0.0, _S.session - _S.idle_counted)
            _S.idle_counted = 0.0
            _pause(f"Auto-paused after {p.inactivity_minutes}m inactivity", idle=True)

    if wm is not None and int(_S.elapsed) != _S.shown_second:
        _S.shown_second = int(_S.elapsed)
        _tag_widget_regions(wm)


def _tick():
    try:
        _step(time.monotonic(), time.process_time())
    except Exception:
        traceback.print_exc()
    return TICK


# ─────────────────────────────────────────────
#  Persistence
# ─────────────────────────────────────────────
#
# Project time is per file, but a file has no file-level ID to hang data on, so
# it is written to every (local) scene on save and read back from whichever
# scene holds the most time. Adding, switching or deleting scenes can't lose it.

class TIMELENDER_PG_log_entry(bpy.types.PropertyGroup):
    timestamp: StringProperty(name="Timestamp")
    event: StringProperty(name="Event")
    elapsed: IntProperty(name="Project Seconds", default=0, min=0)


def _load_from_file():
    scenes = list(bpy.data.scenes)
    source = max(scenes, key=lambda s: s.tl_elapsed, default=None)
    _S.reset()
    if source is not None:
        _S.elapsed = float(source.tl_elapsed)
        _S.log = [(e.timestamp, e.event, e.elapsed) for e in source.tl_log]
    _S.pending_auto_start = _prefs().auto_start
    _S.ignore_until = time.monotonic() + LOAD_GRACE
    _S.ready = True


def _write_to_file():
    for scene in bpy.data.scenes:
        if scene.library is not None:
            continue
        scene.tl_elapsed = int(_S.elapsed)
        scene.tl_log.clear()
        for stamp, event, elapsed in _S.log:
            entry = scene.tl_log.add()
            entry.timestamp = stamp
            entry.event = event
            entry.elapsed = elapsed


@persistent
def _on_load_pre(*_args):
    _S.ready = False
    _HEADER_REGIONS.clear()


@persistent
def _on_load_post(*_args):
    _HEADER_REGIONS.clear()
    _load_from_file()
    _log("Project opened")


@persistent
def _on_save_pre(*_args):
    _log("Project saved")
    _write_to_file()


@persistent
def _on_depsgraph_update(*_args):
    if not _S.ready or time.monotonic() < _S.ignore_until:
        return
    wm = bpy.context.window_manager
    if wm is not None and _animation_playing(wm):
        return
    _touch()


@persistent
def _on_user_action(*_args):
    # undo/redo, frame changes (scrubbing). Playback is filtered out.
    if not _S.ready or time.monotonic() < _S.ignore_until:
        return
    wm = bpy.context.window_manager
    if wm is not None and _animation_playing(wm):
        return
    _touch()


def _deferred_init():
    # The add-on was enabled mid-session (load_post won't fire until the next load).
    if not _S.ready:
        _load_from_file()
    return None


# ─────────────────────────────────────────────
#  Operators
# ─────────────────────────────────────────────

class TIMELENDER_OT_start(bpy.types.Operator):
    bl_idname = "timelender.start"
    bl_label = "Start Timer"
    bl_description = "Start or resume the project timer"

    def execute(self, context):
        if not _S.running:
            _start("Timer resumed" if _S.elapsed >= 1 else "Timer started")
        _S.shown_second = -1
        return {'FINISHED'}


class TIMELENDER_OT_pause(bpy.types.Operator):
    bl_idname = "timelender.pause"
    bl_label = "Pause Timer"
    bl_description = "Pause the project timer"

    def execute(self, context):
        if _S.running or _S.pending_auto_start or _S.idle_paused:
            _pause(f"Timer paused at {_fmt(_S.elapsed)}")
        _S.shown_second = -1
        return {'FINISHED'}


class TIMELENDER_OT_reset(bpy.types.Operator):
    bl_idname = "timelender.reset"
    bl_label = "Reset Timer"
    bl_description = "Reset the project timer to 00:00:00"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        _log(f"Timer reset (was {_fmt(_S.elapsed)})")
        _S.running = False
        _S.idle_paused = False
        _S.pending_auto_start = False
        _S.elapsed = 0.0
        _S.session = 0.0
        _S.shown_second = -1
        return {'FINISHED'}


class TIMELENDER_OT_export_log(bpy.types.Operator, ExportHelper):
    bl_idname = "timelender.export_log"
    bl_label = "Export Session Log"
    bl_description = "Export the session log to a CSV file"

    filename_ext = ".csv"
    filter_glob: StringProperty(default="*.csv", options={'HIDDEN'})

    def invoke(self, context, event):
        blend_name = os.path.splitext(bpy.path.basename(bpy.data.filepath))[0] or "untitled"
        self.filepath = f"{blend_name}_timelender_log.csv"
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        if not _S.log:
            self.report({'WARNING'}, "Session log is empty — nothing to export.")
            return {'CANCELLED'}

        try:
            with open(self.filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "Event", "Project Time", "Project Seconds"])
                for stamp, event, elapsed in _S.log:
                    writer.writerow([stamp, event, _fmt(elapsed), elapsed])
        except OSError as e:
            self.report({'ERROR'}, f"Could not write file: {e}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Log exported to {self.filepath}")
        return {'FINISHED'}


class TIMELENDER_OT_clear_log(bpy.types.Operator):
    bl_idname = "timelender.clear_log"
    bl_label = "Clear Log"
    bl_description = "Remove all session log entries"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        _S.log.clear()
        return {'FINISHED'}


# ─────────────────────────────────────────────
#  Preferences
# ─────────────────────────────────────────────

_LOCATION_ITEMS = [
    ('STATUSBAR',    "Status Bar",   "Show timer in the Status Bar at the bottom"),
    ('TOPBAR_RIGHT', "Topbar Right", "Show timer on the right side of the Topbar"),
    ('TOPBAR_LEFT',  "Topbar Left",  "Show timer on the left side of the Topbar"),
    ('SIDEBAR',      "Sidebar Only", "Show timer only in the N-panel sidebar"),
]


def _draw_settings(layout, prefs):
    layout.prop(prefs, "location")
    layout.separator()
    layout.prop(prefs, "auto_start")
    layout.prop(prefs, "auto_pause")
    col = layout.column()
    col.enabled = prefs.auto_pause
    col.prop(prefs, "inactivity_minutes")
    col.prop(prefs, "auto_resume")
    layout.prop(prefs, "count_jobs")
    layout.prop(prefs, "log_sessions")


class TIMELENDER_AP_preferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    location: EnumProperty(
        name="Widget Location",
        description="Where to display the timer widget",
        items=_LOCATION_ITEMS,
        default='STATUSBAR',
    )
    auto_start: BoolProperty(
        name="Auto-Start on Open",
        description="Start the timer on the first real interaction after opening a project",
        default=True,
    )
    auto_pause: BoolProperty(
        name="Auto-Pause on Inactivity",
        description="Pause the timer when Blender has been idle for the set duration "
                    "and discard the idle time",
        default=True,
    )
    inactivity_minutes: IntProperty(
        name="Inactivity Timeout (min)",
        description="Minutes of inactivity before the timer is paused automatically",
        default=7,
        min=1,
        max=120,
    )
    auto_resume: BoolProperty(
        name="Resume on Activity",
        description="Resume an auto-paused timer as soon as you work again",
        default=True,
    )
    count_jobs: BoolProperty(
        name="Count Render/Bake Time",
        description="Treat running renders, bakes and compositing jobs as activity",
        default=True,
    )
    log_sessions: BoolProperty(
        name="Log Sessions",
        description="Record session events (start, pause, reset, open, save)",
        default=True,
    )

    def draw(self, context):
        _draw_settings(self.layout, self)


# ─────────────────────────────────────────────
#  UI
# ─────────────────────────────────────────────

def _draw_widget(layout):
    """Shared timer widget: play/pause + reset + clock label."""
    row = layout.row(align=True)
    if _S.running:
        row.operator("timelender.pause", text="", icon='PAUSE')
    else:
        row.operator("timelender.start", text="", icon='PLAY')

    reset_row = row.row(align=True)
    reset_row.enabled = _S.elapsed >= 1 or _S.running
    reset_row.operator("timelender.reset", text="", icon='LOOP_BACK')

    label_row = layout.row(align=True)
    label_row.alert = _S.idle_paused
    label_row.active = _S.running or _S.idle_paused
    label_row.label(text=_fmt(_S.elapsed), icon='TIME')


class TIMELENDER_PT_sidebar(bpy.types.Panel):
    bl_idname = "TIMELENDER_PT_sidebar"
    bl_label = "TimeLender"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "TimeLender"

    def draw(self, context):
        layout = self.layout

        col = layout.column(align=True)
        col.label(text=_fmt(_S.elapsed), icon='TIME')
        sub = col.column(align=True)
        sub.active = False
        sub.label(text=f"This session: {_fmt(_S.session)}")
        sub.label(text=_status_text())
        layout.separator()

        col = layout.column(align=True)
        if _S.running:
            col.operator("timelender.pause", icon='PAUSE')
        else:
            col.operator("timelender.start", icon='PLAY')

        reset_row = col.row()
        reset_row.enabled = _S.elapsed >= 1 or _S.running
        reset_row.operator("timelender.reset", icon='LOOP_BACK')


class TIMELENDER_PT_log(bpy.types.Panel):
    bl_idname = "TIMELENDER_PT_log"
    bl_label = "Session Log"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "TimeLender"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(_prefs(), "log_sessions", text="")

    def draw(self, context):
        layout = self.layout

        if not _prefs().log_sessions:
            layout.label(text="Enable logging above to record events.", icon='INFO')

        if not _S.log:
            layout.label(text="No events recorded yet.", icon='INFO')
        else:
            box = layout.box()
            col = box.column(align=True)
            # Newest first, capped: drawing hundreds of rows on every redraw is slow.
            for stamp, event, _elapsed in reversed(_S.log[-LOG_DISPLAY_LIMIT:]):
                row = col.row(align=True)
                row.label(text=stamp[5:16], icon='TIME')
                row.label(text=event)
            if len(_S.log) > LOG_DISPLAY_LIMIT:
                col.label(text=f"… {len(_S.log) - LOG_DISPLAY_LIMIT} older entries (see export)")

        row = layout.row(align=True)
        row.operator("timelender.export_log", icon='EXPORT')
        row.operator("timelender.clear_log", icon='TRASH', text="")


class TIMELENDER_PT_settings(bpy.types.Panel):
    bl_idname = "TIMELENDER_PT_settings"
    bl_label = "Settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "TimeLender"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        prefs = _prefs()
        if prefs is _DefaultPrefs:
            self.layout.label(text="Enable the add-on via Preferences to change settings.")
            return
        _draw_settings(self.layout, prefs)


def _remember_region(context, kind):
    if context.window is not None and context.region is not None:
        _HEADER_REGIONS.setdefault(context.window.as_pointer(), {})[kind] = context.region


def draw_timer_topbar(self, context):
    location = _prefs().location
    if location not in {'TOPBAR_LEFT', 'TOPBAR_RIGHT'}:
        return
    # The topbar has two header regions: alignment 'RIGHT' and the main (left) one,
    # whose alignment is 'TOP', not 'LEFT'.
    is_right = context.region.alignment == 'RIGHT'
    if is_right != (location == 'TOPBAR_RIGHT'):
        return
    _remember_region(context, 'TOPBAR')
    layout = self.layout
    layout.separator(factor=1.2)
    _draw_widget(layout)


def draw_timer_statusbar(self, context):
    if _prefs().location != 'STATUSBAR':
        return
    _remember_region(context, 'STATUSBAR')
    _draw_widget(self.layout)


# ─────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────

CLASSES = (
    TIMELENDER_PG_log_entry,
    TIMELENDER_AP_preferences,
    TIMELENDER_OT_start,
    TIMELENDER_OT_pause,
    TIMELENDER_OT_reset,
    TIMELENDER_OT_export_log,
    TIMELENDER_OT_clear_log,
    TIMELENDER_PT_sidebar,
    TIMELENDER_PT_log,
    TIMELENDER_PT_settings,
)

_HANDLERS = (
    (bpy.app.handlers.load_pre, _on_load_pre),
    (bpy.app.handlers.load_post, _on_load_post),
    (bpy.app.handlers.save_pre, _on_save_pre),
    (bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update),
    (bpy.app.handlers.undo_post, _on_user_action),
    (bpy.app.handlers.redo_post, _on_user_action),
    (bpy.app.handlers.frame_change_post, _on_user_action),
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    # Saved with the .blend file (written in save_pre only)
    bpy.types.Scene.tl_elapsed = IntProperty(name="Elapsed Seconds", default=0, min=0)
    bpy.types.Scene.tl_log = CollectionProperty(type=TIMELENDER_PG_log_entry)

    for handlers, fn in _HANDLERS:
        handlers.append(fn)
    bpy.types.TOPBAR_HT_upper_bar.append(draw_timer_topbar)
    bpy.types.STATUSBAR_HT_header.append(draw_timer_statusbar)

    _S.reset()
    bpy.app.timers.register(_tick, first_interval=TICK, persistent=True)
    bpy.app.timers.register(_deferred_init, first_interval=0.1)


def unregister():
    for fn in (_tick, _deferred_init):
        if bpy.app.timers.is_registered(fn):
            bpy.app.timers.unregister(fn)

    bpy.types.STATUSBAR_HT_header.remove(draw_timer_statusbar)
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_timer_topbar)
    for handlers, fn in _HANDLERS:
        if fn in handlers:
            handlers.remove(fn)
    _HEADER_REGIONS.clear()

    for prop in ("tl_elapsed", "tl_log"):
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
