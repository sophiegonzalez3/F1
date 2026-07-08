"""
F1 Dashboard – tab modules
==========================
Each tab of the app lives (or will live) in its own module here. The
migration recipe, demonstrated by `tabs/upgrades.py`:

1. A tab module imports UI building blocks from `components` and reads the
   loaded dataset through `import state` (`state.laps`, `state.SESSIONS`, …)
   — never from `app`.
2. Anything the tab needs from app-level context that hasn't been extracted
   yet (e.g. championship-order helpers) is passed **as a function argument**
   by the render router in app.py, not imported — that keeps the dependency
   arrow pointing app → tabs and avoids import cycles.
3. Callbacks belonging to a tab use `dash.callback` (module-level, no app
   object needed) once they move.
4. app.py's render() just calls the module's `tab_*` builder.

New tabs and features should start here rather than growing app.py further.
"""
