"""Pydantic models for request/response validation.

SECURITY POLICY
---------------
* All *Request* models use ``model_config = ConfigDict(extra='forbid')``.
  This means any field not explicitly declared causes a 422 Unprocessable
  Entity — no silent pass-through of attacker-controlled keys.
* Response models use ``extra='ignore'`` so raw DB rows can be passed in
  without leaking internal columns.
* All user-supplied strings are length-bounded and pattern-validated before
  they reach any service layer or ORM call.
* Protected server-side fields (user_id, role, is_premium, credits,
  subscription_status, updated_at) are NEVER present on any request model.
"""

from __future__ import annotations

import re
from typing import Annotated, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------- Auth ----------

class SessionRequest(BaseModel):
    """Frontend sends the Supabase access token after login."""
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(..., min_length=10, max_length=2048)


class ResolveUsernameRequest(BaseModel):
    """Payload to look up an email associated with a username."""
    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=1, max_length=50)


class ResolveUsernameResponse(BaseModel):
    """Response returning resolved email or found flag."""
    email: Optional[str] = None
    exists: bool = False


class UserResponse(BaseModel):
    """User profile info returned to the frontend."""
    id: str
    email: str
    username: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class ProfileResponse(BaseModel):
    """Editable user profile payload."""
    id: str
    email: str
    username: Optional[str] = None
    name: str = ""
    phone: str = ""
    avatar_url: str = ""


class ProfileUpdateRequest(BaseModel):
    """Allowed profile updates from frontend.

    SECURITY: extra='forbid' prevents injection of protected fields such as
    id, email, role, is_premium, subscription_status, credits, updated_at.
    """
    model_config = ConfigDict(extra="forbid")

    # Only the four whitelisted user-editable fields are accepted.
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=15)
    avatar_url: Optional[str] = Field(None, max_length=512)

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z0-9_]{3,50}", v):
            raise ValueError(
                "Username must be 3–50 characters and contain only lowercase "
                "letters, digits, or underscores."
            )
        return v

    @field_validator("name")
    @classmethod
    def name_safe_chars(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v and not re.fullmatch(r"[A-Za-z0-9 '_\-]{1,120}", v):
            raise ValueError("Name contains invalid characters.")
        return v

    @field_validator("phone")
    @classmethod
    def phone_digits_only(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v and not re.fullmatch(r"\d{7,15}", v):
            raise ValueError("Phone must be 7–15 digits.")
        return v

    @field_validator("avatar_url")
    @classmethod
    def avatar_url_safe(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if v and not (v.startswith("https://") or v.startswith("data:image/")):
            raise ValueError(
                "avatar_url must start with 'https://' or be a data: image URI."
            )
        return v


# ---------- Questions ----------

class QuestionResponse(BaseModel):
    """A single interview question returned to the frontend."""
    qnum: int
    question_id: str
    problem_name: str
    difficulty: str
    problem_url: str = ""
    statement_text: str = ""
    constraints_text: str = ""
    examples: list = Field(default_factory=list)
    topic_tags: list = Field(default_factory=list)
    company_tags: list = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)


class CompaniesResponse(BaseModel):
    """List of available companies."""
    companies: list[str]


# ---------- AI Assistant ----------

class ChatMessage(BaseModel):
    """Single chat turn provided by frontend.

    SECURITY: role is restricted to a known safe set so callers cannot
    inject arbitrary role strings into the AI prompt context.
    """
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., min_length=1, max_length=20)
    content: str = Field(..., min_length=1, max_length=8000)

    @field_validator("role")
    @classmethod
    def role_allowlist(cls, v: str) -> str:
        allowed = {"user", "assistant", "model"}
        if v.strip().lower() not in allowed:
            raise ValueError(f"role must be one of {allowed}")
        return v.strip().lower()


class AskRequest(BaseModel):
    """Incoming request payload for /assistant/ask.

    SECURITY: extra='forbid' + length caps prevent prompt-injection via
    oversized or unexpected fields.
    """
    model_config = ConfigDict(extra="forbid")

    interview_question: str = Field(..., min_length=1, max_length=4000)
    user_doubt: str = Field(..., min_length=1, max_length=2000)
    conversation_history: list[ChatMessage] = Field(default_factory=list, max_length=50)


class AskResponse(BaseModel):
    """Outgoing response payload for /assistant/ask."""
    answer: str


# ---------- Progress ----------

class ProgressUpdateRequest(BaseModel):
    """Update a question's progress state using is_solved/revisit. Uses qnum.

    SECURITY: extra='forbid' prevents injection of protected fields such as
    user_id, updated_at, or score overrides. The server always stamps user_id
    from the verified JWT — never from this payload.
    """
    model_config = ConfigDict(extra="forbid")

    # Callers must provide at most ONE identifier; the server resolves qnum.
    qnum: Optional[int] = Field(None, ge=1, le=100_000)
    question_id: Optional[str] = Field(None, max_length=128)
    is_solved: Optional[bool] = None
    revisit: Optional[bool] = None


class ProgressStats(BaseModel):
    """Aggregated progress stats for a user."""
    total_attempted: int = 0
    solved_count: int = 0
    unsolved_count: int = 0
    revisit_count: int = 0
    easy_attempted: int = 0
    medium_attempted: int = 0
    hard_attempted: int = 0
    easy_solved: int = 0
    medium_solved: int = 0
    hard_solved: int = 0
    total_questions: int = 0
    solved_total_questions: int = 0
    easy_total_questions: int = 0
    medium_total_questions: int = 0
    hard_total_questions: int = 0
    easy_solved_total_questions: int = 0
    medium_solved_total_questions: int = 0
    hard_solved_total_questions: int = 0


class TopicProgressEntry(BaseModel):
    """Per-topic totals and solved counters across the question bank."""
    topic_key: str
    topic: str
    total_questions: int = 0
    solved_questions: int = 0
    easy_total_questions: int = 0
    medium_total_questions: int = 0
    hard_total_questions: int = 0
    easy_solved_questions: int = 0
    medium_solved_questions: int = 0
    hard_solved_questions: int = 0


class ProgressEntry(BaseModel):
    """Single progress record with boolean solved/revisit state."""
    qnum: int
    question_id: str = ""
    question_title: str = ""
    company: str = ""
    difficulty: str = ""
    is_solved: bool = False
    revisit: bool = False
    updated_at: str = ""


class UserProgressResponse(BaseModel):
    """Full progress response — contains aggregate stats and recent entries."""
    stats: ProgressStats
    recent: list[ProgressEntry] = Field(default_factory=list)
    topic_breakdown: list[TopicProgressEntry] = Field(default_factory=list)


class ProgressStatusResponse(BaseModel):
    """Progress state for one question, or null/false when unset."""
    qnum: int
    is_solved: Optional[bool] = None
    revisit: bool = False


class LearningTrackMeta(BaseModel):
    """Learning-track metadata consumed by frontend dashboards/pages."""
    track_id: str
    display_name: str
    step_count: int = 0
    qnum_base: int = 0
    assets_slug: str = ""


class LearningTrackStepProgress(BaseModel):
    """Progress state for one learning-track lesson step."""
    step_no: int = Field(..., ge=1)
    title: str = ""
    completed: bool = False
    updated_at: Optional[str] = None


class LearningTrackProgressResponse(BaseModel):
    """Learning-track summary and per-step statuses."""
    track_id: str
    total_steps: int = 0
    completed_steps: int = 0
    completion_percent: int = 0
    steps: list[LearningTrackStepProgress] = Field(default_factory=list)


class LearningTrackProgressUpdateRequest(BaseModel):
    """Update payload for a single learning-track lesson step.

    SECURITY: extra='forbid' prevents injection of user_id, track_id or
    timestamps. The server derives those from JWT and URL params.
    """
    model_config = ConfigDict(extra="forbid")

    step_no: int = Field(..., ge=1, le=10_000)
    completed: bool


class SystemDesignStepProgress(BaseModel):
    """Progress state for one system design lesson step."""
    step_no: int = Field(..., ge=1)
    title: str = ""
    completed: bool = False
    updated_at: Optional[str] = None


class SystemDesignProgressResponse(BaseModel):
    """System design learning-track summary and per-step statuses."""
    total_steps: int = 0
    completed_steps: int = 0
    completion_percent: int = 0
    steps: list[SystemDesignStepProgress] = Field(default_factory=list)


class SystemDesignProgressUpdateRequest(BaseModel):
    """Update payload for a single system design lesson step.

    SECURITY: Mirrors LearningTrackProgressUpdateRequest constraints.
    """
    model_config = ConfigDict(extra="forbid")

    step_no: int = Field(..., ge=1, le=10_000)
    completed: bool


class LearningTracksResponse(BaseModel):
    """All available learning-track metadata entries."""
    tracks: list[LearningTrackMeta] = Field(default_factory=list)


# ---------- Revisit ----------

class RevisitEntry(BaseModel):
    """A question in the revisit queue — just qnum."""
    qnum: int
    question_id: str = ""
    question_title: str = ""
    company: str = ""
    difficulty: str = ""
    added_at: str = ""


class RevisitResponse(BaseModel):
    """User's revisit queue."""
    items: list[RevisitEntry] = Field(default_factory=list)


# ---------- Comments ----------

class CommentRequest(BaseModel):
    """Request to add a comment for a question.

    SECURITY: extra='forbid' prevents injection of user_id, created_at, or id.
    comment_text is capped to prevent storage abuse.
    """
    model_config = ConfigDict(extra="forbid")

    qnum: Optional[int] = Field(None, ge=1, le=100_000)
    question_id: Optional[str] = Field(None, max_length=128)
    comment_text: str = Field(..., min_length=1, max_length=10_000)


class CommentEntry(BaseModel):
    """A single comment record."""
    id: str
    qnum: int
    comment_text: str
    created_at: str = ""


class CommentsResponse(BaseModel):
    """All comments for a question."""
    comments: list[CommentEntry] = Field(default_factory=list)


class UserCommentsMapResponse(BaseModel):
    """Map of qnum -> list of comment texts (for bulk checking)."""
    comments_map: dict[int, int] = Field(default_factory=dict)


# ---------- Practice History ----------

class PracticeHistoryEntry(BaseModel):
    """A single practice session record."""
    qnum: int
    practiced_at: str = ""


# ---------- Courses ----------

class CourseSummary(BaseModel):
    """Summary representation of a course."""
    id: str
    slug: str
    title: str
    description: str
    total_lessons: int = 0
    completed_lessons: int = 0
    progress_percentage: float = 0.0


class CourseLessonSummary(BaseModel):
    """Minimal lesson summary inside course detail view."""
    id: str
    slug: str
    title: str
    order_index: int
    completed: bool = False


class CourseDetailResponse(BaseModel):
    """Full course details including ordered lesson list."""
    id: str
    slug: str
    title: str
    description: str
    total_lessons: int = 0
    completed_lessons: int = 0
    progress_percentage: float = 0.0
    lessons: list[CourseLessonSummary] = Field(default_factory=list)


class LessonDetailResponse(BaseModel):
    """Full lesson detail view."""
    id: str
    course_slug: str
    slug: str
    title: str
    order_index: int
    content_markdown: str
    tasks: list[str] = Field(default_factory=list)
    completed: bool = False
    prev_lesson_slug: Optional[str] = None
    next_lesson_slug: Optional[str] = None


class LessonCompleteRequest(BaseModel):
    """Request payload for completing a lesson.

    SECURITY: extra='forbid' prevents injection of user_id, lesson_id,
    completed_at, or course_slug — all derived server-side.
    """
    model_config = ConfigDict(extra="forbid")

    completed: bool = True


class CourseProgressInfo(BaseModel):
    """Course progress summary embedded in completion response."""
    completed_lessons: int = 0
    total_lessons: int = 0
    progress_percentage: float = 0.0


class LessonCompleteResponse(BaseModel):
    """Response returned when a lesson is marked completed."""
    success: bool = True
    course_slug: str
    lesson_slug: str
    completed: bool
    completed_at: str
    course_progress: CourseProgressInfo


class CourseProgressResponse(BaseModel):
    """Course progress response for authenticated user."""
    course_slug: str
    completed_lessons: int = 0
    total_lessons: int = 0
    progress_percentage: float = 0.0
    completed_lesson_slugs: list[str] = Field(default_factory=list)


class SeedTableDefinition(BaseModel):
    """Schema and initial seed rows for a client-side sql.js table."""
    name: str
    schema_sql: str
    insert_sql: str
    columns: list[str] = Field(default_factory=list)
    rows: list[list] = Field(default_factory=list)


class SeedTablesResponse(BaseModel):
    """Collection of SQL seed tables for sql.js execution."""
    course_slug: str
    tables: list[SeedTableDefinition] = Field(default_factory=list)

