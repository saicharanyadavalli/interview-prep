"""Pydantic models for request/response validation."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ---------- Auth ----------

class SessionRequest(BaseModel):
    """Frontend sends the Supabase access token after login."""
    access_token: str = Field(..., min_length=1)


class UserResponse(BaseModel):
    """User profile info returned to the frontend."""
    id: str
    email: str
    name: Optional[str] = None
    avatar_url: Optional[str] = None


class ProfileResponse(BaseModel):
    """Editable user profile payload."""
    id: str
    email: str
    name: str = ""
    phone: str = ""
    avatar_url: str = ""


class ProfileUpdateRequest(BaseModel):
    """Allowed profile updates from frontend."""
    name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=30)
    avatar_url: Optional[str] = Field(None, max_length=500)


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
    """Single chat turn provided by frontend."""
    role: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    """Incoming request payload for /assistant/ask."""
    interview_question: str = Field(..., min_length=1)
    user_doubt: str = Field(..., min_length=1)
    conversation_history: list[ChatMessage] = Field(default_factory=list)


class AskResponse(BaseModel):
    """Outgoing response payload for /assistant/ask."""
    answer: str


# ---------- Progress ----------

class ProgressUpdateRequest(BaseModel):
    """Update a question's progress state using is_solved/revisit. Uses qnum."""
    qnum: Optional[int] = Field(None, ge=1)
    question_id: Optional[str] = None
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
    """Update payload for a single learning-track lesson step."""
    step_no: int = Field(..., ge=1)
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
    """Update payload for a single system design lesson step."""
    step_no: int = Field(..., ge=1)
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
    """Request to add a comment for a question."""
    qnum: int | None = None
    question_id: str | None = None
    comment_text: str = Field(..., min_length=1)


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
    """Request payload for completing a lesson."""
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

