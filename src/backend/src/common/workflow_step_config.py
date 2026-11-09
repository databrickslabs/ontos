"""Checks of Conditional and Script step configs.

Used when a workflow is saved and by the designer before it saves. Each issue
has a ``code`` and ``params`` the UI translates, and an English ``message``.
"""

from typing import Any, Dict, List, Optional

SCRIPT_LANGUAGES = ('python', 'sql')

# Longest condition the designer and a save accept. The DSL parser is
# recursive, so a deeply nested condition could exhaust the stack before the
# parser reports anything; the length cap keeps the check cheap and bounded.
MAX_CONDITION_LENGTH = 10_000


def _issue(code: str, message: str, **params: Any) -> Dict[str, Any]:
    return {'code': code, 'params': params, 'message': message}


def check_condition(condition: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the issue of a Conditional step's condition, or None when it parses.

    The condition is a Compliance DSL expression (no MATCH / ASSERT), parsed
    as ``ConditionalStepHandler`` parses it. Input after a complete expression
    is an issue too: the handler would ignore it and evaluate only the start.
    """
    from src.common.compliance_dsl import Lexer, Parser, TokenType

    if not condition or not condition.strip():
        return _issue('condition_required', "Conditional step requires 'condition' in config")

    if len(condition) > MAX_CONDITION_LENGTH:
        return _issue(
            'condition_too_long',
            f"The condition is longer than {MAX_CONDITION_LENGTH} characters",
            maximum=MAX_CONDITION_LENGTH,
        )

    lexer = Lexer(condition)
    try:
        tokens = lexer.tokenize()
    except ValueError as e:
        return _issue('condition_syntax_error', str(e), line=lexer.line, column=lexer.column)
    except RecursionError:
        return _issue('condition_too_complex', "The condition is nested too deeply to check")

    parser = Parser(tokens)
    try:
        parser.parse_expression()
    except ValueError as e:
        token = parser.current()
        return _issue('condition_syntax_error', str(e), line=token.line, column=token.column)
    except RecursionError:
        return _issue('condition_too_complex', "The condition is nested too deeply to check")

    token = parser.current()
    if token.type != TokenType.EOF:
        return _issue(
            'condition_trailing_input',
            f"Unexpected input after the condition at line {token.line}, column {token.column}",
            line=token.line,
            column=token.column,
            token=str(token.value),
        )
    return None


def check_script_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return the issues of a Script step's config (empty when it can run)."""
    issues: List[Dict[str, Any]] = []
    code = config.get('code')
    if not isinstance(code, str) or not code.strip():
        issues.append(_issue('script_code_required', "Script step requires 'code' in config"))

    language = config.get('language', 'python')
    if language not in SCRIPT_LANGUAGES:
        supported = ', '.join(SCRIPT_LANGUAGES)
        issues.append(_issue(
            'script_language_unsupported',
            f"Script step language '{language}' is not supported. Supported: {supported}",
            language=str(language),
            supported=supported,
        ))

    # Only Python scripts use the timeout: the SQL handler waits on the
    # warehouse with its own limit, and the designer hides the field for SQL.
    timeout = config.get('timeout_seconds', 60)
    if language == 'sql':
        return issues
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        issues.append(_issue(
            'script_timeout_invalid',
            "Script step 'timeout_seconds' must be a whole number of seconds, at least 1",
        ))
    return issues
