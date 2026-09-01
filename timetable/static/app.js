/* =========================================================================
 * Automated Timetable Generator - front-end controller
 * Vanilla ES2017+, zero third-party runtime dependencies (html2pdf is
 * bundled locally and optional).  Runs fully offline.
 * ========================================================================= */
(function () {
  "use strict";

  /* ----------------------------- state --------------------------------- */
  var WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

  var state = {
    courses: [],          // one entry per course-section
    rooms: [],            // all rooms from the DB
    gridRooms: [],        // rooms currently rendered
    slots: [],            // [{start:"08:30", end:"09:50"}]
    days: 5,
    activeDay: 1,
    placements: [],       // {uid, day, start, end, room_id, course_id, section}
    conflicts: {},        // uid -> [conflict]
    dirty: false,
    selectedUid: null,
    config: null
  };

  var uidSeq = 1;
  function nextUid() { return "p" + (uidSeq++); }

  /* ----------------------------- helpers -------------------------------- */
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

  /* ------------------------------ network -------------------------------- */
  function api(path, options) {
    options = options || {};
    var init = { method: options.method || "GET", headers: { "Accept": "application/json" } };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    return fetch(path, init).then(function (response) {
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

  /* ------------------------------- toasts -------------------------------- */
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

  /* ------------------------------ dialogs -------------------------------- */
  function openDialog(id) { var d = $(id); if (d) { d.hidden = false; } }
  function closeDialogs() { $$(".dialog").forEach(function (d) { d.hidden = true; }); }

  /* ------------------------------ courses -------------------------------- */
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
      var haystack = (course.name + " " + course.section + " " + course.instructor + " " + course.department).toLowerCase();
      if (query && haystack.indexOf(query) === -1) return;

      var card = el("div", "course-card" + (isPlaced ? " is-placed" : ""));
      card.draggable = true;
      card.style.backgroundColor = course.color;
      card.style.color = readableInk(course.color);
      card.dataset.courseId = course.id;
      card.dataset.section = course.section;
      card.title = course.name + " - " + course.section + "\nInstructor: " + course.instructor +
        "\nStudents: " + course.num_students;

      card.appendChild(el("div", "cc-title", course.name + " - " + course.section));
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

    if (!shown) host.appendChild(el("p", "empty", state.courses.length ? "No course matches your search." : "No courses found."));
    $("#courseCount").textContent = String(shown);
  }

  /* --------------------------- slot generation ---------------------------- */
  function buildSlots(startTime, endTime, duration, breakTime) {
    var slots = [];
    var cursor = toMinutes(startTime);
    var end = toMinutes(endTime);
    var guard = 0;

    if (!(duration > 0)) throw new Error("Class duration must be greater than zero.");
    if (end <= cursor) throw new Error("The end time must be later than the start time.");

    while (cursor + duration <= end && guard++ < 100) {
      slots.push({ start: fromMinutes(cursor), end: fromMinutes(cursor + duration) });
      cursor += duration + Math.max(0, breakTime);
    }
    if (!slots.length) throw new Error("The working day is shorter than one class. Reduce the class duration.");
    return slots;
  }

  function readSetup() {
    var days = Math.min(7, Math.max(1, parseInt($("#totalDays").value, 10) || 5));
    var duration = parseInt($("#classDuration").value, 10);
    var breakTime = parseInt($("#breakTime").value, 10);
    var roomLimit = Math.max(1, parseInt($("#roomLimit").value, 10) || 12);
    var building = $("#buildingFilter").value;
    return {
      days: days,
      start: $("#startTime").value || "08:30",
      end: $("#endTime").value || "17:15",
      duration: isNaN(duration) ? 60 : duration,
      breakTime: isNaN(breakTime) ? 0 : breakTime,
      roomLimit: roomLimit,
      building: building
    };
  }

  function applySetup(config) {
    if (!config) return;
    if (config.days) $("#totalDays").value = config.days;
    if (config.start) $("#startTime").value = config.start;
    if (config.end) $("#endTime").value = config.end;
    if (config.duration) $("#classDuration").value = config.duration;
    if (config.breakTime !== undefined) $("#breakTime").value = config.breakTime;
    if (config.roomLimit) $("#roomLimit").value = config.roomLimit;
    if (config.building !== undefined) $("#buildingFilter").value = config.building;
  }

  function generateGrid(options) {
    options = options || {};
    var config = readSetup();
    var slots;
    try {
      slots = buildSlots(config.start, config.end, config.duration, config.breakTime);
    } catch (err) {
      toast("Cannot build the grid", err.message, "error");
      return false;
    }

    var pool = state.rooms.filter(function (room) {
      return !config.building || String(room.building_id) === String(config.building);
    });
    if (!pool.length) {
      toast("No rooms", "No rooms exist for the selected building.", "error");
      return false;
    }

    state.slots = slots;
    state.days = config.days;
    state.gridRooms = pool.slice(0, config.roomLimit);
    state.config = config;
    if (state.activeDay > state.days) state.activeDay = 1;

    if (!options.keepPlacements) {
      state.placements = [];
      state.conflicts = {};
    } else {
      dropOrphanPlacements();
    }

    renderTabs();
    renderGrid();
    renderCourses();
    updateCounters();
    if (!options.silent) {
      toast("Grid ready", state.days + " day(s) x " + slots.length + " slots x " + state.gridRooms.length + " rooms.", "success");
    }
    persistConfig();
    return true;
  }

  function dropOrphanPlacements() {
    var validSlot = {};
    state.slots.forEach(function (s) { validSlot[s.start] = s.end; });
    var validRoom = {};
    state.gridRooms.forEach(function (r) { validRoom[r.id] = true; });

    var kept = [], dropped = 0;
    state.placements.forEach(function (p) {
      if (p.day <= state.days && validSlot[p.start] === p.end && validRoom[p.room_id]) kept.push(p);
      else dropped++;
    });
    state.placements = kept;
    if (dropped) toast("Some classes were removed", dropped + " class(es) no longer fit the new grid.", "warning");
  }

  /* ------------------------------ rendering ------------------------------- */
  function renderTabs() {
    var host = $("#dayTabs");
    host.innerHTML = "";
    for (var day = 1; day <= state.days; day++) {
      (function (d) {
        var count = state.placements.filter(function (p) { return p.day === d; }).length;
        var tab = el("button", "day-tab");
        tab.type = "button";
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-selected", d === state.activeDay ? "true" : "false");
        tab.appendChild(document.createTextNode(WEEKDAYS[d - 1]));
        if (count) tab.appendChild(el("span", "tab-badge", count));
        tab.addEventListener("click", function () { state.activeDay = d; renderTabs(); renderGrid(); });
        host.appendChild(tab);
      })(day);
    }
  }

  function placementAt(day, start, roomId) {
    for (var i = 0; i < state.placements.length; i++) {
      var p = state.placements[i];
      if (p.day === day && p.start === start && p.room_id === roomId) return p;
    }
    return null;
  }

  function renderGrid() {
    var host = $("#timetableContainer");
    host.innerHTML = "";

    if (!state.slots.length) {
      var ph = el("div", "placeholder");
      ph.appendChild(el("h3", null, "No grid yet"));
      ph.appendChild(el("p", null, "Choose your working hours above and press Generate grid to begin."));
      host.appendChild(ph);
      return;
    }

    var table = el("table", "timetable");
    var thead = el("thead");
    var headRow = el("tr");
    var corner = el("th", "corner", WEEKDAYS[state.activeDay - 1]);
    headRow.appendChild(corner);
    state.slots.forEach(function (slot) {
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
      roomCell.appendChild(el("small", null, "seats " + room.capacity));
      row.appendChild(roomCell);

      state.slots.forEach(function (slot) {
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
      name: "Course " + placement.course_id, color: "#dddddd", instructor: "", num_students: 0
    };
    var conflicts = state.conflicts[placement.uid] || [];
    var hasError = conflicts.some(function (c) { return c.severity === "error"; });

    var node = el("div", "placed" + (hasError ? " has-conflict" : "") +
      (state.selectedUid === placement.uid ? " selected" : ""));
    node.draggable = true;
    node.dataset.uid = placement.uid;
    node.style.backgroundColor = course.color;
    node.style.color = readableInk(course.color);
    node.appendChild(el("div", "p-title", course.name + " - " + placement.section));
    node.appendChild(el("div", "p-meta", (course.instructor || "Unassigned") + " - " + course.num_students + " std"));

    var remove = el("button", "p-remove", "\u00d7");
    remove.type = "button";
    remove.title = "Remove this class";
    remove.setAttribute("aria-label", "Remove " + course.name + " " + placement.section);
    remove.addEventListener("click", function (event) {
      event.stopPropagation();
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
    renderTabs();
  }

  /* ---------------------------- drag & drop ------------------------------- */
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
      return p.uid !== ignoreUid && p.day === target.day && p.start === target.start && p.room_id === target.room_id;
    });
  }

  function addPlacement(courseId, section, target) {
    if (occupied(target, null)) {
      toast("Slot taken", "That room is already booked for this time. Pick an empty cell.", "warning");
      return;
    }
    var placement = {
      uid: nextUid(), day: target.day, start: target.start, end: target.end,
      room_id: target.room_id, course_id: courseId, section: section
    };
    state.placements.push(placement);
    state.dirty = true;
    renderGrid();
    renderCourses();
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
    var previous = { day: placement.day, start: placement.start, end: placement.end, room_id: placement.room_id };
    placement.day = target.day;
    placement.start = target.start;
    placement.end = target.end;
    placement.room_id = target.room_id;
    state.dirty = true;
    renderGrid();
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
    updateCounters();
    revalidateAll({ silent: true });
  }

  function toAssignment(p) {
    return {
      day: p.day, start_time: p.start, end_time: p.end,
      room_id: p.room_id, course_id: p.course_id, section: p.section
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
      } else if (warnings.length) {
        toast("Scheduled with a warning", warnings[0].message, "warning");
      }
      renderGrid();
      renderCourses();
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
          if (result.ok) toast("All clear", "No clashes found in the whole week.", "success");
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
    var intro = el("p", "muted", WEEKDAYS[placement.day - 1] + ", " + to12h(placement.start) + " - " + to12h(placement.end));
    body.appendChild(intro);
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
        var html = "";
        $("#courseDialogTitle").textContent = details.name;
        html += '<dl class="detail-grid">';
        html += "<dt>Instructor</dt><dd>" + escapeHtml(details.instructor) + "</dd>";
        html += "<dt>Department</dt><dd>" + escapeHtml(details.department) + "</dd>";
        html += "<dt>Section</dt><dd>" + escapeHtml(details.section) + "</dd>";
        html += "<dt>Students</dt><dd>" + details.num_students + "</dd>";
        html += "<dt>Slot</dt><dd>" + escapeHtml(WEEKDAYS[placement.day - 1] + ", " +
          to12h(placement.start) + " - " + to12h(placement.end)) + "</dd>";
        html += "<dt>Room</dt><dd>" + escapeHtml(room ? room.label + " (seats " + room.capacity + ")" : "-") + "</dd>";
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
    if (!state.config) return;
    api("/api/settings", { method: "POST", body: state.config }).catch(function () { /* non fatal */ });
  }

  function saveToDatabase() {
    var button = $("#saveToDatabase");
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
      var maxDay = 1, starts = {};
      entries.forEach(function (entry) {
        maxDay = Math.max(maxDay, entry.day);
        starts[entry.start_time] = entry.end_time;
      });

      // Rebuild a grid that is guaranteed to contain every saved class.
      $("#totalDays").value = maxDay;
      var times = Object.keys(starts).sort();
      if (times.length) {
        var duration = toMinutes(starts[times[0]]) - toMinutes(times[0]);
        var gap = times.length > 1 ? (toMinutes(times[1]) - toMinutes(times[0]) - duration) : parseInt($("#breakTime").value, 10);
        $("#startTime").value = times[0];
        $("#endTime").value = starts[times[times.length - 1]];
        if (duration > 0) $("#classDuration").value = duration;
        if (gap >= 0) $("#breakTime").value = gap;
      }
      var usedRooms = {};
      entries.forEach(function (e) { usedRooms[e.room_id] = true; });
      $("#buildingFilter").value = "";
      $("#roomLimit").value = Math.max(state.rooms.length, 1);

      if (!generateGrid({ silent: true })) return;

      state.placements = entries.map(function (entry) {
        return {
          uid: nextUid(), day: entry.day, start: entry.start_time, end: entry.end_time,
          room_id: entry.room_id, course_id: entry.course_id, section: entry.section
        };
      });
      dropOrphanPlacements();
      state.dirty = false;
      renderGrid();
      renderCourses();
      updateCounters();
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

  /* -------------------------------- exports ------------------------------- */
  function buildPrintable() {
    var host = $("#printArea");
    host.innerHTML = "";
    var title = el("h1", null, "University Timetable");
    title.style.fontSize = "16px";
    host.appendChild(title);

    for (var day = 1; day <= state.days; day++) {
      var wrapper = el("div", "pdf-day");
      wrapper.appendChild(el("h2", null, WEEKDAYS[day - 1]));
      var table = el("table");
      var thead = el("thead");
      var headRow = el("tr");
      headRow.appendChild(el("th", null, "Room"));
      state.slots.forEach(function (slot) {
        headRow.appendChild(el("th", null, to12h(slot.start) + "-" + to12h(slot.end)));
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = el("tbody");
      (function (d) {
        state.gridRooms.forEach(function (room) {
          var row = el("tr");
          row.appendChild(el("td", null, room.label));
          state.slots.forEach(function (slot) {
            var placement = placementAt(d, slot.start, room.id);
            var cell = el("td");
            if (placement) {
              var course = findCourse(placement.course_id, placement.section);
              cell.textContent = (course ? course.name : placement.course_id) + " - " + placement.section;
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
    if (!state.slots.length) { toast("Nothing to export", "Generate a grid first.", "warning"); return; }
    var host = buildPrintable();
    if (typeof window.html2pdf !== "function") {
      toast("PDF engine missing", "Falling back to the browser print dialog.", "warning");
      window.print();
      return;
    }
    host.style.display = "block";
    window.html2pdf().set({
      margin: 8,
      filename: "timetable.pdf",
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
    var rows = [["Day", "Start", "End", "Room", "Course", "Section", "Instructor", "Students"]];
    state.placements.slice().sort(function (a, b) {
      return a.day - b.day || toMinutes(a.start) - toMinutes(b.start);
    }).forEach(function (p) {
      var course = findCourse(p.course_id, p.section) || {};
      var room = state.rooms.filter(function (r) { return r.id === p.room_id; })[0];
      rows.push([
        WEEKDAYS[p.day - 1], p.start, p.end, room ? room.label : p.room_id,
        course.name || p.course_id, p.section, course.instructor || "", course.num_students || 0
      ]);
    });
    var csv = rows.map(function (row) {
      return row.map(function (cell) { return '"' + String(cell).replace(/"/g, '""') + '"'; }).join(",");
    }).join("\r\n");

    var blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8;" });
    var url = URL.createObjectURL(blob);
    var link = el("a");
    link.href = url;
    link.download = "timetable.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    toast("CSV exported", "timetable.csv downloaded.", "success");
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
      if (payload.type === "placed") removePlacement(payload.uid);
    });
  }

  function wireEvents() {
    $("#setupForm").addEventListener("submit", function (event) {
      event.preventDefault();
      if (state.placements.length &&
        !window.confirm("Rebuilding the grid keeps classes that still fit. Continue?")) return;
      generateGrid({ keepPlacements: true });
    });

    $("#courseSearch").addEventListener("input", renderCourses);
    $("#hidePlaced").addEventListener("change", renderCourses);

    $("#sidebarToggle").addEventListener("click", function () {
      var sidebar = $("#sidebar");
      var collapsed = sidebar.classList.toggle("collapsed");
      this.setAttribute("aria-expanded", collapsed ? "false" : "true");
      this.innerHTML = collapsed ? "&#10095;" : "&#10094;";
    });

    $("#saveToDatabase").addEventListener("click", saveToDatabase);
    $("#loadFromDatabase").addEventListener("click", loadFromDatabase);
    $("#validateAll").addEventListener("click", function () { revalidateAll({}); });
    $("#exportPdf").addEventListener("click", exportPdf);
    $("#exportCsv").addEventListener("click", exportCsv);
    $("#printView").addEventListener("click", function () { buildPrintable(); window.print(); });
    $("#clearGrid").addEventListener("click", function () {
      if (!state.placements.length) { toast("Already empty", "", "info"); return; }
      if (!window.confirm("Remove every class from the grid? (The saved timetable is untouched.)")) return;
      state.placements = [];
      state.conflicts = {};
      state.dirty = true;
      renderGrid(); renderCourses(); updateCounters();
    });
    $("#resetTimetable").addEventListener("click", resetSavedTimetable);
    $("#helpButton").addEventListener("click", function () { openDialog("#helpDialog"); });

    $$("[data-close-dialog]").forEach(function (btn) { btn.addEventListener("click", closeDialogs); });
    $$(".dialog").forEach(function (dialog) {
      dialog.addEventListener("click", function (event) { if (event.target === dialog) closeDialogs(); });
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeDialogs();
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        saveToDatabase();
      }
      if (event.key === "Delete" && state.selectedUid) removePlacement(state.selectedUid);
    });

    window.addEventListener("beforeunload", function (event) {
      if (state.dirty && state.placements.length) {
        event.preventDefault();
        event.returnValue = "";
      }
    });

    wireSidebarDropZone();
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
      setStatus((health.backend === "sqlite" ? "Local database" : "Server database") + " - " +
        (stats.courses || 0) + " courses, " + (stats.rooms || 0) + " rooms", "pill-ok");
    }).catch(function (err) {
      setStatus("Database offline", "pill-error");
      toast("Database problem", err.message, "error", 12000);
    });

    Promise.all([api("/api/rooms"), api("/api/courses")])
      .then(function (results) {
        state.rooms = results[0] || [];
        state.courses = results[1] || [];

        var select = $("#buildingFilter");
        var seen = {};
        state.rooms.forEach(function (room) {
          if (seen[room.building_id]) return;
          seen[room.building_id] = true;
          var option = el("option", null, "Building " + room.building_name);
          option.value = room.building_id;
          select.appendChild(option);
        });
        $("#roomLimit").value = Math.min(12, state.rooms.length || 12);

        renderCourses();
        return api("/api/settings").catch(function () { return {}; });
      })
      .then(function (config) {
        applySetup(config);
        generateGrid({ silent: true });
        return api("/api/timetable").catch(function () { return { entries: [] }; });
      })
      .then(function (data) {
        if (data && data.entries && data.entries.length) {
          toast("Saved timetable available",
            data.entries.length + " class(es) are stored. Press \u201cLoad saved\u201d to restore them.", "info", 9000);
        }
      })
      .catch(function (err) { toast("Startup problem", err.message, "error", 10000); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
