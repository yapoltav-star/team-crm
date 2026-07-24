from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_session
from app.catalog import load_catalog
from app.models import Employee, Project, Task
from app.notify import notify_task_assignee
from app.schemas import (
    ArticleOut,
    BoardOut,
    EmployeeIn,
    EmployeeOut,
    EmployeePatch,
    ProjectIn,
    ProjectOut,
    TaskIn,
    TaskOut,
    TaskPatch,
)
from app.sku import enrich_task_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _task_out(task: Task, *, notified: bool | None = None, notify_error: str | None = None) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description or "",
        articles=task.articles or "",
        project_id=task.project_id,
        assignee_id=task.assignee_id,
        created_by_id=task.created_by_id,
        status=task.status,
        kind=task.kind,
        weekdays=task.weekdays or "",
        notify_time=task.notify_time,
        active=task.active,
        position=task.position,
        assignee_name=task.assignee.name if task.assignee else None,
        project_name=task.project.name if task.project else None,
        created_by_name=task.created_by.name if task.created_by else None,
        notified=notified,
        notify_error=notify_error,
    )


async def _load_task(session: AsyncSession, task_id: int) -> Task:
    return (
        await session.scalars(
            select(Task)
            .where(Task.id == task_id)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.project),
                selectinload(Task.created_by),
            )
        )
    ).one()


@router.get("/board", response_model=BoardOut)
async def board(session: AsyncSession = Depends(get_session)) -> BoardOut:
    projects = (
        await session.scalars(select(Project).where(Project.active.is_(True)).order_by(Project.id))
    ).all()
    employees = (
        await session.scalars(
            select(Employee).where(Employee.active.is_(True)).order_by(Employee.name)
        )
    ).all()
    tasks = (
        await session.scalars(
            select(Task)
            .where(Task.active.is_(True))
            .options(
                selectinload(Task.assignee),
                selectinload(Task.project),
                selectinload(Task.created_by),
            )
            .order_by(Task.position, Task.id)
        )
    ).all()
    return BoardOut(
        projects=[ProjectOut.model_validate(p) for p in projects],
        employees=[EmployeeOut.model_validate(e) for e in employees],
        tasks=[_task_out(t) for t in tasks],
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
        # не понижать владельца до менеджера при смене имени с сайта
        if int(existing.telegram_id) == int(settings.owner_telegram_id) or existing.role == "owner":
            existing.role = "owner"
        else:
            existing.role = body.role
        existing.active = True
        await session.commit()
        await session.refresh(existing)
        return EmployeeOut.model_validate(existing)
    role = body.role
    if int(body.telegram_id) == int(settings.owner_telegram_id):
        role = "owner"
    emp = Employee(telegram_id=body.telegram_id, name=body.name.strip()[:200], role=role)
    session.add(emp)
    await session.commit()
    await session.refresh(emp)
    return EmployeeOut.model_validate(emp)


@router.patch("/employees/{employee_id}", response_model=EmployeeOut)
async def patch_employee(
    employee_id: int, body: EmployeePatch, session: AsyncSession = Depends(get_session)
) -> EmployeeOut:
    emp = await session.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    if body.name is not None and body.name.strip():
        emp.name = body.name.strip()[:200]
    await session.commit()
    await session.refresh(emp)
    return EmployeeOut.model_validate(emp)


@router.post("/tasks", response_model=TaskOut)
async def create_task(
    body: TaskIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    settings = get_settings()
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
    task = Task(
        title=title,
        description=body.description,
        articles=articles,
        project_id=body.project_id,
        assignee_id=body.assignee_id,
        created_by_id=body.created_by_id,
        status=body.status,
        kind=body.kind,
        weekdays=body.weekdays,
        notify_time=body.notify_time or now_hm,
        created_at=datetime.utcnow(),
    )
    session.add(task)
    await session.commit()
    task = await _load_task(session, task.id)

    notified: bool | None = None
    notify_error: str | None = None
    if body.notify_now and body.kind == "once":
        bot = getattr(request.app.state, "bot", None)
        notified, notify_error = await notify_task_assignee(
            bot=bot,
            session=session,
            task=task,
            due=datetime.now(settings.tz).date(),
        )
        task = await _load_task(session, task.id)
    return _task_out(task, notified=notified, notify_error=notify_error)


@router.post("/tasks/{task_id}/notify", response_model=TaskOut)
async def retry_notify(
    task_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    settings = get_settings()
    task = await session.get(Task, task_id)
    if not task or not task.active:
        raise HTTPException(404, "Task not found")
    task = await _load_task(session, task_id)
    bot = getattr(request.app.state, "bot", None)
    notified, notify_error = await notify_task_assignee(
        bot=bot,
        session=session,
        task=task,
        due=datetime.now(settings.tz).date(),
    )
    task = await _load_task(session, task_id)
    return _task_out(task, notified=notified, notify_error=notify_error)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def patch_task(
    task_id: int, body: TaskPatch, session: AsyncSession = Depends(get_session)
) -> TaskOut:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(task, key, value)
    await session.commit()
    task = await _load_task(session, task_id)
    return _task_out(task)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.active = False
    await session.commit()
    return {"ok": True}
