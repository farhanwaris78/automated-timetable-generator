# Front-end tests

`drag-and-drop.test.js` runs the real `timetable/static/app.js` against a
JSDOM copy of the real `index.html` and exercises the drag & drop engine.

It reproduces the bug reported against 3.0.0 — *"it does not allow to drop the
courses into the time table"* — and locks in the fix:

* the drag source advertises `effectAllowed = "copyMove"` and the drop target
  answers with a **compatible** `dropEffect` (the old build said `copy` vs
  `move`, which makes the browser reject the drop outright);
* `dragenter` **and** `dragover` both call `preventDefault()`;
* the payload survives even when `dataTransfer.getData()` returns `""`, which
  is what the WebView2 / WKWebView desktop shells do;
* occupied slots are flagged before the drop, highlights never get stuck, and
  keyboard users can pick up / place a class with Enter.

Running the same test against the 3.0.0 build fails 4 checks, including
`COURSE WAS ACTUALLY DROPPED INTO THE TIMETABLE (placed=0)`.

## Run

```bash
cd tests/frontend
npm install
npm test
```
