from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class EmployeeIn(BaseModel):
    telegram_id: int
    name: str
    role: str = "manager"


class EmployeeOut(BaseModel):
    id: int
    telegram_id: int
    name: str
    role: str
    active: bool

    model_config = {"from_attributes": True}


class ProjectIn(BaseModel):
    name: str
    color: str = "#3b82f6"


class ProjectOut(BaseModel):
    id: int
    name: str
    color: str
    active: bool

    model_config = {"from_attributes": True}


class TaskIn(BaseModel):
    title: str
    description: str = ""
    project_id: int | None = None
    assignee_id: int | None = None
    created_by_id: int | None = None
    status: str = "todo"
    kind: str = "once"
    weekdays: str = ""
    notify_time: str = "09:00"
    notify_now: bool = True


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    project_id: int | None = None
    assignee_id: int | None = None
    status: str | None = None
    kind: str | None = None
    weekdays: str | None = None
    notify_time: str | None = None
    position: int | None = None
    active: bool | None = None


class TaskOut(BaseModel):
    id: int
    title: str
    description: str
    project_id: int | None
    assignee_id: int | None
    created_by_id: int | None = None
    status: str
    kind: str
    weekdays: str
    notify_time: str
    active: bool
    position: int
    assignee_name: str | None = None
    project_name: str | None = None
    created_by_name: str | None = None

    model_config = {"from_attributes": True}


class BoardOut(BaseModel):
    projects: list[ProjectOut]
    employees: list[EmployeeOut]
    tasks: list[TaskOut]
    columns: list[str] = Field(default_factory=lambda: ["todo", "doing", "done"])


class TaskRunOut(BaseModel):
    id: int
    task_id: int
    due_date: date
    status: str
    title: str | None = None
    assignee_name: str | None = None
