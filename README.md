# TimeLender (Alpha) ⏱️

> [!WARNING]
> This is an **ALPHA** version. Features are not fully implemented and everything is subject to change.

A lightweight project timer for Blender. Currently in early development. It will take some time and few tokens because this is a vibe project. 

## Current Status (Alpha)
- Start / Pause / Reset widget in the Status Bar (default), Topbar left/right, or Sidebar only.
- Sidebar (N-panel) tab with total project time, time this session, session log and settings.
- Project time and log are saved inside the `.blend` file (written on save).
- Auto-start on the first real interaction after opening a file.
- Auto-pause after N minutes of inactivity: the idle minutes are subtracted, and the timer resumes when you work again.
- Renders/bakes count as activity; time while the machine sleeps is not counted.
- Session log with CSV export (timestamp, event, project time).
- Settings live in the add-on preferences (shared by all files).

## Installation
1. Zip the repository folder so the zip contains `timelender/__init__.py`.
2. Blender → Preferences → Add-ons → Install from Disk.

## Tests
Run headless with the `bpy` wheel (Python 3.11 for Blender 4.2) or with Blender itself:

```sh
pip install bpy==4.2.0
python tests/test_timelender.py
# or: blender -b --python tests/test_timelender.py
```

---

## Roadmap & Feedback
See [TODO.md](./TODO.md) for planned features. This version is for testing the UI and basic modal logic.
