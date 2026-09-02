/*
 * Regression test for the reported Save-As bug: "the naming of saved as
 * project is greyed out, i am not able to name it properly here".
 *
 * The project-name input must ALWAYS be enabled/editable when the dialog is
 * opened, and a Save-As that lands on a read-only folder must hop to a
 * writable folder rather than disable the Save button and strand the user.
 *
 * It runs the real timetable/static/app.js against a JSDOM copy of
 * timetable/templates/index.html, exactly like drag-and-drop.test.js.
 */
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const REPO = path.resolve(__dirname, "..", "..");
const html = fs.readFileSync(path.join(REPO, "timetable/templates/index.html"), "utf8");
const js = fs.readFileSync(path.join(REPO, "timetable/static/app.js"), "utf8");

const plain = html
  .replace(/\{%[\s\S]*?%\}/g, "")
  .replace(/\{\{[^}]*\}\}/g, "x")
  .replace(/<script[\s\S]*?<\/script>/g, "");

const dom = new JSDOM(plain, { runScripts: "outside-only", pretendToBeVisual: true, url: "http://localhost/" });
const { window } = dom;

let passed = 0;
let failed = 0;
function check(name, ok) {
  console.log("  " + (ok ? "PASS" : "FAIL") + "  " + name);
  if (ok) passed++; else failed++;
}

// The home folder is read-only (mimicking the reported bug); the Documents
// shortcut is writable, so the fallback should land there.
let fsListCalls = 0;
window.fetch = function (url, init) {
  let payload = {};
  if (url.startsWith("/api/project")) {
    payload = { name: "Untitled project", path: null, recent: [], home: "/home/u", suffix: ".ttproj", roots: [], places: [], export_dir: "/home/u" };
  } else if (url.startsWith("/api/fs/list")) {
    fsListCalls++;
    let requested = url.match(/[?&]path=([^&]+)/);
    let p = requested ? decodeURIComponent(requested[1]) : "/home/u";
    // Only the Documents shortcut is writable; everything else (home, "", C:) is not.
    let writable = p === "/home/u/Documents";
    payload = {
      ok: true, path: p, parent: "/", can_up: true, writable: writable,
      roots: [{ name: "C:", path: "C:" }],
      places: [{ name: "Documents", path: "/home/u/Documents" }],
      dirs: [], files: [], breadcrumbs: [{ name: "u", path: p }],
    };
  } else if (url.startsWith("/api/fs/roots")) {
    payload = { roots: [{ name: "C:", path: "C:" }], places: [{ name: "Documents", path: "/home/u/Documents" }], home: "/home/u" };
  } else if (url.startsWith("/api/rooms")) payload = [];
  else if (url.startsWith("/api/courses")) payload = [];
  else if (url.startsWith("/api/instructors")) payload = [];
  else if (url.startsWith("/api/buildings")) payload = [];
  else if (url.startsWith("/api/settings")) payload = {};
  else if (url.startsWith("/api/timetable/validate")) payload = { ok: true, conflicts: [] };
  else if (url.startsWith("/api/timetable")) payload = { entries: [], weekdays: [] };
  else if (url.startsWith("/api/health")) payload = { backend: "sqlite", stats: {} };
  else payload = { ok: true };
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

window.eval(js);
window.document.dispatchEvent(new window.Event("DOMContentLoaded"));

setTimeout(() => {
  const $ = (s) => window.document.querySelector(s);
  const saveAs = window.document.querySelector("[data-action='saveProjectAs']");
  saveAs.click();

  setTimeout(() => {
    const input = $("#projectNameInput");
    const row = window.document.querySelector(".project-name-row");
    const primary = $("#projectPrimaryBtn");
    const dialog = $("#projectDialog");
    const preview = $("#fsSaveTarget");

    check("save-as dialog is open", dialog && dialog.hidden === false);
    check("project-name row is visible", row && row.hidden === false);
    check("project-name input is ENABLED (not greyed out)", input && input.disabled === false);
    check("project-name input is not readOnly", input && input.readOnly === false);
    // The home folder was read-only, so the app should auto-hop to Documents.
    check("Save button is ENABLED after hopping to a writable folder", primary && primary.disabled === false);
    check("save target switched to the writable folder", preview &&
      preview.textContent.indexOf("/home/u/Documents") !== -1);
    check("folder was re-listed (read-only -> writable fallback)", fsListCalls >= 2);

    process.exit(failed ? 1 : 0);
  }, 500);
}, 300);
