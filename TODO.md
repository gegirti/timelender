# TimeLender TODO List 🚀

This is a tracking list for the alpha development of TimeLender.

## Persistence & Data
- [x] **Save time within .blend file**: Store elapsed time in Scene or Custom Properties so it persists across sessions.
- [ ] **Project name tracking**: Automatically associate time with the filename.
- [ ] **Automated saving**: Periodic save of the timer state to avoid loss on crash.

## UI/UX Improvements
- [ ] **UI Location Settings**: Allow users to choose where the timer appears (Topbar Left, Topbar Right, Sidebar only, or Status Bar).
- [ ] **Customizable Icons**: Option to change the timer icon or use text-only labels.
- [ ] **Themes**: Color coding for running/paused states.
- [ ] **Compact Mode**: Minimalist version of the timer for small screens.

## Workflow Features
- [ ] **Auto-Pause on Inactivity**: Detect when the user hasn't interacted with Blender for X minutes and pause the timer.
- [ ] **Session Logs**: View history of previous sessions within the sidebar.
- [ ] **Export to CSV/JSON**: Support for exporting time data for billing or tracking.
- [ ] **Multi-file aggregation**: Track total time across various project files.

## Technical Tasks
- [ ] Refactor modal to handle multiple window events better.
- [ ] Improve performance of UI redrawing.
- [ ] Add unit tests for time formatting logic.
