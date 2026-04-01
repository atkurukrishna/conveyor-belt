"""Linear API integration — fetch issues, epics, and PRDs via GraphQL."""

from __future__ import annotations

import os

import httpx

from conveyor_belt.context import LinearIssue

LINEAR_API_URL = "https://api.linear.app/graphql"


def _get_api_key() -> str:
    key = os.environ.get("LINEAR_API_KEY", "")
    if not key:
        raise OSError(
            "LINEAR_API_KEY environment variable is not set. "
            "Create one at https://linear.app/settings/api"
        )
    return key


async def _query(graphql: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against Linear's API."""
    api_key = _get_api_key()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            LINEAR_API_URL,
            json={"query": graphql, "variables": variables or {}},
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            raise RuntimeError(f"Linear API errors: {data['errors']}")
        return data.get("data", {})


# ── Public helpers ─────────────────────────────────────────────────────


async def fetch_issue(identifier: str) -> LinearIssue:
    """Fetch a single Linear issue by its identifier (e.g. 'ENG-123')."""
    data = await _query(
        """
        query IssueByIdentifier($id: String!) {
          issueSearch(filter: { identifier: { eq: $id } }, first: 1) {
            nodes {
              identifier
              title
              description
              state { name }
              labels { nodes { name } }
              children { nodes { identifier title description state { name } } }
            }
          }
        }
        """,
        {"id": identifier},
    )
    nodes = data.get("issueSearch", {}).get("nodes", [])
    if not nodes:
        raise ValueError(f"Linear issue {identifier} not found")
    return _to_linear_issue(nodes[0])


async def fetch_issues(identifiers: list[str]) -> list[LinearIssue]:
    """Fetch multiple issues by identifier."""
    results: list[LinearIssue] = []
    for ident in identifiers:
        try:
            issue = await fetch_issue(ident)
            results.append(issue)
        except (ValueError, RuntimeError):
            continue
    return results


async def fetch_team_issues(
    team_key: str,
    limit: int = 20,
    states: list[str] | None = None,
) -> list[LinearIssue]:
    """Fetch recent issues for a team (for regression lookback)."""
    state_filter = ""
    if states:
        names = ", ".join(f'"{s}"' for s in states)
        state_filter = f', state: {{ name: {{ in: [{names}] }} }}'

    data = await _query(
        f"""
        query TeamIssues($teamKey: String!, $limit: Int!) {{
          issues(
            filter: {{ team: {{ key: {{ eq: $teamKey }} }} {state_filter} }}
            first: $limit
            orderBy: updatedAt
          ) {{
            nodes {{
              identifier
              title
              description
              state {{ name }}
              labels {{ nodes {{ name }} }}
              children {{ nodes {{ identifier title description state {{ name }} }} }}
            }}
          }}
        }}
        """,
        {"teamKey": team_key, "limit": limit},
    )
    return [
        _to_linear_issue(node)
        for node in data.get("issues", {}).get("nodes", [])
    ]


# ── Mapping ────────────────────────────────────────────────────────────


def _to_linear_issue(raw: dict) -> LinearIssue:
    children = [
        LinearIssue(
            identifier=c.get("identifier", ""),
            title=c.get("title", ""),
            description=c.get("description", ""),
            state=c.get("state", {}).get("name", ""),
        )
        for c in raw.get("children", {}).get("nodes", [])
    ]
    return LinearIssue(
        identifier=raw.get("identifier", ""),
        title=raw.get("title", ""),
        description=raw.get("description", ""),
        state=raw.get("state", {}).get("name", ""),
        labels=[
            label.get("name", "") for label in raw.get("labels", {}).get("nodes", [])
        ],
        sub_issues=children,
    )
