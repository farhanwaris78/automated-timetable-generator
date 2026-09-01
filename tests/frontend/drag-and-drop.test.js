/* Verifies the real app.js drag & drop against a JSDOM DOM.
 * Reproduces the exact failure the user reported: dropping a course card
 * onto a grid cell had no effect. */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const REPO = path.resolve(__dirname, "..", "..");
const html = fs.readFileSync(path.join(REPO, "timetable/templates/index.html"), "utf8");
const js = fs.readFileSync(path.join(REPO, "timetable/static/app.js"), "utf8");

// Strip Jinja bits so JSDOM gets plain HTML.
const plain = html
  .replace(/\{\%[\s\S]*?\%\}/g, "")
  .replace(/\{\{[^}]*\}\}/g, "x")
  .replace(/<script[\s\S]*?<\/script>/g, "");

const ROOMS = [
  { id: 1, label: "A-101", building_id: 1, room_type: "Classroom", capacity: 40, room_number: "101" },
  { id: 2, label: "A-102", building_id: 1, room_type: "Classroom", capacity: 30, room_number: "102" },
];
const COURSES = [
  { id: 101, code: "CS-101", name: "Programming", section: "A", kind: "theory", instructor: "Dr A",
    num_students: 25, color: "#a9d2e1", semester: 1, credit_hours: 3, department: "CS", hours: 1 },
  { id: 102, code: "CS-102", name: "Databases", section: "B", kind: "theory", instructor: "Dr B",
    num_students: 20, color: "#e1d2a9", semester: 1, credit_hours: 3, department: "CS", hours: 1 },
];

const dom = new JSDOM(plain, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
const { window } = dom;

// ---- minimal fetch stub -------------------------------------------------
window.fetch = function (url, init) {
  const body = { ok: true };
  let payload = {};
  if (url.startsWith("/api/rooms")) payload = ROOMS;
  else if (url.startsWith("/api/courses")) payload = COURSES;
  else if (url.startsWith("/api/instructors")) payload = [];
  else if (url.startsWith("/api/buildings")) payload = [{ id: 1, name: "A" }];
  else if (url.startsWith("/api/settings")) payload = {};
  else if (url.startsWith("/api/timetable/validate")) payload = { ok: true, conflicts: [] };
  else if (url.startsWith("/api/timetable")) payload = { entries: [], weekdays: [] };
  else if (url.startsWith("/api/project")) payload = { name: "T", path: null, recent: [], home: "/home/u", suffix: ".ttproj", roots: [], places: [] };
  else if (url.startsWith("/api/health")) payload = { backend: "sqlite", stats: {} };
  else payload = body;
  return Promise.resolve({
    ok: true, status: 200,
    text: () => Promise.resolve(JSON.stringify(payload)),
    json: () => Promise.resolve(payload),
    blob: () => Promise.resolve({}),
  });
};
window.URL.createObjectURL = () => "blob:x";
window.URL.revokeObjectURL = () => {};
window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
window.print = () => {};

// ---- DataTransfer polyfill that mimics real browser restrictions --------
class FakeDataTransfer {
  constructor() { this._data = {}; this.effectAllowed = "uninitialized"; this.dropEffect = "none"; this._protected = false; }
  setData(fmt, val) { this._data[fmt] = String(val); }
  /* Real browsers return "" for getData() during dragover/dragenter (the
     "protected mode"), and some desktop WebViews return "" during drop too.
     Simulating that is the whole point of this test. */
  getData(fmt) { return this._protected ? "" : (this._data[fmt] || ""); }
  setDragImage() {}
}

function fire(node, type, dt) {
  const ev = new window.Event(type, { bubbles: true, cancelable: true });
  if (dt) ev.dataTransfer = dt;
  node.dispatchEvent(ev);
  return ev;
}

// ---- run the app --------------------------------------------------------
window.eval(js);
window.document.dispatchEvent(new window.Event("DOMContentLoaded"));

const results = [];
function check(name, cond, extra) {
  results.push({ name, pass: !!cond, extra: extra || "" });
}

setTimeout(() => {
  const $ = (s) => window.document.querySelector(s);
  const $$ = (s) => Array.from(window.document.querySelectorAll(s));

  // The grid must have rendered with drop targets.
  const cells = $$("td.slot");
  check("grid rendered with slot cells", cells.length > 0, `cells=${cells.length}`);

  const cards = $$(".course-card");
  check("course cards rendered", cards.length > 0, `cards=${cards.length}`);
  check("course card is draggable", cards[0] && cards[0].draggable === true);

  // ---------- THE BUG: drop a catalogue card onto an empty cell ----------
  const card = cards[0];
  const cell = cells[0];
  const dt = new FakeDataTransfer();

  fire(card, "dragstart", dt);
  check("dragstart sets a compatible effectAllowed",
    dt.effectAllowed === "copyMove", `effectAllowed=${dt.effectAllowed}`);

  // Browsers protect the payload during dragenter/dragover.
  dt._protected = true;
  const enterEv = fire(cell, "dragenter", dt);
  check("dragenter is preventDefault()ed (cell accepts the drag)", enterEv.defaultPrevented);
  const overEv = fire(cell, "dragover", dt);
  check("dragover is preventDefault()ed", overEv.defaultPrevented);
  check("dropEffect agrees with effectAllowed",
    dt.dropEffect === "copy", `dropEffect=${dt.dropEffect}`);
  check("cell shows the drop highlight", cell.classList.contains("dragover"));

  // Simulate the WebView2/WKWebView case: getData() is empty even on drop.
  const dropEv = fire(cell, "drop", dt);
  check("drop is preventDefault()ed", dropEv.defaultPrevented);

  const placedAfter = $$(".placed");
  check("COURSE WAS ACTUALLY DROPPED INTO THE TIMETABLE",
    placedAfter.length === 1, `placed=${placedAfter.length}`);
  check("highlight cleared after drop", !cell.classList.contains("dragover"));

  fire(card, "dragend", dt);

  // ---------- move an already-placed class to another cell ----------
  const placedNode = $$(".placed")[0];
  check("a placed class exists to move", !!placedNode);
  const dt2 = new FakeDataTransfer();
  fire(placedNode, "dragstart", dt2);
  // The grid re-renders after every change, so cells must be re-queried.
  const cells2 = $$("td.slot");
  const targetCell = cells2.find((c) => !c.querySelector(".placed"));
  dt2._protected = true;
  fire(targetCell, "dragenter", dt2);
  check("move: dropEffect is 'move'", dt2.dropEffect === "move", `dropEffect=${dt2.dropEffect}`);
  const targetKey = targetCell.dataset.start + "|" + targetCell.dataset.roomId;
  fire(targetCell, "drop", dt2);
  const movedInto = $$("td.slot").find((c) => c.dataset.start + "|" + c.dataset.roomId === targetKey);
  check("placed class moved to the new cell",
    movedInto && movedInto.querySelector(".placed") !== null);
  fire(placedNode, "dragend", dt2);

  // ---------- occupied cell must be flagged before the drop ----------
  const occupiedCell = $$("td.slot").find((c) => c.querySelector(".placed"));
  check("an occupied cell exists", !!occupiedCell);
  const card2 = $$(".course-card")[0];
  const dt3 = new FakeDataTransfer();
  fire(card2, "dragstart", dt3);
  dt3._protected = true;
  if (occupiedCell) fire(occupiedCell, "dragenter", dt3);
  check("occupied cell warns with drop-blocked", occupiedCell && occupiedCell.classList.contains("drop-blocked"));
  fire(card2, "dragend", dt3);

  // ---------- dragging a placed class back to the sidebar unschedules ----
  const list = $("#coursesList");
  const stillPlaced = $$(".placed")[0];
  check("a placed class exists for the unschedule test", !!stillPlaced);
  const dt4 = new FakeDataTransfer();
  if (stillPlaced) fire(stillPlaced, "dragstart", dt4);
  else return finish();
  dt4._protected = true;
  const sidebarOver = fire(list, "dragover", dt4);
  check("sidebar accepts the drag", sidebarOver.defaultPrevented);
  fire(list, "drop", dt4);
  check("dragging back to the list unschedules the class", $$(".placed").length === 0);

  // ---------- keyboard accessibility: pick up then place ----------
  const kbCard = $$(".course-card")[0];
  kbCard.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  check("keyboard pick-up marks the card as carried", kbCard.classList.contains("is-carried"));
  const freeCell = $$("td.slot").find((c) => !c.querySelector(".placed"));
  freeCell.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
  check("keyboard placement schedules the class", $$(".placed").length === 1);

  // ---------- stale highlights must never survive a cancelled drag -------
  const c2 = $$(".course-card")[0];
  const dt5 = new FakeDataTransfer();
  fire(c2, "dragstart", dt5);
  dt5._protected = true;
  const someCell = $$("td.slot")[3];
  fire(someCell, "dragenter", dt5);
  fire(c2, "dragend", dt5);
  check("cancelled drag leaves no stale highlight",
    $$(".slot.dragover, .slot.drop-blocked").length === 0);

  // ---- report ----
  finish();

  function finish() {
  let failed = 0;
  for (const r of results) {
    if (!r.pass) failed++;
    console.log(`${r.pass ? "  PASS" : "  FAIL"}  ${r.name}${r.extra ? "   (" + r.extra + ")" : ""}`);
  }
  console.log(`\n${results.length - failed}/${results.length} checks passed`);
  process.exit(failed ? 1 : 0);
  }
}, 400);
