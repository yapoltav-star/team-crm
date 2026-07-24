const COLS = [
  { id: "todo", title: "Новая" },
  { id: "doing", title: "В работе" },
  { id: "done", title: "Выполнено" },
];

const HOME_SECTIONS = [
  { key: "new", title: "Мои новые задачи", empty: "Нет новых" },
  { key: "doing", title: "Мои задачи в работе", empty: "Ничего в работе" },
  { key: "overdue", title: "Просроченные", empty: "Просрочек нет" },
  { key: "today", title: "Задачи на сегодня", empty: "На сегодня пусто" },
  { key: "upcoming", title: "Ближайшие дедлайны", empty: "Ближайших нет" },
];

const REC_LABELS = {
  daily: "Каждый день",
  weekly: "Каждую неделю",
  every_n_days: "Каждые N дней",
  monthly: "Каждый месяц",
  weekdays: "По дням недели",
  month_days: "По числам месяца",
};

const JOB_TITLES = [
  "поддержка",
  "менеджер",
  "склад",
  "партнер",
  "рук",
  "менеджер по китаю",
];

const JOB_TITLE_ORDER = Object.fromEntries(JOB_TITLES.map((t, i) => [t, i]));

const state = {
  view: localStorage.getItem("crm_view") || "home",
  board: null,
  home: null,
  templates: [],
  dragId: null,
  selectedPersonId: null,
  meId: Number(localStorage.getItem("crm_me_id") || 0) || null,
  currentTask: null,
};

const $ = (s) => document.querySelector(s);

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const pwd = localStorage.getItem("crm_password");
  if (pwd) headers["x-crm-password"] = pwd;
  const res = await fetch(path, { ...opts, headers, credentials: "same-origin" });
  if (res.status === 401) {
    localStorage.removeItem("crm_password");
    location.href = "/login";
    throw new Error("Unauthorized");
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

function taskAssigneeIds(t) {
  if (t.assignees?.length) return t.assignees.map((a) => a.id);
  return t.assignee_id ? [t.assignee_id] : [];
}

function taskHasAssignee(t, employeeId) {
  return taskAssigneeIds(t).includes(Number(employeeId));
}

function filteredTasks() {
  const projectId = $("#projectFilter").value;
  return state.board.tasks.filter((t) => {
    if (projectId && String(t.project_id) !== projectId) return false;
    if (state.selectedPersonId && !taskHasAssignee(t, state.selectedPersonId)) {
      return false;
    }
    return true;
  });
}

function openCount(employeeId) {
  return state.board.tasks.filter(
    (t) => taskHasAssignee(t, employeeId) && t.status !== "done"
  ).length;
}

function initials(name) {
  const parts = String(name || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function formatDt(raw) {
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDate(raw) {
  if (!raw) return "—";
  const d = typeof raw === "string" && raw.length <= 10 ? new Date(raw + "T12:00:00") : new Date(raw);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function parseArticles(raw) {
  if (!raw) return [];
  return String(raw)
    .split(/[,;\n]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function avatarsHtml(assignees) {
  const list = assignees?.length ? assignees : [];
  if (!list.length) return "";
  return `<div class="avatars">${list
    .map(
      (a) =>
        `<span class="avatar" title="${escapeHtml(a.name)}">${escapeHtml(initials(a.name))}</span>`
    )
    .join("")}</div>`;
}

function dueDot(flag) {
  if (!flag) return "";
  const title =
    flag === "overdue" ? "Просрочено" : flag === "today" ? "Сегодня" : "Выполнено";
  return `<span class="due-dot ${flag}" title="${title}"></span>`;
}

function setView(view) {
  state.view = view;
  localStorage.setItem("crm_view", view);
  $("#viewHome").classList.toggle("hidden", view !== "home");
  $("#viewBoard").classList.toggle("hidden", view !== "board");
  $("#viewTemplates").classList.toggle("hidden", view !== "templates");
  $("#viewArchive").classList.toggle("hidden", view !== "archive");
  document.querySelectorAll("#navTabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view);
  });
  $("#projectFilter").classList.toggle("hidden", view === "templates" || view === "archive");
}

function fillSelects() {
  const projects = state.board?.projects || [];
  const pf = $("#projectFilter");
  const cur = pf.value;
  pf.innerHTML =
    `<option value="">Все проекты</option>` +
    projects.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  pf.value = cur;
}

function isOwner() {
  return me()?.role === "owner";
}

function visiblePeople() {
  const all = people();
  if (isOwner()) return all;
  const m = me();
  if (!m) return [];
  const allowed = new Set([m.id, ...(m.can_see_ids || [])]);
  return all.filter((e) => allowed.has(e.id));
}

function peopleGroups(list) {
  const map = new Map();
  for (const e of list) {
    let g;
    if (e.role === "owner") g = "Владелец";
    else {
      const title = String(e.job_title || "").trim();
      const group = String(e.team_group || "").trim();
      g = title || group || "Без роли";
    }
    if (!map.has(g)) map.set(g, []);
    map.get(g).push(e);
  }
  return [...map.entries()].sort((a, b) => {
    if (a[0] === "Владелец") return -1;
    if (b[0] === "Владелец") return 1;
    if (a[0] === "Без роли") return 1;
    if (b[0] === "Без роли") return -1;
    const ai = JOB_TITLE_ORDER[a[0]];
    const bi = JOB_TITLE_ORDER[b[0]];
    if (ai != null || bi != null) {
      return (ai ?? 99) - (bi ?? 99) || a[0].localeCompare(b[0], "ru");
    }
    return a[0].localeCompare(b[0], "ru");
  });
}

function updateMeLabel() {
  const m = me();
  $("#meLabel").textContent = m ? `вы: ${m.name}` : "не вошли";
  $("#btnNewManager")?.classList.toggle("hidden", Boolean(m && !isOwner()));
  $("#btnNewGroup")?.classList.toggle("hidden", !isOwner());
}

function renderPeople() {
  const list = $("#peopleList");
  list.innerHTML = "";
  const all = visiblePeople();
  if (!all.length) {
    list.innerHTML = `<div class="people-empty">${
      state.meId
        ? "Нет доступных людей."
        : "Пока никого нет.<br/>Добавь менеджера или войди."
    }</div>`;
    return;
  }
  const owner = isOwner();
  for (const [groupName, members] of peopleGroups(all)) {
    const wrap = document.createElement("div");
    wrap.className = "people-group";
    const head = document.createElement("div");
    head.className = "people-group-head";
    const title = document.createElement("div");
    title.className = "people-group-title";
    title.textContent = groupName;
    head.appendChild(title);
    if (
      owner &&
      groupName !== "Без роли" &&
      groupName !== "Владелец" &&
      JOB_TITLE_ORDER[groupName] == null
    ) {
      const editGrp = document.createElement("button");
      editGrp.type = "button";
      editGrp.className = "ghost people-group-edit";
      editGrp.title = "Переименовать / состав";
      editGrp.textContent = "✎";
      editGrp.addEventListener("click", () => openGroupDialog(groupName));
      head.appendChild(editGrp);
    }
    wrap.appendChild(head);

    for (const m of members) {
      const row = document.createElement("div");
      row.className =
        "person" + (String(state.selectedPersonId) === String(m.id) ? " active" : "");
      const open = openCount(m.id);
      const roleLabel =
        m.role === "owner"
          ? "владелец"
          : String(m.job_title || "").trim() || "без роли";
      const main = document.createElement("button");
      main.type = "button";
      main.className = "person-main";
      main.innerHTML = `
        <span>
          <span class="person-name">${escapeHtml(m.name)}</span>
          <span class="person-role">${escapeHtml(roleLabel)}</span>
        </span>
        <span class="person-count">${open}</span>
      `;
      main.addEventListener("click", () => {
        state.selectedPersonId = m.id;
        $("#assignTo").value = "selected";
        renderBoardView();
      });
      row.appendChild(main);
      if (owner) {
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "ghost person-edit";
        edit.title = "Имя и доступы";
        edit.textContent = "✎";
        edit.addEventListener("click", (e) => {
          e.stopPropagation();
          openEmployeeDialog(m);
        });
        row.appendChild(edit);
      }
      wrap.appendChild(row);
    }
    list.appendChild(wrap);
  }
}

function openGroupDialog(existingName) {
  if (!isOwner()) {
    alert("Только владелец может управлять группами. Нажми «Войти» своим Telegram id.");
    return;
  }
  // Роли из списка — назначаются в карточке человека, не через «+ Группа»
  if (JOB_TITLE_ORDER[existingName] != null) {
    alert(
      `«${existingName}» — это роль.\nОткрой ✎ у человека и выбери роль в списке.`
    );
    return;
  }
  const form = $("#groupForm");
  const old = existingName && existingName !== "Без роли" ? existingName : "";
  form.elements.old_name.value = old;
  form.elements.name.value = old;
  $("#groupDlgTitle").textContent = old ? `Группа «${old}»` : "Новая группа";
  $("#groupDelete").classList.toggle("hidden", !old);
  const selected = new Set(
    people()
      .filter((e) => String(e.team_group || "").trim() === old)
      .map((e) => e.id)
  );
  $("#groupMemberChecks").innerHTML = people()
    .map(
      (e) => `
    <label class="check-row">
      <input type="checkbox" value="${e.id}" ${selected.has(e.id) ? "checked" : ""} />
      <span class="avatar mini">${escapeHtml(initials(e.name))}</span>
      ${escapeHtml(e.name)}
      ${e.role === "owner" ? " (владелец)" : ""}
    </label>`
    )
    .join("");
  $("#groupDlg").showModal();
  form.elements.name.focus();
}

function openEmployeeDialog(emp) {
  const form = $("#empForm");
  form.elements.id.value = emp.id;
  form.elements.name.value = emp.name || "";
  form.elements.job_title.value = emp.job_title || "";
  form.elements.team_group.value = emp.team_group || "";
  $("#empDlgTitle").textContent = emp.name || "Сотрудник";
  // владелец не меняет «должность» так же критично, но может — для единообразия
  form.elements.job_title.disabled = false;
  const accessBox = $("#empAccessChecks");
  const accessField = accessBox?.closest("fieldset");
  if (emp.role === "owner") {
    if (accessField) accessField.classList.add("hidden");
  } else {
    if (accessField) accessField.classList.remove("hidden");
    const others = people().filter((e) => e.id !== emp.id);
    const selected = new Set((emp.can_see_ids || []).map(Number));
    accessBox.innerHTML = others.length
      ? others
          .map(
            (e) => `
      <label class="check-row">
        <input type="checkbox" value="${e.id}" ${selected.has(e.id) ? "checked" : ""} />
        <span class="avatar mini">${escapeHtml(initials(e.name))}</span>
        ${escapeHtml(e.name)}
        ${e.role === "owner" ? " (владелец)" : ""}
      </label>`
          )
          .join("")
      : `<div class="chat-empty">Пока некого добавлять</div>`;
  }
  const groups = [
    ...new Set(
      people()
        .map((e) => String(e.team_group || "").trim())
        .filter(Boolean)
    ),
  ].sort((a, b) => a.localeCompare(b, "ru"));
  $("#groupSuggestions").innerHTML = groups
    .map((g) => `<option value="${escapeHtml(g)}"></option>`)
    .join("");
  $("#empDlg").showModal();
}

function closeDlg() {
  const dlg = $("#taskDlg");
  if (dlg?.open) dlg.close();
  document.body.classList.remove("dlg-open");
  state.currentTask = null;
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

function cardHtml(t) {
  const skus = parseArticles(t.articles);
  const skuHtml = skus.length
    ? `<div class="card-skus">${skus
        .map((s) => `<span class="sku">${escapeHtml(s)}</span>`)
        .join("")}</div>`
    : "";
  const assignees = t.assignees?.length
    ? t.assignees
    : t.assignee_name
      ? [{ id: t.assignee_id, name: t.assignee_name }]
      : [];
  return `
    ${dueDot(t.due_flag)}
    <div class="card-actions">
      <button type="button" class="btn-edit" title="Открыть">✎</button>
      <button type="button" class="btn-del danger" title="Удалить">✕</button>
    </div>
    ${skuHtml}
    <h3>${escapeHtml(t.title)}</h3>
    ${t.description ? `<div class="desc">${escapeHtml(t.description)}</div>` : ""}
    <div class="meta">
      ${avatarsHtml(assignees)}
      ${t.due_date ? `<span class="chip">до ${formatDate(t.due_date)}</span>` : ""}
      ${t.created_by_name ? `<span class="chip">от ${escapeHtml(t.created_by_name)}</span>` : ""}
      ${t.project_name ? `<span class="chip project">${escapeHtml(t.project_name)}</span>` : ""}
    </div>
  `;
}

function bindCard(card, t) {
  card.querySelector(".btn-edit").addEventListener("click", (e) => {
    e.stopPropagation();
    openTaskDialog(t.id);
  });
  card.querySelector(".btn-del").addEventListener("click", async (e) => {
    e.stopPropagation();
    await deleteTask(t);
  });
  card.addEventListener("dblclick", () => openTaskDialog(t.id));
  card.addEventListener("click", (e) => {
    if (e.target.closest(".card-actions")) return;
    openTaskDialog(t.id);
  });
  card.addEventListener("dragstart", (e) => {
    if (e.target.closest(".card-actions")) {
      e.preventDefault();
      return;
    }
    state.dragId = t.id;
    card.classList.add("dragging");
    e.dataTransfer.setData("text/plain", String(t.id));
  });
  card.addEventListener("dragend", () => {
    state.dragId = null;
    card.classList.remove("dragging");
  });
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
        body: JSON.stringify({ status: col.id, actor_id: state.meId || null }),
      });
      await load();
    });

    for (const t of list) {
      const card = document.createElement("article");
      card.className = `card due-${t.due_flag || "none"}`;
      card.draggable = true;
      card.dataset.id = t.id;
      card.innerHTML = cardHtml(t);
      bindCard(card, t);
      cards.appendChild(card);
    }
    colEl.appendChild(cards);
    board.appendChild(colEl);
  }
}

function renderHome() {
  const grid = $("#homeGrid");
  const hint = $("#homeHint");
  if (!state.meId) {
    hint.textContent = "Войди — увидишь свои задачи.";
    grid.innerHTML = `<div class="home-empty">Нажми «Войти» сверху.</div>`;
    return;
  }
  const m = me();
  hint.textContent = m ? `${m.name}, твои задачи` : "Твои задачи";
  if (!state.home) {
    grid.innerHTML = `<div class="home-empty">Загрузка…</div>`;
    return;
  }
  grid.innerHTML = "";
  for (const sec of HOME_SECTIONS) {
    const items = state.home[sec.key] || [];
    const box = document.createElement("section");
    box.className = `home-section ${sec.key}`;
    box.innerHTML = `<h2>${sec.title}<span>${items.length}</span></h2>`;
    const list = document.createElement("div");
    list.className = "home-cards";
    if (!items.length) {
      list.innerHTML = `<div class="home-empty-sec">${sec.empty}</div>`;
    } else {
      for (const t of items) {
        const card = document.createElement("article");
        card.className = `card home-card due-${t.due_flag || "none"}`;
        card.innerHTML = cardHtml(t);
        card.querySelector(".card-actions")?.remove();
        card.addEventListener("click", () => openTaskDialog(t.id));
        list.appendChild(card);
      }
    }
    box.appendChild(list);
    grid.appendChild(box);
  }
}

function renderTemplates() {
  const list = $("#tplList");
  list.innerHTML = "";
  if (!state.templates.length) {
    list.innerHTML = `<div class="home-empty">Шаблонов пока нет — создай первый.</div>`;
    return;
  }
  for (const t of state.templates) {
    const names = (t.assignee_ids || [])
      .map((id) => people().find((e) => e.id === id)?.name || `#${id}`)
      .join(", ");
    const el = document.createElement("article");
    el.className = `tpl-card ${t.active ? "" : "off"}`;
    el.innerHTML = `
      <div class="tpl-card-top">
        <h3>${escapeHtml(t.title)}</h3>
        <span class="chip ${t.active ? "ok" : ""}">${t.active ? "активен" : "выкл"}</span>
      </div>
      ${t.description ? `<p class="desc">${escapeHtml(t.description)}</p>` : ""}
      <div class="meta">
        <span class="chip">${REC_LABELS[t.recurrence] || t.recurrence}${
          t.recurrence_value ? `: ${escapeHtml(t.recurrence_value)}` : ""
        }</span>
        ${t.start_date ? `<span class="chip">с ${formatDate(t.start_date)}</span>` : ""}
        <span class="chip">@ ${escapeHtml(t.notify_time || "09:00")}</span>
        ${names ? `<span class="chip assignee">${escapeHtml(names)}</span>` : ""}
      </div>
    `;
    el.addEventListener("click", () => openTemplateDialog(t));
    list.appendChild(el);
  }
}

function renderBoardView() {
  fillSelects();
  updateMeLabel();
  renderPeople();
  renderManagerBar();
  renderBoard();
}

function render() {
  fillSelects();
  updateMeLabel();
  setView(state.view);
  if (state.view === "home") renderHome();
  if (state.view === "board") renderBoardView();
  if (state.view === "templates") renderTemplates();
  if (state.view === "archive") renderArchive();
}

const MONTH_RU = [
  "",
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];

async function renderArchive() {
  const sel = $("#archiveMonth");
  const list = $("#archiveList");
  const months = await api("/api/archive/months");
  if (!months.length) {
    sel.innerHTML = "";
    list.innerHTML = `<div class="home-empty">Архив пока пуст. Выполненные задачи попадут сюда через 7 дней.</div>`;
    return;
  }
  const cur = sel.value;
  sel.innerHTML = months
    .map(
      (m) =>
        `<option value="${m.year}-${m.month}">${MONTH_RU[m.month] || m.month} ${m.year} (${m.count})</option>`
    )
    .join("");
  if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
  const [y, mo] = sel.value.split("-").map(Number);
  const tasks = await api(
    `/api/archive?year=${y}&month=${mo}${state.meId ? `&viewer_id=${state.meId}` : ""}`
  );
  if (!tasks.length) {
    list.innerHTML = `<div class="home-empty">В этом месяце пусто.</div>`;
    return;
  }
  list.innerHTML = "";
  for (const t of tasks) {
    const el = document.createElement("article");
    el.className = "tpl-card";
    el.innerHTML = `
      <div class="tpl-card-top">
        <h3>${escapeHtml(t.title)}</h3>
        <span class="chip ok">выполнено</span>
      </div>
      <div class="meta">
        ${t.completed_at ? `<span class="chip">${formatDt(t.completed_at)}</span>` : ""}
        ${t.completed_by_name ? `<span class="chip">${escapeHtml(t.completed_by_name)}</span>` : ""}
        ${t.articles ? `<span class="chip project">${escapeHtml(t.articles)}</span>` : ""}
      </div>
    `;
    el.addEventListener("click", () => openTaskDialog(t.id));
    list.appendChild(el);
  }
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
  if (!state.selectedPersonId) {
    throw new Error("Выбери человека слева или поставь «Себе» / «Владельцу»");
  }
  return state.selectedPersonId;
}

function fillAssigneeChecks(containerId, selectedIds) {
  const box = $(containerId);
  const selected = new Set((selectedIds || []).map(Number));
  const list = isOwner() ? people() : visiblePeople();
  box.innerHTML = list
    .map(
      (e) => `
      <label class="check-row">
        <input type="checkbox" value="${e.id}" ${selected.has(e.id) ? "checked" : ""} />
        <span class="avatar mini">${escapeHtml(initials(e.name))}</span>
        ${escapeHtml(e.name)}
      </label>`
    )
    .join("");
}

function readAssigneeChecks(containerId) {
  return [...document.querySelectorAll(`${containerId} input[type=checkbox]:checked`)].map((el) =>
    Number(el.value)
  );
}

function renderDatesBox(task) {
  $("#datesBox").innerHTML = `
    <div class="date-row"><span>Создана</span><b>${formatDt(task.created_at)}</b>${
      task.created_by_name ? ` · ${escapeHtml(task.created_by_name)}` : ""
    }</div>
    <div class="date-row"><span>В работе</span><b>${formatDt(task.started_at)}</b></div>
    <div class="date-row"><span>Выполнена</span><b>${formatDt(task.completed_at)}</b>${
      task.completed_by_name ? ` · ${escapeHtml(task.completed_by_name)}` : ""
    }</div>
  `;
}

function renderComments(task) {
  const box = $("#commentsBox");
  const comments = task.comments || [];
  if (!comments.length) {
    box.innerHTML = `<div class="chat-empty">Пока тихо — напиши первый комментарий.</div>`;
    return;
  }
  box.innerHTML = comments
    .map(
      (c) => `
    <div class="chat-msg">
      <div class="chat-meta">
        <strong>${escapeHtml(c.author_name || "—")}</strong>
        <time>${formatDt(c.created_at)}</time>
      </div>
      <div class="chat-body">${escapeHtml(c.body || "")}</div>
      ${
        c.file_url || c.file_name
          ? `<a class="chat-file" href="${escapeHtml(c.file_url || "#")}" target="_blank" rel="noopener">${escapeHtml(
              c.file_name || c.file_url
            )}</a>`
          : ""
      }
    </div>`
    )
    .join("");
  box.scrollTop = box.scrollHeight;
}

function renderEvents(task) {
  const box = $("#eventsBox");
  const events = task.events || [];
  if (!events.length) {
    box.innerHTML = `<div class="chat-empty">История пуста</div>`;
    return;
  }
  box.innerHTML = events
    .map(
      (e) => `
    <div class="event-row">
      <div class="event-msg">${escapeHtml(e.message)}</div>
      <time>${formatDt(e.created_at)}</time>
    </div>`
    )
    .join("");
}

async function openTaskDialog(taskId) {
  const q = state.meId ? `?viewer_id=${state.meId}` : "";
  const task = await api(`/api/tasks/${taskId}${q}`);
  state.currentTask = task;
  const dlg = $("#taskDlg");
  const form = $("#dlgForm");
  $("#dlgTitle").textContent = `Задача #${task.id}`;
  form.elements.id.value = task.id;
  form.elements.title.value = task.title || "";
  form.elements.articles.value = task.articles || "";
  form.elements.description.value = task.description || "";
  form.elements.status.value = task.status || "todo";
  form.elements.due_date.value = task.due_date || "";
  const project = form.elements.project_id;
  project.innerHTML =
    `<option value="">Без проекта</option>` +
    (state.board?.projects || [])
      .map(
        (p) =>
          `<option value="${p.id}" ${Number(task.project_id) === p.id ? "selected" : ""}>${escapeHtml(p.name)}</option>`
      )
      .join("");
  fillAssigneeChecks("#assigneeChecks", taskAssigneeIds(task));
  renderDatesBox(task);
  renderComments(task);
  renderEvents(task);
  $("#commentBody").value = "";
  $("#commentFile").value = "";
  document.body.classList.add("dlg-open");
  dlg.showModal();
  const grid = dlg.querySelector(".drawer-grid");
  if (grid) grid.scrollTop = 0;
}

async function deleteTask(task) {
  if (!confirm(`Удалить задачу «${task.title}»?\nУдалить может любой из команды.`)) return;
  const q = state.meId ? `?actor_id=${state.meId}` : "";
  await api(`/api/tasks/${task.id}${q}`, { method: "DELETE" });
  closeDlg();
  await load();
}

function updateTplValueHint() {
  const rec = $("#tplRecurrence").value;
  const label = $("#tplValueLabel");
  const input = $("#tplValue");
  const hints = {
    daily: ["Не нужно", ""],
    weekly: ["День недели (1=пн … 7=вс)", "1"],
    every_n_days: ["Каждые N дней", "3"],
    monthly: ["Число месяца", "1"],
    weekdays: ["Дни недели через запятую", "1,3,5"],
    month_days: ["Числа месяца через запятую", "1,15"],
  };
  const [text, ph] = hints[rec] || ["Значение", ""];
  $("#tplValueHint").textContent = text;
  input.placeholder = ph;
  input.disabled = rec === "daily";
  if (rec === "daily") input.value = "";
}

function openTemplateDialog(tpl) {
  const form = $("#tplForm");
  $("#tplDlgTitle").textContent = tpl ? `Шаблон #${tpl.id}` : "Новый шаблон";
  form.elements.id.value = tpl?.id || "";
  form.elements.title.value = tpl?.title || "";
  form.elements.description.value = tpl?.description || "";
  form.elements.recurrence.value = tpl?.recurrence || "daily";
  form.elements.recurrence_value.value = tpl?.recurrence_value || "";
  form.elements.start_date.value = tpl?.start_date || "";
  form.elements.notify_time.value = tpl?.notify_time || "09:00";
  form.elements.active.checked = tpl ? !!tpl.active : true;
  fillAssigneeChecks("#tplAssigneeChecks", tpl?.assignee_ids || []);
  updateTplValueHint();
  $("#tplDelete").classList.toggle("hidden", !tpl?.id);
  $("#tplDlg").showModal();
}

async function loadHome() {
  if (!state.meId) {
    state.home = null;
    return;
  }
  state.home = await api(`/api/home?employee_id=${state.meId}`);
}

async function loadTemplates() {
  state.templates = await api("/api/templates");
}

async function load() {
  const q = state.meId ? `?viewer_id=${state.meId}` : "";
  state.board = await api(`/api/board${q}`);
  if (state.meId && !people().some((e) => e.id === state.meId)) {
    state.meId = null;
    localStorage.removeItem("crm_me_id");
  }
  if (
    state.selectedPersonId &&
    !visiblePeople().some((e) => e.id === state.selectedPersonId)
  ) {
    state.selectedPersonId = null;
  }
  await Promise.all([loadHome(), loadTemplates()]);
  render();
}

/* —— events —— */
document.querySelectorAll("#navTabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    setView(btn.dataset.view);
    render();
  });
});

$("#projectFilter").addEventListener("change", () => {
  if (state.view === "board") renderBoardView();
});

$("#btnAllPeople").addEventListener("click", () => {
  state.selectedPersonId = null;
  renderBoardView();
});

$("#btnLogout").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST", body: "{}" });
  } catch (_) {
    /* ignore */
  }
  localStorage.removeItem("crm_password");
  location.href = "/login";
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
  } else if (!emp.name || /^(владелец|owner)$/i.test(emp.name)) {
    const name = prompt("Как тебя зовут в CRM?", "Ярослав");
    if (name && name.trim()) {
      emp = await api(`/api/employees/${emp.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: name.trim() }),
      });
    }
  }
  state.meId = emp.id;
  localStorage.setItem("crm_me_id", String(emp.id));
  await load();
});

$("#btnRename").addEventListener("click", async () => {
  if (!state.meId) {
    alert("Сначала нажми «Войти»");
    return;
  }
  const current = me()?.name || "";
  const name = prompt("Как тебя зовут в CRM?", current || "Ярослав");
  if (!name || !name.trim()) return;
  try {
    await api(`/api/employees/${state.meId}`, {
      method: "PATCH",
      body: JSON.stringify({ name: name.trim() }),
    });
    await load();
  } catch (err) {
    alert(err.message || String(err));
  }
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
    const due = $("#quickDue").value || null;
    const created = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        title,
        description: "",
        project_id: projectId ? Number(projectId) : null,
        assignee_id: Number(assigneeId),
        assignee_ids: [Number(assigneeId)],
        created_by_id: Number(state.meId),
        due_date: due,
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
  setView("board");
  render();
  alert(
    `${name} добавлен(а).\n\nВажно: пусть откроет вашего бота в Telegram и нажмёт /start — иначе задачи не дойдут.`
  );
});

$("#dlgCancel").addEventListener("click", (e) => {
  e.preventDefault();
  closeDlg();
});
$("#dlgClose").addEventListener("click", (e) => {
  e.preventDefault();
  closeDlg();
});

$("#taskDlg").addEventListener("close", () => {
  document.body.classList.remove("dlg-open");
  state.currentTask = null;
});

$("#taskDlg").addEventListener("click", (e) => {
  if (e.target === $("#taskDlg")) closeDlg();
});

$("#taskDlg").addEventListener(
  "wheel",
  (e) => {
    e.stopPropagation();
  },
  { passive: true }
);

$("#empCancel")?.addEventListener("click", () => $("#empDlg").close());

$("#btnNewGroup")?.addEventListener("click", () => openGroupDialog(""));

$("#groupCancel")?.addEventListener("click", () => $("#groupDlg").close());

$("#groupDelete")?.addEventListener("click", async () => {
  const form = $("#groupForm");
  const old = String(form.elements.old_name.value || "").trim();
  if (!old || !state.meId) return;
  if (!confirm(`Расформировать группу «${old}»?\nЛюди останутся в команде без группы.`)) return;
  try {
    await api("/api/team-groups", {
      method: "POST",
      body: JSON.stringify({
        name: old,
        old_name: old,
        employee_ids: [],
        actor_id: state.meId,
      }),
    });
    $("#groupDlg").close();
    await load();
  } catch (err) {
    alert(err.message || String(err));
  }
});

$("#groupForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!isOwner() || !state.meId) {
    alert("Только владелец может управлять группами. Нажми «Войти».");
    return;
  }
  const form = e.target;
  const name = String(form.elements.name.value || "").trim();
  if (!name) {
    alert("Введи название группы");
    return;
  }
  const employee_ids = [
    ...document.querySelectorAll("#groupMemberChecks input:checked"),
  ].map((el) => Number(el.value));
  try {
    await api("/api/team-groups", {
      method: "POST",
      body: JSON.stringify({
        name,
        old_name: String(form.elements.old_name.value || "").trim() || null,
        employee_ids,
        actor_id: state.meId,
      }),
    });
    $("#groupDlg").close();
    await load();
  } catch (err) {
    alert(err.message || String(err));
  }
});

$("#empForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!isOwner() || !state.meId) {
    alert("Только владелец может редактировать доступы");
    return;
  }
  const form = e.target;
  const id = Number(form.elements.id.value);
  const emp = people().find((e) => e.id === id);
  const can_see_ids =
    emp?.role === "owner"
      ? undefined
      : [...document.querySelectorAll("#empAccessChecks input:checked")].map((el) =>
          Number(el.value)
        );
  try {
    const body = {
      name: String(form.elements.name.value || "").trim(),
      job_title: String(form.elements.job_title.value || "").trim(),
      team_group: String(form.elements.team_group.value || "").trim(),
      actor_id: state.meId,
    };
    if (can_see_ids !== undefined) body.can_see_ids = can_see_ids;
    await api(`/api/employees/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    $("#empDlg").close();
    await load();
  } catch (err) {
    alert(err.message || String(err));
  }
});

$("#archiveMonth")?.addEventListener("change", () => {
  if (state.view === "archive") renderArchive();
});

$("#dlgDelete").addEventListener("click", async () => {
  const id = Number($("#dlgForm").elements.id.value);
  const task = state.currentTask || state.board?.tasks?.find((t) => t.id === id);
  if (!task) return;
  try {
    await deleteTask(task);
  } catch (err) {
    alert(err.message || String(err));
  }
});

$("#dlgForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const id = Number(form.elements.id.value);
  const assignee_ids = readAssigneeChecks("#assigneeChecks");
  const body = {
    title: String(form.elements.title.value || "").trim(),
    description: String(form.elements.description.value || ""),
    articles: String(form.elements.articles.value || "").trim(),
    status: form.elements.status.value,
    due_date: form.elements.due_date.value || null,
    assignee_ids,
    assignee_id: assignee_ids[0] || null,
    project_id: form.elements.project_id.value
      ? Number(form.elements.project_id.value)
      : null,
    actor_id: state.meId || null,
  };
  if (!body.title) {
    alert("Введи текст задачи");
    return;
  }
  try {
    await api(`/api/tasks/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
    closeDlg();
    await load();
  } catch (err) {
    alert(err.message || String(err));
  }
});

$("#btnComment").addEventListener("click", async () => {
  const id = Number($("#dlgForm").elements.id.value);
  const body = String($("#commentBody").value || "").trim();
  const fileRaw = String($("#commentFile").value || "").trim();
  if (!body && !fileRaw) return;
  if (!state.meId) {
    alert("Сначала войди — комментарии от твоего имени.");
    return;
  }
  try {
    await api(`/api/tasks/${id}/comments`, {
      method: "POST",
      body: JSON.stringify({
        body,
        author_id: state.meId,
        file_name: fileRaw && !/^https?:\/\//i.test(fileRaw) ? fileRaw : fileRaw ? "файл" : "",
        file_url: /^https?:\/\//i.test(fileRaw) ? fileRaw : "",
      }),
    });
    await openTaskDialog(id);
    await load();
  } catch (err) {
    alert(err.message || String(err));
  }
});

$("#btnNewTemplate").addEventListener("click", () => openTemplateDialog(null));
$("#tplCancel").addEventListener("click", () => $("#tplDlg").close());
$("#tplRecurrence").addEventListener("change", updateTplValueHint);

$("#tplDelete").addEventListener("click", async () => {
  const id = Number($("#tplForm").elements.id.value);
  if (!id || !confirm("Удалить шаблон? Уже созданные задачи не затронет.")) return;
  await api(`/api/templates/${id}`, { method: "DELETE" });
  $("#tplDlg").close();
  await load();
});

$("#tplForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const id = Number(form.elements.id.value) || null;
  const payload = {
    title: String(form.elements.title.value || "").trim(),
    description: String(form.elements.description.value || ""),
    recurrence: form.elements.recurrence.value,
    recurrence_value: String(form.elements.recurrence_value.value || "").trim(),
    start_date: form.elements.start_date.value || null,
    notify_time: String(form.elements.notify_time.value || "09:00").trim() || "09:00",
    active: !!form.elements.active.checked,
    assignee_ids: readAssigneeChecks("#tplAssigneeChecks"),
  };
  if (!payload.title) {
    alert("Нужно название");
    return;
  }
  try {
    if (id) {
      await api(`/api/templates/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
    } else {
      await api("/api/templates", { method: "POST", body: JSON.stringify(payload) });
    }
    $("#tplDlg").close();
    await load();
  } catch (err) {
    alert(err.message || String(err));
  }
});

load().catch((err) => {
  console.error(err);
  alert("Не удалось загрузить CRM: " + err.message);
});
