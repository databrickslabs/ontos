"""AR review flow: each reviewer's Asset Review runs the AR workflow and submit closes it.

#859 review B10 (submit doesn't close the Asset Review), S8 (reviewer notification went
to the owner), S10 (tracking sees only the newest 100 executions), and the DataSteward
gate that an AR review must not run.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.controller.authority_resolution_manager import AuthorityResolutionManager
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
from src.repositories.process_workflows_repository import process_workflow_repo, workflow_execution_repo


def _user(email):
    return SimpleNamespace(email=email, username=email, user=email, groups=[])


def _reviews_manager(db):
    return DataAssetReviewManager(db, ws_client=None, notifications_manager=MagicMock())


def _two_reviewer_ar(db):
    mgr = AuthorityResolutionManager()
    rel = mgr.create_relation(db, AuthorityRelationCreate(name=f"Review {uuid.uuid4().hex[:6]}", affirmations=[
        AffirmationInput(role="business", principal="rev1@x.com", is_approver=False, is_reviewer=True),
        AffirmationInput(role="technical", principal="rev2@x.com", is_approver=False, is_reviewer=True),
    ]))
    db.commit()
    return mgr, rel


def _participants(mgr, db, rel):
    affs = mgr.to_read_dict(db, rel)["affirmations"]
    return {a["principal"]: a for a in affs if a.get("is_reviewer")}


def _create_ar_wf(db):
    wf = process_workflow_repo.create(db, ProcessWorkflowCreate(
        name=f"AR review {uuid.uuid4().hex[:6]}",
        trigger=WorkflowTrigger(type=TriggerType.ON_REQUEST_REVIEW, entity_types=[EntityType.AUTHORITY_RELATION]),
        steps=[
            WorkflowStepCreate(step_id='notify-reviewer', step_type=StepType.NOTIFICATION, config={
                'recipients': 'reviewer', 'template': 'request_submitted',
                'custom_message': 'Review AR', 'fail_flow_on_failure': False,
            }, on_pass='success'),
            WorkflowStepCreate(step_id='success', step_type=StepType.PASS),
        ],
    ))
    db.commit()
    return wf


def _review_requests(db, mgr, rel, rm):
    tracking = mgr.get_review_tracking(db, rel.id, reviews_manager=rm)
    return {r["principal"]: r for r in tracking["reviews"]}


def test_start_review_fires_the_ar_workflow_per_reviewer_without_a_datasteward_gate(db_session):
    _create_ar_wf(db_session)
    mgr, rel = _two_reviewer_ar(db_session)

    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=_reviews_manager(db_session))

    executions = workflow_execution_repo.list_for_entity_ids(db_session, [rel.id])
    ar_runs = [e for e in executions if rel.id in (e.trigger_context or '')]
    assert len(ar_runs) == 2
    for run in ar_runs:
        assert run.status == 'succeeded'
        assert [s.step_key for s in run.step_executions] == ['notify-reviewer', 'success']


def test_reviewer_is_the_notification_recipient(db_session):
    _create_ar_wf(db_session)
    mgr, rel = _two_reviewer_ar(db_session)

    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=_reviews_manager(db_session))

    recipients = {n.recipient for n in db_session.query(NotificationDb).all()
                  if n.recipient in ('rev1@x.com', 'rev2@x.com', 'owner@x.com')}
    assert 'rev1@x.com' in recipients and 'rev2@x.com' in recipients
    assert 'owner@x.com' not in recipients


def test_submit_closes_the_reviewers_asset_review_and_the_request_stays_open_for_the_other(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    parts = _participants(mgr, db_session, rel)
    requests = _review_requests(db_session, mgr, rel, rm)
    first = requests['rev1@x.com']['review_request_id']
    second = requests['rev2@x.com']['review_request_id']

    mgr.submit_review(db_session, parts['rev1@x.com']['id'], {'q1': 'yes'},
                      user=_user('rev1@x.com'), reviews_manager=rm)
    db_session.commit()

    done = rm.get_review_request(first)
    assert done.status.value == 'approved'
    assert [a.status.value for a in done.assets] == ['approved']
    still_open = rm.get_review_request(second)
    assert still_open.status.value != 'approved'
    assert [a.status.value for a in still_open.assets] == ['pending']
    assert _review_requests(db_session, mgr, rel, rm)['rev2@x.com']['request_status'] != 'approved'
    assert mgr.get_review_tracking(db_session, rel.id, reviews_manager=rm)['all_reviewed'] is False


def test_all_reviewers_submitted_marks_the_review_complete(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    rm = _reviews_manager(db_session)
    mgr.start_review(db_session, rel.id, owner='owner@x.com', reviews_manager=rm)
    parts = _participants(mgr, db_session, rel)
    requests = _review_requests(db_session, mgr, rel, rm)

    for principal in ('rev1@x.com', 'rev2@x.com'):
        mgr.submit_review(db_session, parts[principal]['id'], {'q1': 'yes'},
                          user=_user(principal), reviews_manager=rm)
    db_session.commit()

    for principal in ('rev1@x.com', 'rev2@x.com'):
        request = rm.get_review_request(requests[principal]['review_request_id'])
        assert request.status.value == 'approved'
        assert all(a.status.value == 'approved' for a in request.assets)
    assert mgr.get_review_tracking(db_session, rel.id, reviews_manager=rm)['all_reviewed'] is True


def test_submit_without_an_asset_review_still_saves_the_answers(db_session):
    mgr, rel = _two_reviewer_ar(db_session)
    parts = _participants(mgr, db_session, rel)

    updated = mgr.submit_review(db_session, parts['rev1@x.com']['id'], {'q1': 'yes'},
                                user=_user('rev1@x.com'), reviews_manager=None)

    assert updated.review_status == 'completed'


def test_tracking_lists_only_this_ars_executions(db_session):
    """S10: the tracking's executions are filtered in the repository, not in Python."""
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
    tracking = mgr.get_review_tracking(db_session, rel.id, reviews_manager=None)
    assert {w['entity_id'] for w in tracking['workflows']} <= {rel.id}


def test_list_for_entity_ids_with_no_ids_queries_nothing(db_session):
    assert workflow_execution_repo.list_for_entity_ids(db_session, []) == []
