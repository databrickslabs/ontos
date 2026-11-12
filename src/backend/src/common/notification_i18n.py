"""Translation keys for notification texts.

Notifications store their texts in English (``title``, ``description``). To let
the frontend show them in the user's language, a notification may also carry
i18n keys and the values to fill in, in its ``data``::

    data = {"i18n": {"title": "notifications:statusChangeNotApplied.title",
                     "description": "notifications:statusChangeNotApplied.statusChanged",
                     "params": {"fromStatus": "draft", "toStatus": "proposed"}}}

The keys are ``<namespace>:<key>`` keys of the frontend locale files (e.g.
``src/frontend/src/i18n/locales/<lang>/notifications.json``); the params are
the ``{{placeholders}}`` of those texts. The English ``title`` /
``description`` stay the fallback for keys a locale doesn't have and for
clients that don't translate.
"""
from typing import Any, Dict, Optional


def notification_i18n_data(
    title_key: str,
    description_key: Optional[str] = None,
    **params: Any,
) -> Dict[str, Any]:
    """The ``data`` for a notification whose texts the frontend translates.

    Merge it into existing ``data`` with ``{**data, **notification_i18n_data(...)}``.
    Params are converted to strings, as they are shown in the text.
    """
    i18n: Dict[str, Any] = {'title': title_key}
    if description_key:
        i18n['description'] = description_key
    if params:
        i18n['params'] = {k: '' if v is None else str(v) for k, v in params.items()}
    return {'i18n': i18n}
