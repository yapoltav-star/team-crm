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
  "раздача",
];

/** Быстрые кнопки «Перекинуть» в окне задачи — эти имена сверху. */
const REASSIGN_QUICK = [
  { name: "Афина" },
  { name: "Заира" },
  { name: "Ольга", team_group: "ПВС", job_title: "раздача" },
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
  $("#viewAuto")?.classList.toggle("hidden", view !== "auto");
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

function normJobTitle(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replaceAll("ё", "е");
}

function isPartner() {
  return normJobTitle(me()?.job_title) === "партнер";
}

function isRuk() {
  return normJobTitle(me()?.job_title) === "рук";
}

/** Партнёр видит всех на своём проекте */
function seesProjectTeam() {
  return isPartner();
}

function canReassignTasks() {
  return isOwner() || isRuk();
}

function visiblePeople() {
  const all = people();
  if (isOwner() || isRuk()) return all;
  const m = me();
  if (!m) return [];
  // партнёр видит всех в своём проекте (слева и их задачи)
  if (seesProjectTeam()) {
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

function autoKindOf(task) {
  const blob = `${task?.description || ""}\n${task?.articles || ""}\n${task?.title || ""}`;
  if (task?.auto_kind) return String(task.auto_kind).toLowerCase();
  const m = /\[auto:(own-stock|my-shelf):/i.exec(blob);
  if (m) return m[1].toLowerCase();
  if (/Полка слабая:/i.test(task?.title || "")) return "my-shelf";
  if (/на вашем складе кончился/i.test(task?.title || "")) return "own-stock";
  return "";
}

function autoKindLabel(kind) {
  if (kind === "own-stock") return "склад";
  if (kind === "my-shelf") return "полка";
  return "авто";
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
  const autoKind = autoKindOf(t);
  const archiveBtn =
    t.status === "done" || t.status === "doing"
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
      ${autoKind ? `<span class="chip auto">${escapeHtml(autoKindLabel(autoKind))}</span>` : ""}
      ${t.theme_title ? `<span class="chip theme">${escapeHtml(t.theme_title)}</span>` : ""}
      <label class="chip due-chip" title="Нажми — сменить срок">
        <span>${t.due_date ? `до ${escapeHtml(formatDate(t.due_date))}` : "срок"}</span>
        <input type="date" class="due-chip-input" value="${escapeHtml(t.due_date || "")}" />
      </label>
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
  // из «в работе» — сначала отметить выполненной, тему не трогаем
  if (t.status === "doing") {
    await api(`/api/tasks/${t.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: "done",
        actor_id: state.meId || null,
        ...(t.theme_id != null ? { theme_id: t.theme_id } : {}),
      }),
    });
  }
  await api(`/api/tasks/${t.id}/archive${q}`, { method: "POST" });
  await load();
}

function bindDueChip(card, t) {
  const dueChip = card.querySelector(".due-chip");
  const dueInput = card.querySelector(".due-chip-input");
  if (!dueChip || !dueInput) return;
  dueChip.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    try {
      dueInput.showPicker?.();
    } catch (_) {
      dueInput.focus();
      dueInput.click();
    }
  });
  dueInput.addEventListener("click", (e) => e.stopPropagation());
  dueInput.addEventListener("change", async (e) => {
    e.stopPropagation();
    const due = String(dueInput.value || "").trim() || null;
    try {
      await api(`/api/tasks/${t.id}`, {
        method: "PATCH",
        body: JSON.stringify({ due_date: due, actor_id: state.meId || null }),
      });
      await load();
    } catch (err) {
      alert(err.message || String(err));
    }
  });
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
  bindDueChip(card, t);
  card.addEventListener("dblclick", (e) => {
    if (e.target.closest(".due-chip, .card-actions")) return;
    openTaskDialog(t.id);
  });
  card.addEventListener("click", (e) => {
    if (e.target.closest(".card-actions, .due-chip")) return;
    openTaskDialog(t.id);
  });
  card.addEventListener("dragstart", (e) => {
    if (e.target.closest(".card-actions, .due-chip")) {
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

function boardThemes() {
  return (state.board?.themes || []).filter((t) => t.active !== false);
}

function themeLanes(tasksInCol) {
  const themes = boardThemes();
  const usedHere = new Set(tasksInCol.map((t) => t.theme_id).filter(Boolean));
  // темы из «в работе» и «выполнено» — чтобы пустая колонка всё равно приняла ту же тему
  const usedBoard = new Set(
    (state.board?.tasks || [])
      .filter((t) => t.status === "doing")
      .map((t) => t.theme_id)
      .filter(Boolean)
  );
  const used = new Set([...usedHere, ...usedBoard]);
  const hasUnthemed = tasksInCol.some((t) => !t.theme_id);
  const lanes = [];
  for (const th of themes) {
    if (used.has(th.id)) {
      lanes.push({ id: th.id, title: th.title, is_system: !!th.is_system });
    }
  }
  if (hasUnthemed) {
    lanes.push({ id: null, title: "Без темы" });
  }
  return lanes;
}

function appendCard(host, t) {
  const card = document.createElement("article");
  card.className = `card due-${t.due_flag || "none"}`;
  card.draggable = true;
  card.dataset.id = t.id;
  card.innerHTML = cardHtml(t);
  paintCard(card, t);
  bindCard(card, t);
  host.appendChild(card);
}

function pickThemeForMove({
  taskTitle = "",
  status = "doing",
  preferredThemeId = null,
} = {}) {
  const dlg = $("#pickThemeDlg");
  const list = $("#pickThemeList");
  const titleEl = $("#pickThemeTitle");
  const hintEl = $("#pickThemeHint");
  if (!dlg || !list) {
    return Promise.resolve({ cancelled: true });
  }
  const statusLabel = status === "done" ? "Выполнено" : "В работе";
  if (titleEl) titleEl.textContent = "Выбери тему";
  if (hintEl) {
    hintEl.textContent = taskTitle
      ? `«${taskTitle}» → ${statusLabel}`
      : `Задача переходит в «${statusLabel}»`;
  }

  const themes = boardThemes();
  const preferred =
    preferredThemeId != null && preferredThemeId !== ""
      ? Number(preferredThemeId)
      : null;

  const rows = [
    {
      id: null,
      title: "Без темы",
      note: "",
      selected: preferred == null || Number.isNaN(preferred),
    },
    ...themes.map((th) => ({
      id: th.id,
      title: th.title,
      note: th.is_system ? "системная" : "",
      selected: preferred != null && Number(th.id) === preferred,
    })),
  ];

  list.innerHTML = rows
    .map(
      (r) => `
    <button type="button" class="pick-theme-btn${r.selected ? " selected" : ""}" data-theme-id="${
      r.id == null ? "" : r.id
    }">
      <span>${escapeHtml(r.title)}</span>
      ${r.note ? `<small>${escapeHtml(r.note)}</small>` : ""}
    </button>`
    )
    .join("");

  return new Promise((resolve) => {
    let settled = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      dlg.removeEventListener("close", onClose);
      cancelBtn?.removeEventListener("click", onCancel);
      list.querySelectorAll(".pick-theme-btn").forEach((btn) => {
        btn.removeEventListener("click", onPick);
      });
      if (dlg.open) dlg.close();
      resolve(result);
    };
    const onClose = () => finish({ cancelled: true });
    const onCancel = (e) => {
      e.preventDefault();
      finish({ cancelled: true });
    };
    const onPick = (e) => {
      const btn = e.currentTarget;
      const raw = btn.getAttribute("data-theme-id");
      const themeId = raw === "" || raw == null ? null : Number(raw);
      finish({ cancelled: false, themeId });
    };
    const cancelBtn = $("#pickThemeCancel");
    cancelBtn?.addEventListener("click", onCancel);
    list.querySelectorAll(".pick-theme-btn").forEach((btn) => {
      btn.addEventListener("click", onPick);
    });
    dlg.addEventListener("close", onClose);
    dlg.showModal();
  });
}

function bindDropZone(el, { status, themeId, keepTheme = false }) {
  el.addEventListener("dragover", (e) => {
    e.preventDefault();
    el.classList.add("drag-over");
  });
  el.addEventListener("dragleave", () => el.classList.remove("drag-over"));
  el.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation();
    el.classList.remove("drag-over");
    const id = Number(state.dragId || e.dataTransfer.getData("text/plain"));
    if (!id) return;
    const prev = state.board?.tasks?.find((t) => Number(t.id) === id);
    const body = { status, actor_id: state.meId || null };

    if (status === "todo") {
      body.theme_id = null;
    } else if (status === "doing") {
      let preferred = null;
      if (themeId != null && themeId !== "") preferred = themeId;
      else if (prev && prev.theme_id != null) preferred = prev.theme_id;
      const pick = await pickThemeForMove({
        taskTitle: prev?.title || "",
        status,
        preferredThemeId: preferred,
      });
      if (pick.cancelled) return;
      body.theme_id = pick.themeId;
    } else if (status === "done" || keepTheme) {
      if (prev && prev.theme_id != null) body.theme_id = prev.theme_id;
    } else if (themeId !== undefined) {
      body.theme_id = themeId;
    }

    try {
      await api(`/api/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      await load();
    } catch (err) {
      alert(err.message || String(err));
    }
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

    if (col.id === "todo" || col.id === "done") {
      const cards = document.createElement("div");
      cards.className = "cards";
      cards.dataset.status = col.id;
      // todo: без темы; выполнено: тема не важна в колонке, у карточки сохраняем
      bindDropZone(cards, {
        status: col.id,
        themeId: col.id === "todo" ? null : undefined,
        keepTheme: col.id === "done",
      });
      for (const t of list) appendCard(cards, t);
      colEl.appendChild(cards);
    } else {
      const lanes = themeLanes(list);
      if (!lanes.length) {
        // колонка пуста — сброс статуса, тему не трогаем
        const cards = document.createElement("div");
        cards.className = "cards theme-cards";
        cards.dataset.status = col.id;
        bindDropZone(cards, { status: col.id, keepTheme: true });
        colEl.appendChild(cards);
      } else {
        const lanesWrap = document.createElement("div");
        lanesWrap.className = "theme-lanes";
        for (const lane of lanes) {
          const laneTasks = list.filter((t) =>
            lane.id == null ? !t.theme_id : Number(t.theme_id) === Number(lane.id)
          );
          const laneEl = document.createElement("div");
          laneEl.className = "theme-lane";
          laneEl.innerHTML = `<div class="theme-lane-head"><span>${escapeHtml(
            lane.title
          )}</span><span class="col-count">${laneTasks.length}</span></div>`;
          const cards = document.createElement("div");
          cards.className = "cards theme-cards";
          cards.dataset.status = col.id;
          cards.dataset.themeId = lane.id == null ? "" : String(lane.id);
          bindDropZone(cards, {
            status: col.id,
            themeId: lane.id == null ? null : lane.id,
          });
          for (const t of laneTasks) appendCard(cards, t);
          laneEl.appendChild(cards);
          lanesWrap.appendChild(laneEl);
        }
        colEl.appendChild(lanesWrap);
      }
    }
    board.appendChild(colEl);
  }
}

function renderThemeDialog() {
  const list = $("#themeList");
  if (!list) return;
  const themes = boardThemes();
  const systemRow = $("#themeSystemRow");
  if (systemRow) systemRow.classList.toggle("hidden", !isOwner());
  if (!themes.length) {
    list.innerHTML = `<div class="chat-empty">Тем пока нет</div>`;
    return;
  }
  list.innerHTML = themes
    .map((t) => {
      const canEdit =
        isOwner() || (!t.is_system && t.owner_employee_id === state.meId);
      const kind = t.is_system ? "системная" : "моя";
      return `
      <div class="theme-edit-row" data-id="${t.id}">
        <div>
          <strong>${escapeHtml(t.title)}</strong>
          <span class="chip">${kind}</span>
        </div>
        <div class="theme-edit-actions">
          ${
            canEdit
              ? `<button type="button" class="ghost" data-act="rename">✎</button>
                 <button type="button" class="ghost danger" data-act="del">✕</button>`
              : ""
          }
        </div>
      </div>`;
    })
    .join("");
  list.querySelectorAll(".theme-edit-row").forEach((row) => {
    const id = Number(row.dataset.id);
    row.querySelector('[data-act="rename"]')?.addEventListener("click", async () => {
      const th = themes.find((x) => x.id === id);
      const title = prompt("Название темы", th?.title || "");
      if (title == null) return;
      const name = String(title).trim();
      if (!name) return;
      try {
        await api(`/api/themes/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ title: name, actor_id: state.meId || null }),
        });
        await load();
        renderThemeDialog();
      } catch (err) {
        alert(err.message || String(err));
      }
    });
    row.querySelector('[data-act="del"]')?.addEventListener("click", async () => {
      if (!confirm("Удалить тему? Задачи останутся без темы.")) return;
      try {
        await api(`/api/themes/${id}?actor_id=${state.meId || ""}`, {
          method: "DELETE",
        });
        await load();
        renderThemeDialog();
      } catch (err) {
        alert(err.message || String(err));
      }
    });
  });
}

function openThemeDialog() {
  if (!state.meId) {
    alert("Сначала войди");
    return;
  }
  $("#themeNewTitle").value = "";
  const asSys = $("#themeAsSystem");
  if (asSys) asSys.checked = false;
  renderThemeDialog();
  $("#themeDlg").showModal();
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
        bindDueChip(card, t);
        card.addEventListener("click", (e) => {
          if (e.target.closest(".due-chip")) return;
          openTaskDialog(t.id);
        });
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
  if (state.view === "auto") renderAutoTasks();
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

function formatWatchLast(last) {
  if (!last || typeof last !== "object") {
    return "Ещё не запускалось после деплоя (или ждёт расписания).";
  }
  if (last.ok === false) {
    const reason = last.error || last.skipped || "ошибка";
    if (reason === "paused") return "Пропуск: на паузе";
    if (reason === "disabled") return "Пропуск: выключено в настройках";
    return `Не ок: ${reason}`;
  }
  const created = Array.isArray(last.created) ? last.created.length : Number(last.created || 0);
  const bits = [`создано ${created}`];
  if (last.weak_total != null) bits.push(`слабых полок ${last.weak_total}`);
  if (last.critical_total != null) bits.push(`критичных ${last.critical_total}`);
  if (last.skipped_cooldown != null) bits.push(`кулдаун ${last.skipped_cooldown}`);
  if (last.skipped_excluded != null) bits.push(`исключено ${last.skipped_excluded}`);
  if (last.checked != null) bits.push(`проверено ${last.checked}`);
  return bits.join(" · ");
}

function renderAutoTaskCard(t) {
  const kind = autoKindOf(t);
  const names = (t.assignees?.length
    ? t.assignees.map((a) => a.name)
    : t.assignee_name
      ? [t.assignee_name]
      : []
  ).join(", ");
  const isOpen = t.status !== "done" && !t.archived && !t.archived_at;
  const statusLabel =
    t.archived || t.archived_at
      ? "архив"
      : t.status === "done"
        ? "сделано"
        : t.status === "doing"
          ? "в работе"
          : "новая";
  const managers =
    isOpen && canReassignTasks() ? managersForReassign(t) : [];
  const reassignHtml = managers.length
    ? `<div class="auto-reassign">
        <select class="auto-reassign-select" title="Кому перекинуть">
          <option value="">Перекинуть на…</option>
          ${managers
            .map(
              (e) =>
                `<option value="${e.id}">${escapeHtml(e.name)}${
                  e.job_title ? ` · ${escapeHtml(e.job_title)}` : ""
                }</option>`
            )
            .join("")}
        </select>
        <button type="button" class="auto-reassign-go">Перекинуть</button>
      </div>`
    : "";
  const el = document.createElement("article");
  el.className = "tpl-card";
  el.innerHTML = `
    <div class="tpl-card-top">
      <h3>${escapeHtml(t.title)}</h3>
      <span class="chip auto">${escapeHtml(autoKindLabel(kind))}</span>
    </div>
    <div class="meta">
      <span class="chip ${t.status === "done" || t.archived ? "ok" : ""}">${statusLabel}</span>
      ${names ? `<span class="chip assignee">${escapeHtml(names)}</span>` : ""}
      ${t.due_date ? `<span class="chip">до ${escapeHtml(formatDate(t.due_date))}</span>` : ""}
      ${t.created_at ? `<span class="chip">${escapeHtml(formatDt(t.created_at))}</span>` : ""}
      ${t.articles ? `<span class="chip project">${escapeHtml(t.articles)}</span>` : ""}
    </div>
    ${reassignHtml}
  `;
  el.addEventListener("click", (ev) => {
    if (ev.target.closest(".auto-reassign")) return;
    openTaskDialog(t.id);
  });
  const goBtn = el.querySelector(".auto-reassign-go");
  const sel = el.querySelector(".auto-reassign-select");
  if (goBtn && sel) {
    goBtn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const empId = Number(sel.value);
      if (!empId) {
        alert("Выбери менеджера");
        return;
      }
      goBtn.disabled = true;
      sel.disabled = true;
      try {
        await api(`/api/tasks/${t.id}/reassign`, {
          method: "POST",
          body: JSON.stringify({
            assignee_id: empId,
            actor_id: state.meId || null,
            notify: true,
          }),
        });
        await load();
        if (state.view === "auto") await renderAutoTasks();
      } catch (err) {
        alert(err.message || String(err));
        goBtn.disabled = false;
        sel.disabled = false;
      }
    });
  }
  return el;
}

async function renderAutoTasks() {
  const watchBox = $("#autoWatchCards");
  const openList = $("#autoOpenList");
  const doneList = $("#autoDoneList");
  if (!watchBox || !openList || !doneList) return;
  watchBox.innerHTML = `<div class="home-empty">Загружаю…</div>`;
  openList.innerHTML = "";
  doneList.innerHTML = "";
  let data;
  try {
    const q = state.meId ? `?viewer_id=${state.meId}` : "";
    data = await api(`/api/auto-tasks${q}`);
  } catch (err) {
    watchBox.innerHTML = `<div class="home-empty">${escapeHtml(err.message || String(err))}</div>`;
    return;
  }
  const watches = data.watches || {};
  const managers = (data.managers || []).filter((e) => e && e.id);
  const canEditAssignee = canReassignTasks();
  watchBox.innerHTML = "";

  const addWatchCard = (w, opts) => {
    const {
      key,
      endpoint,
      field,
      pauseField,
      isPick,
      onOpen,
    } = opts;
    const card = document.createElement("article");
    card.className = "auto-watch-card" + (isPick || onOpen ? " auto-watch-pick" : "");
    const paused = !!w.paused;
    const enabled = !!w.enabled;
    const statusLabel = !enabled ? "выкл" : paused ? "пауза" : "вкл";
    const statusClass = !enabled ? "" : paused ? "pause" : "on";
    const assigneeOpts = managers
      .map(
        (e) =>
          `<option value="${e.id}" ${
            Number(w.assignee_id) === Number(e.id) ? "selected" : ""
          }>${escapeHtml(e.name)}${
            e.job_title ? ` · ${escapeHtml(e.job_title)}` : ""
          }${e.role === "owner" ? " · владелец" : ""}</option>`
      )
      .join("");
    const pickCount = Number(
      w.vendor_count != null
        ? w.vendor_count
        : (w.vendor_codes || []).length
    ) || 0;
    const exclCount = Number(w.exclude_count || 0);
    const pickMeta = isPick
      ? ` · артикулов ${pickCount}`
      : onOpen && exclCount
        ? ` · исключено ${exclCount}`
        : "";
    card.innerHTML = `
      <div class="auto-watch-top">
        <div>
          <h3>${escapeHtml(w.label || key)}</h3>
          <p class="desc"><span class="auto-watch-status ${statusClass}">${statusLabel}</span> · ${escapeHtml(w.days || "—")} @ ${escapeHtml(w.time || "—")}${
            w.min_mine_pct != null ? ` · порог &lt;${escapeHtml(String(w.min_mine_pct))}%` : ""
          } · кулдаун ${escapeHtml(String(w.cooldown_days ?? "—"))}д${pickMeta}</p>
        </div>
        <div class="auto-watch-actions">
          ${
            canEditAssignee && enabled
              ? `<button type="button" class="ghost auto-pause-btn">${
                  paused ? "Снять паузу" : "На паузу"
                }</button>`
              : ""
          }
          ${
            onOpen
              ? `<button type="button" class="ghost auto-pick-open">Артикулы</button>`
              : ""
          }
          <button type="button" class="ghost auto-run-btn" data-endpoint="${endpoint}">Запустить сейчас</button>
        </div>
      </div>
      <p class="auto-how">${escapeHtml(w.how_it_works || "")}</p>
      ${
        paused
          ? `<p class="auto-pause-hint">На паузе: по расписанию задачи не создаются. «Запустить сейчас» всё ещё работает.</p>`
          : ""
      }
      ${
        isPick
          ? ""
          : `<div class="auto-assignee-row">
        <label class="auto-assignee-label">Кому ставить все новые задачи этого типа
          <select class="auto-assignee-select" ${canEditAssignee ? "" : "disabled"}>
            ${assigneeOpts || `<option value="">—</option>`}
          </select>
        </label>
        ${
          canEditAssignee
            ? `<button type="button" class="auto-assignee-save">Сохранить</button>`
            : w.assignee_name
              ? `<span class="chip assignee">сейчас: ${escapeHtml(w.assignee_name)}</span>`
              : ""
        }
      </div>
      <p class="auto-assignee-hint">Уже созданные задачи не меняются — их можно перекинуть в списке ниже. После сохранения новые автозапуски пойдут выбранному человеку.${
        onOpen && !isPick
          ? " Ненужные артикулы сними в «Артикулы»."
          : ""
      }</p>`
      }
      ${
        isPick
          ? `<p class="auto-assignee-hint">${
              w.assignee_name
                ? `Исполнитель: <b>${escapeHtml(w.assignee_name)}</b>. `
                : "Исполнитель ещё не выбран. "
            }Кликни карточку или «Артикулы», чтобы выбрать список и человека.</p>`
          : ""
      }
      ${
        w.comment
          ? `<p class="auto-assignee-hint"><b>Коммент:</b> ${escapeHtml(w.comment)}</p>`
          : ""
      }
      <p class="auto-watch-last">${escapeHtml(formatWatchLast(w.last))}</p>
    `;
    if (onOpen) {
      card.style.cursor = "pointer";
      card.addEventListener("click", (ev) => {
        if (ev.target.closest("button, select, a, input, label")) return;
        onOpen();
      });
      card.querySelector(".auto-pick-open")?.addEventListener("click", (ev) => {
        ev.stopPropagation();
        onOpen();
      });
    }
    card.querySelector(".auto-run-btn")?.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = "…";
      try {
        await api(endpoint, { method: "POST", body: "{}" });
        await load();
        await renderAutoTasks();
      } catch (err) {
        alert(err.message || String(err));
      } finally {
        btn.disabled = false;
        btn.textContent = "Запустить сейчас";
      }
    });
    const pauseBtn = card.querySelector(".auto-pause-btn");
    if (pauseBtn) {
      pauseBtn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        pauseBtn.disabled = true;
        try {
          if (isPick) {
            await api("/api/auto-tasks/stock-pick", {
              method: "PATCH",
              body: JSON.stringify({
                id: w.id,
                paused: !paused,
                actor_id: state.meId || null,
              }),
            });
          } else {
            const payload = { actor_id: state.meId || null };
            payload[pauseField] = !paused;
            await api("/api/auto-tasks/pause", {
              method: "PATCH",
              body: JSON.stringify(payload),
            });
          }
          await renderAutoTasks();
        } catch (err) {
          alert(err.message || String(err));
          pauseBtn.disabled = false;
        }
      });
    }
    const saveBtn = card.querySelector(".auto-assignee-save");
    const sel = card.querySelector(".auto-assignee-select");
    if (saveBtn && sel) {
      saveBtn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const empId = Number(sel.value);
        if (!empId) {
          alert("Выбери менеджера");
          return;
        }
        saveBtn.disabled = true;
        sel.disabled = true;
        try {
          const payload = { actor_id: state.meId || null };
          payload[field] = empId;
          await api("/api/auto-tasks/assignees", {
            method: "PATCH",
            body: JSON.stringify(payload),
          });
          await renderAutoTasks();
        } catch (err) {
          alert(err.message || String(err));
          saveBtn.disabled = false;
          sel.disabled = false;
        }
      });
    }
    watchBox.appendChild(card);
  };

  if (watches.stock) {
    addWatchCard(watches.stock, {
      key: "stock",
      endpoint: "/api/stock-watch/run",
      field: "stock_assignee_id",
      pauseField: "stock_paused",
    });
  }
  for (const pick of watches.stock_picks || []) {
    addWatchCard(pick, {
      key: pick.id,
      endpoint: "/api/stock-watch/run",
      isPick: true,
      onOpen: () => openStockPickDialog(pick, managers),
    });
  }
  if (watches.shelf) {
    addWatchCard(watches.shelf, {
      key: "shelf",
      endpoint: "/api/shelf-watch/run",
      field: "shelf_assignee_id",
      pauseField: "shelf_paused",
      onOpen: () => openShelfExcludeDialog(watches.shelf),
    });
  }

  const tasks = data.tasks || [];
  const open = tasks.filter((t) => t.status !== "done" && !t.archived);
  const done = tasks.filter((t) => t.status === "done" || t.archived);
  $("#autoOpenCount").textContent = String(open.length);
  $("#autoDoneCount").textContent = String(done.length);
  if (!open.length) {
    openList.innerHTML = `<div class="home-empty">Открытых автозадач нет.</div>`;
  } else {
    for (const t of open) openList.appendChild(renderAutoTaskCard(t));
  }
  if (!done.length) {
    doneList.innerHTML = `<div class="home-empty">Пока пусто.</div>`;
  } else {
    for (const t of done.slice(0, 80)) doneList.appendChild(renderAutoTaskCard(t));
  }
}

let STOCK_PICK_ARTICLES = null;
let STOCK_PICK_SELECTED = new Set();
let STOCK_PICK_LOCKED = new Set(); // env excludes — нельзя включить обратно из UI
let STOCK_PICK_THRESHOLDS = {}; // lowercase vendor_code → number

async function ensureStockPickArticles(force = false) {
  if (!force && Array.isArray(STOCK_PICK_ARTICLES)) return STOCK_PICK_ARTICLES;
  STOCK_PICK_ARTICLES = await api("/api/articles");
  return STOCK_PICK_ARTICLES;
}

function updateStockPickSelectedCount() {
  const el = $("#stockPickSelectedCount");
  if (!el) return;
  const mode = ($("#stockPickMode") && $("#stockPickMode").value) || "stock-pick";
  if (mode === "shelf-exclude") {
    const total = (STOCK_PICK_ARTICLES || []).length;
    const off = total - STOCK_PICK_SELECTED.size;
    el.textContent = `следим ${STOCK_PICK_SELECTED.size} · снято ${Math.max(0, off)}`;
  } else {
    el.textContent = `${STOCK_PICK_SELECTED.size} выбрано`;
  }
}

function renderStockPickTable() {
  const body = $("#stockPickBody");
  const mode = ($("#stockPickMode") && $("#stockPickMode").value) || "stock-pick";
  const showThr = mode === "stock-pick";
  const thrHead = $("#stockPickThrHead");
  if (thrHead) thrHead.style.display = showThr ? "" : "none";
  const q = (($("#stockPickSearch") && $("#stockPickSearch").value) || "")
    .trim()
    .toLowerCase();
  if (!body) return;
  const rows = (STOCK_PICK_ARTICLES || []).filter((a) => {
    if (!q) return true;
    return String(a.vendor_code || "")
      .toLowerCase()
      .includes(q);
  });
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="${showThr ? 5 : 4}" class="stock-pick-empty">Ничего не найдено</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((a) => {
      const vc = String(a.vendor_code || "");
      const key = vc.toLowerCase();
      const checked = STOCK_PICK_SELECTED.has(key);
      const locked = STOCK_PICK_LOCKED.has(key);
      const thr =
        STOCK_PICK_THRESHOLDS[key] != null ? Number(STOCK_PICK_THRESHOLDS[key]) : 0;
      const thrCell = showThr
        ? `<td style="text-align:right">
            <input type="number" class="stock-pick-thr" data-vc="${escapeHtml(vc)}"
              min="0" step="1" value="${Number.isFinite(thr) ? thr : 0}"
              ${checked && !locked ? "" : "disabled"}
              title="Задача, если остаток на складе ≤ этого числа" />
          </td>`
        : "";
      return `<tr class="${locked ? "stock-pick-locked" : ""}">
        <td><input type="checkbox" data-vc="${escapeHtml(vc)}" ${checked ? "checked" : ""} ${
          locked ? "disabled title=\"Жёсткое исключение из настроек сервера\"" : ""
        } /></td>
        <td><code>${escapeHtml(vc)}</code>${
          locked ? ' <span class="chip">фикс</span>' : ""
        }</td>
        <td style="text-align:right">${a.stock != null ? Number(a.stock) : "—"}</td>
        <td style="text-align:right">${a.sales_90d != null ? Number(a.sales_90d) : "—"}</td>
        ${thrCell}
      </tr>`;
    })
    .join("");
  body.querySelectorAll('input[type="checkbox"][data-vc]').forEach((cb) => {
    cb.addEventListener("change", () => {
      const vc = cb.getAttribute("data-vc") || "";
      const key = vc.toLowerCase();
      if (STOCK_PICK_LOCKED.has(key)) {
        cb.checked = false;
        return;
      }
      if (cb.checked) {
        STOCK_PICK_SELECTED.add(key);
        if (STOCK_PICK_THRESHOLDS[key] == null) STOCK_PICK_THRESHOLDS[key] = 0;
      } else {
        STOCK_PICK_SELECTED.delete(key);
      }
      body.querySelectorAll("input.stock-pick-thr").forEach((thrInp) => {
        if (thrInp.getAttribute("data-vc") === vc) thrInp.disabled = !cb.checked;
      });
      updateStockPickSelectedCount();
    });
  });
  body.querySelectorAll("input.stock-pick-thr").forEach((inp) => {
    const sync = () => {
      const vc = inp.getAttribute("data-vc") || "";
      const key = vc.toLowerCase();
      let n = parseInt(inp.value, 10);
      if (!Number.isFinite(n) || n < 0) n = 0;
      STOCK_PICK_THRESHOLDS[key] = n;
    };
    inp.addEventListener("input", sync);
    inp.addEventListener("change", () => {
      sync();
      inp.value = String(STOCK_PICK_THRESHOLDS[inp.getAttribute("data-vc")?.toLowerCase() || ""] ?? 0);
    });
  });
  updateStockPickSelectedCount();
}

function setStockPickScheduleFields(days, time, comment) {
  const daySet = new Set(
    String(days || "")
      .split(",")
      .map((d) => d.trim().toLowerCase().slice(0, 3))
      .filter(Boolean)
  );
  $("#stockPickDays")
    ?.querySelectorAll('input[type="checkbox"]')
    .forEach((cb) => {
      cb.checked = daySet.has(cb.value);
    });
  const timeEl = $("#stockPickTime");
  if (timeEl) timeEl.value = String(time || "09:00").slice(0, 5);
  const commentEl = $("#stockPickComment");
  if (commentEl) commentEl.value = comment || "";
}

function readStockPickScheduleFields() {
  const days = [
    ...($("#stockPickDays")?.querySelectorAll('input[type="checkbox"]:checked') || []),
  ]
    .map((cb) => cb.value)
    .join(",");
  const time = ($("#stockPickTime") && $("#stockPickTime").value) || "";
  const comment = ($("#stockPickComment") && $("#stockPickComment").value) || "";
  return { days, time, comment };
}

async function openStockPickDialog(pick, managers) {
  const dlg = $("#stockPickDlg");
  if (!dlg) return;
  const canEdit = canReassignTasks();
  $("#stockPickMode").value = "stock-pick";
  $("#stockPickId").value = pick.id || "";
  $("#stockPickTitle").textContent = pick.label || "Наш склад · по артикулам";
  const hint = $("#stockPickHint");
  if (hint) {
    hint.textContent =
      "Отметь артикулы и у каждого поставь порог «Порог ≤» — задача придёт, если остаток на складе не больше этого числа. Дни/время — общее расписание склада.";
  }
  const wrap = $("#stockPickAssigneeWrap");
  if (wrap) wrap.style.display = "";
  const sel = $("#stockPickAssignee");
  sel.innerHTML = (managers || [])
    .map(
      (e) =>
        `<option value="${e.id}" ${
          Number(pick.assignee_id) === Number(e.id) ? "selected" : ""
        }>${escapeHtml(e.name)}${
          e.job_title ? ` · ${escapeHtml(e.job_title)}` : ""
        }</option>`
    )
    .join("");
  sel.disabled = !canEdit;
  $("#stockPickSave").disabled = !canEdit;
  $("#stockPickDelete").style.display = canEdit ? "" : "none";
  STOCK_PICK_LOCKED = new Set();
  STOCK_PICK_SELECTED = new Set(
    (pick.vendor_codes || []).map((c) => String(c).toLowerCase())
  );
  STOCK_PICK_THRESHOLDS = {};
  const thrSrc = pick.thresholds || {};
  for (const [k, v] of Object.entries(thrSrc)) {
    STOCK_PICK_THRESHOLDS[String(k).toLowerCase()] = Number(v) || 0;
  }
  for (const c of pick.vendor_codes || []) {
    const key = String(c).toLowerCase();
    if (STOCK_PICK_THRESHOLDS[key] == null) STOCK_PICK_THRESHOLDS[key] = 0;
  }
  // расписание склада (общее)
  try {
    const data = await api(
      `/api/auto-tasks${state.meId ? `?viewer_id=${state.meId}` : ""}`
    );
    const stock = (data.watches && data.watches.stock) || {};
    setStockPickScheduleFields(stock.days, stock.time, stock.comment);
  } catch (_) {
    setStockPickScheduleFields(pick.days, pick.time, "");
  }
  const search = $("#stockPickSearch");
  if (search) search.value = "";
  try {
    await ensureStockPickArticles(true);
  } catch (err) {
    alert(err.message || String(err));
    return;
  }
  window.__stockPickCanon = {};
  for (const a of STOCK_PICK_ARTICLES || []) {
    const vc = String(a.vendor_code || "");
    if (vc) window.__stockPickCanon[vc.toLowerCase()] = vc;
  }
  for (const c of pick.vendor_codes || []) {
    const vc = String(c || "");
    if (vc) window.__stockPickCanon[vc.toLowerCase()] = vc;
  }
  renderStockPickTable();
  if (!dlg.open) dlg.showModal();
}

async function openShelfExcludeDialog(shelf) {
  const dlg = $("#stockPickDlg");
  if (!dlg) return;
  const canEdit = canReassignTasks();
  $("#stockPickMode").value = "shelf-exclude";
  $("#stockPickId").value = "";
  $("#stockPickTitle").textContent = "Полки своих · артикулы";
  const hint = $("#stockPickHint");
  if (hint) {
    hint.textContent =
      "Галочка = следим. Сними с ненужных — по ним «Полка слабая» не создаётся. Дни, время и комментарий — ниже/выше.";
  }
  const wrap = $("#stockPickAssigneeWrap");
  if (wrap) wrap.style.display = "none";
  $("#stockPickSave").disabled = !canEdit;
  $("#stockPickDelete").style.display = "none";
  setStockPickScheduleFields(shelf.days, shelf.time, shelf.comment);
  const search = $("#stockPickSearch");
  if (search) search.value = "";

  const envEx = new Set(
    (shelf.env_exclude_codes || []).map((c) => String(c).toLowerCase())
  );
  const uiEx = new Set(
    (shelf.exclude_codes || []).map((c) => String(c).toLowerCase())
  );
  STOCK_PICK_LOCKED = envEx;

  try {
    await ensureStockPickArticles(true);
  } catch (err) {
    alert(err.message || String(err));
    return;
  }
  window.__stockPickCanon = {};
  STOCK_PICK_SELECTED = new Set();
  for (const a of STOCK_PICK_ARTICLES || []) {
    const vc = String(a.vendor_code || "");
    if (!vc) continue;
    const key = vc.toLowerCase();
    window.__stockPickCanon[key] = vc;
    if (!envEx.has(key) && !uiEx.has(key)) STOCK_PICK_SELECTED.add(key);
  }
  renderStockPickTable();
  if (!dlg.open) dlg.showModal();
}

async function createStockPickRoute() {
  if (!canReassignTasks()) {
    alert("Добавлять наборы могут владелец и рук");
    return;
  }
  try {
    const res = await api("/api/auto-tasks/stock-pick", {
      method: "PATCH",
      body: JSON.stringify({
        create: true,
        paused: true,
        label: "Наш склад · по артикулам",
        actor_id: state.meId || null,
      }),
    });
    await renderAutoTasks();
    const route = res.route;
    if (route) {
      const data = await api(
        `/api/auto-tasks${state.meId ? `?viewer_id=${state.meId}` : ""}`
      );
      openStockPickDialog(route, data.managers || []);
    }
  } catch (err) {
    alert(err.message || String(err));
  }
}

function bindStockPickDialog() {
  const dlg = $("#stockPickDlg");
  if (!dlg || dlg.dataset.bound) return;
  dlg.dataset.bound = "1";
  $("#stockPickClose")?.addEventListener("click", () => dlg.close());
  $("#stockPickSearch")?.addEventListener("input", () => renderStockPickTable());
  $("#stockPickCheckAll")?.addEventListener("change", (ev) => {
    const on = !!ev.target.checked;
    $("#stockPickBody")
      ?.querySelectorAll('input[type="checkbox"][data-vc]')
      .forEach((cb) => {
        const vc = cb.getAttribute("data-vc") || "";
        const key = vc.toLowerCase();
        if (STOCK_PICK_LOCKED.has(key)) {
          cb.checked = false;
          STOCK_PICK_SELECTED.delete(key);
          return;
        }
        cb.checked = on;
        if (on) {
          STOCK_PICK_SELECTED.add(key);
          if (STOCK_PICK_THRESHOLDS[key] == null) STOCK_PICK_THRESHOLDS[key] = 0;
        } else {
          STOCK_PICK_SELECTED.delete(key);
        }
      });
    renderStockPickTable();
  });
  $("#stockPickForm")?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const mode = ($("#stockPickMode") && $("#stockPickMode").value) || "stock-pick";
    const btn = $("#stockPickSave");
    if (btn) btn.disabled = true;
    try {
      if (mode === "shelf-exclude") {
        const exclude = [];
        for (const a of STOCK_PICK_ARTICLES || []) {
          const vc = String(a.vendor_code || "");
          if (!vc) continue;
          const key = vc.toLowerCase();
          if (STOCK_PICK_LOCKED.has(key)) continue; // env — уже на сервере
          if (!STOCK_PICK_SELECTED.has(key)) exclude.push(vc);
        }
        const sched = readStockPickScheduleFields();
        if (!sched.days) {
          alert("Выбери хотя бы один день");
          return;
        }
        await api("/api/auto-tasks/shelf-exclude", {
          method: "PATCH",
          body: JSON.stringify({
            exclude_codes: exclude,
            days: sched.days,
            time: sched.time,
            comment: sched.comment,
            actor_id: state.meId || null,
          }),
        });
      } else {
        const id = $("#stockPickId").value;
        const assigneeId = Number($("#stockPickAssignee").value);
        if (!assigneeId) {
          alert("Выбери исполнителя");
          return;
        }
        const codes = [...STOCK_PICK_SELECTED].map(
          (k) => (window.__stockPickCanon && window.__stockPickCanon[k]) || k
        );
        const thresholds = {};
        for (const k of STOCK_PICK_SELECTED) {
          const canon = (window.__stockPickCanon && window.__stockPickCanon[k]) || k;
          thresholds[canon] = Number(STOCK_PICK_THRESHOLDS[k]) || 0;
        }
        const sched = readStockPickScheduleFields();
        if (!sched.days) {
          alert("Выбери хотя бы один день");
          return;
        }
        await api("/api/auto-tasks/stock-pick", {
          method: "PATCH",
          body: JSON.stringify({
            id,
            assignee_id: assigneeId,
            vendor_codes: codes,
            thresholds,
            actor_id: state.meId || null,
          }),
        });
        await api("/api/auto-tasks/schedule", {
          method: "PATCH",
          body: JSON.stringify({
            kind: "stock",
            days: sched.days,
            time: sched.time,
            comment: sched.comment,
            actor_id: state.meId || null,
          }),
        });
      }
      dlg.close();
      await renderAutoTasks();
    } catch (err) {
      alert(err.message || String(err));
    } finally {
      if (btn) btn.disabled = false;
    }
  });
  $("#stockPickDelete")?.addEventListener("click", async () => {
    const id = $("#stockPickId").value;
    if (!id) return;
    if (!confirm("Удалить этот набор по артикулам?")) return;
    try {
      await api("/api/auto-tasks/stock-pick", {
        method: "PATCH",
        body: JSON.stringify({
          id,
          delete: true,
          actor_id: state.meId || null,
        }),
      });
      dlg.close();
      await renderAutoTasks();
    } catch (err) {
      alert(err.message || String(err));
    }
  });
}

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
        ${t.theme_title ? `<span class="chip theme">${escapeHtml(t.theme_title)}</span>` : ""}
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

function switchRowHtml(e, { checked = false, showRole = false } = {}) {
  const role = showRole ? employeeRoleName(e) : "";
  const sub =
    showRole && role && role !== "без роли"
      ? `<small>${escapeHtml(role)}</small>`
      : "";
  return `
    <label class="switch-row">
      <span class="switch-meta">
        <span class="avatar mini">${escapeHtml(initials(e.name))}</span>
        <span class="switch-text">
          <strong>${escapeHtml(e.name)}</strong>
          ${sub}
        </span>
      </span>
      <input class="switch-input" type="checkbox" value="${e.id}" ${
        checked ? "checked" : ""
      } />
      <span class="switch-ui" aria-hidden="true"></span>
    </label>`;
}

function fillAssigneeChecks(containerId, selectedIds, { grouped = false } = {}) {
  const box = $(containerId);
  const selected = new Set((selectedIds || []).map(Number));
  const list = (isOwner() ? people() : visiblePeople()).slice();
  if (!grouped) {
    box.innerHTML = list
      .map((e) => switchRowHtml(e, { checked: selected.has(e.id), showRole: true }))
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
            .map((e) => switchRowHtml(e, { checked: selected.has(e.id) }))
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

async function setTaskStatusFromDialog(status) {
  const task = state.currentTask;
  const id = Number(task?.id || $("#dlgForm")?.elements?.id?.value);
  if (!id) return;
  const body = { status, actor_id: state.meId || null };
  if (status === "todo") {
    body.theme_id = null;
  } else if (status === "doing") {
    const pick = await pickThemeForMove({
      taskTitle: task?.title || "",
      status,
      preferredThemeId: task?.theme_id ?? null,
    });
    if (pick.cancelled) return;
    body.theme_id = pick.themeId;
  } else if (status === "done" && task?.theme_id != null) {
    body.theme_id = task.theme_id;
  }
  await api(`/api/tasks/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
  await openTaskDialog(id);
  await load();
}

function renderDlgStatusActions(task) {
  const box = $("#dlgStatusActions");
  if (!box) return;
  const st = task?.status || "todo";
  const buttons = [];
  if (st === "todo") {
    buttons.push(
      `<button type="button" class="dlg-status-btn doing" data-status="doing">🔵 В работу</button>`
    );
    buttons.push(
      `<button type="button" class="dlg-status-btn done" data-status="done">✅ Сделано</button>`
    );
  } else if (st === "doing") {
    buttons.push(
      `<button type="button" class="dlg-status-btn done" data-status="done">✅ Сделано</button>`
    );
    buttons.push(
      `<button type="button" class="dlg-status-btn" data-status="todo">↩ В новые</button>`
    );
  } else if (st === "done") {
    buttons.push(
      `<button type="button" class="dlg-status-btn doing" data-status="doing">🔵 Вернуть в работу</button>`
    );
  }
  box.innerHTML = buttons.join("");
  box.querySelectorAll("[data-status]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const next = btn.getAttribute("data-status");
      if (!next) return;
      box.querySelectorAll("button").forEach((b) => {
        b.disabled = true;
      });
      try {
        await setTaskStatusFromDialog(next);
      } catch (err) {
        alert(err.message || String(err));
        renderDlgStatusActions(state.currentTask || task);
      }
    });
  });
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
  renderDlgStatusActions(task);
  const themeSel = form.elements.theme_id;
  const themes = boardThemes().slice();
  // если у задачи тема, которой нет в списке (чужая личная) — добавим
  if (task.theme_id && !themes.some((th) => Number(th.id) === Number(task.theme_id))) {
    themes.push({
      id: task.theme_id,
      title: task.theme_title || `Тема #${task.theme_id}`,
      is_system: false,
    });
  }
  themeSel.innerHTML =
    `<option value="">Без темы</option>` +
    themes
      .map((th) => {
        const mark = th.is_system ? "" : " · моя";
        return `<option value="${th.id}" ${
          Number(task.theme_id) === Number(th.id) ? "selected" : ""
        }>${escapeHtml(th.title)}${mark}</option>`;
      })
      .join("");
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
  let pool = people().filter((e) => e.active !== false && e.role !== "owner");
  // рук / партнёр — только свой проект
  if (seesProjectTeam()) {
    const team = String(me()?.team_group || "").trim();
    if (team) {
      pool = pool.filter((e) => String(e.team_group || "").trim() === team);
    }
  }
  return prioritizeReassignManagers(
    pool.filter((e) => !current.has(Number(e.id)))
  );
}

function _nameKey(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replaceAll("ё", "е");
}

function _firstName(value) {
  return _nameKey(value).split(/\s+/)[0] || "";
}

function prioritizeReassignManagers(pool) {
  const used = new Set();
  const quick = [];
  for (const want of REASSIGN_QUICK) {
    const wantName = _nameKey(want.name);
    const emp = pool.find((e) => {
      if (used.has(e.id)) return false;
      const first = _firstName(e.name);
      const full = _nameKey(e.name);
      if (first !== wantName && !full.startsWith(wantName)) return false;
      if (
        want.team_group &&
        _nameKey(e.team_group) !== _nameKey(want.team_group)
      ) {
        return false;
      }
      if (
        want.job_title &&
        normJobTitle(e.job_title) !== normJobTitle(want.job_title)
      ) {
        return false;
      }
      return true;
    });
    if (emp) {
      used.add(emp.id);
      quick.push(emp);
    }
  }
  const rest = pool
    .filter((e) => !used.has(e.id))
    .slice()
    .sort((a, b) =>
      String(a.name || "").localeCompare(String(b.name || ""), "ru")
    );
  return [...quick, ...rest];
}

function renderReassignButtons(task) {
  const bar = $("#reassignBar");
  const box = $("#reassignButtons");
  if (!bar || !box) return;
  if (!canReassignTasks()) {
    bar.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
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

$("#btnAutoRefresh")?.addEventListener("click", () => {
  if (state.view === "auto") renderAutoTasks();
});
$("#btnAddStockPick")?.addEventListener("click", () => createStockPickRoute());
bindStockPickDialog();

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
    theme_id: form.elements.theme_id.value
      ? Number(form.elements.theme_id.value)
      : null,
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

$("#btnThemes")?.addEventListener("click", () => openThemeDialog());
$("#themeCancel")?.addEventListener("click", () => $("#themeDlg")?.close());
$("#themeAdd")?.addEventListener("click", async () => {
  const title = String($("#themeNewTitle")?.value || "").trim();
  if (!title) {
    alert("Введи название темы");
    return;
  }
  if (!state.meId) {
    alert("Сначала войди");
    return;
  }
  const asSystem = !!$("#themeAsSystem")?.checked && isOwner();
  try {
    await api("/api/themes", {
      method: "POST",
      body: JSON.stringify({
        title,
        is_system: asSystem,
        owner_employee_id: asSystem ? null : state.meId,
        actor_id: state.meId,
      }),
    });
    $("#themeNewTitle").value = "";
    if ($("#themeAsSystem")) $("#themeAsSystem").checked = false;
    await load();
    renderThemeDialog();
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
