# Changelog

## 2.1.0 — data management, shifts, Excel, undo/redo

**Manage your own data (no SQL needed)**
* Add / edit / delete **teachers** (name, email, department, shift) — <kbd>Alt+T</kbd>
* Add / edit / delete **classrooms** (number, building, capacity, Classroom/Lab/Hall) — <kbd>Alt+R</kbd>;
  typing an unknown building name creates the building
* Add / edit / delete **courses with course codes**, credit hours, colour and
  sections with their teacher — <kbd>Alt+C</kbd>
* **Buildings** (<kbd>Alt+B</kbd>) and **sections** (<kbd>Alt+S</kbd>)
* **Manage data** screen (<kbd>Alt+M</kbd>): searchable Teachers / Classrooms / Courses tables
* Referential safety: the app refuses to delete a teacher who still teaches, a
  room or course used by the saved timetable, or a non-empty building

**Morning & evening shifts**
* Each shift keeps its own hours; both share rooms, teachers and courses
* Clash detection runs across shifts; one save stores both
* `shift` column added to `timetable_entries` (auto-migrated)

**Full week**
* 1–7 days; day tabs, `1`…`7` shortcuts, and per-day class counters

**Excel export**
* `POST /api/export/xlsx` → **one worksheet per day**, colour-coded, frozen
  panes, landscape fit-to-width, plus a filterable **Summary** sheet and a
  **By Teacher** sheet — <kbd>Ctrl+E</kbd>
* Works on the on-screen grid as well as the saved timetable

**Undo / redo**
* 100 steps covering placement, move, delete, clear, load and auto-fill
* Toolbar buttons + <kbd>Ctrl+Z</kbd> / <kbd>Ctrl+Y</kbd> / <kbd>Ctrl+Shift+Z</kbd>

**Discoverable shortcuts**
* One registry in `app.js` drives the key handler, every button tooltip **and**
  the <kbd>F1</kbd> shortcut dialog — the documentation cannot drift from the code

**Auto-fill**
* Greedy scheduler places every unscheduled section in a conflict-free slot
  (all 45 sample sections, verified clash-free by the independent validator)

**Packaging**
* `build.py --engine auto|pyinstaller|cxfreeze` with automatic fallback when the
  interpreter has no shared `libpython`; `portable`/`deb`/`dmg` handle both
  single-file and folder layouts
* openpyxl added to both freezer recipes

**Schema**
* Additive auto-migration on start-up: `courses.code`, `courses.credit_hours`,
  `instructors.email/department/shift`, `rooms.room_type`, `timetable_entries.shift`
* Course codes are back-filled for pre-existing databases

**Tests:** 35 → **56**.

## 2.0.0 — rewrite

34 defects fixed and the project turned into a zero-configuration
cross-platform desktop application. See `docs/BUGS_AND_FIXES.md`.
