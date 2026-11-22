"""AR review flow: one AR-level run per start, one notification per reviewer, and submit closes the Asset Review.

#859 review B10 (submit doesn't close the Asset Review), S8 (reviewer notification went to
the owner), S10 (tracking sees only the newest 100 executions), R5 (reviewer read access),
and the follow-up review items 2-5, 8, 10.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.review_access import (
    authority_relation_fqn,
    authority_relation_id_of,
    caller_is_named_authority_reviewer,
)
from src.controller.authority_resolution_manager import AuthorityResolutionManager, AuthorityReviewOutcomeError
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.db_models.notifications import NotificationDb
from src.models.authority_resolution import AffirmationInput, AuthorityRelationCreate
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    StepType,
    TriggerContext,
    TriggerType,
    WorkflowExecutionCreate,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.repositories.authority_resolution_repository import authority_affirmation_repo
from src.repositories.process_workflows_repository import process_workflow_repo, workflow_execution_repo


def _user(email, groups=None):
    return SimpleNamespace(email=email, username=email, user=email, groups=groups or [])


def _reviews_manager(db):
    return DataAssetReviewManager(db, ws_client=None, notifications_manager=MagicMock())


def _two_reviewer_ar(db, extra=()):
    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db, AuthorityRelationCreate(name=f"Orders AR {uuid.uuid4().hex[:6]}", affirmations=[
        AffirmationInput(role="business", principal="rev1@x.com", is_approver=False, is_reviewer=True),
        AffirmationInput(role="technical", principal="rev2@x.com", is_approver=False, is_reviewer=True),
        *extra,
    ]))
    db.commit()
    return mgr, rel


def _participants(mgr, db, rel):
    affs = mgr.to_read_dict(db, rel)["affirmations"]
    return {a["principal"]: a for a in affs if a.get("is_reviewer")}


def _review_requests(mgr, db, rel, rm):
    tracking = mgr.get_review_tracking(db, rel.id, reviews_manager=rm)
    return {r["principal"]: r for r in tracking["reviews"]}


def _create_ar_wf(db):
    """The shipped AR review workflow: one best-effort notification to each reviewer."""
    wf = process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f"AR review {uuid.uuid4().hex[:6]}",
        trigger=WorkflowTrigger(type=TriggerType.ON_REQUEST_REVIEW, entity_types=[EntityType.AUTHORITY_RELATION]),
        steps=[
            WorkflowStepCreate(step_id='notify-reviewer', step_type=StepType.NOTIFICATION, config={
                'recipients': 'reviewers', 'template': 'request_submitted',
                'custom_message': "You have been asked to review Authority Relation '${entity_name}'.",
                'fail_flow_on_failure': False,
            }, on_pass='success'),
            WorkflowStepCreate(step_id='success', step_type=StepType.PASS),
        ],
    ))
    db.commit()
    return wf


def _notifications_for(db, recipient):
    return db.query(NotificationDb).filter(NotificationDb.recipient == recipient).all()


def _ar_executions(db, rel):
    return [e for e in workflow_execution_repo.list_for_entity_ids(db, [rel.id])
            if (e.trigger_context or '') and rel.id in e.trigger_context]


# --- start: one AR-level run, one notification per reviewer -----------------------

def test_start_review_fires_one_ar_level_run_with_the_reviewers(db_session):
    _create_ar_wf(db_session)
    mgr, rel = _two_reviewer_ar(db_session)

    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=_reviews_manager(db_session))

    runs = _ar_executions(db_session, rel)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == 'succeeded'
    assert [s.step_key for s in run.step_executions] == ['notify-reviewer', 'success']
    payload = json.loads(run.trigger_context)
    assert payload['entity_id'] == rel.id
    assert payload['entity_name'] == rel.name
    assert payload['entity_data']['id'] == rel.id
    assert payload['entity_data']['asset_fqn'] == authority_relation_fqn(rel.id)
    assert sorted(r['principal'] for r in payload['entity_data']['reviewers']) == ['rev1@x.com', 'rev2@x.com']


def test_start_review_notifies_each_reviewer_once_and_not_the_owner(db_session):
    _create_ar_wf(db_session)
    mgr, rel = _two_reviewer_ar(db_session)

    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=_reviews_manager(db_session))

    assert len(_notifications_for(db_session, 'rev1@x.com')) == 1
    assert len(_notifications_for(db_session, 'rev2@x.com')) == 1
    assert _notifications_for(db_session, 'owner@x.com') == []


def test_the_notification_names_the_relation_not_the_review_title(db_session):
    _create_ar_wf(db_session)
    mgr, rel = _two_reviewer_ar(db_session)

    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=_reviews_manager(db_session))

    [note] = _notifications_for(db_session, 'rev1@x.com')
    assert note.description == f"You have been asked to review Authority Relation '{rel.name}'."
    assert 'Authority Relation review' not in note.description


def test_without_a_workflow_each_reviewer_gets_one_direct_notification(db_session):
    mgr, rel = _two_reviewer_ar(db_session)

    result = mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=_reviews_manager(db_session))

    assert result['notifications_sent'] == 2
    assert len(_notifications_for(db_session, 'rev1@x.com')) == 1
    assert len(_notifications_for(db_session, 'rev2@x.com')) == 1


def test_per_reviewer_requests_fire_no_data_asset_workflow(db_session):
    """The per-reviewer Asset Reviews add no DataSteward run and no notification of their own."""
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)

    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)

    requests = _review_requests(mgr, db_session, rel, rm)
    assert all(r['review_request_id'] for r in requests.values())
    runs = workflow_execution_repo.list_all(db_session, limit=500)
    assert not any('data_asset_review' in (e.trigger_context or '') for e in runs)
    assert len(_notifications_for(db_session, 'rev1@x.com')) == 1  # the direct fallback only


# --- submit: closes the Asset Review; outcome -----------------------------------------

def test_submit_closes_the_reviewers_asset_review_and_the_other_stays_open(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    parts = _participants(mgr, db_session, rel)
    requests = _review_requests(mgr, db_session, rel, rm)

    mgr.submit_review(db_session, parts['rev1@x.com']['id'], {'q1': 'yes'},
                      user=_user('rev1@x.com'), reviews_manager=rm)
    db_session.commit()

    done = rm.get_review_request(requests['rev1@x.com']['review_request_id'])
    assert done.status.value == 'approved'
    assert [a.status.value for a in done.assets] == ['approved']
    still_open = rm.get_review_request(requests['rev2@x.com']['review_request_id'])
    assert still_open.status.value not in ('approved', 'needs_review')
    assert [a.status.value for a in still_open.assets] == ['pending']
    assert mgr.get_review_tracking(db_session, rel.id, reviews_manager=rm)['all_reviewed'] is False


def test_all_reviewers_submitted_marks_the_review_complete(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    parts = _participants(mgr, db_session, rel)
    requests = _review_requests(mgr, db_session, rel, rm)

    for principal in ('rev1@x.com', 'rev2@x.com'):
        mgr.submit_review(db_session, parts[principal]['id'], {'q1': 'yes'},
                          user=_user(principal), reviews_manager=rm)
    db_session.commit()

    for principal in ('rev1@x.com', 'rev2@x.com'):
        request = rm.get_review_request(requests[principal]['review_request_id'])
        assert request.status.value == 'approved'
        assert all(a.status.value == 'approved' for a in request.assets)
    assert mgr.get_review_tracking(db_session, rel.id, reviews_manager=rm)['all_reviewed'] is True


def test_a_needs_clarification_outcome_is_not_approved(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    parts = _participants(mgr, db_session, rel)
    request_id = _review_requests(mgr, db_session, rel, rm)['rev1@x.com']['review_request_id']

    mgr.submit_review(db_session, parts['rev1@x.com']['id'], {'q1': 'no'}, user=_user('rev1@x.com'),
                      reviews_manager=rm, outcome='needs_clarification')
    db_session.commit()

    request = rm.get_review_request(request_id)
    assert [a.status.value for a in request.assets] == ['needs_clarification']
    assert request.status.value == 'needs_review'
    affirmation = next(a for a in authority_affirmation_repo.list_for_relation(db_session, relation_id=rel.id)
                       if a.principal == 'rev1@x.com')
    assert affirmation.review_answers['outcome'] == 'needs_clarification'


def test_an_unknown_outcome_is_refused_and_nothing_is_recorded(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    parts = _participants(mgr, db_session, rel)

    with pytest.raises(AuthorityReviewOutcomeError) as exc:
        mgr.submit_review(db_session, parts['rev1@x.com']['id'], {}, user=_user('rev1@x.com'),
                          reviews_manager=rm, outcome='maybe')
    assert exc.value.code == 'authority_invalid_review_outcome'
    assert _participants(mgr, db_session, rel)['rev1@x.com']['review_status'] == 'in_review'


def test_a_failing_close_leaves_the_answers_unrecorded(db_session):
    """The Asset Review is closed first: when that fails, the reviewer's submit is not recorded."""
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    parts = _participants(mgr, db_session, rel)
    broken = MagicMock(wraps=rm)
    broken.update_review_request_status.side_effect = RuntimeError('close failed')

    with pytest.raises(RuntimeError):
        mgr.submit_review(db_session, parts['rev1@x.com']['id'], {'q1': 'yes'}, user=_user('rev1@x.com'),
                          reviews_manager=broken)

    assert _participants(mgr, db_session, rel)['rev1@x.com']['review_status'] == 'in_review'


def test_submit_without_an_asset_review_still_saves_the_answers(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    parts = _participants(mgr, db_session, rel)

    updated = mgr.submit_review(db_session, parts['rev1@x.com']['id'], {'q1': 'yes'},
                                user=_user('rev1@x.com'), reviews_manager=None)

    assert updated.review_status == 'completed'


# --- read access (R5, review item 2 and 3) ---------------------------------------------

def test_the_named_reviewer_can_read_their_request_before_and_after_submitting(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    parts = _participants(mgr, db_session, rel)
    mine = _review_requests(mgr, db_session, rel, rm)['rev1@x.com']['review_request_id']

    assert caller_is_named_authority_reviewer(db_session, _user('rev1@x.com'), mine) is True
    assert caller_is_named_authority_reviewer(db_session, _user('REV1@x.com'), mine) is True
    assert caller_is_named_authority_reviewer(db_session, _user('rev2@x.com'), mine) is False
    assert caller_is_named_authority_reviewer(db_session, _user('owner@x.com'), mine) is False
    assert caller_is_named_authority_reviewer(db_session, _user('rev1@x.com'), str(uuid.uuid4())) is False

    mgr.submit_review(db_session, parts['rev1@x.com']['id'], {'q1': 'yes'},
                      user=_user('rev1@x.com'), reviews_manager=rm)
    db_session.commit()
    assert caller_is_named_authority_reviewer(db_session, _user('rev1@x.com'), mine) is True


def test_a_group_reviewer_member_can_read_the_request(db_session):
    """Review item 3: group reviewers match like submit_review does."""
    # A group reviewer's principal must be an email (EmailStr) to get its Asset Review
    board = AffirmationInput(role="board", principal="board@x.com", principal_type="group", is_approver=False, is_reviewer=True)
    mgr, rel = _two_reviewer_ar(db_session, extra=(board,))
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    board_request = _review_requests(mgr, db_session, rel, rm)['board@x.com']['review_request_id']

    assert caller_is_named_authority_reviewer(db_session, _user('bob@x.com', groups=['Board@x.com']), board_request) is True
    assert caller_is_named_authority_reviewer(db_session, _user('bob@x.com', groups=['Other']), board_request) is False


def test_the_request_of_a_non_ar_review_is_not_granted_by_this_check(db_session):
    from src.models.data_asset_reviews import DataAssetReviewRequestCreate

    rm = _reviews_manager(db_session)
    req = rm.create_review_request(DataAssetReviewRequestCreate(
        requester_email='req@x.com', reviewer_email='rev1@x.com', asset_fqns=['product:some-product'],
    ), db=db_session)

    assert caller_is_named_authority_reviewer(db_session, _user('rev1@x.com'), req.id) is False


# --- tracking (S10) and helpers ----------------------------------------------------------

def test_tracking_lists_only_this_ars_executions(db_session):
    wf = _create_ar_wf(db_session)
    mgr, rel = _two_reviewer_ar(db_session)
    other_id = str(uuid.uuid4())
    for entity_id in (rel.id, other_id):
        workflow_execution_repo.create(db_session, WorkflowExecutionCreate(
            workflow_id=wf.id,
            trigger_context=TriggerContext(
                entity_type='authority_relation', entity_id=entity_id, trigger_type=TriggerType.ON_REQUEST_REVIEW,
            ),
        ))
    db_session.commit()

    found = workflow_execution_repo.list_for_entity_ids(db_session, [rel.id])

    assert found and all(rel.id in (e.trigger_context or '') for e in found)
    assert not any(other_id in (e.trigger_context or '') for e in found)


def test_list_for_entity_ids_with_no_ids_queries_nothing(db_session):
    assert workflow_execution_repo.list_for_entity_ids(db_session, []) == []


def test_authority_relation_id_of_accepts_one_relation_only():
    rid = str(uuid.uuid4())
    assert authority_relation_id_of([authority_relation_fqn(rid)]) == rid
    assert authority_relation_id_of([f"{authority_relation_fqn(rid)}#7"]) == rid
    assert authority_relation_id_of([authority_relation_fqn(rid), authority_relation_fqn(str(uuid.uuid4()))]) is None
    assert authority_relation_id_of([authority_relation_fqn(rid), 'cat.sch.tbl']) is None
    assert authority_relation_id_of([]) is None
