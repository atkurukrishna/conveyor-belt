"""Tests for agent layer — base agent, feature, regression, security agents."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conveyor_belt.agents.base import BaseAgent, _build_llm
from conveyor_belt.agents.feature_agent import (
    FeatureAgent,
)
from conveyor_belt.agents.feature_agent import (
    _parse_json_response as parse_feature,
)
from conveyor_belt.agents.regression_agent import (
    RegressionAgent,
)
from conveyor_belt.agents.regression_agent import (
    _parse_json_response as parse_regression,
)
from conveyor_belt.agents.security_agent import (
    SecurityAgent,
)
from conveyor_belt.agents.security_agent import (
    _parse_json_response as parse_security,
)
from conveyor_belt.config import AgentConfig, LLMProviderConfig
from conveyor_belt.context import LinearIssue


@pytest.fixture
def agent_config() -> AgentConfig:
    return AgentConfig(
        primary=LLMProviderConfig(provider="anthropic", model="test-model"),
        fallback=LLMProviderConfig(provider="google", model="test-fallback"),
    )


# ── _build_llm ─────────────────────────────────────────────────────────


class TestBuildLLM:
    def test_anthropic_provider(self):
        with patch(
            "langchain_anthropic.ChatAnthropic"
        ) as mock_cls:
            _build_llm("anthropic", "claude-test")
            mock_cls.assert_called_once_with(
                model="claude-test", max_tokens=4096, temperature=0
            )

    def test_google_provider(self):
        with patch(
            "langchain_google_genai.ChatGoogleGenerativeAI"
        ) as mock_cls:
            _build_llm("google", "gemini-test")
            mock_cls.assert_called_once_with(
                model="gemini-test", max_output_tokens=4096, temperature=0
            )

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            _build_llm("openai", "gpt-4")


# ── BaseAgent ──────────────────────────────────────────────────────────


class TestBaseAgent:
    @pytest.mark.asyncio
    async def test_invoke_uses_primary(self, agent_config):
        agent = BaseAgent(agent_config, system_prompt="You are helpful.")
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="primary response")
        )
        agent._primary = mock_llm

        result = await agent.invoke("hello")
        assert result == "primary response"
        mock_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_falls_back_on_primary_failure(self, agent_config):
        agent = BaseAgent(agent_config, system_prompt="test")
        mock_primary = AsyncMock()
        mock_primary.ainvoke = AsyncMock(side_effect=Exception("rate limit"))
        mock_fallback = AsyncMock()
        mock_fallback.ainvoke = AsyncMock(
            return_value=MagicMock(content="fallback response")
        )
        agent._primary = mock_primary
        agent._fallback = mock_fallback

        result = await agent.invoke("hello")
        assert result == "fallback response"

    @pytest.mark.asyncio
    async def test_invoke_raises_when_both_fail(self, agent_config):
        agent = BaseAgent(agent_config)
        mock_primary = AsyncMock()
        mock_primary.ainvoke = AsyncMock(side_effect=Exception("fail1"))
        mock_fallback = AsyncMock()
        mock_fallback.ainvoke = AsyncMock(side_effect=Exception("fail2"))
        agent._primary = mock_primary
        agent._fallback = mock_fallback

        with pytest.raises(RuntimeError, match="Both LLM providers failed"):
            await agent.invoke("hello")

    def test_system_prompt_included_in_messages(self, agent_config):
        agent = BaseAgent(agent_config, system_prompt="Be concise.")
        assert agent.system_prompt == "Be concise."

    def test_lazy_llm_init(self, agent_config):
        agent = BaseAgent(agent_config)
        assert agent._primary is None
        assert agent._fallback is None


# ── Feature agent parser ───────────────────────────────────────────────


class TestFeatureAgentParser:
    def test_parses_clean_json(self):
        raw = json.dumps({
            "acceptance_criteria": [
                {"id": "AC-1", "description": "Login", "covered": True}
            ],
            "test_cases": [{"name": "test_login", "language": "python"}],
            "coverage_summary": "1 of 1 AC covered",
        })
        result = parse_feature(raw)
        assert len(result["acceptance_criteria"]) == 1
        assert result["coverage_summary"] == "1 of 1 AC covered"

    def test_parses_markdown_fenced(self):
        inner = json.dumps({
            "acceptance_criteria": [],
            "test_cases": [],
            "coverage_summary": "0 of 0",
        })
        raw = f"Here:\n```json\n{inner}\n```\nDone."
        result = parse_feature(raw)
        assert result["coverage_summary"] == "0 of 0"

    def test_handles_invalid_json(self):
        result = parse_feature("Not JSON")
        assert result["test_cases"] == []
        assert "Failed to parse" in result["coverage_summary"]


# ── Regression agent parser ────────────────────────────────────────────


class TestRegressionAgentParser:
    def test_parses_risk_score(self):
        raw = json.dumps({
            "at_risk_requirements": [
                {"identifier": "ENG-1", "title": "Auth", "risk_reason": "changed"}
            ],
            "regression_tests": [],
            "risk_score": 55,
            "risk_summary": "Medium risk",
        })
        result = parse_regression(raw)
        assert result["risk_score"] == 55
        assert len(result["at_risk_requirements"]) == 1

    def test_handles_invalid_json(self):
        result = parse_regression("broken")
        assert result["risk_score"] == 0
        assert "Failed to parse" in result["risk_summary"]


# ── Security agent parser ─────────────────────────────────────────────


class TestSecurityAgentParser:
    def test_parses_findings(self):
        raw = json.dumps({
            "findings": [{
                "rule": "hardcoded-secret",
                "cwe_id": "CWE-798",
                "severity": "high",
                "file_path": "config.go",
                "line": 15,
                "message": "Hardcoded password",
                "remediation": "Use env vars",
            }],
            "summary": "1 issue",
        })
        result = parse_security(raw)
        assert len(result["findings"]) == 1
        assert result["findings"][0]["cwe_id"] == "CWE-798"

    def test_clean_diff(self):
        raw = json.dumps({"findings": [], "summary": "No issues"})
        result = parse_security(raw)
        assert result["findings"] == []

    def test_handles_invalid_json(self):
        result = parse_security("nope")
        assert result["findings"] == []
        assert "Failed to parse" in result["summary"]


# ── FeatureAgent.generate_test_cases ───────────────────────────────────


class TestFeatureAgentGenerate:
    @pytest.mark.asyncio
    async def test_generates_from_issues(self, agent_config):
        agent = FeatureAgent(agent_config)
        mock_response = json.dumps({
            "acceptance_criteria": [
                {"id": "AC-1", "description": "Works", "covered": True}
            ],
            "test_cases": [{"name": "test_it", "language": "go"}],
            "coverage_summary": "1/1",
        })
        with patch.object(
            agent, "invoke", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await agent.generate_test_cases(
                issues=[LinearIssue(
                    identifier="ENG-1",
                    title="Feature",
                    description="Do the thing",
                )],
                diff_text="+ new code",
                languages=["go"],
            )
        assert len(result["test_cases"]) == 1


# ── RegressionAgent.generate_regression_tests ──────────────────────────


class TestRegressionAgentGenerate:
    @pytest.mark.asyncio
    async def test_generates_from_history(self, agent_config):
        agent = RegressionAgent(agent_config)
        mock_response = json.dumps({
            "at_risk_requirements": [],
            "regression_tests": [],
            "risk_score": 10,
            "risk_summary": "Low",
        })
        with patch.object(
            agent, "invoke", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await agent.generate_regression_tests(
                historical_issues=[LinearIssue(
                    identifier="ENG-2", title="Old feature", description="x"
                )],
                diff_text="+ change",
                changed_files=["main.go"],
                languages=["go"],
            )
        assert result["risk_score"] == 10


# ── SecurityAgent.analyze_diff ─────────────────────────────────────────


class TestSecurityAgentAnalyze:
    @pytest.mark.asyncio
    async def test_analyzes_diff(self, agent_config):
        agent = SecurityAgent(agent_config)
        mock_response = json.dumps({
            "findings": [{
                "rule": "sqli",
                "severity": "high",
                "message": "SQL injection",
            }],
            "summary": "1 issue",
        })
        with patch.object(
            agent, "invoke", new_callable=AsyncMock, return_value=mock_response
        ):
            result = await agent.analyze_diff("+ query(input)", ["python"])
        assert len(result["findings"]) == 1
