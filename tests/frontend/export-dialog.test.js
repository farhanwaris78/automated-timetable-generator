/* Verifies the Export & share dialog really exposes the document-identity
 * options (institution, term, program, semester, commencement) in the GUI,
 * and that the live title-block preview reacts as the user types. */
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

// ---- run the app ---------------------------------------------------------
window.eval(js);
window.document.dispatchEvent(new window.Event("DOMContentLoaded"));

const results = [];
function check(name, cond, extra) {
  results.push({ name, pass: !!cond, extra: extra || "" });
}

setTimeout(() => {
  const $ = (s) => window.document.querySelector(s);

  // Every document-identity option must be present in the real GUI.
  [
    "exportInstitution", "exportTerm", "exportProgram",
    "exportSemester", "exportCommencement", "exportLayout",
  ].forEach((id) => {
    check("identity option #" + id + " is present in the GUI", !!$("#" + id));
  });

  const preview = $("#exportPreview");
  check("live export preview element exists", !!preview);

  // Typing into the identity fields must update the preview sentence.
  const term = $("#exportTerm");
  term.value = "Spring 2026";
  term.dispatchEvent(new window.Event("input", { bubbles: true }));
  const institution = $("#exportInstitution");
  institution.value = "University of Education";
  institution.dispatchEvent(new window.Event("input", { bubbles: true }));
  const program = $("#exportProgram");
  program.value = "BS Chemistry (Post ADP)";
  program.dispatchEvent(new window.Event("input", { bubbles: true }));

  check("preview shows the typed academic term",
    (preview.textContent || "").indexOf("Spring 2026") !== -1, preview.textContent);
  check("preview shows the typed institution",
    (preview.textContent || "").indexOf("University of Education") !== -1, preview.textContent);
  check("preview shows the typed program",
    (preview.textContent || "").indexOf("BS Chemistry (Post ADP)") !== -1, preview.textContent);

  const failing = results.filter((r) => !r.pass);
  results.forEach((r) => console.log((r.pass ? "  PASS  " : "  FAIL  ") + r.name +
    (r.extra ? "   (" + r.extra + ")" : "")));
  console.log(failing.length + "/" + results.length + " checks passed");
  process.exit(failing.length ? 1 : 0);
}, 60);
