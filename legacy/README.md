# Legacy reference files

`SQL_TimeTable_original.sql` is the Microsoft SQL Server script from version 1.
It is **not used by the application any more** — the schema now lives in
`timetable/db.py` and is created automatically on any backend, and the data it
contained was extracted into `timetable/seed_data.json`.

It is kept for reference (and because the defects it contains are documented in
`docs/BUGS_AND_FIXES.md` §D). Do not run it against a fresh database expecting
the app to work: the table and column names differ.
