from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class EmployeeIn(BaseModel):
    telegram_id: int
    name: str
    role: str = "manager"


class EmployeePatch(BaseModel):
    name: str | None = None
    team_group: str | None = None
    can_see_ids: list[int] | None = None
    active: bool | None = None
    actor_id: int | None = None  # кто меняет (для проверки владельца)


class TeamGroupIn(BaseModel):
    """Создать / переименовать группу и назначить участников (владелец)."""

    name: str
    employee_ids: list[int] = Field(default_factory=list)
    old_name: str | None = None  # при переименовании
    actor_id: int


class EmployeeOut(BaseModel):
    id: int
    telegram_id: int
    name: str
    role: str
    team_group: str = ""
    active: bool
    can_see_ids: list[int] = Field(default_factory=list)

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


class ArticleOut(BaseModel):
    vendor_code: str
    nm_id: int | None = None
    stock: int = 0
    sales_90d: int = 0

    model_config = {"from_attributes": True}


class AssigneeOut(BaseModel):
    id: int
    name: str


class CommentIn(BaseModel):
    body: str
    author_id: int | None = None
    file_name: str = ""
    file_url: str = ""


class CommentOut(BaseModel):
    id: int
    body: str
    author_id: int | None = None
    author_name: str | None = None
    file_name: str = ""
    file_url: str = ""
    created_at: datetime


class EventOut(BaseModel):
    id: int
    kind: str
    message: str
    actor_name: str | None = None
    created_at: datetime


class TaskIn(BaseModel):
    title: str
    description: str = ""
    articles: str = ""
    project_id: int | None = None
    assignee_id: int | None = None
    assignee_ids: list[int] = Field(default_factory=list)
    created_by_id: int | None = None
    status: str = "todo"
    kind: str = "once"
    weekdays: str = ""
    notify_time: str = "09:00"
    due_date: date | None = None
    priority: str = "normal"
    notify_now: bool = True


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    articles: str | None = None
    project_id: int | None = None
    assignee_id: int | None = None
    assignee_ids: list[int] | None = None
    status: str | None = None
    kind: str | None = None
    weekdays: str | None = None
    notify_time: str | None = None
    due_date: date | None = None
    priority: str | None = None
    position: int | None = None
    active: bool | None = None
    actor_id: int | None = None


class TaskOut(BaseModel):
    id: int
    title: str
    description: str
    articles: str = ""
    project_id: int | None
    assignee_id: int | None
    created_by_id: int | None = None
    completed_by_id: int | None = None
    status: str
    kind: str
    weekdays: str
    notify_time: str
    due_date: date | None = None
    priority: str = "normal"
    active: bool
    position: int
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    assignee_name: str | None = None
    assignees: list[AssigneeOut] = Field(default_factory=list)
    project_name: str | None = None
    created_by_name: str | None = None
    completed_by_name: str | None = None
    due_flag: str | None = None  # overdue|today|done|null
    notified: bool | None = None
    notify_error: str | None = None
    comments: list[CommentOut] = Field(default_factory=list)
    events: list[EventOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class BoardOut(BaseModel):
    projects: list[ProjectOut]
    employees: list[EmployeeOut]
    tasks: list[TaskOut]
    columns: list[str] = Field(default_factory=lambda: ["todo", "doing", "done"])


class HomeOut(BaseModel):
    new: list[TaskOut]
    doing: list[TaskOut]
    overdue: list[TaskOut]
    today: list[TaskOut]
    upcoming: list[TaskOut]


class TemplateIn(BaseModel):
    title: str
    description: str = ""
    assignee_ids: list[int] = Field(default_factory=list)
    recurrence: str = "daily"
    recurrence_value: str = ""
    start_date: date | None = None
    notify_time: str = "09:00"
    active: bool = True


class TemplateOut(BaseModel):
    id: int
    title: str
    description: str
    assignee_ids: list[int]
    recurrence: str
    recurrence_value: str
    start_date: date | None
    notify_time: str
    active: bool
    last_spawned_on: date | None = None

    model_config = {"from_attributes": True}
