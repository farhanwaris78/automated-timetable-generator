# User guide

## Installing

| Platform | File | How |
|---|---|---|
| Windows 10/11 | `AutomatedTimetableGenerator-2.0.0-win64.msi` | Double-click → Next → Install. Launch from the Start menu. |
| Windows (no admin rights) | `TimetableGenerator-2.0.0-windows-x64.zip` | Extract anywhere, double-click `TimetableGenerator.exe`. |
| macOS | `TimetableGenerator-2.0.0-macos-*.dmg` | Open the DMG, drag the app to *Applications*. First launch: right-click → **Open**. |
| Ubuntu/Debian | `timetable-generator_2.0.0_amd64.deb` | `sudo apt install ./timetable-generator_2.0.0_amd64.deb` |
| Any Linux | `TimetableGenerator-2.0.0-linux-x86_64.tar.gz` | Extract and run `./start.sh` |

Nothing else is required — no Python, no SQL Server, no ODBC driver, no
internet connection.

A console window appears with the address the app is serving on, and your
default browser opens automatically. **Closing that window stops the app.**

---

## The screen at a glance

```
┌──────────────────────────────────────────────────────────────────────┐
│ Automated Timetable Generator            [Local database · 18 …] Help│
├───────────┬──────────────────────────────────────────────────────────┤
│ Courses   │ Days | Start | End | Class | Break | Building | Rooms  ▶ │
│ [search]  ├──────────────────────────────────────────────────────────┤
│ ▣ MLOps A │ Save to database · Load saved · Check clashes · PDF · CSV│
│ ▣ MLOps B ├──────────────────────────────────────────────────────────┤
│ ▣ ML A    │ Mon | Tue | Wed | Thu | Fri                              │
│ …         ├──────────────────────────────────────────────────────────┤
│           │ Room \ Time | 08:30-09:50 | 10:00-11:20 | …              │
│           │ A-108       | [ MLOps A ] |             |                │
└───────────┴──────────────────────────────────────────────────────────┘
```

---

## Step by step

1. **Set the working week** — days per week, the start/end of the teaching day,
   class length and the break between classes. Optionally restrict the grid to
   one building and cap how many rooms are shown.
2. **Generate grid.** Slots are identical for every day, so headers and cells
   always line up.
3. **Drag a course** from the left panel into a `room × time` cell.
   Every drop is checked by the server *before* it is accepted.
4. **Read the clash report.** If the placement is impossible you get a dialog
   listing every reason:

   | Type | Meaning |
   |---|---|
   | **room** | that room is already booked in an overlapping slot |
   | **instructor** | the teacher of this section already teaches elsewhere then |
   | **student** | students enrolled in both classes would collide — their roll numbers are listed |
   | **duplicate** | the same course-section is already scheduled at that time |
   | **capacity** | *(warning only)* more students than seats; the class is still placed |

5. **Adjust.** Drag a placed class to another cell to move it, drag it back to
   the left panel (or press ✕ / <kbd>Delete</kbd>) to unschedule it.
6. **Click a scheduled class** to see instructor, department, headcount, room
   and the complete list of enrolled roll numbers.
7. **Check all clashes** re-validates the entire week in one pass — do this
   before you publish.
8. **Save to database.** The whole week is written in a single transaction.
   If anything still clashes, nothing is saved and the offending cells turn red.
9. **Load saved** restores the stored week (grid settings included) next time
   you open the app.
10. **Export**: PDF (one page per day, A3 landscape), CSV (for Excel), or Print.

### Keyboard shortcuts

| Key | Action |
|---|---|
| <kbd>Ctrl</kbd>/<kbd>⌘</kbd>+<kbd>S</kbd> | Save to database |
| <kbd>Delete</kbd> | Remove the selected class |
| <kbd>Esc</kbd> | Close a dialog |

---

## Buttons that delete things

| Button | Effect |
|---|---|
| **Clear grid** | empties the on-screen week; the saved timetable is untouched |
| **Reset saved timetable** | deletes the timetable stored in the database |
| `--reset-database` (command line) | wipes everything and reloads the sample data |

---

## Where your data lives

| OS | Folder |
|---|---|
| Windows | `%LOCALAPPDATA%\TimetableGenerator\` |
| macOS | `~/Library/Application Support/TimetableGenerator/` |
| Linux | `~/.local/share/timetable-generator/` |

* `timetable.db` — everything you have entered (SQLite; open it with *DB Browser
  for SQLite* if you want to bulk-edit courses or students).
* `timetable.log` — rotating log, the first place to look if something misbehaves.

Back up = copy `timetable.db`. Factory reset = delete the folder.

---

## Command-line options

```
TimetableGenerator --help

  --host HOST            interface to bind (default 127.0.0.1)
  --port PORT            fixed port (default: first free port)
  --no-browser           do not open a browser
  --debug                verbose logs + Flask debugger
  --database-url URL     any SQLAlchemy URL (overrides .env)
  --data-dir PATH        keep the database and logs somewhere else
  --reset-database       recreate the database from the sample data, then exit
  --version
```

Sharing one timetable with colleagues on the LAN:

```
TimetableGenerator --host 0.0.0.0 --port 8080 --no-browser
```
Then they open `http://<your-ip>:8080/`.
*(There is no login screen — only do this on a trusted network.)*

---

## Using a central database instead of SQLite

Put a `.env` file next to the executable (see `.env.example`):

```ini
# Microsoft SQL Server (requires: pip install pyodbc, plus the ODBC driver)
DB_SERVER=SQL01
DB_NAME=timetable
DB_USER=sa
DB_PASSWORD=secret
DB_DRIVER=ODBC Driver 17 for SQL Server

# ... or anything SQLAlchemy understands
# TTG_DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/timetable
```

The schema is created automatically on first connect.

---

## FAQ

**Windows says "Windows protected your PC".**
The binary is not code-signed. Click *More info* → *Run anyway*, or install the
signed MSI if your institution provides one.

**macOS says the app is damaged.**
`xattr -dr com.apple.quarantine /Applications/TimetableGenerator.app`

**The browser did not open.**
Copy the URL printed in the console window into your browser.

**Nothing appears in the course list.**
The status pill in the header will say *Database offline*; check
`timetable.log`, or run `TimetableGenerator --reset-database`.

**Can I add my own courses/rooms/students?**
Yes — edit `timetable.db` with DB Browser for SQLite, or point the app at your
institution's database with `.env`. A built-in admin screen is on the roadmap.
