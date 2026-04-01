bl_info = {
    "name": "TimeLender (Alpha)",
    "author": "TimeLender",
    "version": (0, 1, 0),
    "blender": (4, 0, 0),
    "location": "Topbar (Right) / Sidebar (TimeLender tab)",
    "description": "Project session timer (Alpha Version - Work in Progress)",
    "category": "System",
}

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
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


# ─────────────────────────────────────────────
#  Persistence — load_post handler
# ─────────────────────────────────────────────

@persistent
def _on_load_post(_filepath):
    wm = bpy.context.window_manager
    scene = bpy.context.scene
    if wm and scene:
        wm.tl_elapsed = scene.tl_elapsed


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
        wm.tl_is_running = True
        if not wm.tl_modal_running:
            wm.tl_modal_running = True
            bpy.ops.timelender.modal('INVOKE_DEFAULT')
        _redraw_all()
        return {'FINISHED'}


class TIMELENDER_OT_pause(bpy.types.Operator):
    bl_idname = "timelender.pause"
    bl_label = "Pause Timer"
    bl_description = "Pause the project timer"

    def execute(self, context):
        context.window_manager.tl_is_running = False
        _redraw_all()
        return {'FINISHED'}


class TIMELENDER_OT_reset(bpy.types.Operator):
    bl_idname = "timelender.reset"
    bl_label = "Reset Timer"
    bl_description = "Reset the project timer to 00:00:00"

    def execute(self, context):
        wm = context.window_manager
        wm.tl_is_running = False
        wm.tl_elapsed = 0
        context.scene.tl_elapsed = 0
        if wm.tl_modal_running:
            wm.tl_should_stop = True
        _redraw_all()
        return {'FINISHED'}


# ─────────────────────────────────────────────
#  Sidebar (N-panel) — Timer Panel
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
#  Sidebar (N-panel) — Settings Panel
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
#  Topbar Draw Functions
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


# ─────────────────────────────────────────────
#  Status Bar Draw Function
# ─────────────────────────────────────────────

def draw_timer_statusbar(self, context):
    if context.scene.tl_location != 'STATUSBAR':
        return
    _draw_widget(self.layout, context.window_manager)


# ─────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────

CLASSES = (
    TIMELENDER_OT_modal,
    TIMELENDER_OT_start,
    TIMELENDER_OT_pause,
    TIMELENDER_OT_reset,
    TIMELENDER_PT_sidebar,
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
    bpy.types.Scene.tl_elapsed = IntProperty(
        name="Elapsed Seconds",
        default=0,
        min=0,
    )
    bpy.types.Scene.tl_location = EnumProperty(
        name="Widget Location",
        description="Where to display the timer widget",
        items=_LOCATION_ITEMS,
        default='TOPBAR_RIGHT',
    )

    # WindowManager properties — session-scoped
    bpy.types.WindowManager.tl_is_running = BoolProperty(name="Timer Running", default=False)
    bpy.types.WindowManager.tl_elapsed = IntProperty(name="Elapsed Seconds (Live)", default=0, min=0)
    bpy.types.WindowManager.tl_modal_running = BoolProperty(name="Modal Active", default=False)
    bpy.types.WindowManager.tl_should_stop = BoolProperty(name="Stop Signal", default=False)

    bpy.app.handlers.load_post.append(_on_load_post)
    bpy.types.TOPBAR_HT_upper_bar.append(draw_timer_topbar_right)
    bpy.types.TOPBAR_HT_upper_bar.append(draw_timer_topbar_left)
    bpy.types.STATUSBAR_HT_header.append(draw_timer_statusbar)


def unregister():
    bpy.types.STATUSBAR_HT_header.remove(draw_timer_statusbar)
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_timer_topbar_left)
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_timer_topbar_right)
    bpy.app.handlers.load_post.remove(_on_load_post)

    for prop in ("tl_is_running", "tl_elapsed", "tl_modal_running", "tl_should_stop"):
        try:
            delattr(bpy.types.WindowManager, prop)
        except AttributeError:
            pass

    for prop in ("tl_elapsed", "tl_location"):
        try:
            delattr(bpy.types.Scene, prop)
        except AttributeError:
            pass

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
