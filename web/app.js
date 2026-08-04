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
  monthly: "Число месяца",
  weekdays: "Дни недели",
  month_days: "Числа месяца",
};

const WEEKDAY_RU = [
  { v: 1, short: "Пн" },
  { v: 2, short: "Вт" },
  { v: 3, short: "Ср" },
  { v: 4, short: "Чт" },
  { v: 5, short: "Пт" },
  { v: 6, short: "Сб" },
  { v: 7, short: "Вс" },
];

const JOB_TITLES = [
  "поддержка",
  "менеджер",
  "склад",
  "партнер",
  "рук",
  "менеджер по китаю",
];

const JOB_TITLE_ORDER = Object.fromEntries(JOB_TITLES.map((t, i) => [t, i]));

const PROJECT_COLORS = [
  "#2563eb",
  "#059669",
  "#d97706",
  "#dc2626",
  "#7c3aed",
  "#db2777",
  "#0891b2",
  "#65a30d",
  "#ea580c",
  "#4f46e5",
];

function projectColor(name) {
  const key = String(name || "Без проекта").trim() || "Без проекта";
  if (key === "Владелец") return "#64748b";
  if (key === "Без проекта") return "#94a3b8";
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 33 + key.charCodeAt(i)) >>> 0;
  return PROJECT_COLORS[h % PROJECT_COLORS.length];
}

function taskProjectName(t) {
  if (t.assignees?.length) {
    for (const a of t.assignees) {
      if (a.team_group) return String(a.team_group).trim();
    }
  }
  const ids = taskAssigneeIds(t);
  for (const id of ids) {
    const emp = people().find((e) => e.id === id);
    if (emp?.team_group) return String(emp.team_group).trim();
  }
  if (t.created_by_id) {
    const author = people().find((e) => e.id === t.created_by_id);
    if (author?.team_group) return String(author.team_group).trim();
  }
  return "Без проекта";
}


const _savedView = localStorage.getItem("crm_view") || "home";
const state = {
  view: _savedView === "mindmap" ? "home" : _savedView,
  board: null,
  home: null,
  templates: [],
  dragId: null,
  selectedPersonId: null,
  selectedProject: null,
  meId: Number(localStorage.getItem("crm_me_id") || 0) || null,
  currentTask: null,
};

const $ = (s) => document.querySelector(s);

function getTheme() {
  const t = localStorage.getItem("pw_theme") || localStorage.getItem("crm_theme") || "light";
  return t === "dark" ? "dark" : "light";
}

function applyTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("pw_theme", next);
  localStorage.setItem("crm_theme", next);
  const icon = $("#themeIcon");
  const label = $("#themeLabel");
  if (icon) icon.textContent = next === "dark" ? "☀" : "☾";
  if (label) label.textContent = next === "dark" ? "Светлая" : "Тёмная";
}

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
  const projectPeople =
    state.selectedProject && state.selectedProject !== "Владелец"
      ? new Set(
          visiblePeople()
            .filter((e) => {
              if (state.selectedProject === "Без проекта") {
                return e.role !== "owner" && !String(e.team_group || "").trim();
              }
              return String(e.team_group || "").trim() === state.selectedProject;
            })
            .map((e) => e.id)
        )
      : null;
  return state.board.tasks.filter((t) => {
    if (state.selectedPersonId && !taskHasAssignee(t, state.selectedPersonId)) {
      return false;
    }
    if (projectPeople && !state.selectedPersonId) {
      const ids = taskAssigneeIds(t);
      if (!ids.some((id) => projectPeople.has(id))) return false;
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
}

function fillSelects() {
  /* project filter removed from header — sidebar filters the board */
}

function isOwner() {
  return me()?.role === "owner";
}

function isPartner() {
  const t = String(me()?.job_title || "")
    .trim()
    .toLowerCase()
    .replaceAll("ё", "е");
  return t === "партнер";
}

function visiblePeople() {
  const all = people();
  if (isOwner()) return all;
  const m = me();
  if (!m) return [];
  // партнёр видит всех в своём проекте (слева и их задачи)
  if (isPartner()) {
    const team = String(m.team_group || "").trim();
    if (team) {
      return all.filter(
        (e) =>
          e.id === m.id ||
          (e.role !== "owner" && String(e.team_group || "").trim() === team)
      );
    }
  }
  const allowed = new Set([m.id, ...(m.can_see_ids || [])]);
  return all.filter((e) => allowed.has(e.id));
}

function peopleTree(list) {
  /** project → role → people */
  const tree = new Map();
  for (const e of list) {
    const project =
      e.role === "owner"
        ? "Владелец"
        : String(e.team_group || "").trim() || "Без проекта";
    const role =
      e.role === "owner"
        ? "владелец"
        : String(e.job_title || "").trim() || "без роли";
    if (!tree.has(project)) tree.set(project, new Map());
    const roles = tree.get(project);
    if (!roles.has(role)) roles.set(role, []);
    roles.get(role).push(e);
  }

  const sortRoles = (entries) =>
    entries.sort((a, b) => {
      if (a[0] === "владелец") return -1;
      if (b[0] === "владелец") return 1;
      if (a[0] === "без роли") return 1;
      if (b[0] === "без роли") return -1;
      const ai = JOB_TITLE_ORDER[a[0]];
      const bi = JOB_TITLE_ORDER[b[0]];
      if (ai != null || bi != null) {
        return (ai ?? 99) - (bi ?? 99) || a[0].localeCompare(b[0], "ru");
      }
      return a[0].localeCompare(b[0], "ru");
    });

  return [...tree.entries()]
    .sort((a, b) => {
      if (a[0] === "Владелец") return -1;
      if (b[0] === "Владелец") return 1;
      if (a[0] === "Без проекта") return 1;
      if (b[0] === "Без проекта") return -1;
      return a[0].localeCompare(b[0], "ru");
    })
    .map(([project, roles]) => [project, sortRoles([...roles.entries()])]);
}

function updateMeLabel() {
  const m = me();
  const label = $("#meLabel");
  const login = $("#btnLogin");
  const logout = $("#btnLogout");
  if (m) {
    label.textContent = `вы: ${m.name}`;
    label.title = "Нажми, чтобы сменить имя";
    label.classList.add("is-user");
    login?.classList.add("hidden");
    logout?.classList.remove("hidden");
  } else {
    label.textContent = "не вошли";
    label.title = "Нажми, чтобы войти";
    label.classList.remove("is-user");
    login?.classList.remove("hidden");
    logout?.classList.add("hidden");
  }
  $("#btnNewGroup")?.classList.toggle("hidden", !isOwner());
}

async function renameEmployee(emp, { promptLabel } = {}) {
  if (!emp?.id) return;
  const current = emp.name || "";
  const name = prompt(
    promptLabel || "Как зовут в Project Workflow?",
    current || ""
  );
  if (!name || !name.trim() || name.trim() === current) return;
  await api(`/api/employees/${emp.id}`, {
    method: "PATCH",
    body: JSON.stringify({ name: name.trim() }),
  });
  await load();
}

function renderPersonRow(m, owner) {
  const row = document.createElement("div");
  row.className =
    "person" + (String(state.selectedPersonId) === String(m.id) ? " active" : "");
  const open = openCount(m.id);
  const main = document.createElement("button");
  main.type = "button";
  main.className = "person-main";
  const canRenameSelf = state.meId && Number(m.id) === Number(state.meId);
  main.innerHTML = `
    <span class="person-name${canRenameSelf ? " can-rename" : ""}" title="${
      canRenameSelf ? "Двойной клик — сменить имя" : ""
    }">${escapeHtml(m.name)}</span>
    <span class="person-count">${open}</span>
  `;
  main.addEventListener("click", () => {
    state.selectedPersonId = m.id;
    state.selectedProject = String(m.team_group || "").trim() ||
      (m.role === "owner" ? "Владелец" : "Без проекта");
    $("#assignTo").value = "selected";
    renderBoardView();
  });
  if (canRenameSelf) {
    main.addEventListener("dblclick", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        await renameEmployee(m, {
          promptLabel: "Как тебя зовут в Project Workflow?",
        });
      } catch (err) {
        alert(err.message || String(err));
      }
    });
  }
  row.appendChild(main);
  if (owner) {
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "ghost person-edit";
    edit.title = "Проект, роль и доступы";
    edit.textContent = "✎";
    edit.addEventListener("click", (e) => {
      e.stopPropagation();
      openEmployeeDialog(m);
    });
    row.appendChild(edit);
  }
  return row;
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
  for (const [projectName, roles] of peopleTree(all)) {
    const wrap = document.createElement("div");
    wrap.className =
      "people-project" +
      (state.selectedProject === projectName && !state.selectedPersonId ? " active" : "");
    const color = projectColor(projectName);
    wrap.style.setProperty("--project-color", color);
    wrap.style.borderLeftColor = color;

    const head = document.createElement("div");
    head.className = "people-project-head";
    const titleBtn = document.createElement("button");
    titleBtn.type = "button";
    titleBtn.className = "people-project-title";
    const memberCount = roles.reduce((n, [, members]) => n + members.length, 0);
    titleBtn.innerHTML = `<span>${escapeHtml(projectName)}</span><span class="people-project-count">${memberCount}</span>`;
    titleBtn.addEventListener("click", () => {
      state.selectedProject = projectName;
      state.selectedPersonId = null;
      renderBoardView();
    });
    head.appendChild(titleBtn);

    if (owner && projectName !== "Без проекта" && projectName !== "Владелец") {
      const editGrp = document.createElement("button");
      editGrp.type = "button";
      editGrp.className = "ghost people-group-edit";
      editGrp.title = "Состав проекта";
      editGrp.textContent = "✎";
      editGrp.addEventListener("click", (e) => {
        e.stopPropagation();
        openGroupDialog(projectName);
      });
      head.appendChild(editGrp);
    }
    wrap.appendChild(head);

    for (const [roleName, members] of roles) {
      const roleBlock = document.createElement("div");
      roleBlock.className = "people-role";
      const roleTitle = document.createElement("div");
      roleTitle.className = "people-role-title";
      roleTitle.textContent = roleName;
      roleBlock.appendChild(roleTitle);
      for (const m of members) {
        roleBlock.appendChild(renderPersonRow(m, owner));
      }
      wrap.appendChild(roleBlock);
    }
    list.appendChild(wrap);
  }
}

function openGroupDialog(existingName) {
  if (!isOwner()) {
    alert("Только владелец может управлять проектами. Нажми «Войти» своим Telegram id.");
    return;
  }
  if (JOB_TITLE_ORDER[existingName] != null) {
    alert(`«${existingName}» — это роль, не проект.\nРоль ставь в ✎ у человека.`);
    return;
  }
  const form = $("#groupForm");
  const old =
    existingName && existingName !== "Без проекта" && existingName !== "Владелец"
      ? existingName
      : "";
  form.elements.old_name.value = old;
  form.elements.name.value = old;
  $("#groupDlgTitle").textContent = old ? `Проект «${old}»` : "Новый проект";
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
      ${e.job_title ? ` · ${escapeHtml(e.job_title)}` : ""}
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
  if (state.selectedPersonId) {
    const m = people().find((e) => e.id === state.selectedPersonId);
    $("#managerName").textContent = m ? m.name : "—";
    const open = tasks.filter((t) => t.status !== "done").length;
    const role = m?.job_title || (m?.role === "owner" ? "владелец" : "");
    const proj = m?.team_group || "";
    $("#managerSub").textContent = [
      role,
      proj ? `проект: ${proj}` : "",
      `открытых: ${open}`,
    ]
      .filter(Boolean)
      .join(" · ");
  } else if (state.selectedProject) {
    $("#managerName").textContent = state.selectedProject;
    $("#managerSub").textContent = `Задачи участников проекта · открытых: ${
      tasks.filter((t) => t.status !== "done").length
    }`;
  } else {
    $("#managerName").textContent = "Все проекты";
    $("#managerSub").textContent = "Слева проект → роль → человек";
  }
  hint.classList.toggle("hidden", tasks.length > 0);
}

function cardDisplayDescription(raw) {
  const s = String(raw || "").trim();
  if (!s) return "";
  // автозадачи — на карточке без техтекста
  if (
    /\[auto:own-stock:/i.test(s) ||
    /\[auto:my-shelf:/i.test(s) ||
    /Автозадача:\s*остаток/i.test(s)
  )
    return "";
  return s;
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
  const desc = cardDisplayDescription(t.description);
  const archiveBtn =
    t.status === "done"
      ? `<button type="button" class="btn-archive" title="В архив">Архив</button>`
      : "";
  return `
    ${dueDot(t.due_flag)}
    <div class="card-actions">
      ${archiveBtn}
      <button type="button" class="btn-edit" title="Открыть">✎</button>
      <button type="button" class="btn-del danger" title="Удалить">✕</button>
    </div>
    ${skuHtml}
    <h3>${escapeHtml(t.title)}</h3>
    ${desc ? `<div class="desc">${escapeHtml(desc)}</div>` : ""}
    <div class="meta">
      ${avatarsHtml(assignees)}
      ${t.due_date ? `<span class="chip">до ${formatDate(t.due_date)}</span>` : ""}
      ${t.created_by_name ? `<span class="chip">от ${escapeHtml(t.created_by_name)}</span>` : ""}
      ${t.project_name ? `<span class="chip project">${escapeHtml(t.project_name)}</span>` : ""}
    </div>
  `;
}

function paintCard(el, t) {
  const color = projectColor(taskProjectName(t));
  el.style.setProperty("--project-color", color);
}

async function archiveTask(t) {
  if (!confirm(`Отправить «${t.title}» в архив?`)) return;
  const q = state.meId ? `?actor_id=${state.meId}` : "";
  await api(`/api/tasks/${t.id}/archive${q}`, { method: "POST" });
  await load();
}

function bindCard(card, t) {
  card.querySelector(".btn-edit")?.addEventListener("click", (e) => {
    e.stopPropagation();
    openTaskDialog(t.id);
  });
  card.querySelector(".btn-del")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    await deleteTask(t);
  });
  card.querySelector(".btn-archive")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      await archiveTask(t);
    } catch (err) {
      alert(err.message || String(err));
    }
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
    colEl.innerHTML = `<div class="col-head"><span class="col-badge">${col.title}</span><span class="col-count">${list.length}</span></div>`;
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
      paintCard(card, t);
      bindCard(card, t);
      cards.appendChild(card);
    }
    colEl.appendChild(cards);
    board.appendChild(colEl);
  }
}

function renderHomeStats() {
  const wrap = $("#homeStats");
  const list = $("#homeStatsList");
  if (!wrap || !list) return;
  if (!state.meId || !state.board) {
    wrap.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  const tasks = state.board.tasks || [];
  const rows = visiblePeople().map((e) => {
    const mine = tasks.filter((t) => taskHasAssignee(t, e.id));
    const open = mine.filter((t) => t.status !== "done").length;
    const done = mine.filter((t) => t.status === "done").length;
    const total = open + done;
    const pct = total ? Math.round((done / total) * 100) : 0;
    return { e, open, done, total, pct };
  });
  if (!rows.length) {
    wrap.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  wrap.classList.remove("hidden");
  list.innerHTML = rows
    .map(
      ({ e, open, pct }) => `
      <div class="home-stats-row">
        <div class="home-stats-name">
          <span class="avatar">${escapeHtml(initials(e.name))}</span>
          <span>${escapeHtml(e.name)}</span>
        </div>
        <div class="home-stats-meta">
          <span>висит ${open}</span>
          <span class="home-stats-pct">${pct}% выполнено</span>
        </div>
        <div class="home-stats-bar" aria-hidden="true">
          <i style="width:${pct}%"></i>
        </div>
      </div>`
    )
    .join("");
}

function renderHome() {
  const grid = $("#homeGrid");
  const hint = $("#homeHint");
  if (!state.meId) {
    hint.textContent = "Войди — увидишь свои задачи.";
    grid.innerHTML = `<div class="home-empty">Нажми «Войти» сверху или на «не вошли».</div>`;
    renderHomeStats();
    return;
  }
  const m = me();
  hint.textContent = m ? `${m.name}, твои задачи` : "Твои задачи";
  if (!state.home) {
    grid.innerHTML = `<div class="home-empty">Загрузка…</div>`;
    renderHomeStats();
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
        paintCard(card, t);
        card.querySelector(".card-actions")?.remove();
        card.addEventListener("click", () => openTaskDialog(t.id));
        list.appendChild(card);
      }
    }
    box.appendChild(list);
    grid.appendChild(box);
  }
  renderHomeStats();
}

function formatTemplateSchedule(t) {
  const time = t.notify_time || "09:00";
  const rec = t.recurrence || "daily";
  const val = String(t.recurrence_value || "").trim();
  if (rec === "daily") return `Каждый день @ ${time}`;
  if (rec === "monthly" || rec === "month_days") {
    const days = val
      ? val
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean)
          .join(", ")
      : "?";
    return `${days} числа каждого месяца @ ${time}`;
  }
  if (rec === "weekdays" || rec === "weekly") {
    const map = Object.fromEntries(WEEKDAY_RU.map((d) => [d.v, d.short]));
    const days = val
      .split(",")
      .map((x) => Number(x.trim()))
      .filter((n) => map[n])
      .map((n) => map[n])
      .join(", ");
    return `${days || "день недели"} @ ${time}`;
  }
  if (rec === "every_n_days") return `Каждые ${val || "N"} дн. @ ${time}`;
  return `${REC_LABELS[rec] || rec}${val ? `: ${val}` : ""} @ ${time}`;
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
        <span class="chip">${escapeHtml(formatTemplateSchedule(t))}</span>
        ${t.start_date ? `<span class="chip">с ${formatDate(t.start_date)}</span>` : ""}
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

function employeeTeamName(e) {
  if (e.role === "owner") return "Владелец";
  return String(e.team_group || "").trim() || "Без команды";
}

function employeeRoleName(e) {
  if (e.role === "owner") return "владелец";
  return String(e.job_title || "").trim() || "без роли";
}

function groupEmployeesByTeamRole(list) {
  const teams = new Map();
  for (const e of list) {
    const team = employeeTeamName(e);
    const role = employeeRoleName(e);
    if (!teams.has(team)) teams.set(team, new Map());
    const roles = teams.get(team);
    if (!roles.has(role)) roles.set(role, []);
    roles.get(role).push(e);
  }
  const teamNames = [...teams.keys()].sort((a, b) => {
    if (a === "Владелец") return -1;
    if (b === "Владелец") return 1;
    if (a === "Без команды") return 1;
    if (b === "Без команды") return -1;
    return a.localeCompare(b, "ru");
  });
  return teamNames.map((team) => {
    const rolesMap = teams.get(team);
    const roleNames = [...rolesMap.keys()].sort((a, b) => {
      const ai = JOB_TITLE_ORDER[a];
      const bi = JOB_TITLE_ORDER[b];
      if (ai != null || bi != null) return (ai ?? 99) - (bi ?? 99);
      return a.localeCompare(b, "ru");
    });
    return {
      team,
      roles: roleNames.map((role) => ({
        role,
        people: rolesMap.get(role).slice().sort((a, b) => a.name.localeCompare(b.name, "ru")),
      })),
    };
  });
}

function fillAssigneeChecks(containerId, selectedIds, { grouped = false } = {}) {
  const box = $(containerId);
  const selected = new Set((selectedIds || []).map(Number));
  const list = (isOwner() ? people() : visiblePeople()).slice();
  if (!grouped) {
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
    return;
  }

  const groups = groupEmployeesByTeamRole(list);
  if (!groups.length) {
    box.innerHTML = `<div class="chat-empty">Нет сотрудников</div>`;
    return;
  }
  box.innerHTML = groups
    .map((g) => {
      const teamIds = g.roles.flatMap((r) => r.people.map((p) => p.id));
      const rolesHtml = g.roles
        .map((r) => {
          const roleIds = r.people.map((p) => p.id);
          const peopleHtml = r.people
            .map(
              (e) => `
            <label class="check-row">
              <input type="checkbox" value="${e.id}" ${selected.has(e.id) ? "checked" : ""} />
              <span class="avatar mini">${escapeHtml(initials(e.name))}</span>
              ${escapeHtml(e.name)}
            </label>`
            )
            .join("");
          return `
          <div class="check-role">
            <div class="check-role-head">
              <span>${escapeHtml(r.role)}</span>
              <button type="button" class="ghost" data-select-ids="${roleIds.join(",")}">все</button>
            </div>
            ${peopleHtml}
          </div>`;
        })
        .join("");
      return `
      <div class="check-team" data-team="${escapeHtml(g.team)}">
        <div class="check-team-head">
          <strong>${escapeHtml(g.team)}</strong>
          <button type="button" class="ghost" data-select-ids="${teamIds.join(",")}">вся команда</button>
        </div>
        ${rolesHtml}
      </div>`;
    })
    .join("");

  box.querySelectorAll("[data-select-ids]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const ids = String(btn.dataset.selectIds || "")
        .split(",")
        .map(Number)
        .filter(Boolean);
      const checks = [...box.querySelectorAll('input[type="checkbox"]')];
      const targets = checks.filter((c) => ids.includes(Number(c.value)));
      const allOn = targets.length && targets.every((c) => c.checked);
      targets.forEach((c) => {
        c.checked = !allOn;
      });
    });
  });
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
  form.elements.description.value = cardDisplayDescription(task.description);
  form.dataset.autoMarker =
    (
      /\[auto:(?:own-stock|my-shelf):[^\]]+\]/i.exec(String(task.description || "")) ||
      []
    )[0] || "";
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
  renderReassignButtons(task);
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

function managersForReassign(task) {
  const current = new Set(taskAssigneeIds(task));
  return people().filter(
    (e) =>
      e.active !== false &&
      e.role !== "owner" &&
      !current.has(Number(e.id))
  );
}

function renderReassignButtons(task) {
  const bar = $("#reassignBar");
  const box = $("#reassignButtons");
  if (!bar || !box) return;
  const managers = managersForReassign(task);
  if (!managers.length) {
    bar.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  bar.classList.remove("hidden");
  box.innerHTML = managers
    .map(
      (e) =>
        `<button type="button" class="reassign-btn" data-reassign-id="${e.id}" title="Перекинуть на ${escapeHtml(e.name)}">
          <span class="avatar mini">${escapeHtml(initials(e.name))}</span>
          ${escapeHtml(e.name)}
        </button>`
    )
    .join("");
  box.querySelectorAll("[data-reassign-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const empId = Number(btn.getAttribute("data-reassign-id"));
      if (!empId || !task?.id) return;
      btn.disabled = true;
      try {
        await api(`/api/tasks/${task.id}/reassign`, {
          method: "POST",
          body: JSON.stringify({
            assignee_id: empId,
            actor_id: state.meId || null,
            notify: true,
          }),
        });
        await openTaskDialog(task.id);
        await load();
      } catch (err) {
        alert(err.message || String(err));
        btn.disabled = false;
      }
    });
  });
}

async function deleteTask(task) {
  if (!confirm(`Удалить задачу «${task.title}»?\nУдалить может любой из команды.`)) return;
  const q = state.meId ? `?actor_id=${state.meId}` : "";
  await api(`/api/tasks/${task.id}${q}`, { method: "DELETE" });
  closeDlg();
  await load();
}

function parseCsvInts(val) {
  return String(val || "")
    .split(",")
    .map((x) => Number(String(x).trim()))
    .filter((n) => Number.isFinite(n) && n > 0);
}

function ensureTplDayChips() {
  const month = $("#tplMonthDays");
  const week = $("#tplWeekDays");
  if (month && !month.dataset.ready) {
    month.innerHTML = Array.from({ length: 31 }, (_, i) => i + 1)
      .map(
        (d) =>
          `<label><input type="checkbox" value="${d}" /><span>${d}</span></label>`
      )
      .join("");
    month.dataset.ready = "1";
  }
  if (week && !week.dataset.ready) {
    week.innerHTML = WEEKDAY_RU.map(
      (d) =>
        `<label><input type="checkbox" value="${d.v}" /><span>${d.short}</span></label>`
    ).join("");
    week.dataset.ready = "1";
  }
}

function setTplChipValues(containerId, values) {
  const set = new Set((values || []).map(Number));
  document.querySelectorAll(`${containerId} input[type=checkbox]`).forEach((el) => {
    el.checked = set.has(Number(el.value));
  });
}

function readTplChipValues(containerId) {
  return [...document.querySelectorAll(`${containerId} input[type=checkbox]:checked`)]
    .map((el) => Number(el.value))
    .filter((n) => n > 0)
    .sort((a, b) => a - b);
}

function tplScheduleKindFromRecurrence(rec) {
  if (rec === "weekdays" || rec === "weekly") return "weekday";
  if (rec === "daily" || rec === "every_n_days") return "daily";
  return "month_day";
}

function syncTplScheduleUi() {
  const kind = $("#tplScheduleKind")?.value || "month_day";
  $("#tplMonthWrap")?.classList.toggle("hidden", kind !== "month_day");
  $("#tplWeekWrap")?.classList.toggle("hidden", kind !== "weekday");
}

function applyTplScheduleToForm() {
  const kind = $("#tplScheduleKind")?.value || "month_day";
  const recEl = $("#tplRecurrence");
  const valEl = $("#tplValue");
  if (!recEl || !valEl) return;
  if (kind === "daily") {
    recEl.value = "daily";
    valEl.value = "";
    return;
  }
  if (kind === "weekday") {
    const days = readTplChipValues("#tplWeekDays");
    recEl.value = "weekdays";
    valEl.value = (days.length ? days : [1]).join(",");
    return;
  }
  const days = readTplChipValues("#tplMonthDays");
  const picked = days.length ? days : [1];
  if (picked.length === 1) {
    recEl.value = "monthly";
    valEl.value = String(picked[0]);
  } else {
    recEl.value = "month_days";
    valEl.value = picked.join(",");
  }
}

function openTemplateDialog(tpl) {
  const form = $("#tplForm");
  ensureTplDayChips();
  $("#tplDlgTitle").textContent = tpl ? `Шаблон #${tpl.id}` : "Новый шаблон";
  form.elements.id.value = tpl?.id || "";
  form.elements.title.value = tpl?.title || "";
  form.elements.description.value = tpl?.description || "";
  form.elements.start_date.value = tpl?.start_date || "";
  form.elements.notify_time.value = tpl?.notify_time || "10:00";
  form.elements.active.checked = tpl ? !!tpl.active : true;

  const rec = tpl?.recurrence || "monthly";
  const val = tpl?.recurrence_value || (rec === "monthly" ? "1" : "");
  form.elements.recurrence.value = rec;
  form.elements.recurrence_value.value = val;

  const kind = tplScheduleKindFromRecurrence(rec);
  $("#tplScheduleKind").value = kind;
  if (kind === "weekday") {
    setTplChipValues("#tplWeekDays", parseCsvInts(val).length ? parseCsvInts(val) : [1]);
    setTplChipValues("#tplMonthDays", []);
  } else if (kind === "month_day") {
    setTplChipValues("#tplMonthDays", parseCsvInts(val).length ? parseCsvInts(val) : [1]);
    setTplChipValues("#tplWeekDays", []);
  } else {
    setTplChipValues("#tplMonthDays", []);
    setTplChipValues("#tplWeekDays", []);
  }
  syncTplScheduleUi();
  fillAssigneeChecks("#tplAssigneeChecks", tpl?.assignee_ids || [], { grouped: true });
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
  if (state.selectedProject) {
    const names = new Set(
      visiblePeople().map((e) =>
        e.role === "owner"
          ? "Владелец"
          : String(e.team_group || "").trim() || "Без проекта"
      )
    );
    if (!names.has(state.selectedProject)) state.selectedProject = null;
  }
  await Promise.all([loadHome(), loadTemplates()]);
  render();
}

/* —— events —— */
document.querySelectorAll("#navTabs button").forEach((btn) => {
  btn.addEventListener("click", async () => {
    setView(btn.dataset.view);
    render();
  });
});

$("#btnAllPeople").addEventListener("click", () => {
  state.selectedPersonId = null;
  state.selectedProject = null;
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

async function loginAsEmployee() {
  const tid = prompt("Твой Telegram numeric id (как в userinfobot):");
  if (!tid || !/^\d+$/.test(tid)) return;
  let emp = people().find((e) => String(e.telegram_id) === String(tid));
  if (!emp) {
    const name = prompt("Тебя ещё нет в Project Workflow. Как тебя зовут?");
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
    const name = prompt("Как тебя зовут в Project Workflow?", "Ярослав");
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
}

$("#btnLogin").addEventListener("click", () => {
  loginAsEmployee().catch((err) => alert(err.message || String(err)));
});

$("#meLabel").addEventListener("click", async () => {
  if (!state.meId) {
    try {
      await loginAsEmployee();
    } catch (err) {
      alert(err.message || String(err));
    }
    return;
  }
  try {
    await renameEmployee(me(), {
      promptLabel: "Как тебя зовут в Project Workflow?",
    });
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
    const due = $("#quickDue").value || null;
    const created = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        title,
        description: "",
        project_id: null,
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
  if (!confirm(`Убрать проект «${old}»?\nУчастники останутся без проекта (роли сохранятся).`)) return;
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
    description: (() => {
      const typed = String(form.elements.description.value || "").trim();
      const marker = form.dataset.autoMarker || "";
      if (typed) return typed;
      return marker;
    })(),
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
$("#tplScheduleKind")?.addEventListener("change", syncTplScheduleUi);

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
  applyTplScheduleToForm();
  const kind = $("#tplScheduleKind")?.value || "month_day";
  if (kind === "month_day" && !readTplChipValues("#tplMonthDays").length) {
    alert("Выбери хотя бы одно число месяца");
    return;
  }
  if (kind === "weekday" && !readTplChipValues("#tplWeekDays").length) {
    alert("Выбери хотя бы один день недели");
    return;
  }
  const time = String(form.elements.notify_time.value || "").trim();
  if (!/^\d{1,2}:\d{2}$/.test(time)) {
    alert("Время в формате ЧЧ:ММ, например 10:00");
    return;
  }
  const [hh, mm] = time.split(":").map(Number);
  if (hh > 23 || mm > 59) {
    alert("Некорректное время");
    return;
  }
  const notify_time = `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
  const assignee_ids = readAssigneeChecks("#tplAssigneeChecks");
  if (!assignee_ids.length) {
    alert("Выбери хотя бы одного сотрудника");
    return;
  }
  const payload = {
    title: String(form.elements.title.value || "").trim(),
    description: String(form.elements.description.value || ""),
    recurrence: form.elements.recurrence.value,
    recurrence_value: String(form.elements.recurrence_value.value || "").trim(),
    start_date: form.elements.start_date.value || null,
    notify_time,
    active: !!form.elements.active.checked,
    assignee_ids,
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

applyTheme(getTheme());
$("#btnTheme")?.addEventListener("click", () => {
  applyTheme(getTheme() === "dark" ? "light" : "dark");
});

load().catch((err) => {
  console.error(err);
  alert("Не удалось загрузить Project Workflow: " + err.message);
});
