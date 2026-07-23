const COLS = [
  { id: "todo", title: "К выполнению" },
  { id: "doing", title: "В работе" },
  { id: "done", title: "Сделано" },
];

const state = {
  board: null,
  dragId: null,
  selectedManagerId: null, // null = all
};

const $ = (s) => document.querySelector(s);

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const pwd = localStorage.getItem("crm_password");
  if (pwd) headers["x-crm-password"] = pwd;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    const entered = prompt("Пароль к CRM (WEB_PASSWORD):");
    if (entered) {
      localStorage.setItem("crm_password", entered);
      return api(path, opts);
    }
  }
  if (!res.ok) throw new Error(await res.text());
  if (res.status === 204) return null;
  return res.json();
}

function managersOnly() {
  return (state.board?.employees || []).filter((e) => e.role === "manager" || e.role === "owner");
}

function filteredTasks() {
  const projectId = $("#projectFilter").value;
  return state.board.tasks.filter((t) => {
    if (projectId && String(t.project_id) !== projectId) return false;
    if (state.selectedManagerId && String(t.assignee_id) !== String(state.selectedManagerId)) {
      return false;
    }
    return true;
  });
}

function openCount(employeeId) {
  return state.board.tasks.filter(
    (t) => t.assignee_id === employeeId && t.status !== "done"
  ).length;
}

function fillSelects() {
  const projects = state.board.projects;
  const employees = state.board.employees;
  const pf = $("#projectFilter");
  const cur = pf.value;
  pf.innerHTML =
    `<option value="">Все проекты</option>` +
    projects.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  pf.value = cur;

  $("#dlgProject").innerHTML =
    `<option value="">Без проекта</option>` +
    projects.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  $("#dlgAssignee").innerHTML =
    `<option value="">Без исполнителя</option>` +
    employees.map((e) => `<option value="${e.id}">${e.name}</option>`).join("");
}

function renderPeople() {
  const list = $("#peopleList");
  list.innerHTML = "";
  const people = managersOnly();
  if (!people.length) {
    list.innerHTML = `<div class="people-empty">Пока никого нет.<br/>Нажми «+ Менеджер».</div>`;
    return;
  }
  for (const m of people) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className =
      "person" + (String(state.selectedManagerId) === String(m.id) ? " active" : "");
    const open = openCount(m.id);
    btn.innerHTML = `
      <span class="person-name">${escapeHtml(m.name)}</span>
      <span class="person-count">${open}</span>
    `;
    btn.addEventListener("click", () => {
      state.selectedManagerId = m.id;
      render();
    });
    list.appendChild(btn);
  }
}

function renderManagerBar() {
  const bar = $("#managerBar");
  const hint = $("#emptyHint");
  if (!state.selectedManagerId) {
    bar.classList.add("hidden");
    hint.classList.add("hidden");
    return;
  }
  const m = state.board.employees.find((e) => e.id === state.selectedManagerId);
  if (!m) {
    bar.classList.add("hidden");
    return;
  }
  bar.classList.remove("hidden");
  $("#managerName").textContent = m.name;
  const tasks = filteredTasks();
  const open = tasks.filter((t) => t.status !== "done").length;
  $("#managerSub").textContent = `Открытых задач: ${open} · всего на доске: ${tasks.length}`;
  hint.classList.toggle("hidden", tasks.length > 0);
}

function renderBoard() {
  const tasks = filteredTasks();
  const board = $("#board");
  board.innerHTML = "";

  for (const col of COLS) {
    const colEl = document.createElement("section");
    colEl.className = `column ${col.id}`;
    const list = tasks.filter((t) => t.status === col.id);
    colEl.innerHTML = `<h2>${col.title}<span>${list.length}</span></h2>`;
    const cards = document.createElement("div");
    cards.className = "cards";
    cards.dataset.status = col.id;

    cards.addEventListener("dragover", (e) => {
      e.preventDefault();
      cards.classList.add("drag-over");
    });
    cards.addEventListener("dragleave", () => cards.classList.remove("drag-over"));
    cards.addEventListener("drop", async (e) => {
      e.preventDefault();
      cards.classList.remove("drag-over");
      const id = Number(state.dragId || e.dataTransfer.getData("text/plain"));
      if (!id) return;
      await api(`/api/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: col.id }),
      });
      await load();
    });

    for (const t of list) {
      const card = document.createElement("article");
      card.className = "card";
      card.draggable = true;
      card.dataset.id = t.id;
      card.innerHTML = `
        <h3>${escapeHtml(t.title)}</h3>
        ${t.description ? `<div class="desc">${escapeHtml(t.description)}</div>` : ""}
        <div class="meta">
          ${t.project_name ? `<span class="chip project">${escapeHtml(t.project_name)}</span>` : ""}
          ${!state.selectedManagerId && t.assignee_name ? `<span class="chip">${escapeHtml(t.assignee_name)}</span>` : ""}
          ${t.kind === "weekly" ? `<span class="chip">↻ ${escapeHtml(t.weekdays)} @ ${escapeHtml(t.notify_time)}</span>` : ""}
        </div>
      `;
      card.addEventListener("dragstart", (e) => {
        state.dragId = t.id;
        card.classList.add("dragging");
        e.dataTransfer.setData("text/plain", String(t.id));
      });
      card.addEventListener("dragend", () => {
        state.dragId = null;
        card.classList.remove("dragging");
      });
      cards.appendChild(card);
    }
    colEl.appendChild(cards);
    board.appendChild(colEl);
  }
}

function render() {
  fillSelects();
  renderPeople();
  renderManagerBar();
  renderBoard();
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function load() {
  state.board = await api("/api/board");
  if (
    state.selectedManagerId &&
    !state.board.employees.some((e) => e.id === state.selectedManagerId)
  ) {
    state.selectedManagerId = null;
  }
  render();
}

$("#projectFilter").addEventListener("change", render);

$("#btnAllPeople").addEventListener("click", () => {
  state.selectedManagerId = null;
  render();
});

$("#quickAdd").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.selectedManagerId) return;
  const input = e.target.elements.title;
  const title = String(input.value || "").trim();
  if (!title) return;
  const projectId = $("#projectFilter").value;
  await api("/api/tasks", {
    method: "POST",
    body: JSON.stringify({
      title,
      description: "",
      project_id: projectId ? Number(projectId) : null,
      assignee_id: Number(state.selectedManagerId),
      kind: "once",
      weekdays: "",
      notify_time: "09:00",
      status: "todo",
    }),
  });
  input.value = "";
  await load();
});

$("#btnNewProject").addEventListener("click", async () => {
  const name = prompt("Название проекта:");
  if (!name) return;
  await api("/api/projects", { method: "POST", body: JSON.stringify({ name }) });
  await load();
});

$("#btnNewManager").addEventListener("click", async () => {
  const name = prompt("Имя менеджера:");
  const tid = prompt("Telegram numeric id:");
  if (!name || !tid) return;
  const emp = await api("/api/employees", {
    method: "POST",
    body: JSON.stringify({ name, telegram_id: Number(tid), role: "manager" }),
  });
  await load();
  state.selectedManagerId = emp.id;
  render();
});

$("#dlgForm").addEventListener("submit", async (e) => {
  const submitter = e.submitter;
  if (submitter && submitter.value === "cancel") return;
  e.preventDefault();
  const fd = new FormData($("#dlgForm"));
  const body = {
    title: fd.get("title"),
    description: fd.get("description") || "",
    project_id: fd.get("project_id") ? Number(fd.get("project_id")) : null,
    assignee_id: fd.get("assignee_id") ? Number(fd.get("assignee_id")) : null,
    kind: fd.get("kind"),
    weekdays: fd.get("weekdays") || "",
    notify_time: fd.get("notify_time") || "09:00",
    status: "todo",
  };
  await api("/api/tasks", { method: "POST", body: JSON.stringify(body) });
  $("#dlg").close();
  await load();
});

load().catch((err) => {
  console.error(err);
  alert("Не удалось загрузить доску: " + err.message);
});
