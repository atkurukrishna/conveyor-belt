"""StationContext — data bag passed to every station."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChangedFile(BaseModel):
    """A file touched in the PR."""

    path: str
    status: str = "modified"  # added | modified | deleted | renamed
    additions: int = 0
    deletions: int = 0
    patch: str = ""


class LinearIssue(BaseModel):
    """Minimal representation of a Linear issue / epic."""

    identifier: str  # e.g. "ENG-123"
    title: str
    description: str = ""
    labels: list[str] = Field(default_factory=list)
    state: str = ""
    sub_issues: list[LinearIssue] = Field(default_factory=list)


class StationContext(BaseModel):
    """Everything a station needs to do its job."""

    repo_root: str
    pr_number: int | None = None
    pr_title: str = ""
    pr_body: str = ""
    base_ref: str = "main"
    head_ref: str = "HEAD"
    languages: list[str] = Field(default_factory=list)
    changed_files: list[ChangedFile] = Field(default_factory=list)
    linear_issues: list[LinearIssue] = Field(default_factory=list)
    historical_issues: list[LinearIssue] = Field(default_factory=list)
