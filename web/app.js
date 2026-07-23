const COLS = [
  { id: "todo", title: "К выполнению" },
  { id: "doing", title: "В работе" },
  { id: "done", title: "Сделано" },
];

const state = { board: null, dragId: null };

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

function fillSelects() {
  const projects = state.board.projects;
  const employees = state.board.employees;
  const pf = $("#projectFilter");
  const cur = pf.value;
  pf.innerHTML = `<option value="">Все проекты</option>` +
    projects.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  pf.value = cur;

  $("#dlgProject").innerHTML =
    `<option value="">Без проекта</option>` +
    projects.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  $("#dlgAssignee").innerHTML =
    `<option value="">Без исполнителя</option>` +
    employees.map((e) => `<option value="${e.id}">${e.name}</option>`).join("");
}

function render() {
  const projectId = $("#projectFilter").value;
  const tasks = state.board.tasks.filter((t) => !projectId || String(t.project_id) === projectId);
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
          ${t.assignee_name ? `<span class="chip">${escapeHtml(t.assignee_name)}</span>` : ""}
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

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function load() {
  state.board = await api("/api/board");
  fillSelects();
  render();
}

$("#projectFilter").addEventListener("change", render);

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
  await api("/api/employees", {
    method: "POST",
    body: JSON.stringify({ name, telegram_id: Number(tid), role: "manager" }),
  });
  await load();
});

$("#btnNewTask").addEventListener("click", () => {
  fillSelects();
  $("#dlgTitle").textContent = "Новая задача";
  $("#dlgForm").reset();
  $("#dlg").showModal();
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
