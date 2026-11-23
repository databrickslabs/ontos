"""One rule for a request body that sends a field under two spellings.

A model field with an alias can be sent as its name or its alias (``populate_by_name``),
for example ``domainIds`` and ``domain_ids``. When a body sends both, the camelCase
spelling (the one without an underscore, the documented input) wins and the other one is
ignored, on create and update alike. Pydantic alone reads the alias first, which made the
winner depend on which spelling a model declares as the alias.
"""
from typing import Any, List

from pydantic import AliasChoices, BaseModel, model_validator


def _spellings(name: str, field) -> List[str]:
    """The field's name, its alias and its string validation aliases, in that order."""
    spellings = [name]
    choices = field.validation_alias
    extra = choices.choices if isinstance(choices, AliasChoices) else [choices]
    for spelling in [field.alias, *extra]:
        if isinstance(spelling, str) and spelling not in spellings:
            spellings.append(spelling)
    return spellings


def camel_case_spelling_wins(model: type[BaseModel], data: Any) -> Any:
    """``data`` without the other spellings of a field also sent in camelCase.

    Only a field sent under two or more spellings changes, and only when one of them is
    camelCase; any other input is returned as is. Needs ``populate_by_name`` (else only
    the alias is read, and dropping it would lose the value).
    """
    if not isinstance(data, dict) or not model.model_config.get('populate_by_name'):
        return data
    result = data
    for name, field in model.model_fields.items():
        sent = [s for s in _spellings(name, field) if s in data]
        winner = next((s for s in sent if '_' not in s), None)
        if len(sent) < 2 or winner is None:
            continue
        if result is data:
            result = dict(data)
        for spelling in sent:
            if spelling != winner:
                result.pop(spelling)
    return result


class CamelCaseSpellingWins(BaseModel):
    """Base for request models: a field sent as camelCase and snake_case reads camelCase."""

    @model_validator(mode='before')
    @classmethod
    def _camel_case_spelling_wins(cls, data: Any) -> Any:
        return camel_case_spelling_wins(cls, data)
