import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Depends, Body, Query, Request
from starlette.concurrency import run_in_threadpool

from src.common.api_errors import CodedValueError, UserTokenRequiredError
from src.common.dependencies import DBSessionDep, AuditManagerDep, AuditCurrentUserDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker, user_has_feature_level
from src.common.manager_dependencies import get_auth_manager
from src.common.compliance_errors import public_run_error
from src.common.compliance_result_visibility import viewer_read_checks
from src.controller.compliance_manager import viewer_run_fields
from src.common.run_identity import RunIdentity
from src.controller.authorization_manager import AuthorizationManager
from src.controller.compliance_manager import (
    ComplianceManager,
    SampleEntityNotFoundError,
    rule_changes_tags,
    rule_sends_notifications,
    rule_uses_llm_check,
)
from src.models.compliance import (
    CompliancePolicy,
    CompliancePolicyCreate,
    ComplianceRun,
    ComplianceResult,
    ComplianceRunRequest,
    ComplianceResultsResponse,
    LlmCheckTestRequest,
    LlmCheckTestResponse,
)
from src.db_models.compliance import CompliancePolicyDb, ComplianceRunDb, ComplianceResultDb
from src.common.compliance_dsl import evaluate_rule_on_object as eval_dsl
from src.common.compliance_entities import (
    APP_ENTITY_FEATURES, parse_entity_filter, validate_rule,
)
from src.common.compliance_llm_check import (
    QUOTA_EXCEEDED, LlmCheckQuotaExceededError, seconds_to_next_utc_day,
)

from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Compliance"])
manager = ComplianceManager()

FEATURE_ID = 'compliance'
# Results per page of a run (the run details page asks for one page at a time)
RESULTS_PAGE_SIZE = 500


def _check_rule(rule: str) -> list:
    """Reject rules that do not parse; return warnings for rules that cannot work as written."""
    try:
        return validate_rule(rule)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# DEPRECATED: Demo data loading has been moved to SQL-based approach.
# Demo data is now loaded via POST /api/settings/demo-data/load?preset=<retail|hls|fsi|mfg|auto>.
# Each preset is a self-contained file: src/backend/src/data/demo_data_{preset}.sql.


@router.get("/compliance/policies")
async def get_policies(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get all compliance policies with stats and scores."""
    return manager.get_policies_with_stats(db)


@router.get("/compliance/policies/{policy_id}")
async def get_policy(
    policy_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get a specific compliance policy with examples."""
    policy = manager.get_policy_with_examples(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    return policy


def require_tag_write_for_tag_actions(rule: Optional[str], auth_manager, current_user, request: Request) -> None:
    """ASSIGN_TAG / REMOVE_TAG change tag associations, so saving or running a
    rule that uses them needs write access to tags, as the tag routes do.

    Scheduled runs have no acting user; they run rules saved by users who had
    that access.
    """
    if rule_changes_tags(rule) and not user_has_feature_level(
        auth_manager, current_user, 'tags', FeatureAccessLevel.READ_WRITE, request
    ):
        raise HTTPException(
            status_code=403,
            detail="This policy assigns or removes tags (ASSIGN_TAG / REMOVE_TAG); "
                   "saving or running it requires write access to tags",
        )


def require_compliance_admin_for_notify(rule: Optional[str], auth_manager, current_user, request: Request) -> None:
    """NOTIFY creates in-app notifications for any user, group or role, so saving or
    running a rule that uses it needs admin access to compliance (Data Governance
    Officers and Admins by default), not just write access.

    Scheduled runs have no acting user; they run rules saved by users who had
    that access.
    """
    if rule_sends_notifications(rule) and not user_has_feature_level(
        auth_manager, current_user, FEATURE_ID, FeatureAccessLevel.ADMIN, request
    ):
        raise HTTPException(
            status_code=403,
            detail="This policy sends notifications (NOTIFY); saving or running it "
                   "requires admin access to compliance",
        )


class LlmCheckAdminRequiredError(CodedValueError):
    """A user without admin access to compliance saved, ran or tested an LLM_CHECK rule."""

    code = 'llm_check_admin_required'


def require_compliance_admin_for_llm_check(
    rule: Optional[str], auth_manager, current_user, request: Request,
) -> None:
    """LLM_CHECK calls the serving endpoint for each entity (paid by the app), so
    saving, running or testing a rule that uses it needs admin access to
    compliance, as NOTIFY does (Data Governance Officers and Admins by default).

    Scheduled runs have no acting user; they run rules saved by users who had
    that access.
    """
    if rule_uses_llm_check(rule) and not user_has_feature_level(
        auth_manager, current_user, FEATURE_ID, FeatureAccessLevel.ADMIN, request
    ):
        error = LlmCheckAdminRequiredError(
            "This policy uses LLM_CHECK; saving, running or testing it requires admin "
            "access to compliance",
        )
        raise HTTPException(status_code=403, detail=str(error)) from error


def refuse_when_the_quota_stopped_a_test(result, quota_limit: int) -> None:
    """429 ``llm_check_daily_quota_exceeded`` (with Retry-After, seconds to midnight
    UTC) when a rule test needed model calls the user had no longer left today
    (COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_USER_PER_DAY). A test answered from cached
    verdicts needs none, so it is never refused for the quota; nor is a run, whose
    checks past the quota are not evaluated (the run warns how many).
    """
    codes = {result.error_code, *(c.code for c in result.llm_checks)}
    if QUOTA_EXCEEDED not in codes:
        return
    error = LlmCheckQuotaExceededError(
        f"You used your {quota_limit} LLM_CHECK model calls for today",
        limit=quota_limit, retryAfter=seconds_to_next_utc_day(),
    )
    raise HTTPException(
        status_code=429, detail=str(error),
        headers={'Retry-After': str(error.params['retryAfter'])},
    ) from error


def _username(current_user) -> str:
    return current_user.username if current_user else 'unknown'


class LlmCheckPolicyInUseError(CodedValueError):
    """An LLM_CHECK rule for a policy that a workflow step or a maturity gate evaluates."""

    code = 'llm_check_policy_in_use'


def refuse_llm_check_where_it_cannot_run(db, policy_id: str, rule: Optional[str]) -> None:
    """409 when a policy that workflow policy_check steps or maturity gates use gets a
    rule with LLM_CHECK: they evaluate it without a model, so it would fail every
    entity there (a policy check would block every update)."""
    if not rule_uses_llm_check(rule):
        return
    uses = manager.policy_gate_uses(db, policy_id)
    if uses['workflowSteps'] or uses['maturityGates']:
        error = LlmCheckPolicyInUseError(
            f"This policy is used by {uses['workflowSteps']} workflow policy checks and "
            f"{uses['maturityGates']} maturity gates, which can't evaluate LLM_CHECK",
            **uses,
        )
        raise HTTPException(status_code=409, detail=str(error)) from error


class LlmCheckReadRequiredError(CodedValueError):
    """A user ran an LLM_CHECK rule over app entities they can't read."""

    code = 'llm_check_entity_read_required'


def require_entity_read_for_llm_check(
    request: Request, rule: Optional[str], auth_manager, current_user,
) -> None:
    """A run or test that a user starts of an LLM_CHECK rule needs read access to
    the app entity types the rule matches (403 ``llm_check_entity_read_required``).

    The model's reasons can quote the text it judged, so a user only gets them
    for what they can read. Unity Catalog objects are covered by the run's
    identity: every run a user starts reads as them (``RunIdentity.for_request``),
    LLM_CHECK or not; scheduled runs read as the app.
    """
    if not rule_uses_llm_check(rule):
        return
    try:
        entity_types = parse_entity_filter(rule).entity_types
    except Exception:
        return  # rejected by the run or the rule check
    for entity_type in entity_types:
        feature = APP_ENTITY_FEATURES.get(entity_type)
        if feature and not user_has_feature_level(
            auth_manager, current_user, feature, FeatureAccessLevel.READ_ONLY, request
        ):
            error = LlmCheckReadRequiredError(
                f"This rule uses LLM_CHECK on {entity_type} entities; running or testing "
                f"it requires read access to them",
                entityType=entity_type,
            )
            raise HTTPException(status_code=403, detail=str(error)) from error


@router.post("/compliance/policies")
async def create_policy(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    policy: CompliancePolicyCreate = Body(...),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    warnings = _check_rule(policy.rule)
    require_tag_write_for_tag_actions(policy.rule, auth_manager, current_user, request)
    require_compliance_admin_for_notify(policy.rule, auth_manager, current_user, request)
    require_compliance_admin_for_llm_check(policy.rule, auth_manager, current_user, request)
    created = manager.create_policy(
        db, 
        policy, 
        current_user=current_user.username if current_user else None
    )
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='CREATE_POLICY',
        success=True,
        details={'policy_id': created.id, 'policy_name': created.name}
    )
    
    return {
        'id': created.id,
        'name': created.name,
        'description': created.description,
        'rule': created.rule,
        'created_at': created.created_at,
        'updated_at': created.updated_at,
        'is_active': created.is_active,
        'severity': created.severity,
        'category': created.category,
        'compliance': 0.0,
        'history': [],
        'warnings': warnings,
    }


@router.put("/compliance/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    policy: CompliancePolicy = Body(...),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    # Only a changed rule is checked: an older policy with an invalid rule
    # can still be renamed, disabled or recategorised
    existing = manager.get_policy(db, policy_id)
    rule_changed = existing is None or existing.rule != policy.rule
    warnings = _check_rule(policy.rule) if rule_changed else []
    if rule_changed:
        require_tag_write_for_tag_actions(policy.rule, auth_manager, current_user, request)
        require_compliance_admin_for_llm_check(policy.rule, auth_manager, current_user, request)
        refuse_llm_check_where_it_cannot_run(db, policy_id, policy.rule)
    # The name is the title of the notifications NOTIFY sends: renaming is gated too
    if rule_changed or existing.name != policy.name:
        require_compliance_admin_for_notify(policy.rule, auth_manager, current_user, request)
    updated = manager.update_policy(
        db, 
        policy_id, 
        policy,
        current_user=current_user.username if current_user else None
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='UPDATE_POLICY',
        success=True,
        details={'policy_id': policy_id, 'policy_name': updated.name}
    )
    
    return {
        'id': updated.id,
        'name': updated.name,
        'description': updated.description,
        'rule': updated.rule,
        'created_at': updated.created_at,
        'updated_at': updated.updated_at,
        'is_active': updated.is_active,
        'severity': updated.severity,
        'category': updated.category,
        'warnings': warnings,
    }


@router.delete("/compliance/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    # Get policy name before deleting for audit
    policy = manager.get_policy(db, policy_id)
    policy_name = policy.name if policy else 'unknown'
    
    ok = manager.delete_policy(
        db, 
        policy_id,
        current_user=current_user.username if current_user else None
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Policy not found")
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='DELETE_POLICY',
        success=True,
        details={'policy_id': policy_id, 'policy_name': policy_name}
    )
    
    return {"status": "success"}


def _json_params(value):
    import json

    try:
        return json.loads(value) if value else None
    except (TypeError, ValueError):
        return None


def _run_error_code(run) -> dict:
    """The run's error code and parameters, which the UI translates. The stored
    error text is not sent: it can name objects or hosts the reader can't see."""
    code, params = public_run_error(run.status, run.error_code, _json_params(run.error_params))
    return {'error_code': code, 'error_params': params}


def _run_codes(run) -> dict:
    """The run's error and warning codes and their parameters, which the UI translates."""
    return {
        **_run_error_code(run),
        'warning_code': run.warning_code,
        'warning_params': _json_params(run.warning_params),
    }


def _run_llm_usage(run) -> dict:
    """The run's LLM_CHECK usage: model calls, cached verdicts and the entities left
    without a verdict (None when the run didn't count them)."""
    return {
        'llm_calls': getattr(run, 'llm_calls', None),
        'llm_cache_hits': getattr(run, 'llm_cache_hits', None),
        'not_evaluated_count': getattr(run, 'not_evaluated_count', None),
    }


@router.post("/compliance/policies/{policy_id}/runs")
async def run_policy(
    policy_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: ComplianceRunRequest = Body(default=ComplianceRunRequest()),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    policy = manager.get_policy(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    require_tag_write_for_tag_actions(policy.rule, auth_manager, current_user, request)
    require_compliance_admin_for_notify(policy.rule, auth_manager, current_user, request)
    require_compliance_admin_for_llm_check(policy.rule, auth_manager, current_user, request)
    require_entity_read_for_llm_check(request, policy.rule, auth_manager, current_user)

    # For now, implement inline only; async can be backed by Databricks job later
    # The user's own token reads Unity Catalog, so the stored results hold only
    # what they can read; scheduled runs (the compliance-checks job) read as the app.
    # Off the event loop: the run can wait on SQL warehouse statements (tags, lineage)
    # and LLM_CHECK rules call the serving endpoint per entity
    run = await run_in_threadpool(
        manager.run_policy_inline,
        db,
        policy=policy,
        limit=payload.limit,
        current_user=current_user.username if current_user else None,
        run_identity=RunIdentity.for_request(request),
        quota_user=_username(current_user),
    )
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=FEATURE_ID,
        action='RUN_POLICY',
        success=True,
        details={'policy_id': policy_id, 'policy_name': policy.name, 'run_id': run.id}
    )
    
    counts = await run_in_threadpool(
        manager.viewer_run_counts, db, [run], viewer_read_checks(request),
    )
    return _run_payload(run, counts[run.id])


def _run_payload(run, counts: dict) -> dict:
    """A run as the API returns it: its counts, its score (None without one) and
    its coverage over the results the viewer can read, ``hidden_count``, and its
    codes. ``counts``: the run's entry of ``manager.viewer_run_counts``."""
    return {
        'id': run.id,
        'policy_id': run.policy_id,
        'status': run.status,
        'started_at': run.started_at,
        'finished_at': run.finished_at,
        **viewer_run_fields(run, counts),
        **_run_codes(run),
        **_run_llm_usage(run),
        # Over the results the viewer can read, as the coverage (not the stored count)
        'not_evaluated_count': counts['not_evaluated'],
    }


@router.get("/compliance/policies/{policy_id}/runs")
async def list_runs(
    policy_id: str,
    request: Request,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    policy = manager.get_policy(db, policy_id)
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    runs = manager.list_runs(db, policy_id=policy_id, limit=50)
    # Counts and scores over the results the viewer can read (their own token, one
    # listing per schema for all the runs); off the event loop, as it lists UC
    counts = await run_in_threadpool(
        manager.viewer_run_counts, db, runs, viewer_read_checks(request),
    )
    return [_run_payload(r, counts[r.id]) for r in runs]


@router.get("/compliance/runs/{run_id}/results")
async def get_run_results(
    run_id: str,
    request: Request,
    db: DBSessionDep,
    only_failed: Optional[bool] = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=RESULTS_PAGE_SIZE, ge=1, le=RESULTS_PAGE_SIZE),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    run = db.get(ComplianceRunDb, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    # Only the Unity Catalog objects the viewer can read, with their own token
    # (a run reads as its starter or as the app), paged after that filter; the
    # run's counts and score too. Off the event loop, as it lists UC
    checks = viewer_read_checks(request)

    def _read():
        page = manager.viewer_results_page(
            db, run_id=run_id, checks=checks, only_failed=bool(only_failed),
            offset=offset, limit=limit,
        )
        return page, manager.viewer_run_counts(db, [run], checks)[run.id]

    (results, total, hidden), counts = await run_in_threadpool(_read)
    return {
        'run': _run_payload(run, counts),
        'results': [
            {
                'id': r.id,
                'run_id': r.run_id,
                'object_type': r.object_type,
                'object_id': r.object_id,
                'object_name': r.object_name,
                'passed': r.passed,
                'not_evaluated': bool(getattr(r, 'not_evaluated', False)),
                'message': r.message,
                'details_json': r.details_json,
                'created_at': r.created_at,
            } for r in results
        ],
        'only_failed': bool(only_failed),
        # Visible results on every page; the page starts at ``offset``
        'total': total,
        'offset': offset,
        'limit': limit,
        # Results on objects the viewer can't read: counted, not listed
        'hidden_count': hidden,
    }


# Rule tests per user and window (seconds): each test can call the serving endpoint
RULE_TEST_MAX_CALLS = 10
RULE_TEST_WINDOW_SECONDS = 60.0
_rule_tests: Dict[str, Deque[float]] = defaultdict(deque)
_rule_tests_lock = threading.Lock()


class RuleTestRateLimitedError(CodedValueError):
    """A user ran more rule tests than the limit in the window."""

    code = 'llm_check_test_rate_limited'


def _throttle_rule_test(user: str) -> None:
    """Count a rule test of ``user``; RuleTestRateLimitedError past the limit.

    In memory, so the limit holds per backend process.
    """
    now = time.monotonic()
    with _rule_tests_lock:
        # Users whose tests all expired: drop them, so the dict doesn't keep growing
        for expired in [
            u for u, q in _rule_tests.items() if not q or now - q[-1] >= RULE_TEST_WINDOW_SECONDS
        ]:
            del _rule_tests[expired]
        calls = _rule_tests[user]
        while calls and now - calls[0] >= RULE_TEST_WINDOW_SECONDS:
            calls.popleft()
        if len(calls) >= RULE_TEST_MAX_CALLS:
            retry_after = max(1, int(RULE_TEST_WINDOW_SECONDS - (now - calls[0])) + 1)
            raise RuleTestRateLimitedError(
                f"Too many rule tests; try again in {retry_after} seconds",
                retryAfter=retry_after,
            )
        calls.append(now)


@router.post("/compliance/llm-check/test", response_model=LlmCheckTestResponse)
async def test_llm_check(
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: LlmCheckTestRequest = Body(...),
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Try a rule (and its LLM_CHECK criteria) on one entity before saving it.

    READ_WRITE, as saving a rule, and admin access to compliance for a rule with
    LLM_CHECK (each one calls the serving endpoint). At most RULE_TEST_MAX_CALLS
    tests per user a minute (429). Nothing but cached verdicts is written.
    """
    _check_rule(payload.rule)
    require_compliance_admin_for_llm_check(payload.rule, auth_manager, current_user, request)
    # Any rule tested here reads Unity Catalog as the user, LLM_CHECK or not: as the
    # app, its verdict would tell what the user can't read (an existence and value oracle)
    require_entity_read_for_llm_check(request, payload.rule, auth_manager, current_user)
    identity = RunIdentity.for_request(request)
    try:
        _throttle_rule_test(current_user.username if current_user else 'unknown')
    except RuleTestRateLimitedError as e:
        raise HTTPException(
            status_code=429, detail=str(e),
            headers={'Retry-After': str(e.params['retryAfter'])},
        ) from e
    try:
        # The model calls block: run them off the event loop
        result = await run_in_threadpool(
            manager.test_rule_on_sample, db, rule=payload.rule, entity=payload.entity,
            run_identity=identity, quota_user=_username(current_user),
        )
    except SampleEntityNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except UserTokenRequiredError as e:
        # The test reads Unity Catalog as the user, and the request has no token
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        if getattr(e, 'error_code', None) == 'workspace_client_unavailable':
            raise HTTPException(
                status_code=503, detail="Databricks workspace client unavailable",
            ) from e
        raise
    quota_limit = manager.llm_quota(db, _username(current_user)).limit
    refuse_when_the_quota_stopped_a_test(result, quota_limit)
    return result


@router.get("/compliance/stats")
async def get_stats(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return manager.get_compliance_stats(db)


@router.get("/compliance/trend")
async def get_compliance_trend(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    return manager.get_compliance_trend(db)


def register_routes(app: FastAPI) -> None:
    app.include_router(router)


@router.post("/compliance/validate-inline")
async def validate_inline(
    body: dict = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Validate a single object against a DSL rule inline (no DB writes)."""
    try:
        rule = body.get('rule') or ''
        obj = body.get('object') or {}
        passed, msg = eval_dsl(rule, obj)
        return {"passed": passed, "message": msg}
    except Exception as e:
        logger.error("DSL evaluation failed", exc_info=True)
        raise HTTPException(status_code=400, detail="DSL evaluation failed")
