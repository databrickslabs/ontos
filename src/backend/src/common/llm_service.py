"""
LLM Service with Two-Phased Security Verification

This service provides a secure interface to Databricks-hosted LLM endpoints with:
1. Phase 1: Security check for injection attempts and malicious content
2. Phase 2: Content analysis with configurable system prompt

All interactions use the OpenAI SDK with Databricks endpoints.
"""

from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from src.common.config import Settings, get_settings
from src.common.llm_content import block_types, coerce_message_text
from src.common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMAnalysisResult:
    """Result from LLM analysis with security metadata."""
    success: bool
    content: str
    phase1_passed: bool  # True if security check passed
    render_as_markdown: bool  # True if safe to render as markdown (phase1 passed)
    llm_model_used: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


class LLMService:
    """Service for secure LLM interactions with two-phased verification."""

    def __init__(self, settings: Settings):
        """
        Initialize LLM service.

        Args:
            settings: Application settings with LLM configuration
        """
        self.settings = settings

    def _get_openai_client(self, user_token: Optional[str] = None):
        """Create OpenAI client via the shared factory.

        Args:
            user_token: Per-user access token from request header (Databricks Apps context)

        Returns:
            Configured OpenAI client instance
        """
        from src.common.llm_client import create_openai_client

        return create_openai_client(self.settings, user_token=user_token)

    def is_enabled(self) -> bool:
        """Check if LLM functionality is enabled."""
        return self.settings.LLM_ENABLED

    def get_endpoint(self) -> Optional[str]:
        """Get the configured LLM endpoint."""
        endpoint = self.settings.LLM_ENDPOINT
        if not endpoint:
            logger.warning("No LLM endpoint configured (LLM_ENDPOINT)")
        return endpoint

    def _call_llm(self, messages: list[Dict[str, str]], max_tokens: int = 1024, user_token: Optional[str] = None) -> Optional[str]:
        """
        Internal method to call LLM endpoint via OpenAI SDK.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Maximum tokens in response
            user_token: Per-user access token (for Databricks Apps)

        Returns:
            Response content string or None on failure
        """
        endpoint = self.get_endpoint()
        if not endpoint:
            logger.error("Cannot call LLM: No endpoint configured")
            return None

        try:
            client = self._get_openai_client(user_token=user_token)

            response = client.chat.completions.create(
                model=endpoint,
                messages=messages,
                max_tokens=max_tokens
            )

            # Extract content from OpenAI response
            raw_content = None
            finish_reason = None
            if response.choices and len(response.choices) > 0:
                choice = response.choices[0]
                raw_content = choice.message.content
                finish_reason = getattr(choice, "finish_reason", None)
                # Reasoning models return a block list; keep only the text
                # blocks so an all-reasoning response counts as "no content".
                content = coerce_message_text(raw_content).strip()
                if content:
                    return content

            logger.warning(
                "LLM returned no content in response (finish_reason=%s, block types: %s)",
                finish_reason,
                block_types(raw_content),
            )
            return None

        except Exception as e:
            logger.error(f"Error calling LLM endpoint {endpoint}: {e}", exc_info=True)
            return None

    def _phase1_security_check(self, content: str, user_token: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Phase 1: Security check for injection attempts and malicious content.

        Args:
            content: User-provided content to analyze
            user_token: Per-user access token (for Databricks Apps)

        Returns:
            Tuple of (passed: bool, reason: Optional[str])
        """
        logger.info("Running Phase 1: Security injection check")

        messages = [
            {"role": "system", "content": self.settings.LLM_INJECTION_CHECK_PROMPT},
            {"role": "user", "content": content}
        ]

        response = self._call_llm(messages, max_tokens=256, user_token=user_token)

        if response is None:
            logger.error("Phase 1 security check failed: No response from LLM")
            return False, "Security check failed: Unable to verify content safety"

        # Check if response indicates content is safe
        response_upper = response.upper()
        if "SAFE" in response_upper and "UNSAFE" not in response_upper:
            logger.info("Phase 1 PASSED: Content deemed safe")
            return True, None
        else:
            # Extract reason if available
            reason = response if "UNSAFE" in response_upper else "Content flagged as potentially unsafe"
            logger.warning(f"Phase 1 FAILED: {reason}")
            return False, reason

    def _phase2_content_analysis(self, content: str, user_token: Optional[str] = None) -> Optional[str]:
        """
        Phase 2: Content analysis with configurable system prompt.

        Args:
            content: Content to analyze (already passed security check)
            user_token: Per-user access token (for Databricks Apps)

        Returns:
            Analysis result or None on failure
        """
        logger.info("Running Phase 2: Content analysis")

        # Use configured system prompt or fallback to a default
        system_prompt = self.settings.LLM_SYSTEM_PROMPT or (
            "You are a Data Steward tasked with reviewing metadata, data, and SQL/Python code to check if "
            "any sensitive information is used. These include PII data, like names, addresses, age, "
            "social security numbers, credit card numbers etc. Look at the provided text and identify "
            "insecure coding or sensitive data and return a summary."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ]

        response = self._call_llm(messages, max_tokens=2048, user_token=user_token)

        if response:
            logger.info("Phase 2 COMPLETED: Content analysis successful")
        else:
            logger.error("Phase 2 FAILED: No response from LLM")

        return response

    def analyze_content(self, content: str, user_token: Optional[str] = None) -> LLMAnalysisResult:
        """
        Analyze content with two-phased verification.

        Phase 1: Security check for injections/malicious content
        Phase 2: Content analysis with configured prompt (only if phase 1 passes)

        Args:
            content: Content to analyze
            user_token: Per-user access token from x-forwarded-access-token header (Databricks Apps)

        Returns:
            LLMAnalysisResult with security metadata
        """
        # Check if LLM is enabled
        if not self.is_enabled():
            logger.warning("LLM analysis requested but LLM_ENABLED is False")
            return LLMAnalysisResult(
                success=False,
                content="",
                phase1_passed=False,
                render_as_markdown=False,
                error_message="LLM functionality is disabled"
            )

        endpoint = self.get_endpoint()
        if not endpoint:
            return LLMAnalysisResult(
                success=False,
                content="",
                phase1_passed=False,
                render_as_markdown=False,
                error_message="No LLM endpoint configured"
            )

        # Phase 1: Security Check
        phase1_passed, security_reason = self._phase1_security_check(content, user_token=user_token)

        if not phase1_passed:
            # Return security failure - content should be displayed as plain text
            warning_message = (
                f"⚠️ SECURITY WARNING ⚠️\n\n"
                f"The content analysis was blocked due to potential security concerns:\n\n"
                f"{security_reason}\n\n"
                f"Please review the content manually."
            )
            return LLMAnalysisResult(
                success=False,
                content=warning_message,
                phase1_passed=False,
                render_as_markdown=False,  # Must display as plain text
                llm_model_used=endpoint,
                error_message=security_reason
            )

        # Phase 2: Content Analysis
        analysis = self._phase2_content_analysis(content, user_token=user_token)

        if analysis is None:
            return LLMAnalysisResult(
                success=False,
                content="",
                phase1_passed=True,
                render_as_markdown=False,
                llm_model_used=endpoint,
                error_message="Content analysis failed after security check"
            )

        # Success: Both phases passed
        return LLMAnalysisResult(
            success=True,
            content=analysis,
            phase1_passed=True,
            render_as_markdown=True,  # Safe to render as markdown
            llm_model_used=endpoint
        )


def get_llm_service() -> LLMService:
    """Get or create the global LLM service instance."""
    settings = get_settings()
    return LLMService(settings)
