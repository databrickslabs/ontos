"""Notifications can carry i18n keys for the frontend to translate their texts."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import datetime

from src.common.notification_i18n import notification_i18n_data
from src.models.notifications import Notification, NotificationType
from src.repositories.notification_repository import notification_repo


def test_keys_and_params():
    assert notification_i18n_data(
        'notifications:statusChangeNotApplied.title',
        'notifications:statusChangeNotApplied.refused',
        toStatus='deprecated', reason='Invalid status transition',
    ) == {'i18n': {
        'title': 'notifications:statusChangeNotApplied.title',
        'description': 'notifications:statusChangeNotApplied.refused',
        'params': {'toStatus': 'deprecated', 'reason': 'Invalid status transition'},
    }}


def test_title_only_and_params_as_text():
    assert notification_i18n_data('ns:key') == {'i18n': {'title': 'ns:key'}}
    assert notification_i18n_data('ns:key', count=3, none=None)['i18n']['params'] == {
        'count': '3', 'none': '',
    }


def test_the_keys_are_stored_and_read_back_with_the_english_texts(db_session):
    created = notification_repo.create(db=db_session, obj_in=Notification(
        id=str(uuid.uuid4()), created_at=datetime.utcnow(), type=NotificationType.WARNING,
        title='Status change not applied', description="... the status is now 'sandbox' ...",
        recipient='rita@example.com',
        data=notification_i18n_data(
            'notifications:statusChangeNotApplied.title',
            'notifications:statusChangeNotApplied.statusChanged',
            fromStatus='draft', toStatus='proposed', currentStatus='sandbox',
        ),
    ))
    db_session.flush()

    read = Notification.model_validate(notification_repo.get(db_session, id=created.id))
    assert read.title == 'Status change not applied'
    assert read.data['i18n']['description'] == 'notifications:statusChangeNotApplied.statusChanged'
    assert read.data['i18n']['params']['currentStatus'] == 'sandbox'
