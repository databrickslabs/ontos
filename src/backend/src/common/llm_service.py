"""
LLM Service with Two-Phased Security Verification

This service provides a secure interface to Databricks-hosted LLM endpoints with:
1. Phase 1: Security check for injection attempts and malicious content
2. Phase 2: Content analysis with configurable system prompt

All interactions use the OpenAI SDK with Databricks endpoints.
"""

import re
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from src.common.config import Settings, get_settings
from src.common.llm_content import (
    REFUSAL_DISPLAY_MAX_CHARS,
    REFUSAL_LOG_MAX_CHARS,
    block_types,
    coerce_message_text,
    refusal_text,
    truncate_text,
)
from src.common.logging import get_logger

logger = get_logger(__name__)

# Output budget of the Phase 1 safety check. The answer is one word (SAFE /
# UNSAFE plus a reason), but reasoning models spend part of the budget on
# reasoning first: at 256 tokens the reply often had no answer left
# (finish_reason=length), and the check failed closed on harmless content.
PHASE1_MAX_TOKENS = 2048
# Output budget of the Phase 2 content analysis.
PHASE2_MAX_TOKENS = 2048
# ``notice_code`` of a refusal; the frontend shows a localized notice for each.
PHASE1_REFUSED_CODE = "llm_safety_check_refused"
PHASE2_REFUSED_CODE = "llm_analysis_refused"
# Fixed reason of a Phase 1 refusal: the refusal itself can quote the
# injection-check prompt, so it is only logged (truncated), never returned.
PHASE1_REFUSED_REASON = "Security check failed: the model refused to check the content"
# The Phase 1 verdict must open the reply ("SAFE" / "UNSAFE: reason"); a
# substring match passed "NOT SAFE" and "SAFEGUARDS MISSING".
_PHASE1_VERDICT_RE = re.compile(r"^\s*(UNSAFE|SAFE)\b", re.IGNORECASE)


@dataclass
class _LLMReply:
    """Answer text (text blocks only), refusal text and finish_reason of one completion."""
    text: str
    refusal: str
    finish_reason: Optional[str] = None


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
    refused: bool = False  # True if the model refused (shown as plain text, never markdown)
    notice_code: Optional[str] = None  # Code of the localized notice the UI shows

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
            Response content string or None on failure (a refusal is not content)
        """
        reply = self._complete(messages, max_tokens=max_tokens, user_token=user_token)
        return reply.text if reply is not None and reply.text else None

    def _complete(
        self, messages: list[Dict[str, str]], max_tokens: int, user_token: Optional[str] = None
    ) -> Optional[_LLMReply]:
        """Call the endpoint; None when there is neither answer text nor a refusal."""
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
                refusal = refusal_text(choice.message)
                if refusal:
                    logger.warning(
                        "LLM refused the request (finish_reason=%s, block types: %s)",
                        finish_reason,
                        block_types(raw_content),
                    )
                if content or refusal:
                    return _LLMReply(
                        text=content, refusal=refusal, finish_reason=finish_reason
                    )

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

        reply = self._complete(messages, max_tokens=PHASE1_MAX_TOKENS, user_token=user_token)

        if reply is not None and reply.refusal:
            # A refusal is not a verdict: fail closed, even next to a "SAFE" text block.
            logger.warning(
                "Phase 1 FAILED: the model refused the security check: %s",
                truncate_text(reply.refusal, REFUSAL_LOG_MAX_CHARS),
            )
            return False, PHASE1_REFUSED_REASON

        if reply is None or not reply.text:
            logger.error("Phase 1 security check failed: No response from LLM")
            return False, "Security check failed: Unable to verify content safety"
        if reply.finish_reason != "stop":
            # Cut off (length, content filter, unknown): the verdict may be partial.
            logger.error(
                "Phase 1 security check failed: reply did not finish (finish_reason=%s)",
                reply.finish_reason,
            )
            return False, "Security check failed: Unable to verify content safety"
        response = reply.text

        # Only a reply that opens with SAFE, and never mentions UNSAFE, passes;
        # anything else (no verdict, free text) fails closed.
        match = _PHASE1_VERDICT_RE.match(response)
        verdict = match.group(1).upper() if match else None
        if verdict == "SAFE" and "UNSAFE" not in response.upper():
            logger.info("Phase 1 PASSED: Content deemed safe")
            return True, None
        reason = (
            truncate_text(response, REFUSAL_DISPLAY_MAX_CHARS)
            if verdict == "UNSAFE"
            else "Content flagged as potentially unsafe"
        )
        logger.warning(f"Phase 1 FAILED: {reason}")
        return False, reason

    def _phase2_content_analysis(
        self, content: str, user_token: Optional[str] = None
    ) -> Optional[_LLMReply]:
        """
        Phase 2: Content analysis with configurable system prompt.

        Args:
            content: Content to analyze (already passed security check)
            user_token: Per-user access token (for Databricks Apps)

        Returns:
            The reply (answer text and refusal text) or None on failure
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

        reply = self._complete(messages, max_tokens=PHASE2_MAX_TOKENS, user_token=user_token)

        if reply is None:
            logger.error("Phase 2 FAILED: No response from LLM")
        elif reply.refusal:
            logger.warning(
                "Phase 2 REFUSED: %s", truncate_text(reply.refusal, REFUSAL_LOG_MAX_CHARS)
            )
        else:
            logger.info("Phase 2 COMPLETED: Content analysis successful")

        return reply

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
            refused = security_reason == PHASE1_REFUSED_REASON
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
                error_message=security_reason,
                refused=refused,
                notice_code=PHASE1_REFUSED_CODE if refused else None,
            )

        # Phase 2: Content Analysis
        analysis = self._phase2_content_analysis(content, user_token=user_token)

        if analysis is not None and analysis.refusal:
            # A refusal is not a vetted analysis, also next to a text block:
            # return it as a refused result, capped and shown as plain text.
            return LLMAnalysisResult(
                success=False,
                content=truncate_text(analysis.refusal, REFUSAL_DISPLAY_MAX_CHARS),
                phase1_passed=True,
                render_as_markdown=False,
                llm_model_used=endpoint,
                error_message="The model refused to analyze the content",
                refused=True,
                notice_code=PHASE2_REFUSED_CODE,
            )

        if analysis is None or not analysis.text:
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
            content=analysis.text,
            phase1_passed=True,
            render_as_markdown=True,  # Safe to render as markdown
            llm_model_used=endpoint
        )


def get_llm_service() -> LLMService:
    """Get or create the global LLM service instance."""
    settings = get_settings()
    return LLMService(settings)
