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

const MM_COLORS = [
  { id: "yellow", hex: "#fff475", ink: "#1f1f1f" },
  { id: "peach", hex: "#fad2cf", ink: "#1f1f1f" },
  { id: "pink", hex: "#fdcfe8", ink: "#1f1f1f" },
  { id: "purple", hex: "#d7aefb", ink: "#1f1f1f" },
  { id: "blue", hex: "#aecbfa", ink: "#1f1f1f" },
  { id: "cyan", hex: "#cbf0f8", ink: "#1f1f1f" },
  { id: "lime", hex: "#ccff90", ink: "#1f1f1f" },
  { id: "mint", hex: "#a7ffeb", ink: "#1f1f1f" },
];

const state = {
  view: localStorage.getItem("crm_view") || "home",
  board: null,
  home: null,
  templates: [],
  mindmaps: [],
  currentMap: null,
  mmScale: 1,
  mmPan: { x: 0, y: 0 },
  mmTool: "select",
  mmArrowFrom: null,
  mmIdeaDraft: null,
  mmSelectedColor: MM_COLORS[0].hex,
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
  $("#viewMindmap")?.classList.toggle("hidden", view !== "mindmap");
  $("#viewArchive").classList.toggle("hidden", view !== "archive");
  document.querySelectorAll("#navTabs button").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === view);
  });
  if (view !== "mindmap") {
    state.currentMap = null;
    $("#mmListWrap")?.classList.remove("hidden");
    $("#mmEditorWrap")?.classList.add("hidden");
  }
}

function fillSelects() {
  /* project filter removed from header — sidebar filters the board */
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
  // автозадачи по складу — на карточке без техтекста
  if (/\[auto:own-stock:/i.test(s) || /Автозадача:\s*остаток/i.test(s)) return "";
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
  if (state.view === "mindmap") renderMindmap();
  if (state.view === "archive") renderArchive();
}

/* —— Mind Map (Miro-like) —— */
const MM_NODE_W = 168;
const MM_NODE_H = 110;

function mmRoot(nodes) {
  return (nodes || []).find((n) => n.parent_id == null) || (nodes || [])[0] || null;
}

function showMmList() {
  state.currentMap = null;
  state.mmArrowFrom = null;
  $("#mmListWrap")?.classList.remove("hidden");
  $("#mmEditorWrap")?.classList.add("hidden");
}

function showMmEditor() {
  $("#mmListWrap")?.classList.add("hidden");
  $("#mmEditorWrap")?.classList.remove("hidden");
  setMmTool(state.mmTool || "select");
}

function renderMindmapList() {
  const list = $("#mmList");
  if (!list) return;
  if (!state.mindmaps.length) {
    list.innerHTML = `<div class="home-empty">Карт пока нет — создай первую и зови команду дополнять идеи.</div>`;
    return;
  }
  list.innerHTML = "";
  for (const m of state.mindmaps) {
    const el = document.createElement("article");
    el.className = "tpl-card mm-card";
    el.innerHTML = `
      <div class="tpl-card-top">
        <h3>${escapeHtml(m.title)}</h3>
        <span class="chip">${m.node_count || 0} идей</span>
      </div>
      ${m.description ? `<p class="desc">${escapeHtml(m.description)}</p>` : ""}
      <div class="meta">
        ${m.created_by_name ? `<span class="chip assignee">${escapeHtml(m.created_by_name)}</span>` : ""}
        ${m.updated_at ? `<span class="chip">${formatDt(m.updated_at)}</span>` : ""}
      </div>
    `;
    el.addEventListener("click", () => openMindMap(m.id));
    list.appendChild(el);
  }
}

function setMmTool(tool) {
  state.mmTool = tool;
  state.mmArrowFrom = null;
  clearMmDraftArrow();
  document.querySelectorAll("#mmTools .mm-tool").forEach((b) => {
    b.classList.toggle("active", b.dataset.tool === tool);
  });
  const canvas = $("#mmCanvas");
  canvas?.classList.toggle("tool-sticky", tool === "sticky");
  canvas?.classList.toggle("tool-arrow", tool === "arrow");
  const hint = $("#mmToolHint");
  if (!hint) return;
  if (tool === "sticky") hint.textContent = "Кликни по доске — появится стикер";
  else if (tool === "arrow") hint.textContent = "Кликни первую идею, потом вторую — нарисуется стрелка";
  else hint.textContent = "Перетаскивай стикеры · двойной клик — редактировать · колёсико — масштаб";
}

function applyMmTransform() {
  const nodes = $("#mmNodes");
  const links = $("#mmLinks");
  const t = `translate(${state.mmPan.x}px, ${state.mmPan.y}px) scale(${state.mmScale})`;
  if (nodes) nodes.style.transform = t;
  if (links) links.style.transform = t;
}

function mmNodeCenter(n) {
  return { x: n.x + MM_NODE_W / 2, y: n.y + MM_NODE_H / 2 };
}

function mmArrowPath(a, b) {
  const x1 = a.x;
  const y1 = a.y;
  const x2 = b.x;
  const y2 = b.y;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const shorten = 36;
  const sx = x1 + (dx / len) * 28;
  const sy = y1 + (dy / len) * 28;
  const ex = x2 - (dx / len) * shorten;
  const ey = y2 - (dy / len) * shorten;
  const mx = (sx + ex) / 2;
  const my = (sy + ey) / 2;
  const cx = mx - dy * 0.12;
  const cy = my + dx * 0.12;
  return `M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`;
}

function clearMmDraftArrow() {
  const draft = $("#mmDraftArrow");
  if (draft) draft.setAttribute("d", "");
}

function drawMmLinks() {
  const body = $("#mmLinksBody");
  const svg = $("#mmLinks");
  const map = state.currentMap;
  if (!body || !svg || !map) return;
  const byId = Object.fromEntries((map.nodes || []).map((n) => [n.id, n]));
  const parts = [];
  for (const arrow of map.arrows || []) {
    const from = byId[arrow.from_node_id];
    const to = byId[arrow.to_node_id];
    if (!from || !to) continue;
    const d = mmArrowPath(mmNodeCenter(from), mmNodeCenter(to));
    const color = escapeHtml(arrow.color || "#1f1f1f");
    parts.push(`
      <g class="mm-arrow-group" data-id="${arrow.id}">
        <path class="mm-arrow-hit" d="${d}" fill="none" stroke="transparent" stroke-width="14" />
        <path class="mm-arrow" d="${d}" fill="none" stroke="${color}" stroke-width="2.4"
          marker-end="url(#mmArrowHead)" />
      </g>
    `);
  }
  body.innerHTML = parts.join("");
  svg.setAttribute("width", "5000");
  svg.setAttribute("height", "4000");
  body.querySelectorAll(".mm-arrow-group").forEach((g) => {
    g.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (state.mmTool !== "select") return;
      if (!confirm("Удалить стрелку?")) return;
      try {
        await api(`/api/mindmaps/${map.id}/arrows/${g.dataset.id}`, { method: "DELETE" });
        await refreshCurrentMap();
      } catch (err) {
        alert(err.message || String(err));
      }
    });
  });
  applyMmTransform();
}

function renderMmColorPicker(selected) {
  const host = $("#mmIdeaColors");
  if (!host) return;
  host.innerHTML = MM_COLORS.map(
    (c) =>
      `<button type="button" class="mm-color-swatch${
        c.hex === selected ? " active" : ""
      }" data-color="${c.hex}" style="--sw:${c.hex}" title="${c.id}"></button>`
  ).join("");
  host.querySelectorAll(".mm-color-swatch").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.mmSelectedColor = btn.dataset.color;
      host.querySelectorAll(".mm-color-swatch").forEach((b) => {
        b.classList.toggle("active", b === btn);
      });
      const ta = $("#mmIdeaText");
      if (ta) ta.style.background = state.mmSelectedColor;
    });
  });
}

function openMmIdeaDialog({ title, text, color, mode, parentId, x, y, nodeId }) {
  state.mmIdeaDraft = { mode, parentId, x, y, nodeId };
  state.mmSelectedColor = color || MM_COLORS[0].hex;
  $("#mmIdeaDlgTitle").textContent = title;
  const ta = $("#mmIdeaText");
  ta.value = text || "";
  ta.style.background = state.mmSelectedColor;
  renderMmColorPicker(state.mmSelectedColor);
  $("#mmIdeaDlg").showModal();
  setTimeout(() => ta.focus(), 30);
}

function closeMmIdeaDialog() {
  $("#mmIdeaDlg")?.close();
  state.mmIdeaDraft = null;
}

function renderMmNodes() {
  const host = $("#mmNodes");
  const map = state.currentMap;
  if (!host || !map) return;
  host.innerHTML = "";
  for (const n of map.nodes || []) {
    const el = document.createElement("div");
    const isRoot = n.parent_id == null && n === mmRoot(map.nodes);
    el.className =
      "mm-sticky" +
      (isRoot ? " is-root" : "") +
      (state.mmArrowFrom === n.id ? " arrow-from" : "");
    el.dataset.id = String(n.id);
    el.style.left = `${n.x}px`;
    el.style.top = `${n.y}px`;
    el.style.setProperty("--sticky", n.color || "#fff475");
    el.innerHTML = `
      <div class="mm-sticky-text">${escapeHtml(n.text)}</div>
      <div class="mm-sticky-foot">
        ${
          n.created_by_name
            ? `<span class="mm-sticky-author">${escapeHtml(n.created_by_name)}</span>`
            : `<span></span>`
        }
        <div class="mm-sticky-actions">
          <button type="button" class="mm-add" title="Ветка">+</button>
          <button type="button" class="mm-del" title="Удалить">×</button>
        </div>
      </div>
    `;
    bindMmNode(el, n);
    host.appendChild(el);
  }
  applyMmTransform();
  drawMmLinks();
}

function bindMmNode(el, node) {
  el.querySelector(".mm-add")?.addEventListener("click", (e) => {
    e.stopPropagation();
    openMmIdeaDialog({
      title: "Новая идея",
      text: "",
      color: MM_COLORS[Math.floor(Math.random() * MM_COLORS.length)].hex,
      mode: "create",
      parentId: node.id,
      x: node.x + 200,
      y: node.y + (Math.random() * 80 - 40),
    });
  });
  el.querySelector(".mm-del")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    if (!confirm("Удалить стикер?")) return;
    try {
      await api(`/api/mindmaps/${state.currentMap.id}/nodes/${node.id}`, {
        method: "DELETE",
      });
      await refreshCurrentMap();
    } catch (err) {
      alert(err.message || String(err));
    }
  });
  el.addEventListener("dblclick", (e) => {
    e.stopPropagation();
    if (state.mmTool === "arrow") return;
    openMmIdeaDialog({
      title: "Редактировать идею",
      text: node.text || "",
      color: node.color || MM_COLORS[0].hex,
      mode: "edit",
      nodeId: node.id,
    });
  });

  el.addEventListener("click", async (e) => {
    if (state.mmTool !== "arrow") return;
    e.stopPropagation();
    if (!state.mmArrowFrom) {
      state.mmArrowFrom = node.id;
      renderMmNodes();
      $("#mmToolHint").textContent = "Теперь кликни вторую идею";
      return;
    }
    if (state.mmArrowFrom === node.id) {
      state.mmArrowFrom = null;
      clearMmDraftArrow();
      renderMmNodes();
      return;
    }
    try {
      await api(`/api/mindmaps/${state.currentMap.id}/arrows`, {
        method: "POST",
        body: JSON.stringify({
          from_node_id: state.mmArrowFrom,
          to_node_id: node.id,
          created_by_id: state.meId || null,
        }),
      });
      state.mmArrowFrom = null;
      clearMmDraftArrow();
      await refreshCurrentMap();
      $("#mmToolHint").textContent = "Стрелка добавлена — можно провести ещё";
    } catch (err) {
      alert(err.message || String(err));
    }
  });

  let dragging = false;
  let moved = false;
  let startX = 0;
  let startY = 0;
  let origX = 0;
  let origY = 0;
  el.addEventListener("pointerdown", (e) => {
    if (state.mmTool !== "select") return;
    if (e.target.closest(".mm-sticky-actions")) return;
    dragging = true;
    moved = false;
    el.setPointerCapture(e.pointerId);
    startX = e.clientX;
    startY = e.clientY;
    origX = node.x;
    origY = node.y;
    el.classList.add("dragging");
  });
  el.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = (e.clientX - startX) / state.mmScale;
    const dy = (e.clientY - startY) / state.mmScale;
    if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
    node.x = Math.round(origX + dx);
    node.y = Math.round(origY + dy);
    el.style.left = `${node.x}px`;
    el.style.top = `${node.y}px`;
    drawMmLinks();
  });
  el.addEventListener("pointerup", async (e) => {
    if (!dragging) return;
    dragging = false;
    el.classList.remove("dragging");
    try {
      el.releasePointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }
    if (!moved) return;
    try {
      await api(`/api/mindmaps/${state.currentMap.id}/nodes/${node.id}`, {
        method: "PATCH",
        body: JSON.stringify({ x: node.x, y: node.y }),
      });
    } catch (err) {
      alert(err.message || String(err));
      await refreshCurrentMap();
    }
  });
}

function canvasToWorld(clientX, clientY) {
  const canvas = $("#mmCanvas");
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.round((clientX - rect.left - state.mmPan.x) / state.mmScale),
    y: Math.round((clientY - rect.top - state.mmPan.y) / state.mmScale),
  };
}

async function refreshCurrentMap() {
  if (!state.currentMap?.id) return;
  const keepFrom = state.mmArrowFrom;
  state.currentMap = await api(`/api/mindmaps/${state.currentMap.id}`);
  state.mmArrowFrom = keepFrom;
  $("#mmTitleInput").value = state.currentMap.title || "";
  renderMmNodes();
  await loadMindmaps();
}

async function openMindMap(id) {
  try {
    state.currentMap = await api(`/api/mindmaps/${id}`);
    state.mmScale = 1;
    state.mmPan = { x: 60, y: 40 };
    state.mmArrowFrom = null;
    state.mmTool = "select";
    $("#mmTitleInput").value = state.currentMap.title || "";
    showMmEditor();
    renderMmNodes();
  } catch (err) {
    alert(err.message || String(err));
  }
}

function renderMindmap() {
  if (state.currentMap) {
    showMmEditor();
    renderMmNodes();
  } else {
    showMmList();
    renderMindmapList();
  }
}

async function loadMindmaps() {
  try {
    state.mindmaps = await api("/api/mindmaps");
  } catch (_) {
    state.mindmaps = [];
  }
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
  form.elements.description.value = cardDisplayDescription(task.description);
  form.dataset.autoMarker =
    (/\[auto:own-stock:[^\]]+\]/i.exec(String(task.description || "")) || [])[0] || "";
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
  await Promise.all([loadHome(), loadTemplates(), loadMindmaps()]);
  render();
}

/* —— events —— */
document.querySelectorAll("#navTabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
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

$("#btnNewMindMap")?.addEventListener("click", async () => {
  openMmIdeaDialog({
    title: "Новая доска идей",
    text: "Новая карта",
    color: MM_COLORS[0].hex,
    mode: "new-board",
  });
});

$("#btnMmBack")?.addEventListener("click", async () => {
  state.currentMap = null;
  state.mmArrowFrom = null;
  await loadMindmaps();
  showMmList();
  renderMindmapList();
});

$("#btnMmDelete")?.addEventListener("click", async () => {
  if (!state.currentMap) return;
  if (!confirm(`Удалить карту «${state.currentMap.title}»?`)) return;
  try {
    await api(`/api/mindmaps/${state.currentMap.id}`, { method: "DELETE" });
    state.currentMap = null;
    await loadMindmaps();
    showMmList();
    renderMindmapList();
  } catch (err) {
    alert(err.message || String(err));
  }
});

document.querySelectorAll("#mmTools .mm-tool").forEach((btn) => {
  btn.addEventListener("click", () => setMmTool(btn.dataset.tool));
});

$("#mmIdeaClose")?.addEventListener("click", () => closeMmIdeaDialog());
$("#mmIdeaCancel")?.addEventListener("click", () => closeMmIdeaDialog());

$("#mmIdeaForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const draft = state.mmIdeaDraft;
  if (!draft) return;
  const text = String($("#mmIdeaText").value || "").trim();
  if (!text) return;
  const color = state.mmSelectedColor || MM_COLORS[0].hex;
  try {
    if (draft.mode === "new-board") {
      const created = await api("/api/mindmaps", {
        method: "POST",
        body: JSON.stringify({
          title: text,
          created_by_id: state.meId || null,
        }),
      });
      closeMmIdeaDialog();
      await loadMindmaps();
      await openMindMap(created.id);
      const root = mmRoot(state.currentMap?.nodes);
      if (root) {
        await api(`/api/mindmaps/${created.id}/nodes/${root.id}`, {
          method: "PATCH",
          body: JSON.stringify({ color, text }),
        });
        await refreshCurrentMap();
      }
      return;
    }
    if (draft.mode === "edit" && draft.nodeId) {
      await api(`/api/mindmaps/${state.currentMap.id}/nodes/${draft.nodeId}`, {
        method: "PATCH",
        body: JSON.stringify({ text, color }),
      });
      const root = mmRoot(state.currentMap.nodes);
      if (root && root.id === draft.nodeId) {
        await api(`/api/mindmaps/${state.currentMap.id}`, {
          method: "PATCH",
          body: JSON.stringify({ title: text }),
        });
      }
      closeMmIdeaDialog();
      await refreshCurrentMap();
      return;
    }
    if (draft.mode === "create") {
      await api(`/api/mindmaps/${state.currentMap.id}/nodes`, {
        method: "POST",
        body: JSON.stringify({
          text,
          color,
          parent_id: draft.parentId ?? null,
          x: draft.x ?? null,
          y: draft.y ?? null,
          created_by_id: state.meId || null,
        }),
      });
      closeMmIdeaDialog();
      await refreshCurrentMap();
    }
  } catch (err) {
    alert(err.message || String(err));
  }
});

let mmTitleTimer = null;
$("#mmTitleInput")?.addEventListener("input", () => {
  clearTimeout(mmTitleTimer);
  mmTitleTimer = setTimeout(async () => {
    if (!state.currentMap) return;
    const title = String($("#mmTitleInput").value || "").trim();
    if (!title || title === state.currentMap.title) return;
    try {
      await api(`/api/mindmaps/${state.currentMap.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      await loadMindmaps();
    } catch (err) {
      console.error(err);
    }
  }, 500);
});

(() => {
  const canvas = $("#mmCanvas");
  if (!canvas) return;
  let panning = false;
  let sx = 0;
  let sy = 0;
  let ox = 0;
  let oy = 0;
  canvas.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".mm-sticky")) return;
    if (e.target.closest(".mm-arrow-group")) return;
    if (state.mmTool === "sticky") {
      const pos = canvasToWorld(e.clientX, e.clientY);
      openMmIdeaDialog({
        title: "Новая идея",
        text: "",
        color: state.mmSelectedColor || MM_COLORS[0].hex,
        mode: "create",
        parentId: null,
        x: pos.x - MM_NODE_W / 2,
        y: pos.y - MM_NODE_H / 2,
      });
      return;
    }
    if (state.mmTool !== "select") return;
    panning = true;
    canvas.setPointerCapture(e.pointerId);
    sx = e.clientX;
    sy = e.clientY;
    ox = state.mmPan.x;
    oy = state.mmPan.y;
    canvas.classList.add("panning");
  });
  canvas.addEventListener("pointermove", (e) => {
    if (state.mmTool === "arrow" && state.mmArrowFrom && state.currentMap) {
      const from = state.currentMap.nodes.find((n) => n.id === state.mmArrowFrom);
      if (from) {
        const draft = $("#mmDraftArrow");
        const to = canvasToWorld(e.clientX, e.clientY);
        if (draft) {
          draft.setAttribute("d", mmArrowPath(mmNodeCenter(from), to));
          draft.setAttribute("marker-end", "url(#mmArrowHeadDraft)");
        }
      }
    }
    if (!panning) return;
    state.mmPan.x = ox + (e.clientX - sx);
    state.mmPan.y = oy + (e.clientY - sy);
    applyMmTransform();
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!panning) return;
    panning = false;
    canvas.classList.remove("panning");
    try {
      canvas.releasePointerCapture(e.pointerId);
    } catch (_) {
      /* ignore */
    }
  });
  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const next = Math.min(1.8, Math.max(0.45, state.mmScale * (e.deltaY > 0 ? 0.92 : 1.08)));
      state.mmScale = next;
      applyMmTransform();
    },
    { passive: false }
  );
})();

applyTheme(getTheme());
$("#btnTheme")?.addEventListener("click", () => {
  applyTheme(getTheme() === "dark" ? "light" : "dark");
});

load().catch((err) => {
  console.error(err);
  alert("Не удалось загрузить Project Workflow: " + err.message);
});
