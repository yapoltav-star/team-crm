from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_session
from app.models import Employee, Project, Task, TaskRun
from app.schemas import (
    BoardOut,
    EmployeeIn,
    EmployeeOut,
    ProjectIn,
    ProjectOut,
    TaskIn,
    TaskOut,
    TaskPatch,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description or "",
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
    )


async def _ensure_run(session: AsyncSession, task_id: int, due: date) -> TaskRun:
    existing = await session.scalar(
        select(TaskRun).where(TaskRun.task_id == task_id, TaskRun.due_date == due)
    )
    if existing:
        return existing
    run = TaskRun(task_id=task_id, due_date=due, status="pending")
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def _notify_assignee(request: Request, session: AsyncSession, task: Task) -> None:
    bot = getattr(request.app.state, "bot", None)
    if not bot or not task.assignee:
        return
    settings = get_settings()
    due = datetime.now(settings.tz).date()
    run = await _ensure_run(session, task.id, due)
    author = task.created_by.name if task.created_by else "кто-то"
    text = (
        f"📋 Новая задача от <b>{author}</b>\n"
        f"<b>{task.title}</b>\n\n"
        "Жми «Сделано», когда выполнишь."
    )
    try:
        from app.bot import done_kb

        await bot.send_message(
            task.assignee.telegram_id,
            text,
            reply_markup=done_kb(run.id),
            parse_mode="HTML",
        )
        run.notified_at = datetime.utcnow()
        await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("web notify failed task=%s", task.id)


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
    existing = await session.scalar(select(Employee).where(Employee.telegram_id == body.telegram_id))
    if existing:
        existing.name = body.name
        existing.role = body.role
        existing.active = True
        await session.commit()
        await session.refresh(existing)
        return EmployeeOut.model_validate(existing)
    emp = Employee(telegram_id=body.telegram_id, name=body.name, role=body.role)
    session.add(emp)
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
    task = Task(
        title=body.title,
        description=body.description,
        project_id=body.project_id,
        assignee_id=body.assignee_id,
        created_by_id=body.created_by_id,
        status=body.status,
        kind=body.kind,
        weekdays=body.weekdays,
        notify_time=body.notify_time or datetime.now(settings.tz).strftime("%H:%M"),
        created_at=datetime.utcnow(),
    )
    session.add(task)
    await session.commit()
    task = (
        await session.scalars(
            select(Task)
            .where(Task.id == task.id)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.project),
                selectinload(Task.created_by),
            )
        )
    ).one()
    if body.notify_now and body.kind == "once":
        await _notify_assignee(request, session, task)
        task = (
            await session.scalars(
                select(Task)
                .where(Task.id == task.id)
                .options(
                    selectinload(Task.assignee),
                    selectinload(Task.project),
                    selectinload(Task.created_by),
                )
            )
        ).one()
    return _task_out(task)


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
    task = (
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
    return _task_out(task)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    task.active = False
    await session.commit()
    return {"ok": True}
