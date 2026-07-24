from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="manager")  # owner|manager
    team_group: Mapped[str] = mapped_column(String(100), default="")  # группа в «Команда»
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    assigned_tasks: Mapped[list[Task]] = relationship(
        back_populates="assignee",
        foreign_keys="Task.assignee_id",
    )
    task_links: Mapped[list[TaskAssignee]] = relationship(back_populates="employee")
    access_grants: Mapped[list[EmployeeAccess]] = relationship(
        back_populates="viewer",
        foreign_keys="EmployeeAccess.viewer_id",
        cascade="all, delete-orphan",
    )


class EmployeeAccess(Base):
    """Менеджер (viewer) может видеть задачи сотрудника (subject)."""

    __tablename__ = "employee_access"
    __table_args__ = (UniqueConstraint("viewer_id", "subject_id", name="uq_viewer_subject"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    viewer_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)

    viewer: Mapped[Employee] = relationship(
        back_populates="access_grants",
        foreign_keys=[viewer_id],
    )
    subject: Mapped[Employee] = relationship(foreign_keys=[subject_id])


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    color: Mapped[str] = mapped_column(String(20), default="#3b82f6")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tasks: Mapped[list[Task]] = relationship(back_populates="project")


class Task(Base):
    """Статусы только: todo=Новая, doing=В работе, done=Выполнено."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    articles: Mapped[str] = mapped_column(String(500), default="")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    # primary assignee (совместимость с ботом); полный список — в TaskAssignee
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="todo")  # todo|doing|done
    kind: Mapped[str] = mapped_column(String(20), default="once")  # once|weekly
    weekdays: Mapped[str] = mapped_column(String(50), default="")
    notify_time: Mapped[str] = mapped_column(String(5), default="09:00")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")  # low|normal|high
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("task_templates.id"), nullable=True)

    project: Mapped[Project | None] = relationship(back_populates="tasks")
    assignee: Mapped[Employee | None] = relationship(
        back_populates="assigned_tasks",
        foreign_keys=[assignee_id],
    )
    created_by: Mapped[Employee | None] = relationship(foreign_keys=[created_by_id])
    completed_by: Mapped[Employee | None] = relationship(foreign_keys=[completed_by_id])
    runs: Mapped[list[TaskRun]] = relationship(back_populates="task")
    assignees: Mapped[list[TaskAssignee]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )
    comments: Mapped[list[TaskComment]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskComment.created_at"
    )
    events: Mapped[list[TaskEvent]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskEvent.created_at"
    )


class TaskAssignee(Base):
    __tablename__ = "task_assignees"
    __table_args__ = (UniqueConstraint("task_id", "employee_id", name="uq_task_employee"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"))

    task: Mapped[Task] = relationship(back_populates="assignees")
    employee: Mapped[Employee] = relationship(back_populates="task_links")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    # простое вложение: имя + URL/путь (без тяжёлого storage пока)
    file_name: Mapped[str] = mapped_column(String(300), default="")
    file_url: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped[Task] = relationship(back_populates="comments")
    author: Mapped[Employee | None] = relationship(foreign_keys=[author_id])


class TaskEvent(Base):
    """Неизменяемый журнал действий по задаче."""

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(50))  # created|assigned|status|comment|due|…
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped[Task] = relationship(back_populates="events")
    actor: Mapped[Employee | None] = relationship(foreign_keys=[actor_id])


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("task_id", "due_date", name="uq_task_due"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    task: Mapped[Task] = relationship(back_populates="runs")


class TaskTemplate(Base):
    """Шаблоны повторяющихся задач."""

    __tablename__ = "task_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    # csv employee ids
    assignee_ids: Mapped[str] = mapped_column(String(500), default="")
    # daily | weekly | every_n_days | monthly | weekdays | month_days
    recurrence: Mapped[str] = mapped_column(String(30), default="daily")
    # weekdays: "1,3,5"; every_n_days: "3"; month_days: "1,15"; monthly: "1"
    recurrence_value: Mapped[str] = mapped_column(String(100), default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notify_time: Mapped[str] = mapped_column(String(5), default="09:00")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_spawned_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_code: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    nm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    sales_90d: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
