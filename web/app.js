const COLS = [
  { id: "todo", title: "К выполнению" },
  { id: "doing", title: "В работе" },
  { id: "done", title: "Сделано" },
];

const state = {
  board: null,
  dragId: null,
  selectedPersonId: null,
  meId: Number(localStorage.getItem("crm_me_id") || 0) || null,
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

function people() {
  return state.board?.employees || [];
}

function me() {
  return people().find((e) => e.id === state.meId) || null;
}

function boss() {
  return people().find((e) => e.role === "owner") || null;
}

function filteredTasks() {
  const projectId = $("#projectFilter").value;
  return state.board.tasks.filter((t) => {
    if (projectId && String(t.project_id) !== projectId) return false;
    if (state.selectedPersonId && String(t.assignee_id) !== String(state.selectedPersonId)) {
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
  const pf = $("#projectFilter");
  const cur = pf.value;
  pf.innerHTML =
    `<option value="">Все проекты</option>` +
    projects.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  pf.value = cur;
}

function updateMeLabel() {
  const m = me();
  $("#meLabel").textContent = m ? `вы: ${m.name}` : "не вошли";
}

function renderPeople() {
  const list = $("#peopleList");
  list.innerHTML = "";
  const all = people();
  if (!all.length) {
    list.innerHTML = `<div class="people-empty">Пока никого нет.<br/>Добавь менеджера или войди.</div>`;
    return;
  }
  for (const m of all) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className =
      "person" + (String(state.selectedPersonId) === String(m.id) ? " active" : "");
    const open = openCount(m.id);
    const role = m.role === "owner" ? "владелец" : "менеджер";
    btn.innerHTML = `
      <span>
        <span class="person-name">${escapeHtml(m.name)}</span>
        <span class="person-role">${role}</span>
      </span>
      <span class="person-count">${open}</span>
    `;
    btn.addEventListener("click", () => {
      state.selectedPersonId = m.id;
      $("#assignTo").value = "selected";
      render();
    });
    list.appendChild(btn);
  }
}

function renderManagerBar() {
  const hint = $("#emptyHint");
  const tasks = filteredTasks();
  if (!state.selectedPersonId) {
    $("#managerName").textContent = "Вся команда";
    $("#managerSub").textContent = "Можно писать задачу себе, владельцу или выбранному человеку";
  } else {
    const m = people().find((e) => e.id === state.selectedPersonId);
    $("#managerName").textContent = m ? m.name : "—";
    const open = tasks.filter((t) => t.status !== "done").length;
    $("#managerSub").textContent = `Открытых: ${open} · всего: ${tasks.length}`;
  }
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
          ${t.assignee_name ? `<span class="chip">→ ${escapeHtml(t.assignee_name)}</span>` : ""}
          ${t.created_by_name ? `<span class="chip">от ${escapeHtml(t.created_by_name)}</span>` : ""}
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
  updateMeLabel();
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

function resolveAssigneeId(mode) {
  if (mode === "me") {
    if (!state.meId) throw new Error("Сначала нажми «Войти» и укажи свой Telegram id");
    return state.meId;
  }
  if (mode === "boss") {
    const b = boss();
    if (!b) throw new Error("Владелец ещё не в базе — пусть напишет боту /start");
    return b.id;
  }
  // selected
  if (!state.selectedPersonId) {
    throw new Error("Выбери человека слева или поставь «Себе» / «Владельцу»");
  }
  return state.selectedPersonId;
}

async function load() {
  state.board = await api("/api/board");
  if (state.meId && !people().some((e) => e.id === state.meId)) {
    // maybe match by telegram later — keep id if still valid only
    state.meId = null;
    localStorage.removeItem("crm_me_id");
  }
  if (
    state.selectedPersonId &&
    !people().some((e) => e.id === state.selectedPersonId)
  ) {
    state.selectedPersonId = null;
  }
  render();
}

$("#projectFilter").addEventListener("change", render);

$("#btnAllPeople").addEventListener("click", () => {
  state.selectedPersonId = null;
  render();
});

$("#btnLogin").addEventListener("click", async () => {
  const tid = prompt("Твой Telegram numeric id (как в userinfobot):");
  if (!tid || !/^\d+$/.test(tid)) return;
  let emp = people().find((e) => String(e.telegram_id) === String(tid));
  if (!emp) {
    const name = prompt("Тебя ещё нет в CRM. Как тебя зовут?");
    if (!name) return;
    emp = await api("/api/employees", {
      method: "POST",
      body: JSON.stringify({
        name,
        telegram_id: Number(tid),
        role: "manager",
      }),
    });
  }
  state.meId = emp.id;
  localStorage.setItem("crm_me_id", String(emp.id));
  await load();
});

$("#quickAdd").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = e.target.elements.title;
  const title = String(input.value || "").trim();
  if (!title) return;
  try {
    if (!state.meId) {
      alert("Сначала нажми «Войти» — чтобы было понятно, от кого задача.");
      return;
    }
    const assigneeId = resolveAssigneeId($("#assignTo").value);
    const projectId = $("#projectFilter").value;
    const created = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        title,
        description: "",
        project_id: projectId ? Number(projectId) : null,
        assignee_id: Number(assigneeId),
        created_by_id: Number(state.meId),
        kind: "once",
        weekdays: "",
        status: "todo",
        notify_now: true,
      }),
    });
    input.value = "";
    await load();
    if (created && created.notified === false) {
      const retry = confirm(
        (created.notify_error || "В Telegram не ушло.") +
          "\n\nЧаще всего менеджер ещё не нажал /start у бота.\nПовторить отправку сейчас?"
      );
      if (retry && created.id) {
        const again = await api(`/api/tasks/${created.id}/notify`, { method: "POST" });
        if (again?.notified) alert("Отправлено в Telegram ✅");
        else alert(again?.notify_error || "Снова не ушло — пусть напишет боту /start");
      }
    }
  } catch (err) {
    alert(err.message || String(err));
  }
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
  if (!/^\d+$/.test(String(tid).trim())) {
    alert("Telegram id должен быть числом (как в @userinfobot)");
    return;
  }
  const emp = await api("/api/employees", {
    method: "POST",
    body: JSON.stringify({ name, telegram_id: Number(tid), role: "manager" }),
  });
  await load();
  state.selectedPersonId = emp.id;
  render();
  alert(
    `${name} добавлен(а).\n\nВажно: пусть откроет вашего бота в Telegram и нажмёт /start — иначе задачи не дойдут.`
  );
});

load().catch((err) => {
  console.error(err);
  alert("Не удалось загрузить доску: " + err.message);
});
