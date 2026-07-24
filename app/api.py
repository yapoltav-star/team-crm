from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.catalog import load_catalog
from app.config import get_settings
from app.db import SessionLocal, get_session
from app.job_titles import JOB_TITLE_SET
from app.models import (
    Employee,
    EmployeeAccess,
    Project,
    Task,
    TaskAssignee,
    TaskComment,
    TaskTemplate,
)
from app.notify import notify_task_assignee
from app.schemas import (
    ArticleOut,
    BoardOut,
    CommentIn,
    CommentOut,
    EmployeeIn,
    EmployeeOut,
    EmployeePatch,
    EventOut,
    HomeOut,
    ProjectIn,
    ProjectOut,
    TaskIn,
    TaskOut,
    TaskPatch,
    TeamGroupIn,
    TemplateIn,
    TemplateOut,
    AssigneeOut,
)
from app.sku import enrich_task_text
from app.tasks_service import (
    add_event,
    apply_status,
    due_flag,
    load_task_full,
    resolve_due_date,
    set_assignees,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


async def _can_see_ids(session: AsyncSession, viewer_id: int) -> list[int]:
    rows = (
        await session.scalars(
            select(EmployeeAccess.subject_id).where(EmployeeAccess.viewer_id == viewer_id)
        )
    ).all()
    return [int(x) for x in rows]


async def _employee_out(session: AsyncSession, emp: Employee) -> EmployeeOut:
    return EmployeeOut(
        id=emp.id,
        telegram_id=emp.telegram_id,
        name=emp.name,
        role=emp.role,
        job_title=emp.job_title or "",
        team_group=emp.team_group or "",
        active=emp.active,
        can_see_ids=await _can_see_ids(session, emp.id),
    )


async def _visible_subject_ids(
    session: AsyncSession, viewer: Employee
) -> set[int] | None:
    """None = все (владелец). Иначе id сотрудников, чьи задачи видны."""
    if viewer.role == "owner":
        return None
    granted = await _can_see_ids(session, viewer.id)
    return {viewer.id, *granted}


def _task_matches_subjects(task: Task, subject_ids: set[int]) -> bool:
    ids = {link.employee_id for link in (task.assignees or [])}
    if task.assignee_id:
        ids.add(task.assignee_id)
    if ids & subject_ids:
        return True
    if task.created_by_id in subject_ids and not ids:
        return True
    return False


def _task_visible_to(
    task: Task, viewer: Employee, subject_ids: set[int] | None
) -> bool:
    """Владелец — всё; иначе свои назначения/доступы + всё, что сам поставил."""
    if subject_ids is None:
        return True
    if task.created_by_id == viewer.id:
        return True
    return _task_matches_subjects(task, subject_ids)


def _assignees_out(task: Task) -> list[AssigneeOut]:
    out: list[AssigneeOut] = []
    seen: set[int] = set()
    for link in task.assignees or []:
        if link.employee and link.employee_id not in seen:
            seen.add(link.employee_id)
            out.append(
                AssigneeOut(
                    id=link.employee.id,
                    name=link.employee.name,
                    team_group=link.employee.team_group or "",
                    job_title=link.employee.job_title or "",
                )
            )
    if not out and task.assignee:
        out.append(
            AssigneeOut(
                id=task.assignee.id,
                name=task.assignee.name,
                team_group=task.assignee.team_group or "",
                job_title=task.assignee.job_title or "",
            )
        )
    return out


def _task_out(
    task: Task,
    *,
    today: date | None = None,
    notified: bool | None = None,
    notify_error: str | None = None,
    with_thread: bool = False,
) -> TaskOut:
    today = today or date.today()
    comments: list[CommentOut] = []
    events: list[EventOut] = []
    if with_thread:
        for c in task.comments or []:
            comments.append(
                CommentOut(
                    id=c.id,
                    body=c.body,
                    author_id=c.author_id,
                    author_name=c.author.name if c.author else None,
                    file_name=c.file_name or "",
                    file_url=c.file_url or "",
                    created_at=c.created_at,
                )
            )
        for e in task.events or []:
            events.append(
                EventOut(
                    id=e.id,
                    kind=e.kind,
                    message=e.message,
                    actor_name=e.actor.name if e.actor else None,
                    created_at=e.created_at,
                )
            )
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description or "",
        articles=task.articles or "",
        project_id=task.project_id,
        assignee_id=task.assignee_id,
        created_by_id=task.created_by_id,
        completed_by_id=task.completed_by_id,
        status=task.status,
        kind=task.kind,
        weekdays=task.weekdays or "",
        notify_time=task.notify_time,
        due_date=task.due_date,
        priority=task.priority or "normal",
        active=task.active,
        position=task.position,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        assignee_name=task.assignee.name if task.assignee else None,
        assignees=_assignees_out(task),
        project_name=task.project.name if task.project else None,
        created_by_name=task.created_by.name if task.created_by else None,
        completed_by_name=task.completed_by.name if task.completed_by else None,
        due_flag=due_flag(task.due_date, task.status, today),
        notified=notified,
        notify_error=notify_error,
        comments=comments,
        events=events,
    )


def _task_options():
    return (
        selectinload(Task.assignee),
        selectinload(Task.project),
        selectinload(Task.created_by),
        selectinload(Task.completed_by),
        selectinload(Task.assignees).selectinload(TaskAssignee.employee),
    )


@router.get("/board", response_model=BoardOut)
async def board(
    viewer_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> BoardOut:
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    projects = (
        await session.scalars(select(Project).where(Project.active.is_(True)).order_by(Project.id))
    ).all()
    all_employees = (
        await session.scalars(
            select(Employee).where(Employee.active.is_(True)).order_by(Employee.name)
        )
    ).all()

    viewer: Employee | None = None
    if viewer_id is not None:
        viewer = await session.get(Employee, viewer_id)
        if not viewer or not viewer.active:
            raise HTTPException(404, "Employee not found")

    if viewer is None:
        emp_outs = [await _employee_out(session, e) for e in all_employees]
        return BoardOut(
            projects=[ProjectOut.model_validate(p) for p in projects],
            employees=emp_outs,
            tasks=[],
        )

    subject_ids = await _visible_subject_ids(session, viewer)
    if subject_ids is None:
        visible_employees = all_employees
    else:
        visible_employees = [e for e in all_employees if e.id in subject_ids]

    tasks = (
        await session.scalars(
            select(Task)
            .where(Task.active.is_(True), Task.archived_at.is_(None))
            .options(*_task_options())
            .order_by(Task.position, Task.id)
        )
    ).all()
    if subject_ids is not None:
        tasks = [t for t in tasks if _task_visible_to(t, viewer, subject_ids)]

    emp_source = all_employees if viewer.role == "owner" else visible_employees
    emp_outs = [await _employee_out(session, e) for e in emp_source]

    return BoardOut(
        projects=[ProjectOut.model_validate(p) for p in projects],
        employees=emp_outs,
        tasks=[_task_out(t, today=today) for t in tasks],
    )


@router.get("/home", response_model=HomeOut)
async def home(
    employee_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
) -> HomeOut:
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    soon = today + timedelta(days=7)
    viewer = await session.get(Employee, employee_id)
    if not viewer or not viewer.active:
        raise HTTPException(404, "Employee not found")
    subject_ids = await _visible_subject_ids(session, viewer)

    tasks = (
        await session.scalars(
            select(Task)
            .where(
                Task.active.is_(True),
                Task.archived_at.is_(None),
                Task.status != "done",
            )
            .options(*_task_options())
            .order_by(Task.due_date.nulls_last(), Task.id)
        )
    ).all()

    if subject_ids is None:
        # владелец на главной — свои назначения + поставленные им
        mine_tasks = [t for t in tasks if _task_visible_to(t, viewer, {viewer.id})]
    else:
        mine_tasks = [t for t in tasks if _task_visible_to(t, viewer, subject_ids)]

    return HomeOut(
        new=[_task_out(t, today=today) for t in mine_tasks if t.status == "todo"],
        doing=[_task_out(t, today=today) for t in mine_tasks if t.status == "doing"],
        overdue=[
            _task_out(t, today=today)
            for t in mine_tasks
            if t.due_date and t.due_date < today
        ],
        today=[
            _task_out(t, today=today)
            for t in mine_tasks
            if t.due_date == today
        ],
        upcoming=[
            _task_out(t, today=today)
            for t in mine_tasks
            if t.due_date and today < t.due_date <= soon
        ][:10],
    )


@router.get("/articles", response_model=list[ArticleOut])
async def list_articles(session: AsyncSession = Depends(get_session)) -> list[ArticleOut]:
    rows = await load_catalog(session)
    return [
        ArticleOut(
            vendor_code=a.vendor_code,
            nm_id=a.nm_id,
            stock=a.stock,
            sales_90d=a.sales_90d,
        )
        for a in rows
    ]


@router.post("/projects", response_model=ProjectOut)
async def create_project(body: ProjectIn, session: AsyncSession = Depends(get_session)) -> ProjectOut:
    project = Project(name=body.name, color=body.color)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return ProjectOut.model_validate(project)


@router.post("/employees", response_model=EmployeeOut)
async def create_employee(
    body: EmployeeIn, session: AsyncSession = Depends(get_session)
) -> EmployeeOut:
    settings = get_settings()
    existing = await session.scalar(select(Employee).where(Employee.telegram_id == body.telegram_id))
    if existing:
        existing.name = body.name.strip()[:200]
        if int(existing.telegram_id) == int(settings.owner_telegram_id) or existing.role == "owner":
            existing.role = "owner"
        else:
            existing.role = body.role
        existing.active = True
        await session.commit()
        await session.refresh(existing)
        return await _employee_out(session, existing)
    role = body.role
    if int(body.telegram_id) == int(settings.owner_telegram_id):
        role = "owner"
    emp = Employee(telegram_id=body.telegram_id, name=body.name.strip()[:200], role=role)
    session.add(emp)
    await session.commit()
    await session.refresh(emp)
    return await _employee_out(session, emp)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut)
async def patch_employee(
    employee_id: int, body: EmployeePatch, session: AsyncSession = Depends(get_session)
) -> EmployeeOut:
    emp = await session.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")

    actor: Employee | None = None
    if body.actor_id is not None:
        actor = await session.get(Employee, body.actor_id)

    needs_owner = (
        body.job_title is not None
        or body.team_group is not None
        or body.can_see_ids is not None
        or body.active is not None
    )
    if needs_owner and (not actor or actor.role != "owner"):
        raise HTTPException(403, "Только владелец может менять группу и доступы")

    if body.name is not None and body.name.strip():
        if body.actor_id is not None and body.actor_id != employee_id:
            if not actor or actor.role != "owner":
                raise HTTPException(403, "Нельзя менять чужое имя")
        emp.name = body.name.strip()[:200]
    if body.job_title is not None:
        title = body.job_title.strip()
        if title and title not in JOB_TITLE_SET:
            raise HTTPException(400, f"Неизвестная роль. Доступны: {', '.join(sorted(JOB_TITLE_SET))}")
        emp.job_title = title
    if body.team_group is not None:
        emp.team_group = body.team_group.strip()[:100]
    if body.active is not None:
        emp.active = body.active
    if body.can_see_ids is not None:
        await session.execute(delete(EmployeeAccess).where(EmployeeAccess.viewer_id == emp.id))
        for sid in set(body.can_see_ids):
            if sid == emp.id:
                continue
            subject = await session.get(Employee, sid)
            if subject and subject.active:
                session.add(EmployeeAccess(viewer_id=emp.id, subject_id=sid))

    await session.commit()
    await session.refresh(emp)
    return await _employee_out(session, emp)


@router.post("/team-groups", response_model=list[EmployeeOut])
async def save_team_group(
    body: TeamGroupIn, session: AsyncSession = Depends(get_session)
) -> list[EmployeeOut]:
    """Создать или обновить группу: название + список участников."""
    actor = await session.get(Employee, body.actor_id)
    if not actor or actor.role != "owner":
        raise HTTPException(403, "Только владелец может управлять группами")
    name = body.name.strip()[:100]
    if not name:
        raise HTTPException(400, "Укажи название группы")
    old = (body.old_name or "").strip()
    member_ids = set(body.employee_ids)

    all_emps = (
        await session.scalars(select(Employee).where(Employee.active.is_(True)))
    ).all()

    for emp in all_emps:
        current = (emp.team_group or "").strip()
        if emp.id in member_ids:
            emp.team_group = name
        elif old and current == old:
            # убрали из группы при редактировании
            emp.team_group = ""
        elif not old and current == name and emp.id not in member_ids:
            # при создании с тем же именем — синхронизируем состав
            emp.team_group = ""

    await session.commit()
    refreshed = (
        await session.scalars(
            select(Employee).where(Employee.active.is_(True)).order_by(Employee.name)
        )
    ).all()
    return [await _employee_out(session, e) for e in refreshed]


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: int,
    viewer_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    try:
        task = await load_task_full(session, task_id)
    except Exception:
        raise HTTPException(404, "Task not found") from None
    if viewer_id is not None:
        viewer = await session.get(Employee, viewer_id)
        if not viewer or not viewer.active:
            raise HTTPException(404, "Employee not found")
        subject_ids = await _visible_subject_ids(session, viewer)
        if subject_ids is not None and not _task_visible_to(task, viewer, subject_ids):
            raise HTTPException(403, "Нет доступа к этой задаче")
    return _task_out(task, today=today, with_thread=True)


@router.post("/tasks", response_model=TaskOut)
async def create_task(
    body: TaskIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    now_hm = datetime.now(settings.tz).strftime("%H:%M")
    title = body.title
    articles = (body.articles or "").strip()
    catalog = await load_catalog(session)
    title2, arts, clarify = enrich_task_text(title, catalog)
    if clarify and not articles:
        raise HTTPException(409, clarify)
    if arts and not articles:
        articles = arts
        title = title2
    elif arts:
        title = title2

    ids = list(body.assignee_ids or [])
    if body.assignee_id and body.assignee_id not in ids:
        ids.insert(0, body.assignee_id)

    due = body.due_date
    if due is None and (body.kind or "once") == "once":
        due = resolve_due_date(today, text=title)

    task = Task(
        title=title,
        description=body.description,
        articles=articles,
        project_id=body.project_id,
        assignee_id=ids[0] if ids else None,
        created_by_id=body.created_by_id,
        status="todo" if body.status not in {"todo", "doing", "done"} else body.status,
        kind=body.kind,
        weekdays=body.weekdays,
        notify_time=body.notify_time or now_hm,
        due_date=due,
        priority=body.priority or "normal",
        created_at=datetime.utcnow(),
    )
    if task.status == "doing":
        task.started_at = datetime.utcnow()
    if task.status == "done":
        task.completed_at = datetime.utcnow()
        task.completed_by_id = body.created_by_id

    session.add(task)
    await session.commit()
    task = await load_task_full(session, task.id)
    if ids:
        await set_assignees(session, task, ids, actor_id=body.created_by_id, log=True)
    author = task.created_by.name if task.created_by else "кто-то"
    await add_event(session, task.id, f"Создана — {author}", kind="created", actor_id=body.created_by_id)
    await session.commit()
    task = await load_task_full(session, task.id)

    notified: bool | None = None
    notify_error: str | None = None
    if body.notify_now and body.kind == "once":
        bot = getattr(request.app.state, "bot", None)
        notified, notify_error = await notify_task_assignee(
            bot=bot,
            session=session,
            task=task,
            due=task.due_date or today,
        )
        task = await load_task_full(session, task.id)
    return _task_out(task, today=today, notified=notified, notify_error=notify_error, with_thread=True)


@router.post("/tasks/{task_id}/notify", response_model=TaskOut)
async def retry_notify(
    task_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    task = await session.get(Task, task_id)
    if not task or not task.active:
        raise HTTPException(404, "Task not found")
    task = await load_task_full(session, task_id)
    bot = getattr(request.app.state, "bot", None)
    notified, notify_error = await notify_task_assignee(
        bot=bot,
        session=session,
        task=task,
        due=task.due_date or today,
    )
    task = await load_task_full(session, task_id)
    return _task_out(task, today=today, notified=notified, notify_error=notify_error, with_thread=True)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def patch_task(
    task_id: int, body: TaskPatch, session: AsyncSession = Depends(get_session)
) -> TaskOut:
    settings = get_settings()
    today = datetime.now(settings.tz).date()
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task = await load_task_full(session, task_id)
    data = body.model_dump(exclude_unset=True)
    actor_id = data.pop("actor_id", None)
    assignee_ids = data.pop("assignee_ids", None)
    new_status = data.pop("status", None)

    single_assignee = data.pop("assignee_id", None)

    for key, value in data.items():
        setattr(task, key, value)

    if new_status is not None:
        try:
            await apply_status(session, task, new_status, actor_id=actor_id)
        except ValueError:
            raise HTTPException(400, "Статус только: todo | doing | done") from None

    if assignee_ids is not None:
        await set_assignees(session, task, assignee_ids, actor_id=actor_id, log=True)
    elif single_assignee is not None:
        await set_assignees(
            session,
            task,
            [single_assignee] if single_assignee else [],
            actor_id=actor_id,
            log=True,
        )

    await session.commit()
    task = await load_task_full(session, task_id)
    return _task_out(task, today=today, with_thread=True)


@router.post("/tasks/{task_id}/comments", response_model=CommentOut)
async def add_comment(
    task_id: int, body: CommentIn, session: AsyncSession = Depends(get_session)
) -> CommentOut:
    task = await session.get(Task, task_id)
    if not task or not task.active:
        raise HTTPException(404, "Task not found")
    text = (body.body or "").strip()
    if not text and not body.file_url:
        raise HTTPException(400, "Пустой комментарий")
    c = TaskComment(
        task_id=task_id,
        author_id=body.author_id,
        body=text,
        file_name=(body.file_name or "")[:300],
        file_url=(body.file_url or "")[:1000],
        created_at=datetime.utcnow(),
    )
    session.add(c)
    author = None
    if body.author_id:
        author = await session.get(Employee, body.author_id)
    await add_event(
        session,
        task_id,
        f"Комментарий — {author.name if author else 'кто-то'}",
        kind="comment",
        actor_id=body.author_id,
    )
    await session.commit()
    await session.refresh(c)
    return CommentOut(
        id=c.id,
        body=c.body,
        author_id=c.author_id,
        author_name=author.name if author else None,
        file_name=c.file_name or "",
        file_url=c.file_url or "",
        created_at=c.created_at,
    )


@router.delete("/tasks/{task_id}")
async def delete_task(
    task_id: int,
    actor_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Мягкое удаление — доступно любому залогиненному (менеджеры тоже)."""
    task = await session.get(Task, task_id)
    if not task or not task.active:
        raise HTTPException(404, "Task not found")
    task.active = False
    who = "кто-то"
    if actor_id:
        emp = await session.get(Employee, actor_id)
        if emp:
            who = emp.name
    await add_event(session, task_id, f"Удалена — {who}", kind="deleted", actor_id=actor_id)
    await session.commit()
    return {"ok": True}


@router.get("/archive/months")
async def archive_months(session: AsyncSession = Depends(get_session)) -> list[dict]:
    from app.archive import list_archive_months

    return await list_archive_months(session)


@router.get("/archive")
async def archive_list(
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    viewer_id: int | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[TaskOut]:
    from app.archive import list_archive_tasks

    settings = get_settings()
    today = datetime.now(settings.tz).date()
    tasks = await list_archive_tasks(session, year=year, month=month)
    if viewer_id is not None:
        viewer = await session.get(Employee, viewer_id)
        if not viewer or not viewer.active:
            raise HTTPException(404, "Employee not found")
        subject_ids = await _visible_subject_ids(session, viewer)
        if subject_ids is not None:
            tasks = [t for t in tasks if _task_visible_to(t, viewer, subject_ids)]
    elif viewer_id is None:
        tasks = []
    return [_task_out(t, today=today) for t in tasks]


@router.post("/archive/run")
async def archive_run() -> dict:
    from app.archive import archive_old_done_tasks

    return await archive_old_done_tasks(SessionLocal)


def _template_out(t: TaskTemplate) -> TemplateOut:
    ids = [int(x) for x in (t.assignee_ids or "").split(",") if x.strip().isdigit()]
    return TemplateOut(
        id=t.id,
        title=t.title,
        description=t.description or "",
        assignee_ids=ids,
        recurrence=t.recurrence,
        recurrence_value=t.recurrence_value or "",
        start_date=t.start_date,
        notify_time=t.notify_time,
        active=t.active,
        last_spawned_on=t.last_spawned_on,
    )


@router.get("/templates", response_model=list[TemplateOut])
async def list_templates(session: AsyncSession = Depends(get_session)) -> list[TemplateOut]:
    rows = (
        await session.scalars(select(TaskTemplate).order_by(TaskTemplate.id.desc()))
    ).all()
    return [_template_out(t) for t in rows]


@router.post("/templates", response_model=TemplateOut)
async def create_template(
    body: TemplateIn, session: AsyncSession = Depends(get_session)
) -> TemplateOut:
    t = TaskTemplate(
        title=body.title.strip(),
        description=body.description or "",
        assignee_ids=",".join(str(i) for i in body.assignee_ids),
        recurrence=body.recurrence,
        recurrence_value=body.recurrence_value or "",
        start_date=body.start_date,
        notify_time=body.notify_time or "09:00",
        active=body.active,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return _template_out(t)


@router.patch("/templates/{template_id}", response_model=TemplateOut)
async def patch_template(
    template_id: int, body: TemplateIn, session: AsyncSession = Depends(get_session)
) -> TemplateOut:
    t = await session.get(TaskTemplate, template_id)
    if not t:
        raise HTTPException(404, "Not found")
    t.title = body.title.strip()
    t.description = body.description or ""
    t.assignee_ids = ",".join(str(i) for i in body.assignee_ids)
    t.recurrence = body.recurrence
    t.recurrence_value = body.recurrence_value or ""
    t.start_date = body.start_date
    t.notify_time = body.notify_time or "09:00"
    t.active = body.active
    await session.commit()
    await session.refresh(t)
    return _template_out(t)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    t = await session.get(TaskTemplate, template_id)
    if not t:
        raise HTTPException(404, "Not found")
    await session.delete(t)
    await session.commit()
    return {"ok": True}


@router.post("/stock-watch/run")
async def stock_watch_run(request: Request) -> dict:
    """Ручной запуск проверки остатков → автозадачи."""
    from app.stock_watch import run_stock_watch

    settings = get_settings()
    bot = getattr(request.app.state, "bot", None)
    return await run_stock_watch(
        session_factory=SessionLocal,
        settings=settings,
        bot=bot,
    )


@router.post("/digest/run")
async def digest_run(
    request: Request,
    kind: str = Query("morning", pattern="^(morning|evening)$"),
) -> dict:
    """Ручная утренняя/вечерняя рассылка задач менеджерам."""
    from app.task_digest import send_task_digests

    settings = get_settings()
    bot = getattr(request.app.state, "bot", None)
    return await send_task_digests(
        session_factory=SessionLocal,
        settings=settings,
        bot=bot,
        kind=kind,
    )
