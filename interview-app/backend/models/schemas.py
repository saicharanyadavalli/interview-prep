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


class ProgressStatusResponse(BaseModel):
    """Progress state for one question, or null/false when unset."""
    qnum: int
    is_solved: Optional[bool] = None
    revisit: bool = False


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
    qnum: int
    question_id: str
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
