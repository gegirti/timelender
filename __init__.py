bl_info = {
    "name": "TimeLender (Alpha)",
    "author": "TimeLender",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "Topbar (Right) / Sidebar (TimeLender tab)",
    "description": "Project session timer (Alpha Version - Work in Progress)",
    "category": "System",
}

import datetime
import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.app.handlers import persistent


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _fmt(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _redraw_all():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


def _draw_widget(layout, wm):
    """Shared timer widget: play/pause + reset + clock label."""
    row = layout.row(align=True)
    is_running = wm.tl_is_running

    if not is_running:
        row.operator("timelender.start", text="", icon='PLAY', emboss=True)
        row.active = True
    else:
        row.operator("timelender.pause", text="", icon='PAUSE', emboss=True)

    reset_row = row.row(align=True)
    reset_row.enabled = wm.tl_elapsed > 0 or is_running
    reset_row.operator("timelender.reset", text="", icon='LOOP_BACK', emboss=True)

    label_row = layout.row(align=True)
    label_row.label(text=_fmt(wm.tl_elapsed), icon='TIME')


def _log(scene, event: str):
    """Append a timestamped entry to the session log if logging is enabled."""
    if not scene.tl_log_sessions:
        return
    entry = scene.tl_log.add()
    entry.timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry.event = event


# ─────────────────────────────────────────────
#  Log Entry PropertyGroup
# ─────────────────────────────────────────────

class TIMELENDER_PG_log_entry(bpy.types.PropertyGroup):
    timestamp: StringProperty(name="Timestamp")
    event: StringProperty(name="Event")


# ─────────────────────────────────────────────
#  Persistence handlers
# ─────────────────────────────────────────────

@persistent
def _on_load_post(_filepath):
    wm = bpy.context.window_manager
    scene = bpy.context.scene
    if wm and scene:
        wm.tl_elapsed = scene.tl_elapsed
        _log(scene, "Project opened")


@persistent
def _on_save_post(_filepath):
    scene = bpy.context.scene
    if scene:
        _log(scene, "Project saved")


# ─────────────────────────────────────────────
#  Modal Timer Operator
# ─────────────────────────────────────────────

class TIMELENDER_OT_modal(bpy.types.Operator):
    bl_idname = "timelender.modal"
    bl_label = "TimeLender Background Modal"
    bl_options = {'INTERNAL'}

    _timer = None

    def invoke(self, context, _event):
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        wm = context.window_manager

        if wm.tl_should_stop:
            return self.cancel(context)

        if event.type == 'TIMER' and wm.tl_is_running:
            wm.tl_elapsed += 1
            context.scene.tl_elapsed = wm.tl_elapsed
            _redraw_all()

        return {'PASS_THROUGH'}

    def cancel(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        wm.tl_modal_running = False
        wm.tl_should_stop = False
        return {'CANCELLED'}


# ─────────────────────────────────────────────
#  Start / Pause / Reset Operators
# ─────────────────────────────────────────────

class TIMELENDER_OT_start(bpy.types.Operator):
    bl_idname = "timelender.start"
    bl_label = "Start Timer"
    bl_description = "Start or resume the project timer"

    def execute(self, context):
        wm = context.window_manager
        was_running = wm.tl_is_running
        wm.tl_is_running = True
        if not wm.tl_modal_running:
            wm.tl_modal_running = True
            bpy.ops.timelender.modal('INVOKE_DEFAULT')
        if not was_running:
            label = "Timer resumed" if wm.tl_elapsed > 0 else "Timer started"
            _log(context.scene, label)
        _redraw_all()
        return {'FINISHED'}


class TIMELENDER_OT_pause(bpy.types.Operator):
    bl_idname = "timelender.pause"
    bl_label = "Pause Timer"
    bl_description = "Pause the project timer"

    def execute(self, context):
        context.window_manager.tl_is_running = False
        _log(context.scene, f"Timer paused at {_fmt(context.window_manager.tl_elapsed)}")
        _redraw_all()
        return {'FINISHED'}


class TIMELENDER_OT_reset(bpy.types.Operator):
    bl_idname = "timelender.reset"
    bl_label = "Reset Timer"
    bl_description = "Reset the project timer to 00:00:00"

    def execute(self, context):
        wm = context.window_manager
        _log(context.scene, f"Timer reset (was {_fmt(wm.tl_elapsed)})")
        wm.tl_is_running = False
        wm.tl_elapsed = 0
        context.scene.tl_elapsed = 0
        if wm.tl_modal_running:
            wm.tl_should_stop = True
        _redraw_all()
        return {'FINISHED'}


# ─────────────────────────────────────────────
#  Clear Log Operator
# ─────────────────────────────────────────────

class TIMELENDER_OT_clear_log(bpy.types.Operator):
    bl_idname = "timelender.clear_log"
    bl_label = "Clear Log"
    bl_description = "Remove all session log entries"

    def execute(self, context):
        context.scene.tl_log.clear()
        return {'FINISHED'}


# ─────────────────────────────────────────────
#  Sidebar — Timer Panel
# ─────────────────────────────────────────────

class TIMELENDER_PT_sidebar(bpy.types.Panel):
    bl_idname = "TIMELENDER_PT_sidebar"
    bl_label = "TimeLender"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "TimeLender"

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout

        layout.label(text=_fmt(wm.tl_elapsed), icon='TIME')
        layout.separator()

        col = layout.column(align=True)
        is_running = wm.tl_is_running

        if not is_running:
            col.operator("timelender.start", icon='PLAY')
        else:
            col.operator("timelender.pause", icon='PAUSE')

        reset_row = col.row()
        reset_row.enabled = wm.tl_elapsed > 0 or is_running
        reset_row.operator("timelender.reset", icon='LOOP_BACK')


# ─────────────────────────────────────────────
#  Sidebar — Session Log Panel
# ─────────────────────────────────────────────

class TIMELENDER_PT_log(bpy.types.Panel):
    bl_idname = "TIMELENDER_PT_log"
    bl_label = "Session Log"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "TimeLender"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene, "tl_log_sessions", text="")

    def draw(self, context):
        scene = context.scene
        layout = self.layout

        if not scene.tl_log_sessions:
            layout.label(text="Enable logging above to record events.", icon='INFO')
            return

        log = scene.tl_log
        if not log:
            layout.label(text="No events recorded yet.", icon='INFO')
        else:
            box = layout.box()
            col = box.column(align=True)
            # Show newest entries first
            for entry in reversed(list(log)):
                row = col.row(align=True)
                row.label(text=entry.timestamp, icon='TIME')
                row.label(text=entry.event)

        layout.operator("timelender.clear_log", icon='TRASH')


# ─────────────────────────────────────────────
#  Sidebar — Settings Panel
# ─────────────────────────────────────────────

class TIMELENDER_PT_settings(bpy.types.Panel):
    bl_idname = "TIMELENDER_PT_settings"
    bl_label = "Settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "TimeLender"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        layout.prop(context.scene, "tl_location", text="Widget Location")


# ─────────────────────────────────────────────
#  Topbar / Statusbar Draw Functions
# ─────────────────────────────────────────────

def draw_timer_topbar_right(self, context):
    if context.region.alignment != 'RIGHT':
        return
    if context.scene.tl_location != 'TOPBAR_RIGHT':
        return
    layout = self.layout
    layout.separator(factor=1.2)
    _draw_widget(layout, context.window_manager)


def draw_timer_topbar_left(self, context):
    if context.region.alignment != 'LEFT':
        return
    if context.scene.tl_location != 'TOPBAR_LEFT':
        return
    layout = self.layout
    layout.separator(factor=1.2)
    _draw_widget(layout, context.window_manager)


def draw_timer_statusbar(self, context):
    if context.scene.tl_location != 'STATUSBAR':
        return
    _draw_widget(self.layout, context.window_manager)


# ─────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────

CLASSES = (
    TIMELENDER_PG_log_entry,
    TIMELENDER_OT_modal,
    TIMELENDER_OT_start,
    TIMELENDER_OT_pause,
    TIMELENDER_OT_reset,
    TIMELENDER_OT_clear_log,
    TIMELENDER_PT_sidebar,
    TIMELENDER_PT_log,
    TIMELENDER_PT_settings,
)

_LOCATION_ITEMS = [
    ('TOPBAR_RIGHT', "Topbar Right", "Show timer on the right side of the Topbar"),
    ('TOPBAR_LEFT',  "Topbar Left",  "Show timer on the left side of the Topbar"),
    ('SIDEBAR',      "Sidebar Only", "Show timer only in the N-panel sidebar"),
    ('STATUSBAR',    "Status Bar",   "Show timer in the Status Bar at the bottom"),
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    # Scene properties — saved with the .blend file
    bpy.types.Scene.tl_elapsed = IntProperty(name="Elapsed Seconds", default=0, min=0)
    bpy.types.Scene.tl_location = EnumProperty(
        name="Widget Location",
        description="Where to display the timer widget",
        items=_LOCATION_ITEMS,
        default='TOPBAR_RIGHT',
    )
    bpy.types.Scene.tl_log_sessions = BoolProperty(
        name="Log Sessions",
        description="Record session events (start, pause, reset, open, save)",
        default=False,
    )
    bpy.types.Scene.tl_log = CollectionProperty(type=TIMELENDER_PG_log_entry)

    # WindowManager properties — session-scoped
    bpy.types.WindowManager.tl_is_running = BoolProperty(name="Timer Running", default=False)
    bpy.types.WindowManager.tl_elapsed = IntProperty(name="Elapsed Seconds (Live)", default=0, min=0)
    bpy.types.WindowManager.tl_modal_running = BoolProperty(name="Modal Active", default=False)
    bpy.types.WindowManager.tl_should_stop = BoolProperty(name="Stop Signal", default=False)

    bpy.app.handlers.load_post.append(_on_load_post)
    bpy.app.handlers.save_post.append(_on_save_post)
    bpy.types.TOPBAR_HT_upper_bar.append(draw_timer_topbar_right)
    bpy.types.TOPBAR_HT_upper_bar.append(draw_timer_topbar_left)
    bpy.types.STATUSBAR_HT_header.append(draw_timer_statusbar)


def unregister():
    bpy.types.STATUSBAR_HT_header.remove(draw_timer_statusbar)
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_timer_topbar_left)
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_timer_topbar_right)
    bpy.app.handlers.save_post.remove(_on_save_post)
    bpy.app.handlers.load_post.remove(_on_load_post)

    for prop in ("tl_is_running", "tl_elapsed", "tl_modal_running", "tl_should_stop"):
        try:
            delattr(bpy.types.WindowManager, prop)
        except AttributeError:
            pass

    for prop in ("tl_elapsed", "tl_location", "tl_log_sessions", "tl_log"):
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
