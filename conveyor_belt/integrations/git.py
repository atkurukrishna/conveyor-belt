"""Git / GitHub integration — extract PR diff and changed file list."""

from __future__ import annotations

import asyncio
import json
import re

from conveyor_belt.context import ChangedFile


async def _run(cmd: list[str], cwd: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, stdout.decode()


async def changed_files_from_diff(repo_root: str, diff_ref: str = "HEAD~1") -> list[ChangedFile]:
    """Get changed files from a local git diff."""
    rc, output = await _run(
        ["git", "diff", "--numstat", "--diff-filter=ACDMR", diff_ref],
        cwd=repo_root,
    )
    files: list[ChangedFile] = []
    for line in output.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        adds = int(parts[0]) if parts[0] != "-" else 0
        dels = int(parts[1]) if parts[1] != "-" else 0
        path = parts[2]
        files.append(
            ChangedFile(path=path, status="modified", additions=adds, deletions=dels)
        )

    # Grab the actual patch content for each file
    rc, patch_output = await _run(
        ["git", "diff", "-U3", diff_ref],
        cwd=repo_root,
    )
    _attach_patches(files, patch_output)
    return files


async def changed_files_from_pr(repo_root: str, pr_number: int) -> list[ChangedFile]:
    """Get changed files from a GitHub PR using `gh` CLI."""
    rc, output = await _run(
        ["gh", "pr", "diff", str(pr_number), "--name-only"],
        cwd=repo_root,
    )
    paths = [p.strip() for p in output.strip().splitlines() if p.strip()]

    rc, stat_out = await _run(
        ["gh", "pr", "view", str(pr_number), "--json", "files"],
        cwd=repo_root,
    )
    file_stats: dict[str, dict] = {}
    try:
        data = json.loads(stat_out)
        for f in data.get("files", []):
            file_stats[f["path"]] = f
    except (json.JSONDecodeError, KeyError):
        pass

    files: list[ChangedFile] = []
    for p in paths:
        stats = file_stats.get(p, {})
        files.append(
            ChangedFile(
                path=p,
                status=_gh_status(stats.get("status", "modified")),
                additions=stats.get("additions", 0),
                deletions=stats.get("deletions", 0),
            )
        )

    # Get full diff patch
    rc, patch_output = await _run(
        ["gh", "pr", "diff", str(pr_number)],
        cwd=repo_root,
    )
    _attach_patches(files, patch_output)
    return files


async def get_pr_body(repo_root: str, pr_number: int) -> tuple[str, str]:
    """Return (title, body) for a PR."""
    rc, output = await _run(
        ["gh", "pr", "view", str(pr_number), "--json", "title,body"],
        cwd=repo_root,
    )
    try:
        data = json.loads(output)
        return data.get("title", ""), data.get("body", "")
    except json.JSONDecodeError:
        return "", ""


def parse_issue_tags(text: str) -> list[str]:
    """Extract Linear issue tags like [ENG-123] from PR title/body."""
    return re.findall(r"\[([A-Z]+-\d+)\]", text)


async def changed_files_from_staged(repo_root: str) -> list[ChangedFile]:
    """Get changed files from the staging area (uncommitted changes)."""
    rc, output = await _run(
        ["git", "diff", "--numstat", "--diff-filter=ACDMR", "--cached"],
        cwd=repo_root,
    )
    # If nothing staged, fall back to unstaged working tree changes
    if not output.strip():
        rc, output = await _run(
            ["git", "diff", "--numstat", "--diff-filter=ACDMR"],
            cwd=repo_root,
        )
    files: list[ChangedFile] = []
    for line in output.strip().splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        adds = int(parts[0]) if parts[0] != "-" else 0
        dels = int(parts[1]) if parts[1] != "-" else 0
        path = parts[2]
        files.append(
            ChangedFile(path=path, status="modified", additions=adds, deletions=dels)
        )
    return files


# ── helpers ────────────────────────────────────────────────────────────


def _gh_status(status: str) -> str:
    return {
        "added": "added",
        "removed": "deleted",
        "modified": "modified",
        "renamed": "renamed",
    }.get(status, "modified")


def _attach_patches(files: list[ChangedFile], full_patch: str) -> None:
    """Attach per-file patch hunks from a unified diff."""
    current_file: str | None = None
    current_patch_lines: list[str] = []

    file_map = {f.path: f for f in files}

    for line in full_patch.splitlines(keepends=True):
        if line.startswith("diff --git"):
            if current_file and current_file in file_map:
                file_map[current_file].patch = "".join(current_patch_lines)
            match = re.search(r" b/(.+)$", line)
            current_file = match.group(1) if match else None
            current_patch_lines = [line]
        else:
            current_patch_lines.append(line)

    if current_file and current_file in file_map:
        file_map[current_file].patch = "".join(current_patch_lines)
