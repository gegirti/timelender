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
from bpy.props import BoolProperty, IntProperty
from bpy.app.handlers import persistent


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _fmt(seconds: int) -> str:
    """Return HH:MM:SS string from total seconds."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _redraw_topbar():
    """Ask every screen area to redraw so the timer label updates."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()


# ─────────────────────────────────────────────
#  Persistence — load_post handler
#  Restores wm.tl_elapsed from the scene when
#  a .blend file is opened.
# ─────────────────────────────────────────────

@persistent
def _on_load_post(_filepath):
    wm = bpy.context.window_manager
    scene = bpy.context.scene
    if wm and scene:
        wm.tl_elapsed = scene.tl_elapsed


# ─────────────────────────────────────────────
#  Modal Timer Operator
#  Runs silently in the background; increments
#  tl_elapsed every second while tl_is_running.
# ─────────────────────────────────────────────

class TIMELENDER_OT_modal(bpy.types.Operator):
    bl_idname = "timelender.modal"
    bl_label = "TimeLender Background Modal"
    bl_options = {'INTERNAL'}

    _timer = None

    def invoke(self, context, event):
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        wm = context.window_manager

        # If someone called Stop (reset), we cancel cleanly.
        if wm.tl_should_stop:
            return self.cancel(context)

        if event.type == 'TIMER' and wm.tl_is_running:
            wm.tl_elapsed += 1
            # Persist to scene so the value is saved with the .blend file.
            context.scene.tl_elapsed = wm.tl_elapsed
            _redraw_topbar()

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
#  Start / Resume Operator
# ─────────────────────────────────────────────

class TIMELENDER_OT_start(bpy.types.Operator):
    bl_idname = "timelender.start"
    bl_label = "Start Timer"
    bl_description = "Start or resume the project timer"

    def execute(self, context):
        wm = context.window_manager
        wm.tl_is_running = True

        # Launch the modal once; it stays alive until stop/reset.
        if not wm.tl_modal_running:
            wm.tl_modal_running = True
            bpy.ops.timelender.modal('INVOKE_DEFAULT')

        _redraw_topbar()
        return {'FINISHED'}


# ─────────────────────────────────────────────
#  Pause Operator
# ─────────────────────────────────────────────

class TIMELENDER_OT_pause(bpy.types.Operator):
    bl_idname = "timelender.pause"
    bl_label = "Pause Timer"
    bl_description = "Pause the project timer"

    def execute(self, context):
        wm = context.window_manager
        wm.tl_is_running = False
        _redraw_topbar()
        return {'FINISHED'}


# ─────────────────────────────────────────────
#  Reset Operator
# ─────────────────────────────────────────────

class TIMELENDER_OT_reset(bpy.types.Operator):
    bl_idname = "timelender.reset"
    bl_label = "Reset Timer"
    bl_description = "Reset the project timer to 00:00:00"

    def execute(self, context):
        wm = context.window_manager
        wm.tl_is_running = False
        wm.tl_elapsed = 0
        context.scene.tl_elapsed = 0
        # Signal the modal to terminate itself cleanly.
        if wm.tl_modal_running:
            wm.tl_should_stop = True
        _redraw_topbar()
        return {'FINISHED'}


# ─────────────────────────────────────────────
#  Sidebar (N-panel) Panel
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

        # Time display
        row = layout.row()
        row.label(text=_fmt(wm.tl_elapsed), icon='TIME')

        layout.separator()

        # Controls
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
#  Topbar Draw Function
# ─────────────────────────────────────────────

def draw_timer_in_topbar(self, context):
    # TOPBAR_HT_upper_bar is called for both left and right regions;
    # only draw in the RIGHT region to avoid duplicate widgets.
    if context.region.alignment != 'RIGHT':
        return

    wm = context.window_manager
    layout = self.layout

    # Thin separator to visually offset from the existing right-side items
    layout.separator(factor=1.2)

    row = layout.row(align=True)
    row.scale_x = 1.0

    is_running = wm.tl_is_running

    # ▶ / ⏸  toggle button
    if not is_running:
        row.operator(
            "timelender.start",
            text="",
            icon='PLAY',
            emboss=True,
        )
        row.active = True
    else:
        row.operator(
            "timelender.pause",
            text="",
            icon='PAUSE',
            emboss=True,
        )

    # ↺ Reset
    reset_row = row.row(align=True)
    reset_row.enabled = (wm.tl_elapsed > 0 or is_running)
    reset_row.operator("timelender.reset", text="", icon='LOOP_BACK', emboss=True)

    # Time display ── styled as a label
    time_row = layout.row(align=True)
    time_row.scale_x = 1.0
    time_row.enabled = True
    time_row.label(text=_fmt(wm.tl_elapsed), icon='TIME')


# ─────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────

CLASSES = (
    TIMELENDER_OT_modal,
    TIMELENDER_OT_start,
    TIMELENDER_OT_pause,
    TIMELENDER_OT_reset,
    TIMELENDER_PT_sidebar,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    # Scene property — saved with the .blend file
    bpy.types.Scene.tl_elapsed = IntProperty(
        name="Elapsed Seconds",
        default=0,
        min=0,
    )

    # WindowManager properties — session-scoped (running state, modal flag)
    bpy.types.WindowManager.tl_is_running = BoolProperty(
        name="Timer Running",
        default=False,
    )
    bpy.types.WindowManager.tl_elapsed = IntProperty(
        name="Elapsed Seconds (Live)",
        default=0,
        min=0,
    )
    bpy.types.WindowManager.tl_modal_running = BoolProperty(
        name="Modal Active",
        default=False,
    )
    bpy.types.WindowManager.tl_should_stop = BoolProperty(
        name="Stop Signal",
        default=False,
    )

    bpy.app.handlers.load_post.append(_on_load_post)
    bpy.types.TOPBAR_HT_upper_bar.append(draw_timer_in_topbar)


def unregister():
    bpy.types.TOPBAR_HT_upper_bar.remove(draw_timer_in_topbar)
    bpy.app.handlers.load_post.remove(_on_load_post)

    for prop in ("tl_is_running", "tl_elapsed", "tl_modal_running", "tl_should_stop"):
        try:
            delattr(bpy.types.WindowManager, prop)
        except AttributeError:
            pass

    try:
        del bpy.types.Scene.tl_elapsed
    except AttributeError:
        pass

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
