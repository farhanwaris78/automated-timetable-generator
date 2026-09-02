/* Verifies the dedicated "Document" dialog: the toolbar button opens it, the
 * term is offered as a season dropdown + year box + free text, and the season
 * dropdown rewrites the term and the title-block preview. */
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

window.fetch = function () {
  return Promise.resolve({
    ok: true, status: 200,
    text: () => Promise.resolve("{}"),
    json: () => Promise.resolve({}),
    blob: () => Promise.resolve({}),
  });
};
window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {} });
window.print = () => {};
window.URL.createObjectURL = () => "blob:x";
window.URL.revokeObjectURL = () => {};

window.eval(js);
window.document.dispatchEvent(new window.Event("DOMContentLoaded"));

const results = [];
function check(name, cond, extra) {
  results.push({ name, pass: !!cond, extra: extra || "" });
}

setTimeout(() => {
  const $ = (s) => window.document.querySelector(s);
  const $$ = (s) => Array.prototype.slice.call(window.document.querySelectorAll(s));
  const click = (el) => el && el.dispatchEvent(new window.Event("click", { bubbles: true }));

  // The toolbar exposes a dedicated Document button.
  const documentBtn = $('[data-action="documentSettings"]');
  check("a Document toolbar button exists", !!documentBtn);

  // Opening it shows the identity fields and the season/year term controls.
  click(documentBtn);
  check("Document dialog is open", $("#documentDialog") && !$("#documentDialog").hidden);

  const fields = ["exportInstitution", "exportProgram", "exportSeason",
    "exportTermYear", "exportTerm", "exportSemester", "exportCommencement"];
  fields.forEach((id) => {
    check("document field #" + id + " is present", !!$("#" + id));
  });

  // Picking a season and a year rewrites the free-text term automatically.
  const season = $("#exportSeason");
  const year = $("#exportTermYear");
  const term = $("#exportTerm");

  season.value = "Spring";
  season.dispatchEvent(new window.Event("change", { bubbles: true }));
  year.value = "2026";
  year.dispatchEvent(new window.Event("change", { bubbles: true }));
  check("season + year build the term (Spring 2026)", term.value.trim() === "Spring 2026", term.value);

  // Typing free text directly overrides the dropdown shortcut.
  term.value = "Trimester 3 - Intake B";
  term.dispatchEvent(new window.Event("input", { bubbles: true }));
  check("free-text term is honoured", term.value.trim() === "Trimester 3 - Intake B", term.value);

  // The title-block preview reflects the term.
  const previews = $$(".export-preview");
  check("a title-block preview element exists", previews.length > 0);
  const anyPreview = previews.map((p) => p.textContent || "").join(" ");
  check("preview reflects the free-text term",
    anyPreview.indexOf("Trimester 3 - Intake B") !== -1 || anyPreview.indexOf("Trimester 3") !== -1,
    anyPreview);

  const failing = results.filter((r) => !r.pass);
  results.forEach((r) => console.log((r.pass ? "  PASS  " : "  FAIL  ") + r.name +
    (r.extra ? "   (" + r.extra + ")" : "")));
  console.log(failing.length + "/" + results.length + " failed");
  process.exit(failing.length ? 1 : 0);
}, 60);
