"""Built-in texts of workflow notification steps, and their i18n keys.

A notification step stores its title and message in English. The title comes
from the step's template (``TEMPLATE_TITLES``); the message is the step's
``custom_message``, else the template's message (``TEMPLATE_MESSAGES``).

``notification_step_i18n`` gives the ``data.i18n`` of such a notification
(see ``notification_i18n``), so the frontend shows the built-in texts in the
user's language:

- the title always, as it is built in;
- the message when it is the template's, or a ``custom_message`` that is still
  the one shipped in ``default_workflows.yaml``. A message an admin wrote or
  changed has no key and is shown as written.

``approval_notification_i18n`` does the same for the notification of an
approval step ("Approval Required"): its description is one line per fact
(requester, resource, permission ...), each sent with its key, and the step's
message translated while it is still the shipped one.

The keys are under ``notifications:workflowDefaults`` in the frontend locales
(``src/frontend/src/i18n/locales/<lang>/notifications.json``), where the
``${variable}`` placeholders of the texts are ``{{variable}}``.
"""
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import yaml

from src.common.notification_i18n import notification_i18n_data

logger = logging.getLogger(__name__)

DEFAULT_WORKFLOWS_PATH = Path(__file__).parent.parent / 'data' / 'default_workflows.yaml'

KEY_PREFIX = 'notifications:workflowDefaults'

# Titles and messages of the notification templates; ``{entity_type}`` and
# ``{entity_name}`` are filled in with str.format.
TEMPLATE_TITLES: Dict[str, str] = {
    'validation_failed': "Validation Failed",
    'validation_passed': "Validation Passed",
    'product_approved': "Data Product Approved",
    'product_rejected': "Data Product Rejected",
    'approval_requested': "Approval Requested",
    'request_submitted': "Request Submitted",
    'request_approved': "Request Approved",
    'request_rejected': "Request Denied",
    'dataset_updated': "Dataset Updated",
    'pii_detected': "PII Detected",
}
DEFAULT_TEMPLATE_TITLE = "Workflow Notification"

TEMPLATE_MESSAGES: Dict[str, str] = {
    'validation_failed': "Validation failed for {entity_type} '{entity_name}'",
    'validation_passed': "Validation passed for {entity_type} '{entity_name}'",
    'product_approved': "Data product '{entity_name}' has been approved",
    'product_rejected': "Data product '{entity_name}' has been rejected",
    'approval_requested': "Approval requested for {entity_type} '{entity_name}'",
    'request_submitted': "Your request for {entity_type} '{entity_name}' has been submitted and is pending review.",
    'request_approved': "Your request for {entity_type} '{entity_name}' has been approved.",
    'request_rejected': "Your request for {entity_type} '{entity_name}' has been denied.",
    'dataset_updated': "Dataset '{entity_name}' has been updated.",
    'pii_detected': "Potential PII detected in {entity_type} '{entity_name}'. Please review.",
}
DEFAULT_TEMPLATE_MESSAGE = "Workflow notification for {entity_name}"

# ${variable} and {{variable}}, as substitute_template reads them
PLACEHOLDER = re.compile(r'\$\{([^}]+)\}|\{\{([^}]+)\}\}')


def placeholders(text: str) -> list:
    """The placeholder names of a text, in order of appearance."""
    names = []
    for dollar, braces in PLACEHOLDER.findall(text):
        name = (dollar or braces).strip()
        if name not in names:
            names.append(name)
    return names


@lru_cache(maxsize=1)
def _default_workflows() -> List[Dict[str, Any]]:
    try:
        with open(DEFAULT_WORKFLOWS_PATH) as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Could not read the default workflows for notification texts: {e}")
        return []
    return data.get('workflows') or []


def _shipped_texts(step_type: str, field: str, group: str) -> Dict[str, str]:
    keys: Dict[str, str] = {}
    for workflow in _default_workflows():
        for step in workflow.get('steps') or []:
            text = (step.get('config') or {}).get(field)
            if step.get('type') == step_type and text:
                keys.setdefault(text, f"{KEY_PREFIX}.{group}.{workflow.get('id')}.{step.get('id')}")
    return keys


@lru_cache(maxsize=1)
def shipped_messages() -> Dict[str, str]:
    """The i18n key of each notification message shipped in the default workflows.

    By text: ``notifications:workflowDefaults.messages.<workflow id>.<step id>``.
    """
    return _shipped_texts('notification', 'custom_message', 'messages')


@lru_cache(maxsize=1)
def shipped_approval_messages() -> Dict[str, str]:
    """The i18n key of each approval step message shipped in the default workflows.

    By text: ``notifications:workflowDefaults.approvalMessages.<workflow id>.<step id>``.
    """
    return _shipped_texts('approval', 'message', 'approvalMessages')


def template_title_key(template: str) -> str:
    name = template if template in TEMPLATE_TITLES else 'default'
    return f"{KEY_PREFIX}.templates.{name}.title"


def template_message_key(template: str) -> str:
    name = template if template in TEMPLATE_MESSAGES else 'default'
    return f"{KEY_PREFIX}.templates.{name}.message"


def notification_step_i18n(
    template: str,
    custom_message: Optional[str],
    entity_type: Optional[str],
    entity_name: Optional[str],
    resolve: Callable[[str], str],
) -> Dict[str, Any]:
    """The ``data`` of a notification step's notification, with its i18n keys.

    ``entity_name`` is the name shown in template messages; ``resolve`` gives
    the value of a ``${variable}`` of a shipped message, as the step fills it in.
    """
    if not custom_message:
        return notification_i18n_data(
            template_title_key(template), template_message_key(template),
            entity_type=entity_type, entity_name=entity_name,
        )
    message_key = shipped_messages().get(custom_message)
    if not message_key:
        return notification_i18n_data(template_title_key(template))
    params = {name: resolve(name) for name in placeholders(custom_message)}
    return notification_i18n_data(template_title_key(template), message_key, **params)


# --- Approval notifications ------------------------------------------------

APPROVAL_TITLE = "Approval Required"

# Labelled lines of an approval notification's description, as
# ``_build_approval_description`` writes them ("<Label>: <value>"): the label,
# the line's key and the name of its value in the key's text. Resource and
# Duration lines are read on their own.
APPROVAL_LINES: Dict[str, tuple] = {
    'Requester': ('requester', 'requester'),
    'Permission': ('permission', 'permission'),
    'Reason': ('reason', 'reason'),
    'Workflow message': ('workflowMessage', 'message'),
    'Message': ('message', 'message'),
    'Justification': ('justification', 'justification'),
}
UNKNOWN_REQUESTER = "Unknown"
UNKNOWN_ENTITY_TYPE = "Entity"
DURATION_LINE = re.compile(r'^Duration: (\d+) days?$')


def _approval_text(key: str, text: str, **params: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {'key': f"{KEY_PREFIX}.approval.{key}", 'text': text}
    if params:
        entry['params'] = params
    return entry


def approval_notification_i18n(
    description: str,
    raw_message: Optional[str],
    message: Optional[str],
    resolve: Callable[[str], str],
    entity_type_labels: Mapping[str, str],
) -> Dict[str, Any]:
    """The ``data`` of an approval step's notification, with its i18n keys.

    ``description`` is the English description as built for the notification;
    each of its lines is sent as ``{key, params, text}`` in
    ``i18n.descriptionLines`` (a param can itself be such a text), and a line
    it doesn't know as ``{text}``. ``raw_message`` is the step's configured
    message and ``message`` the same with its ``${variables}`` filled in;
    ``resolve`` gives a variable's value. ``entity_type_labels`` are the labels
    of the entity types in the description (type → label).
    """
    types = {label: entity_type for entity_type, label in entity_type_labels.items()}
    types.setdefault(UNKNOWN_ENTITY_TYPE, 'entity')

    def entity_type(label: str) -> Any:
        if label in types:
            return _approval_text(f"entityTypes.{types[label]}", label)
        return label

    def line_text(line: str) -> Dict[str, Any]:
        duration = DURATION_LINE.match(line)
        if duration:
            return _approval_text('lines.duration', line, count=int(duration.group(1)))
        label, separator, value = line.partition(': ')
        if not separator:
            return {'text': line}
        if label == 'Resource':
            type_label, dot, name = value.partition(' · ')
            if dot:
                return _approval_text('lines.resource', line,
                                      resourceType=entity_type(type_label), resourceName=name)
            return _approval_text('lines.resourceType', line, resourceType=entity_type(value))
        if label not in APPROVAL_LINES:
            return {'text': line}
        key, param = APPROVAL_LINES[label]
        shown: Any = value
        if label == 'Requester' and value == UNKNOWN_REQUESTER:
            shown = _approval_text('lines.unknownRequester', value)
        elif label == 'Workflow message' and value == message:
            message_key = shipped_approval_messages().get(raw_message or '')
            if message_key:
                shown = {'key': message_key, 'text': value}
                params = {name: resolve(name) for name in placeholders(raw_message)}
                if params:
                    shown['params'] = params
        return _approval_text(f"lines.{key}", line, **{param: shown})

    return {'i18n': {
        'title': f"{KEY_PREFIX}.approval.title",
        'descriptionLines': [line_text(line) for line in description.split('\n')],
    }}
