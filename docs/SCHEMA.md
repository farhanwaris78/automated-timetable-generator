# Data model

The schema is declared once in `timetable/db.py` (SQLAlchemy Core) and created
automatically on any supported backend: SQLite (default), Microsoft SQL Server,
PostgreSQL or MySQL. The original `SQL_TimeTable.sql` is kept for historical
reference only — see `docs/BUGS_AND_FIXES.md` §D for why it was replaced.

```
buildings ──< rooms ──────────┐
                              │
courses ──< course_sections ──┼──< timetable_entries
                │             │
                ├──< courses_taught_by >── instructors
                │
students ──< enrollments >────┘
```

| Table | Key | Notes |
|---|---|---|
| `courses` | `id` | `name`, `color` (chip colour), `department`, `credit_hours`, **`semester`** (0 = unassigned), **`has_lab`** (0/1), **`lab_credit_hours`** |
| `course_sections` | `(course_id, section)` | the schedulable unit |
| `instructors` | `id` | |
| `courses_taught_by` | `(instructor_id, course_id, section)` | who teaches which section |
| `buildings` | `id` | |
| `rooms` | `id` | `room_number` is text (`"108"`), unique per building, plus `capacity` |
| `students` | `roll_number` | |
| `enrollments` | `(roll_number, course_id, section)` | drives student-clash detection |
| `timetable_entries` | `id` | `day` 1–7, `start_time`/`end_time` as `"HH:MM"` 24 h, `room_id`, `course_id`, `section`, **`kind`** (`theory` \| `lab`); **unique on `(day, start_time, room_id)`** |
| `app_settings` | `key` | grid preferences, so the app reopens as you left it |

## Design decisions

* **`"HH:MM"` strings, not `DATETIME`.** A timetable slot is a time of day, not
  a moment in time; strings sort correctly, survive every backend and never
  drift with time zones or DST.
* **Half-open intervals.** Overlap is `a.start < b.end AND b.start < a.end`, so
  a class ending at 10:20 and one starting at 10:20 do **not** clash.
* **`day` as an integer 1–7** (Monday = 1) — locale-independent; names are
  rendered in the UI.
* **The uniqueness constraint on `(day, start_time, room_id)`** makes a room
  double-booking impossible at the storage layer, even if a bug slipped past
  the validation layer.
* **Cascade deletes** everywhere, so removing a course cannot leave orphaned
  timetable rows.
* **Every write is parameterised** and wrapped in a transaction.

## Labs and semesters

A **class** is a `(course, section, kind)` triple: the lecture and the lab of one
section are scheduled separately but belong to the same students, so they may
never overlap. `courses.semester` groups sections into student batches — a
`(semester, section)` pair can only be in one room at a time, which is the
*semester clash* rule. All four columns were added by additive migrations, so an
existing database upgrades in place and every pre-existing entry reads as `theory`.

## Seed data

`timetable/seed_data.json` holds the dataset extracted from the original SQL
script (18 courses, 45 sections, 27 instructors, 3 buildings, 36 rooms,
20 students) plus a realistic 5-course load per student — 106 enrolments —
so student-clash detection is demonstrable out of the box. It is loaded only
when the `courses` table is empty, so your own data is never overwritten.
