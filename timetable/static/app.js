/* =========================================================================
 * Automated Timetable Generator - front-end controller
 * Vanilla ES2017+, zero third-party runtime dependencies (html2pdf is
 * bundled locally and optional).  Runs fully offline.
 * ========================================================================= */
(function () {
  "use strict";

  var WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  var HISTORY_LIMIT = 100;

  /* ------------------------- keyboard shortcut map ----------------------- */
  /* One registry drives the handler, the button tooltips AND the help dialog,
     so what the user reads is always what the app actually does.            */
  var SHORTCUTS = [
    { group: "Add data", combo: "Alt+T", action: "addTeacher", label: "Add teacher" },
    { group: "Add data", combo: "Alt+R", action: "addRoom", label: "Add classroom" },
    { group: "Add data", combo: "Alt+C", action: "addCourse", label: "Add course (with code)" },
    { group: "Add data", combo: "Alt+B", action: "addBuilding", label: "Add building" },
    { group: "Add data", combo: "Alt+S", action: "addSection", label: "Add section to a course" },
    { group: "Add data", combo: "Alt+M", action: "manage", label: "Manage teachers / rooms / courses" },

    { group: "Edit", combo: "Ctrl+Z", action: "undo", label: "Undo" },
    { group: "Edit", combo: "Ctrl+Y", action: "redo", label: "Redo" },
    { group: "Edit", combo: "Ctrl+Shift+Z", action: "redo", label: "Redo (alternative)" },
    { group: "Edit", combo: "Delete", action: "removeSelected", label: "Remove the selected class" },
    { group: "Edit", combo: "Ctrl+Backspace", action: "clearGrid", label: "Clear the whole grid" },

    { group: "Timetable", combo: "Ctrl+G", action: "generate", label: "Generate the grid" },
    { group: "Timetable", combo: "Ctrl+S", action: "save", label: "Save to database" },
    { group: "Timetable", combo: "Ctrl+O", action: "load", label: "Load the saved timetable" },
    { group: "Timetable", combo: "Ctrl+K", action: "validate", label: "Check every clash" },
    { group: "Timetable", combo: "Ctrl+Shift+A", action: "autofill", label: "Auto-fill the remaining sections" },

    { group: "Export", combo: "Ctrl+E", action: "exportExcel", label: "Export to Excel (one sheet per day)" },
    { group: "Export", combo: "Alt+P", action: "exportPdf", label: "Export to PDF" },
    { group: "Export", combo: "Alt+V", action: "exportCsv", label: "Export to CSV" },
    { group: "Export", combo: "Ctrl+P", action: "print", label: "Print" },

    { group: "View", combo: "Alt+1", action: "shiftMorning", label: "Switch to the morning shift" },
    { group: "View", combo: "Alt+2", action: "shiftEvening", label: "Switch to the evening shift" },
    { group: "View", combo: "1 … 7", action: null, label: "Jump to Monday … Sunday" },
    { group: "View", combo: "Ctrl+F", action: "focusSearch", label: "Search the course list" },
    { group: "View", combo: "Alt+H", action: "toggleSidebar", label: "Show / hide the course panel" },
    { group: "View", combo: "F1", action: "shortcuts", label: "This shortcut list" },
    { group: "View", combo: "Esc", action: null, label: "Close a dialog" }
  ];

  var DEFAULT_SHIFTS = {
    morning: { start: "08:30", end: "13:00" },
    evening: { start: "13:30", end: "19:00" }
  };

  var state = {
    courses: [],
    rooms: [],
    buildings: [],
    instructors: [],
    shift: "morning",
    shiftHours: JSON.parse(JSON.stringify(DEFAULT_SHIFTS)),
    days: 5,
    duration: 80,
    breakTime: 10,
    roomLimit: 12,
    building: "",
    roomType: "",
    slots: { morning: [], evening: [] },
    gridRooms: [],
    activeDay: 1,
    placements: [],
    conflicts: {},
    selectedUid: null,
    dirty: false,
    history: [],
    future: [],
    manageTab: "teachers"
  };

  var uidSeq = 1;
  function nextUid() { return "p" + (uidSeq++); }

  /* ------------------------------- helpers ------------------------------- */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function toMinutes(hhmm) {
    var parts = String(hhmm).split(":");
    return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
  }

  function fromMinutes(total) {
    total = ((total % 1440) + 1440) % 1440;
    var h = Math.floor(total / 60), m = total % 60;
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function to12h(hhmm) {
    var mins = toMinutes(hhmm), h = Math.floor(mins / 60), m = mins % 60;
    var suffix = h < 12 ? "AM" : "PM";
    var display = h % 12 || 12;
    return (display < 10 ? "0" : "") + display + ":" + (m < 10 ? "0" : "") + m + " " + suffix;
  }

  function readableInk(hex) {
    var c = String(hex || "").replace("#", "");
    if (c.length === 3) c = c[0] + c[0] + c[1] + c[1] + c[2] + c[2];
    if (c.length !== 6) return "#16223d";
    var r = parseInt(c.slice(0, 2), 16), g = parseInt(c.slice(2, 4), 16), b = parseInt(c.slice(4, 6), 16);
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? "#16223d" : "#ffffff";
  }

  function escapeHtml(value) {
    return String(value === undefined || value === null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function titleCase(value) { return String(value || "").charAt(0).toUpperCase() + String(value || "").slice(1); }

  /* ------------------------------- network -------------------------------- */
  function api(path, options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: { "Accept": "application/json" } };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    if (options.raw) init.headers.Accept = "*/*";

    return fetch(path, init).then(function (response) {
      if (options.raw) {
        if (!response.ok) {
          return response.text().then(function (raw) {
            var data = {};
            try { data = JSON.parse(raw); } catch (err) { data = { message: raw }; }
            var error = new Error(data.message || ("HTTP " + response.status));
            error.status = response.status;
            throw error;
          });
        }
        return response.blob();
      }
      return response.text().then(function (raw) {
        var data = null;
        if (raw) { try { data = JSON.parse(raw); } catch (err) { data = { message: raw }; } }
        if (!response.ok) {
          var error = new Error((data && (data.message || data.error)) || ("HTTP " + response.status));
          error.status = response.status;
          error.payload = data;
          throw error;
        }
        return data;
      });
    });
  }

  function downloadBlob(blob, filename) {
    var url = URL.createObjectURL(blob);
    var link = el("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  /* -------------------------------- toasts -------------------------------- */
  function toast(title, message, kind, timeout) {
    var host = $("#toasts");
    var node = el("div", "toast " + (kind || "info"));
    node.appendChild(el("strong", null, title));
    if (message) node.appendChild(el("span", null, message));
    host.appendChild(node);
    window.setTimeout(function () {
      node.style.transition = "opacity .25s";
      node.style.opacity = "0";
      window.setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 260);
    }, timeout || (kind === "error" ? 8000 : 4000));
  }

  /* ------------------------------- dialogs -------------------------------- */
  function openDialog(id) {
    var dialog = $(id);
    if (!dialog) return;
    dialog.hidden = false;
    var focusable = dialog.querySelector("input:not([type=hidden]), select, textarea, button");
    if (focusable) window.setTimeout(function () { focusable.focus(); }, 30);
  }

  function closeDialogs() { $$(".dialog").forEach(function (dialog) { dialog.hidden = true; }); }

  /* ------------------------------ undo / redo ----------------------------- */
  function snapshot() {
    state.history.push(JSON.stringify(state.placements));
    if (state.history.length > HISTORY_LIMIT) state.history.shift();
    state.future.length = 0;
    updateHistoryButtons();
  }

  function restore(json) {
    state.placements = JSON.parse(json);
    state.conflicts = {};
    state.selectedUid = null;
    renderAll();
    revalidateAll({ silent: true });
  }

  function undo() {
    if (!state.history.length) { toast("Nothing to undo", "", "info", 2000); return; }
    state.future.push(JSON.stringify(state.placements));
    restore(state.history.pop());
    state.dirty = true;
    updateHistoryButtons();
    toast("Undone", "", "info", 1600);
  }

  function redo() {
    if (!state.future.length) { toast("Nothing to redo", "", "info", 2000); return; }
    state.history.push(JSON.stringify(state.placements));
    restore(state.future.pop());
    state.dirty = true;
    updateHistoryButtons();
    toast("Redone", "", "info", 1600);
  }

  function updateHistoryButtons() {
    $("#undoBtn").disabled = !state.history.length;
    $("#redoBtn").disabled = !state.future.length;
  }

  /* ------------------------------- catalogue ------------------------------ */
  function courseKey(courseId, section) { return courseId + ":" + section; }

  function findCourse(courseId, section) {
    for (var i = 0; i < state.courses.length; i++) {
      if (state.courses[i].id === courseId && state.courses[i].section === section) return state.courses[i];
    }
    return null;
  }

  function placedKeys() {
    var set = {};
    state.placements.forEach(function (p) { set[courseKey(p.course_id, p.section)] = true; });
    return set;
  }

  function renderCourses() {
    var host = $("#coursesList");
    var query = ($("#courseSearch").value || "").trim().toLowerCase();
    var hidePlaced = $("#hidePlaced").checked;
    var placed = placedKeys();

    host.innerHTML = "";
    var shown = 0;

    state.courses.forEach(function (course) {
      var isPlaced = !!placed[courseKey(course.id, course.section)];
      if (hidePlaced && isPlaced) return;
      var haystack = [course.code, course.name, course.section, course.instructor, course.department]
        .join(" ").toLowerCase();
      if (query && haystack.indexOf(query) === -1) return;

      var card = el("div", "course-card" + (isPlaced ? " is-placed" : ""));
      card.draggable = true;
      card.style.backgroundColor = course.color;
      card.style.color = readableInk(course.color);
      card.dataset.courseId = course.id;
      card.dataset.section = course.section;
      card.title = (course.code ? course.code + " · " : "") + course.name + " - " + course.section +
        "\nTeacher: " + course.instructor + "\nStudents: " + course.num_students;

      var title = el("div", "cc-title");
      if (course.code) title.appendChild(el("span", "cc-code", course.code));
      title.appendChild(document.createTextNode(course.name + " - " + course.section));
      card.appendChild(title);

      var meta = el("div", "cc-meta");
      meta.appendChild(el("span", null, course.instructor));
      meta.appendChild(el("span", null, course.num_students + " std"));
      card.appendChild(meta);

      card.addEventListener("dragstart", function (event) {
        event.dataTransfer.effectAllowed = "copy";
        event.dataTransfer.setData("text/plain", JSON.stringify({
          type: "catalogue", course_id: course.id, section: course.section
        }));
      });

      host.appendChild(card);
      shown++;
    });

    if (!shown) {
      host.appendChild(el("p", "empty", state.courses.length
        ? "No course matches your search."
        : "No courses yet - press Alt+C to add one."));
    }
    $("#courseCount").textContent = String(shown);
  }

  /* ---------------------------- slot generation --------------------------- */
  function buildSlots(startTime, endTime, duration, breakTime) {
    var slots = [];
    var cursor = toMinutes(startTime);
    var end = toMinutes(endTime);
    var guard = 0;

    if (!(duration > 0)) throw new Error("Class duration must be greater than zero.");
    if (end <= cursor) throw new Error("The shift's end time must be later than its start time.");

    while (cursor + duration <= end && guard++ < 100) {
      slots.push({ start: fromMinutes(cursor), end: fromMinutes(cursor + duration) });
      cursor += duration + Math.max(0, breakTime);
    }
    if (!slots.length) throw new Error("This shift is shorter than one class. Reduce the class duration.");
    return slots;
  }

  function readSetup() {
    state.days = Math.min(7, Math.max(1, parseInt($("#totalDays").value, 10) || 5));
    var duration = parseInt($("#classDuration").value, 10);
    var breakTime = parseInt($("#breakTime").value, 10);
    state.duration = isNaN(duration) ? 60 : duration;
    state.breakTime = isNaN(breakTime) ? 0 : breakTime;
    state.roomLimit = Math.max(1, parseInt($("#roomLimit").value, 10) || 12);
    state.building = $("#buildingFilter").value;
    state.roomType = $("#roomTypeFilter").value;
    state.shiftHours[state.shift] = {
      start: $("#startTime").value || DEFAULT_SHIFTS[state.shift].start,
      end: $("#endTime").value || DEFAULT_SHIFTS[state.shift].end
    };
  }

  function writeSetup() {
    $("#totalDays").value = state.days;
    $("#classDuration").value = state.duration;
    $("#breakTime").value = state.breakTime;
    $("#roomLimit").value = state.roomLimit;
    $("#buildingFilter").value = state.building || "";
    $("#roomTypeFilter").value = state.roomType || "";
    $("#startTime").value = state.shiftHours[state.shift].start;
    $("#endTime").value = state.shiftHours[state.shift].end;
    $$(".seg").forEach(function (button) {
      button.setAttribute("aria-pressed", button.dataset.shift === state.shift ? "true" : "false");
    });
    var pill = $("#shiftPill");
    pill.textContent = titleCase(state.shift) + " shift";
    pill.className = "pill pill-shift " + state.shift;
  }

  function currentSlots() { return state.slots[state.shift] || []; }

  function generateGrid(options) {
    options = options || {};
    readSetup();

    var built;
    try {
      built = buildSlots(
        state.shiftHours[state.shift].start,
        state.shiftHours[state.shift].end,
        state.duration,
        state.breakTime
      );
    } catch (err) {
      toast("Cannot build the grid", err.message, "error");
      return false;
    }

    var pool = state.rooms.filter(function (room) {
      if (state.building && String(room.building_id) !== String(state.building)) return false;
      if (state.roomType && room.room_type !== state.roomType) return false;
      return true;
    });
    if (!pool.length) {
      toast("No rooms", "No rooms match the selected building/type filter.", "error");
      return false;
    }

    state.slots[state.shift] = built;
    state.gridRooms = pool.slice(0, state.roomLimit);
    if (state.activeDay > state.days) state.activeDay = 1;

    if (options.keepPlacements === false) {
      state.placements = [];
      state.conflicts = {};
    } else {
      dropOrphanPlacements();
    }

    renderAll();
    if (!options.silent) {
      toast("Grid ready",
        titleCase(state.shift) + " shift · " + state.days + " day(s) × " + built.length + " slots × " +
        state.gridRooms.length + " rooms.", "success");
    }
    persistConfig();
    return true;
  }

  function dropOrphanPlacements() {
    var valid = {};
    ["morning", "evening"].forEach(function (shift) {
      (state.slots[shift] || []).forEach(function (slot) { valid[shift + "|" + slot.start] = slot.end; });
    });
    var validRoom = {};
    state.rooms.forEach(function (room) { validRoom[room.id] = true; });

    var kept = [], dropped = 0;
    state.placements.forEach(function (p) {
      var slotOk = valid[(p.shift || "morning") + "|" + p.start] === p.end;
      if (p.day <= state.days && slotOk && validRoom[p.room_id]) kept.push(p);
      else dropped++;
    });
    state.placements = kept;
    if (dropped) toast("Some classes were removed", dropped + " class(es) no longer fit the new grid.", "warning");
  }

  /* ------------------------------- rendering ------------------------------ */
  function renderAll() {
    writeSetup();
    renderTabs();
    renderGrid();
    renderCourses();
    updateCounters();
    updateHistoryButtons();
  }

  function shiftPlacements() {
    return state.placements.filter(function (p) { return (p.shift || "morning") === state.shift; });
  }

  function renderTabs() {
    var host = $("#dayTabs");
    host.innerHTML = "";
    for (var day = 1; day <= state.days; day++) {
      (function (d) {
        var count = shiftPlacements().filter(function (p) { return p.day === d; }).length;
        var tab = el("button", "day-tab");
        tab.type = "button";
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-selected", d === state.activeDay ? "true" : "false");
        tab.title = "Press " + d;
        tab.appendChild(document.createTextNode(WEEKDAYS[d - 1]));
        if (count) tab.appendChild(el("span", "tab-badge", count));
        tab.addEventListener("click", function () { state.activeDay = d; renderTabs(); renderGrid(); });
        host.appendChild(tab);
      })(day);
    }
  }

  function placementAt(day, start, roomId) {
    var list = shiftPlacements();
    for (var i = 0; i < list.length; i++) {
      var p = list[i];
      if (p.day === day && p.start === start && p.room_id === roomId) return p;
    }
    return null;
  }

  function renderGrid() {
    var host = $("#timetableContainer");
    host.innerHTML = "";
    var slots = currentSlots();

    if (!slots.length) {
      var ph = el("div", "placeholder");
      ph.appendChild(el("h3", null, "No grid for the " + state.shift + " shift yet"));
      ph.appendChild(el("p", null, "Set the shift hours above and press Generate grid (Ctrl+G)."));
      host.appendChild(ph);
      return;
    }

    var table = el("table", "timetable");
    var thead = el("thead");
    var headRow = el("tr");
    headRow.appendChild(el("th", "corner", WEEKDAYS[state.activeDay - 1]));
    slots.forEach(function (slot) {
      headRow.appendChild(el("th", null, to12h(slot.start) + " - " + to12h(slot.end)));
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = el("tbody");
    state.gridRooms.forEach(function (room) {
      var row = el("tr");
      var roomCell = el("th", "room-cell");
      roomCell.scope = "row";
      roomCell.appendChild(document.createTextNode(room.label));
      roomCell.appendChild(el("small", null, room.room_type + " · " + room.capacity + " seats"));
      row.appendChild(roomCell);

      slots.forEach(function (slot) {
        var cell = el("td", "slot");
        cell.dataset.start = slot.start;
        cell.dataset.end = slot.end;
        cell.dataset.roomId = room.id;
        wireDropTarget(cell);
        var placement = placementAt(state.activeDay, slot.start, room.id);
        if (placement) cell.appendChild(renderPlacement(placement));
        row.appendChild(cell);
      });
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  function renderPlacement(placement) {
    var course = findCourse(placement.course_id, placement.section) || {
      name: "Course " + placement.course_id, color: "#dddddd", instructor: "", num_students: 0, code: ""
    };
    var conflicts = state.conflicts[placement.uid] || [];
    var hasError = conflicts.some(function (c) { return c.severity === "error"; });

    var node = el("div", "placed" + (hasError ? " has-conflict" : "") +
      (state.selectedUid === placement.uid ? " selected" : ""));
    node.draggable = true;
    node.dataset.uid = placement.uid;
    node.style.backgroundColor = course.color;
    node.style.color = readableInk(course.color);

    var title = el("div", "p-title");
    if (course.code) title.appendChild(el("span", "p-code", course.code));
    title.appendChild(document.createTextNode(course.name + " - " + placement.section));
    node.appendChild(title);
    node.appendChild(el("div", "p-meta", (course.instructor || "Unassigned") + " · " + course.num_students + " std"));

    var remove = el("button", "p-remove", "\u00d7");
    remove.type = "button";
    remove.title = "Remove this class";
    remove.setAttribute("aria-label", "Remove " + course.name + " " + placement.section);
    remove.addEventListener("click", function (event) {
      event.stopPropagation();
      snapshot();
      removePlacement(placement.uid);
    });
    node.appendChild(remove);

    if (conflicts.length) {
      node.title = conflicts.map(function (c) { return "[" + c.kind + "] " + c.message; }).join("\n");
    }

    node.addEventListener("dragstart", function (event) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", JSON.stringify({ type: "placed", uid: placement.uid }));
    });
    node.addEventListener("click", function (event) {
      event.stopPropagation();
      state.selectedUid = placement.uid;
      showCourseDetails(placement);
      renderGrid();
    });
    return node;
  }

  function updateCounters() {
    $("#placedCount").textContent = state.placements.length + " scheduled";
    var errors = 0;
    Object.keys(state.conflicts).forEach(function (uid) {
      if ((state.conflicts[uid] || []).some(function (c) { return c.severity === "error"; })) errors++;
    });
    var pill = $("#conflictCount");
    pill.textContent = errors ? errors + " clash(es)" : "No clashes";
    pill.className = "pill " + (errors ? "pill-error" : "pill-ok");
  }

  /* ----------------------------- drag & drop ------------------------------ */
  function readDragPayload(event) {
    try { return JSON.parse(event.dataTransfer.getData("text/plain") || "{}"); }
    catch (err) { return {}; }
  }

  function wireDropTarget(cell) {
    cell.addEventListener("dragover", function (event) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      cell.classList.add("dragover");
    });
    cell.addEventListener("dragleave", function () { cell.classList.remove("dragover"); });
    cell.addEventListener("drop", function (event) {
      event.preventDefault();
      cell.classList.remove("dragover");
      var payload = readDragPayload(event);
      var target = {
        day: state.activeDay,
        start: cell.dataset.start,
        end: cell.dataset.end,
        room_id: parseInt(cell.dataset.roomId, 10)
      };
      if (payload.type === "catalogue") addPlacement(payload.course_id, payload.section, target);
      else if (payload.type === "placed") movePlacement(payload.uid, target);
    });
  }

  function occupied(target, ignoreUid) {
    return state.placements.some(function (p) {
      return p.uid !== ignoreUid && (p.shift || "morning") === state.shift &&
        p.day === target.day && p.start === target.start && p.room_id === target.room_id;
    });
  }

  function addPlacement(courseId, section, target) {
    if (occupied(target, null)) {
      toast("Slot taken", "That room is already booked for this time. Pick an empty cell.", "warning");
      return;
    }
    snapshot();
    var placement = {
      uid: nextUid(), day: target.day, start: target.start, end: target.end,
      room_id: target.room_id, course_id: courseId, section: section, shift: state.shift
    };
    state.placements.push(placement);
    state.dirty = true;
    renderGrid();
    renderCourses();
    renderTabs();
    updateCounters();
    validatePlacement(placement, null);
  }

  function movePlacement(uid, target) {
    var placement = state.placements.filter(function (p) { return p.uid === uid; })[0];
    if (!placement) return;
    if (occupied(target, uid)) {
      toast("Slot taken", "That room is already booked for this time.", "warning");
      return;
    }
    snapshot();
    var previous = { day: placement.day, start: placement.start, end: placement.end, room_id: placement.room_id };
    placement.day = target.day;
    placement.start = target.start;
    placement.end = target.end;
    placement.room_id = target.room_id;
    state.dirty = true;
    renderGrid();
    renderTabs();
    updateCounters();
    validatePlacement(placement, previous);
  }

  function removePlacement(uid) {
    state.placements = state.placements.filter(function (p) { return p.uid !== uid; });
    delete state.conflicts[uid];
    if (state.selectedUid === uid) state.selectedUid = null;
    state.dirty = true;
    renderGrid();
    renderCourses();
    renderTabs();
    updateCounters();
    revalidateAll({ silent: true });
  }

  function toAssignment(p) {
    return {
      day: p.day, start_time: p.start, end_time: p.end, room_id: p.room_id,
      course_id: p.course_id, section: p.section, shift: p.shift || "morning"
    };
  }

  /* ---------------------------- clash checking ---------------------------- */
  function validatePlacement(placement, revertTo) {
    var others = state.placements.filter(function (p) { return p.uid !== placement.uid; }).map(toAssignment);
    return api("/api/timetable/validate", {
      method: "POST",
      body: { candidate: toAssignment(placement), grid: others }
    }).then(function (result) {
      state.conflicts[placement.uid] = result.conflicts || [];
      var errors = (result.conflicts || []).filter(function (c) { return c.severity === "error"; });
      var warnings = (result.conflicts || []).filter(function (c) { return c.severity === "warning"; });

      if (errors.length) {
        showConflictDialog(placement, result.conflicts);
        if (revertTo) {
          placement.day = revertTo.day; placement.start = revertTo.start;
          placement.end = revertTo.end; placement.room_id = revertTo.room_id;
          toast("Move rejected", errors[0].message, "error");
          state.conflicts[placement.uid] = [];
        } else {
          state.placements = state.placements.filter(function (p) { return p.uid !== placement.uid; });
          delete state.conflicts[placement.uid];
          toast("Clash detected", errors[0].message, "error");
        }
        state.history.pop();       // the rejected action never happened
        updateHistoryButtons();
      } else if (warnings.length) {
        toast("Scheduled with a warning", warnings[0].message, "warning");
      }
      renderGrid();
      renderCourses();
      renderTabs();
      updateCounters();
      return result;
    }).catch(function (err) {
      toast("Validation unavailable", err.message, "error");
    });
  }

  function revalidateAll(options) {
    options = options || {};
    if (!state.placements.length) {
      state.conflicts = {};
      updateCounters();
      if (!options.silent) toast("Nothing to check", "The grid is empty.", "info");
      return Promise.resolve();
    }
    var payload = state.placements.map(toAssignment);
    return api("/api/timetable/validate", { method: "POST", body: { assignments: payload } })
      .then(function (result) {
        state.conflicts = {};
        (result.reports || []).forEach(function (report) {
          var placement = state.placements[report.index];
          if (placement) state.conflicts[placement.uid] = report.conflicts;
        });
        renderGrid();
        updateCounters();
        if (!options.silent) {
          if (result.ok) toast("All clear", "No clashes anywhere in the week.", "success");
          else toast("Clashes found", (result.reports || []).length + " class(es) need attention.", "error");
        }
        return result;
      })
      .catch(function (err) { if (!options.silent) toast("Check failed", err.message, "error"); });
  }

  function showConflictDialog(placement, conflicts) {
    var course = findCourse(placement.course_id, placement.section) || { name: "Course " + placement.course_id };
    var body = $("#courseDialogBody");
    $("#courseDialogTitle").textContent = "Clash: " + course.name + " - " + placement.section;
    body.innerHTML = "";
    body.appendChild(el("p", "muted",
      WEEKDAYS[placement.day - 1] + ", " + to12h(placement.start) + " - " + to12h(placement.end)));
    var list = el("ul", "conflict-list");
    conflicts.forEach(function (conflict) {
      var item = el("li", conflict.severity);
      item.appendChild(el("div", "conflict-kind", conflict.kind + " clash"));
      item.appendChild(el("div", null, conflict.message));
      list.appendChild(item);
    });
    body.appendChild(list);
    openDialog("#courseDialog");
  }

  /* ----------------------------- detail view ------------------------------ */
  function showCourseDetails(placement) {
    var body = $("#courseDialogBody");
    $("#courseDialogTitle").textContent = "Class details";
    body.innerHTML = '<p class="muted">Loading&hellip;</p>';
    openDialog("#courseDialog");

    api("/api/course-details/" + placement.course_id + "/" + encodeURIComponent(placement.section))
      .then(function (details) {
        var room = state.rooms.filter(function (r) { return r.id === placement.room_id; })[0];
        var conflicts = state.conflicts[placement.uid] || [];
        $("#courseDialogTitle").textContent = (details.code ? details.code + " · " : "") + details.name;

        var html = '<dl class="detail-grid">';
        html += "<dt>Code</dt><dd>" + escapeHtml(details.code || "-") + "</dd>";
        html += "<dt>Teacher</dt><dd>" + escapeHtml(details.instructor) + "</dd>";
        html += "<dt>Department</dt><dd>" + escapeHtml(details.department) + "</dd>";
        html += "<dt>Credit hours</dt><dd>" + escapeHtml(details.credit_hours) + "</dd>";
        html += "<dt>Students</dt><dd>" + details.num_students + "</dd>";
        html += "<dt>Shift</dt><dd>" + escapeHtml(titleCase(placement.shift || "morning")) + "</dd>";
        html += "<dt>Slot</dt><dd>" + escapeHtml(WEEKDAYS[placement.day - 1] + ", " +
          to12h(placement.start) + " - " + to12h(placement.end)) + "</dd>";
        html += "<dt>Room</dt><dd>" + escapeHtml(room ? room.label + " (" + room.room_type + ", " +
          room.capacity + " seats)" : "-") + "</dd>";
        html += "</dl>";

        if (conflicts.length) {
          html += '<h4>Clashes</h4><ul class="conflict-list">';
          conflicts.forEach(function (c) {
            html += '<li class="' + escapeHtml(c.severity) + '"><div class="conflict-kind">' +
              escapeHtml(c.kind) + " clash</div><div>" + escapeHtml(c.message) + "</div></li>";
          });
          html += "</ul>";
        }

        if (details.students && details.students.length) {
          html += "<h4>Enrolled students (" + details.students.length + ")</h4><div class='roster'>";
          details.students.forEach(function (s) {
            html += "<span title='" + escapeHtml(s.name) + "'>" + escapeHtml(s.roll_number) + "</span>";
          });
          html += "</div>";
        } else {
          html += "<p class='muted'>No students are enrolled in this section yet.</p>";
        }
        body.innerHTML = html;
      })
      .catch(function (err) {
        body.innerHTML = '<p class="muted">Could not load details: ' + escapeHtml(err.message) + "</p>";
      });
  }

  /* ------------------------------ persistence ----------------------------- */
  function persistConfig() {
    api("/api/settings", {
      method: "POST",
      body: {
        days: state.days, duration: state.duration, breakTime: state.breakTime,
        roomLimit: state.roomLimit, building: state.building, roomType: state.roomType,
        shift: state.shift, shiftHours: state.shiftHours
      }
    }).catch(function () { /* non fatal */ });
  }

  function applyConfig(config) {
    if (!config) return;
    if (config.days) state.days = config.days;
    if (config.duration) state.duration = config.duration;
    if (config.breakTime !== undefined) state.breakTime = config.breakTime;
    if (config.roomLimit) state.roomLimit = config.roomLimit;
    if (config.building !== undefined) state.building = config.building;
    if (config.roomType !== undefined) state.roomType = config.roomType;
    if (config.shift === "morning" || config.shift === "evening") state.shift = config.shift;
    if (config.shiftHours && config.shiftHours.morning && config.shiftHours.evening) {
      state.shiftHours = config.shiftHours;
    }
  }

  function saveToDatabase() {
    var button = $("[data-action='save']");
    button.disabled = true;
    api("/api/timetable", { method: "POST", body: { assignments: state.placements.map(toAssignment) } })
      .then(function (result) {
        state.dirty = false;
        toast("Saved", result.message, "success");
      })
      .catch(function (err) {
        var payload = err.payload || {};
        if (payload.conflicts && payload.conflicts.length) {
          state.conflicts = {};
          payload.conflicts.forEach(function (report) {
            var placement = state.placements[report.index];
            if (placement) state.conflicts[placement.uid] = report.conflicts;
          });
          renderGrid();
          updateCounters();
          toast("Not saved", payload.conflicts.length + " class(es) still clash. Fix the red cells first.", "error");
        } else {
          toast("Save failed", err.message, "error");
        }
      })
      .then(function () { button.disabled = false; });
  }

  function loadFromDatabase() {
    api("/api/timetable").then(function (data) {
      var entries = data.entries || [];
      if (!entries.length) {
        toast("Nothing saved", "There is no timetable in the database yet.", "info");
        return;
      }
      snapshot();

      var perShift = { morning: {}, evening: {} };
      var maxDay = 1;
      entries.forEach(function (entry) {
        var shift = entry.shift || "morning";
        maxDay = Math.max(maxDay, entry.day);
        perShift[shift][entry.start_time] = entry.end_time;
      });

      state.days = maxDay;
      ["morning", "evening"].forEach(function (shift) {
        var starts = Object.keys(perShift[shift]).sort(function (a, b) { return toMinutes(a) - toMinutes(b); });
        if (!starts.length) return;
        state.slots[shift] = starts.map(function (start) {
          return { start: start, end: perShift[shift][start] };
        });
        state.shiftHours[shift] = { start: starts[0], end: perShift[shift][starts[starts.length - 1]] };
      });

      state.gridRooms = state.rooms.slice(0, Math.max(state.roomLimit, 1));
      var usedRooms = {};
      entries.forEach(function (e) { usedRooms[e.room_id] = true; });
      state.rooms.forEach(function (room) {
        if (usedRooms[room.id] && state.gridRooms.indexOf(room) === -1) state.gridRooms.push(room);
      });

      state.placements = entries.map(function (entry) {
        return {
          uid: nextUid(), day: entry.day, start: entry.start_time, end: entry.end_time,
          room_id: entry.room_id, course_id: entry.course_id, section: entry.section,
          shift: entry.shift || "morning"
        };
      });
      state.dirty = false;
      renderAll();
      toast("Loaded", state.placements.length + " class(es) restored from the database.", "success");
      revalidateAll({ silent: true });
    }).catch(function (err) { toast("Load failed", err.message, "error"); });
  }

  function resetSavedTimetable() {
    if (!window.confirm("This deletes the saved timetable from the database. Continue?")) return;
    api("/api/timetable/reset", { method: "POST" })
      .then(function (result) { toast("Reset done", result.message, "success"); })
      .catch(function (err) { toast("Reset failed", err.message, "error"); });
  }

  function autofill() {
    var slots = currentSlots();
    if (!slots.length) { toast("Generate a grid first", "", "warning"); return; }
    api("/api/timetable/autofill", {
      method: "POST",
      body: {
        assignments: state.placements.map(toAssignment),
        days: state.days,
        slots: slots,
        room_ids: state.gridRooms.map(function (room) { return room.id; }),
        shift: state.shift
      }
    }).then(function (result) {
      var created = result.created || [];
      if (!created.length) {
        toast("Nothing to add", "Every section is already scheduled, or no free slot fits.", "info");
        return;
      }
      snapshot();
      created.forEach(function (entry) {
        state.placements.push({
          uid: nextUid(), day: entry.day, start: entry.start_time, end: entry.end_time,
          room_id: entry.room_id, course_id: entry.course_id, section: entry.section, shift: entry.shift
        });
      });
      state.dirty = true;
      renderAll();
      toast("Auto-filled", created.length + " section(s) placed. Review before saving.", "success");
      revalidateAll({ silent: true });
    }).catch(function (err) { toast("Auto-fill failed", err.message, "error"); });
  }

  /* -------------------------------- exports ------------------------------- */
  function exportExcel() {
    if (!state.placements.length) { toast("Nothing to export", "Schedule at least one class first.", "warning"); return; }
    toast("Building workbook", "One worksheet per day…", "info", 2500);
    api("/api/export/xlsx", {
      method: "POST",
      raw: true,
      body: {
        assignments: state.placements.map(toAssignment),
        days: state.days,
        shift: "all",
        title: "University Timetable"
      }
    }).then(function (blob) {
      downloadBlob(blob, "timetable.xlsx");
      toast("Excel exported", "timetable.xlsx — Summary, one sheet per day, and By Teacher.", "success");
    }).catch(function (err) {
      toast("Excel export failed", err.message, "error");
    });
  }

  function buildPrintable() {
    var host = $("#printArea");
    host.innerHTML = "";
    var title = el("h1", null, "University Timetable — " + titleCase(state.shift) + " shift");
    title.style.fontSize = "16px";
    host.appendChild(title);

    var slots = currentSlots();
    for (var day = 1; day <= state.days; day++) {
      var wrapper = el("div", "pdf-day");
      wrapper.appendChild(el("h2", null, WEEKDAYS[day - 1]));
      var table = el("table");
      var thead = el("thead");
      var headRow = el("tr");
      headRow.appendChild(el("th", null, "Room"));
      slots.forEach(function (slot) {
        headRow.appendChild(el("th", null, to12h(slot.start) + "-" + to12h(slot.end)));
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = el("tbody");
      (function (d) {
        state.gridRooms.forEach(function (room) {
          var row = el("tr");
          row.appendChild(el("td", null, room.label));
          slots.forEach(function (slot) {
            var placement = placementAt(d, slot.start, room.id);
            var cell = el("td");
            if (placement) {
              var course = findCourse(placement.course_id, placement.section);
              cell.textContent = ((course && course.code) ? course.code + " " : "") +
                (course ? course.name : placement.course_id) + " - " + placement.section;
              cell.style.backgroundColor = course ? course.color : "#eeeeee";
            }
            row.appendChild(cell);
          });
          tbody.appendChild(row);
        });
      })(day);
      table.appendChild(tbody);
      wrapper.appendChild(table);
      host.appendChild(wrapper);
    }
    return host;
  }

  function exportPdf() {
    if (!currentSlots().length) { toast("Nothing to export", "Generate a grid first.", "warning"); return; }
    var host = buildPrintable();
    if (typeof window.html2pdf !== "function") {
      toast("PDF engine missing", "Falling back to the browser print dialog.", "warning");
      window.print();
      return;
    }
    host.style.display = "block";
    window.html2pdf().set({
      margin: 8,
      filename: "timetable-" + state.shift + ".pdf",
      image: { type: "jpeg", quality: 0.96 },
      html2canvas: { scale: 2, useCORS: true },
      jsPDF: { unit: "mm", format: "a3", orientation: "landscape" }
    }).from(host).save().then(function () {
      host.style.display = "none";
      toast("PDF exported", "Saved to your Downloads folder.", "success");
    }).catch(function (err) {
      host.style.display = "none";
      toast("PDF failed", err.message || String(err), "error");
    });
  }

  function exportCsv() {
    if (!state.placements.length) { toast("Nothing to export", "Schedule at least one class first.", "warning"); return; }
    var rows = [["Day", "Shift", "Start", "End", "Room", "Code", "Course", "Section", "Teacher", "Students"]];
    state.placements.slice().sort(function (a, b) {
      return a.day - b.day || toMinutes(a.start) - toMinutes(b.start);
    }).forEach(function (p) {
      var course = findCourse(p.course_id, p.section) || {};
      var room = state.rooms.filter(function (r) { return r.id === p.room_id; })[0];
      rows.push([
        WEEKDAYS[p.day - 1], titleCase(p.shift || "morning"), p.start, p.end,
        room ? room.label : p.room_id, course.code || "", course.name || p.course_id, p.section,
        course.instructor || "", course.num_students || 0
      ]);
    });
    var csv = rows.map(function (row) {
      return row.map(function (cell) { return '"' + String(cell).replace(/"/g, '""') + '"'; }).join(",");
    }).join("\r\n");
    downloadBlob(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" }), "timetable.csv");
    toast("CSV exported", "timetable.csv downloaded.", "success");
  }

  /* ============================ data management ============================ */
  function refreshCatalogue() {
    return Promise.all([
      api("/api/rooms"),
      api("/api/courses"),
      api("/api/instructors"),
      api("/api/buildings")
    ]).then(function (results) {
      state.rooms = results[0] || [];
      state.courses = results[1] || [];
      state.instructors = results[2] || [];
      state.buildings = results[3] || [];
      fillBuildingControls();
      fillTeacherSelect();
      renderCourses();
      return true;
    });
  }

  function fillBuildingControls() {
    var select = $("#buildingFilter");
    var current = select.value;
    select.innerHTML = '<option value="">All buildings</option>';
    state.buildings.forEach(function (building) {
      var option = el("option", null, "Building " + building.name);
      option.value = building.id;
      select.appendChild(option);
    });
    select.value = current;

    var list = $("#buildingOptions");
    list.innerHTML = "";
    state.buildings.forEach(function (building) {
      var option = el("option");
      option.value = building.name;
      list.appendChild(option);
    });
  }

  function fillTeacherSelect() {
    var select = $("#courseTeacher");
    var current = select.value;
    select.innerHTML = '<option value="">Unassigned</option>';
    state.instructors.forEach(function (teacher) {
      var option = el("option", null, teacher.name + " (" + teacher.department + ")");
      option.value = teacher.id;
      select.appendChild(option);
    });
    select.value = current;
  }

  /* ---- teacher ---- */
  function openTeacherDialog(teacher) {
    $("#teacherDialogTitle").textContent = teacher ? "Edit teacher" : "Add teacher";
    $("#teacherId").value = teacher ? teacher.id : "";
    $("#teacherName").value = teacher ? teacher.name : "";
    $("#teacherEmail").value = teacher ? teacher.email : "";
    $("#teacherDept").value = teacher ? teacher.department : "";
    $("#teacherShift").value = teacher ? teacher.shift : "both";
    openDialog("#teacherDialog");
  }

  function submitTeacher(event) {
    event.preventDefault();
    var id = $("#teacherId").value;
    var body = {
      name: $("#teacherName").value,
      email: $("#teacherEmail").value,
      department: $("#teacherDept").value,
      shift: $("#teacherShift").value
    };
    api(id ? "/api/instructors/" + id : "/api/instructors", { method: id ? "PUT" : "POST", body: body })
      .then(function (teacher) {
        closeDialogs();
        toast(id ? "Teacher updated" : "Teacher added", teacher.name, "success");
        return refreshCatalogue().then(function () { if (!$("#manageDialog").hidden) renderManage(); });
      })
      .catch(function (err) { toast("Could not save the teacher", err.message, "error"); });
  }

  /* ---- room ---- */
  function openRoomDialog(room) {
    $("#roomDialogTitle").textContent = room ? "Edit classroom" : "Add classroom";
    $("#roomId").value = room ? room.id : "";
    $("#roomNumber").value = room ? room.room_number : "";
    $("#roomBuilding").value = room ? room.building_name : "";
    $("#roomCapacity").value = room ? room.capacity : 60;
    $("#roomType").value = room ? room.room_type : "Classroom";
    openDialog("#roomDialog");
  }

  function submitRoom(event) {
    event.preventDefault();
    var id = $("#roomId").value;
    var body = {
      room_number: $("#roomNumber").value,
      building_name: $("#roomBuilding").value,
      capacity: $("#roomCapacity").value,
      room_type: $("#roomType").value
    };
    api(id ? "/api/rooms/" + id : "/api/rooms", { method: id ? "PUT" : "POST", body: body })
      .then(function () {
        closeDialogs();
        toast(id ? "Room updated" : "Room added", body.room_number, "success");
        return refreshCatalogue().then(function () { if (!$("#manageDialog").hidden) renderManage(); });
      })
      .catch(function (err) { toast("Could not save the room", err.message, "error"); });
  }

  function addBuilding() {
    var name = window.prompt("Name of the new building (e.g. D or Science Block):", "");
    if (!name) return;
    api("/api/buildings", { method: "POST", body: { name: name } })
      .then(function (building) {
        toast("Building added", building.name, "success");
        return refreshCatalogue();
      })
      .catch(function (err) { toast("Could not add the building", err.message, "error"); });
  }

  /* ---- course ---- */
  function openCourseDialog(course) {
    $("#courseFormTitle").textContent = course ? "Edit course" : "Add course";
    $("#courseIdField").value = course ? course.id : "";
    $("#courseCode").value = course ? course.code : "";
    $("#courseName").value = course ? course.name : "";
    $("#courseDept").value = course ? course.department : "";
    $("#courseCredits").value = course ? course.credit_hours : 3;
    $("#courseColor").value = (course && course.color) ? course.color : "#a9d2e1";
    $("#courseSections").value = course ? (course.sections || []).map(function (s) { return s.section; }).join(", ") : "A";
    $("#courseTeacher").value = (course && course.sections && course.sections[0] && course.sections[0].instructor_id)
      ? course.sections[0].instructor_id : "";
    openDialog("#courseFormDialog");
  }

  function submitCourse(event) {
    event.preventDefault();
    var id = $("#courseIdField").value;
    var teacherId = $("#courseTeacher").value;
    var sections = ($("#courseSections").value || "")
      .split(/[,\s]+/)
      .map(function (value) { return value.trim().toUpperCase(); })
      .filter(Boolean)
      .map(function (section) { return { section: section, instructor_id: teacherId || null }; });

    var body = {
      code: $("#courseCode").value,
      name: $("#courseName").value,
      department: $("#courseDept").value,
      credit_hours: $("#courseCredits").value,
      color: $("#courseColor").value,
      sections: sections
    };
    api(id ? "/api/courses/" + id : "/api/courses", { method: id ? "PUT" : "POST", body: body })
      .then(function (course) {
        closeDialogs();
        toast(id ? "Course updated" : "Course added", course.code + " " + course.name, "success");
        return refreshCatalogue().then(function () { if (!$("#manageDialog").hidden) renderManage(); });
      })
      .catch(function (err) { toast("Could not save the course", err.message, "error"); });
  }

  function addSection() {
    api("/api/admin/courses").then(function (courses) {
      if (!courses.length) { toast("Add a course first", "", "warning"); return; }
      var listing = courses.slice(0, 40).map(function (c) { return c.code + " — " + c.name; }).join("\n");
      var code = window.prompt("Course code to add a section to:\n\n" + listing, courses[0].code);
      if (!code) return;
      var match = courses.filter(function (c) { return c.code.toUpperCase() === code.trim().toUpperCase(); })[0];
      if (!match) { toast("Unknown course code", code, "error"); return; }
      var section = window.prompt("New section for " + match.code + " (e.g. D):", "");
      if (!section) return;
      api("/api/courses/" + match.id + "/sections", { method: "POST", body: { section: section } })
        .then(function () {
          toast("Section added", match.code + " - " + section.toUpperCase(), "success");
          return refreshCatalogue().then(function () { if (!$("#manageDialog").hidden) renderManage(); });
        })
        .catch(function (err) { toast("Could not add the section", err.message, "error"); });
    });
  }

  /* ---- manage dialog ---- */
  function openManage(tab) {
    if (tab) state.manageTab = tab;
    $$("#manageDialog .tab").forEach(function (button) {
      button.setAttribute("aria-selected", button.dataset.tab === state.manageTab ? "true" : "false");
    });
    $("#manageSearch").value = "";
    openDialog("#manageDialog");
    renderManage();
  }

  function renderManage() {
    var host = $("#managePanel");
    var query = ($("#manageSearch").value || "").trim().toLowerCase();
    host.innerHTML = '<p class="muted">Loading…</p>';

    var addButton = $("#manageAddBtn");
    addButton.textContent = { teachers: "+ Add teacher", rooms: "+ Add classroom", courses: "+ Add course" }[state.manageTab];

    function table(headers, rows) {
      var element = el("table", "manage-table");
      var thead = el("thead"), headRow = el("tr");
      headers.forEach(function (heading) { headRow.appendChild(el("th", null, heading)); });
      thead.appendChild(headRow);
      element.appendChild(thead);
      var tbody = el("tbody");
      rows.forEach(function (row) { tbody.appendChild(row); });
      element.appendChild(tbody);
      return rows.length ? element : el("p", "muted", "Nothing here yet.");
    }

    function actions(onEdit, onDelete) {
      var cell = el("td", "row-actions");
      var edit = el("button", "btn btn-tiny", "Edit");
      edit.type = "button";
      edit.addEventListener("click", onEdit);
      var remove = el("button", "btn btn-tiny btn-danger", "Delete");
      remove.type = "button";
      remove.addEventListener("click", onDelete);
      cell.appendChild(edit);
      cell.appendChild(remove);
      return cell;
    }

    function confirmDelete(what, request) {
      if (!window.confirm("Delete " + what + "?")) return;
      request()
        .then(function () {
          toast("Deleted", what, "success");
          return refreshCatalogue().then(renderManage);
        })
        .catch(function (err) { toast("Could not delete", err.message, "error"); });
    }

    if (state.manageTab === "teachers") {
      var teachers = state.instructors.filter(function (teacher) {
        return !query || (teacher.name + " " + teacher.email + " " + teacher.department).toLowerCase().indexOf(query) >= 0;
      });
      host.innerHTML = "";
      host.appendChild(table(["Name", "Email", "Department", "Shift", "Sections", ""], teachers.map(function (teacher) {
        var row = el("tr");
        row.appendChild(el("td", null, teacher.name));
        row.appendChild(el("td", null, teacher.email || "-"));
        row.appendChild(el("td", null, teacher.department));
        row.appendChild(el("td", null, titleCase(teacher.shift)));
        row.appendChild(el("td", null, teacher.sections));
        row.appendChild(actions(
          function () { openTeacherDialog(teacher); },
          function () {
            confirmDelete(teacher.name, function () {
              return api("/api/instructors/" + teacher.id, { method: "DELETE" });
            });
          }
        ));
        return row;
      })));
      return;
    }

    if (state.manageTab === "rooms") {
      var rooms = state.rooms.filter(function (room) {
        return !query || (room.label + " " + room.room_type).toLowerCase().indexOf(query) >= 0;
      });
      host.innerHTML = "";
      host.appendChild(table(["Room", "Building", "Type", "Capacity", ""], rooms.map(function (room) {
        var row = el("tr");
        row.appendChild(el("td", null, room.room_number));
        row.appendChild(el("td", null, room.building_name));
        row.appendChild(el("td", null, room.room_type));
        row.appendChild(el("td", null, room.capacity));
        row.appendChild(actions(
          function () { openRoomDialog(room); },
          function () {
            confirmDelete("room " + room.label, function () {
              return api("/api/rooms/" + room.id, { method: "DELETE" });
            });
          }
        ));
        return row;
      })));
      return;
    }

    api("/api/admin/courses").then(function (courses) {
      var filtered = courses.filter(function (course) {
        return !query || (course.code + " " + course.name + " " + course.department).toLowerCase().indexOf(query) >= 0;
      });
      host.innerHTML = "";
      host.appendChild(table(["Code", "Course", "Dept", "Cr", "Sections", ""], filtered.map(function (course) {
        var row = el("tr");
        var code = el("td");
        code.appendChild(el("span", "code-chip", course.code));
        row.appendChild(code);
        row.appendChild(el("td", null, course.name));
        row.appendChild(el("td", null, course.department));
        row.appendChild(el("td", null, course.credit_hours));

        var sectionCell = el("td", "section-cell");
        (course.sections || []).forEach(function (section) {
          var chip = el("span", "section-chip");
          chip.appendChild(document.createTextNode(section.section + " · " + section.instructor));
          var kill = el("button", "chip-x", "×");
          kill.type = "button";
          kill.title = "Remove section " + section.section;
          kill.addEventListener("click", function () {
            confirmDelete("section " + course.code + "-" + section.section, function () {
              return api("/api/courses/" + course.id + "/sections/" + encodeURIComponent(section.section),
                { method: "DELETE" });
            });
          });
          chip.appendChild(kill);
          sectionCell.appendChild(chip);
        });
        row.appendChild(sectionCell);

        row.appendChild(actions(
          function () { openCourseDialog(course); },
          function () {
            confirmDelete(course.code + " " + course.name, function () {
              return api("/api/courses/" + course.id, { method: "DELETE" });
            });
          }
        ));
        return row;
      })));
    });
  }

  /* ---------------------------- shortcuts engine --------------------------- */
  function comboFor(event) {
    var parts = [];
    if (event.ctrlKey || event.metaKey) parts.push("Ctrl");
    if (event.altKey) parts.push("Alt");
    if (event.shiftKey) parts.push("Shift");
    var key = event.key;
    if (key === " ") key = "Space";
    if (key && key.length === 1) key = key.toUpperCase();
    parts.push(key);
    return parts.join("+");
  }

  function renderShortcutsDialog() {
    var host = $("#shortcutsBody");
    host.innerHTML = "";
    var groups = {};
    SHORTCUTS.forEach(function (item) {
      (groups[item.group] = groups[item.group] || []).push(item);
    });
    Object.keys(groups).forEach(function (group) {
      var column = el("div", "shortcut-group");
      column.appendChild(el("h4", null, group));
      var list = el("dl");
      groups[group].forEach(function (item) {
        var term = el("dt");
        item.combo.split(" ").forEach(function (chunk, index) {
          if (index) term.appendChild(document.createTextNode(" "));
          if (chunk === "…") { term.appendChild(document.createTextNode(" … ")); return; }
          chunk.split("+").forEach(function (key, keyIndex) {
            if (keyIndex) term.appendChild(document.createTextNode("+"));
            term.appendChild(el("kbd", null, key));
          });
        });
        list.appendChild(term);
        list.appendChild(el("dd", null, item.label));
      });
      column.appendChild(list);
      host.appendChild(column);
    });
  }

  function decorateButtonTooltips() {
    var byAction = {};
    SHORTCUTS.forEach(function (item) {
      if (item.action && !byAction[item.action]) byAction[item.action] = item.combo;
    });
    $$("[data-action]").forEach(function (button) {
      var combo = byAction[button.dataset.action];
      if (!combo) return;
      // Ignore any <kbd> hint already printed on the button, so the tooltip
      // never reads "Generate grid Ctrl+G (Ctrl+G)".
      var label = Array.prototype.filter
        .call(button.childNodes, function (node) { return !(node.tagName === "KBD"); })
        .map(function (node) { return node.textContent || ""; })
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      button.title = (label || button.dataset.action) + "  (" + combo + ")";
    });
  }

  var ACTIONS = {
    addTeacher: function () { openTeacherDialog(null); },
    addRoom: function () { openRoomDialog(null); },
    addCourse: function () { openCourseDialog(null); },
    addBuilding: addBuilding,
    addSection: addSection,
    manage: function () { openManage(); },
    undo: undo,
    redo: redo,
    removeSelected: function () {
      if (!state.selectedUid) { toast("Nothing selected", "Click a class first.", "info", 2500); return; }
      snapshot();
      removePlacement(state.selectedUid);
    },
    clearGrid: function () {
      if (!state.placements.length) { toast("Already empty", "", "info", 2000); return; }
      if (!window.confirm("Remove every class from the grid? (The saved timetable is untouched.)")) return;
      snapshot();
      state.placements = [];
      state.conflicts = {};
      state.dirty = true;
      renderAll();
    },
    generate: function () { generateGrid({}); },
    save: saveToDatabase,
    load: loadFromDatabase,
    validate: function () { revalidateAll({}); },
    autofill: autofill,
    exportExcel: exportExcel,
    exportPdf: exportPdf,
    exportCsv: exportCsv,
    print: function () { buildPrintable(); window.print(); },
    resetSaved: resetSavedTimetable,
    shiftMorning: function () { switchShift("morning"); },
    shiftEvening: function () { switchShift("evening"); },
    focusSearch: function () { $("#courseSearch").focus(); $("#courseSearch").select(); },
    toggleSidebar: toggleSidebar,
    shortcuts: function () { renderShortcutsDialog(); openDialog("#shortcutsDialog"); },
    help: function () { openDialog("#helpDialog"); }
  };

  function runAction(name) {
    var fn = ACTIONS[name];
    if (fn) fn();
  }

  function switchShift(shift) {
    if (state.shift === shift) return;
    readSetup();
    state.shift = shift;
    writeSetup();
    if (!currentSlots().length) generateGrid({ silent: true });
    else renderAll();
    persistConfig();
    toast(titleCase(shift) + " shift", "Showing " + shiftPlacements().length + " class(es).", "info", 2500);
  }

  function toggleSidebar() {
    var sidebar = $("#sidebar");
    var button = $("#sidebarToggle");
    var collapsed = sidebar.classList.toggle("collapsed");
    button.setAttribute("aria-expanded", collapsed ? "false" : "true");
    button.innerHTML = collapsed ? "&#10095;" : "&#10094;";
  }

  function handleKeydown(event) {
    if (event.key === "Escape") { closeDialogs(); return; }

    var target = event.target || {};
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || "") || target.isContentEditable;
    var combo = comboFor(event);

    // Day switching with the number row - only when not typing.
    if (!typing && !event.ctrlKey && !event.metaKey && !event.altKey && /^[1-7]$/.test(event.key)) {
      var day = parseInt(event.key, 10);
      if (day <= state.days) {
        state.activeDay = day;
        renderTabs();
        renderGrid();
        event.preventDefault();
      }
      return;
    }

    for (var i = 0; i < SHORTCUTS.length; i++) {
      var item = SHORTCUTS[i];
      if (!item.action || item.combo !== combo) continue;
      // Plain keys (Delete) must not fire while the user is typing.
      if (typing && !(event.ctrlKey || event.metaKey || event.altKey)) return;
      event.preventDefault();
      runAction(item.action);
      return;
    }
  }

  /* -------------------------------- startup ------------------------------- */
  function wireSidebarDropZone() {
    var host = $("#coursesList");
    host.addEventListener("dragover", function (event) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      host.classList.add("dragover");
    });
    host.addEventListener("dragleave", function () { host.classList.remove("dragover"); });
    host.addEventListener("drop", function (event) {
      event.preventDefault();
      host.classList.remove("dragover");
      var payload = readDragPayload(event);
      if (payload.type === "placed") { snapshot(); removePlacement(payload.uid); }
    });
  }

  function wireEvents() {
    $("#setupForm").addEventListener("submit", function (event) {
      event.preventDefault();
      generateGrid({});
    });

    $$("[data-action]").forEach(function (button) {
      if (button.type === "submit") return;
      button.addEventListener("click", function () { runAction(button.dataset.action); });
    });

    $$(".seg").forEach(function (button) {
      button.addEventListener("click", function () { switchShift(button.dataset.shift); });
    });

    $("#courseSearch").addEventListener("input", renderCourses);
    $("#hidePlaced").addEventListener("change", renderCourses);
    $("#sidebarToggle").addEventListener("click", toggleSidebar);

    $("#teacherForm").addEventListener("submit", submitTeacher);
    $("#roomForm").addEventListener("submit", submitRoom);
    $("#courseForm").addEventListener("submit", submitCourse);

    $$("#manageDialog .tab").forEach(function (tab) {
      tab.addEventListener("click", function () { openManage(tab.dataset.tab); });
    });
    $("#manageSearch").addEventListener("input", renderManage);
    $("#manageAddBtn").addEventListener("click", function () {
      if (state.manageTab === "teachers") openTeacherDialog(null);
      else if (state.manageTab === "rooms") openRoomDialog(null);
      else openCourseDialog(null);
    });

    $$("[data-close-dialog]").forEach(function (button) { button.addEventListener("click", closeDialogs); });
    $$(".dialog").forEach(function (dialog) {
      dialog.addEventListener("click", function (event) { if (event.target === dialog) closeDialogs(); });
    });

    document.addEventListener("keydown", handleKeydown);

    window.addEventListener("beforeunload", function (event) {
      if (state.dirty && state.placements.length) {
        event.preventDefault();
        event.returnValue = "";
      }
    });

    wireSidebarDropZone();
    decorateButtonTooltips();
    renderShortcutsDialog();
  }

  function setStatus(text, kind) {
    var pill = $("#dbStatus");
    pill.textContent = text;
    pill.className = "pill " + (kind || "pill-muted");
  }

  function boot() {
    wireEvents();

    api("/api/health").then(function (health) {
      var stats = health.stats || {};
      setStatus((health.backend === "sqlite" ? "Local database" : "Server database") + " · " +
        (stats.courses || 0) + " courses · " + (stats.rooms || 0) + " rooms", "pill-ok");
    }).catch(function (err) {
      setStatus("Database offline", "pill-error");
      toast("Database problem", err.message, "error", 12000);
    });

    refreshCatalogue()
      .then(function () {
        state.roomLimit = Math.min(12, state.rooms.length || 12);
        return api("/api/settings").catch(function () { return {}; });
      })
      .then(function (config) {
        applyConfig(config);
        generateGrid({ silent: true });
        return api("/api/timetable").catch(function () { return { entries: [] }; });
      })
      .then(function (data) {
        if (data && data.entries && data.entries.length) {
          toast("Saved timetable available",
            data.entries.length + " class(es) are stored. Press Ctrl+O to restore them.", "info", 9000);
        }
      })
      .catch(function (err) { toast("Startup problem", err.message, "error", 10000); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
