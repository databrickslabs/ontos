"""
Shared test helper functions and utilities.
"""
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, MagicMock
from datetime import datetime
from databricks.sdk import WorkspaceClient
from sqlalchemy import event


def create_mock_table(
    name: str = "test_table",
    catalog_name: str = "test_catalog",
    schema_name: str = "test_schema",
    table_type: str = "MANAGED",
    comment: Optional[str] = None,
    columns: Optional[List[Dict[str, Any]]] = None,
) -> Mock:
    """
    Create a mock Databricks table object.

    Args:
        name: Table name
        catalog_name: Catalog name
        schema_name: Schema name
        table_type: Type of table (MANAGED, EXTERNAL, VIEW)
        comment: Table comment/description
        columns: List of column definitions

    Returns:
        Mock table object
    """
    if columns is None:
        columns = [
            {"name": "id", "type_text": "bigint", "comment": "ID column"},
            {"name": "name", "type_text": "string", "comment": "Name column"},
        ]

    table_mock = Mock()
    table_mock.name = name
    table_mock.catalog_name = catalog_name
    table_mock.schema_name = schema_name
    table_mock.table_type = table_type
    table_mock.comment = comment
    table_mock.columns = [Mock(**col) for col in columns]
    table_mock.full_name = f"{catalog_name}.{schema_name}.{name}"
    table_mock.created_at = int(datetime.now().timestamp() * 1000)
    table_mock.updated_at = int(datetime.now().timestamp() * 1000)

    return table_mock


def create_mock_catalog(
    name: str = "test_catalog",
    comment: Optional[str] = None,
    properties: Optional[Dict[str, str]] = None,
) -> Mock:
    """
    Create a mock Databricks catalog object.

    Args:
        name: Catalog name
        comment: Catalog comment/description
        properties: Catalog properties

    Returns:
        Mock catalog object
    """
    catalog_mock = Mock()
    catalog_mock.name = name
    catalog_mock.comment = comment or f"Test catalog {name}"
    catalog_mock.properties = properties or {}
    catalog_mock.created_at = int(datetime.now().timestamp() * 1000)

    return catalog_mock


def create_mock_schema(
    name: str = "test_schema",
    catalog_name: str = "test_catalog",
    comment: Optional[str] = None,
) -> Mock:
    """
    Create a mock Databricks schema object.

    Args:
        name: Schema name
        catalog_name: Parent catalog name
        comment: Schema comment/description

    Returns:
        Mock schema object
    """
    schema_mock = Mock()
    schema_mock.name = name
    schema_mock.catalog_name = catalog_name
    schema_mock.comment = comment or f"Test schema {name}"
    schema_mock.full_name = f"{catalog_name}.{name}"
    schema_mock.created_at = int(datetime.now().timestamp() * 1000)

    return schema_mock


def create_mock_job(
    job_id: str = "123456",
    job_name: str = "test_job",
    status: str = "RUNNING",
) -> Mock:
    """
    Create a mock Databricks job object.

    Args:
        job_id: Job ID
        job_name: Job name
        status: Job status

    Returns:
        Mock job object
    """
    job_mock = Mock()
    job_mock.job_id = job_id
    job_mock.settings = Mock()
    job_mock.settings.name = job_name
    job_mock.state = Mock()
    job_mock.state.life_cycle_state = status

    return job_mock


def create_mock_workspace_client_with_data(
    catalogs: Optional[List[str]] = None,
    schemas: Optional[Dict[str, List[str]]] = None,
    tables: Optional[Dict[str, List[str]]] = None,
) -> MagicMock:
    """
    Create a mock WorkspaceClient with realistic test data.

    Args:
        catalogs: List of catalog names to mock
        schemas: Dict mapping catalog names to schema names
        tables: Dict mapping schema full names to table names

    Returns:
        Configured MagicMock of WorkspaceClient
    """
    mock_client = MagicMock(spec=WorkspaceClient)

    # Set up catalog mocks
    if catalogs:
        mock_client.catalogs.list.return_value = [
            create_mock_catalog(name=cat) for cat in catalogs
        ]

    # Set up schema mocks
    if schemas:
        def get_schemas(catalog_name: str):
            return [
                create_mock_schema(name=sch, catalog_name=catalog_name)
                for sch in schemas.get(catalog_name, [])
            ]
        mock_client.schemas.list.side_effect = get_schemas

    # Set up table mocks
    if tables:
        def get_tables(catalog_name: str, schema_name: str):
            full_schema = f"{catalog_name}.{schema_name}"
            return [
                create_mock_table(
                    name=tbl,
                    catalog_name=catalog_name,
                    schema_name=schema_name
                )
                for tbl in tables.get(full_schema, [])
            ]
        mock_client.tables.list.side_effect = get_tables

    # Default empty responses for other operations
    mock_client.jobs.list.return_value = []
    mock_client.workspace.list.return_value = []
    mock_client.clusters.list.return_value = []

    return mock_client


def assert_audit_log_created(
    db_session,
    feature: str,
    action: str,
    username: str = "test_user",
    success: bool = True,
):
    """
    Assert that an audit log entry was created with expected values.

    Args:
        db_session: Database session
        feature: Feature name
        action: Action name
        username: Expected username
        success: Expected success status
    """
    from src.db_models.audit_log import AuditLogDb

    audit = (
        db_session.query(AuditLogDb)
        .filter_by(feature=feature, action=action, username=username)
        .order_by(AuditLogDb.timestamp.desc())
        .first()
    )

    assert audit is not None, f"No audit log found for {feature}/{action}"
    assert audit.success == success, f"Expected success={success}, got {audit.success}"


def create_sample_data_product_dict() -> Dict[str, Any]:
    """
    Create sample data product dictionary for testing.

    Returns:
        Sample data product as dict
    """
    return {
        "name": "Test Data Product",
        "description": "A test data product",
        "version": "1.0.0",
        "status": "draft",
        "owner": "test@example.com",
        "domain": "test_domain",
        "tags": ["test", "sample"],
    }


def create_sample_data_contract_dict() -> Dict[str, Any]:
    """
    Create sample data contract dictionary for testing.

    Returns:
        Sample data contract as dict
    """
    return {
        "name": "Test Data Contract",
        "description": "A test data contract",
        "version": "1.0.0",
        "status": "draft",
        "owner": "test@example.com",
        "schema": {
            "fields": [
                {"name": "id", "type": "integer", "required": True},
                {"name": "name", "type": "string", "required": True},
            ]
        },
    }


def create_sample_team_dict() -> Dict[str, Any]:
    """
    Create sample team dictionary for testing.

    Returns:
        Sample team as dict
    """
    return {
        "name": "Test Team",
        "description": "A test team",
        "email": "team@example.com",
        "members": ["user1@example.com", "user2@example.com"],
    }


def create_sample_domain_dict() -> Dict[str, Any]:
    """
    Create sample data domain dictionary for testing.

    Returns:
        Sample domain as dict
    """
    return {
        "name": "Test Domain",
        "description": "A test data domain",
        "owner": "test@example.com",
        "parent_id": None,
    }


def compare_dicts_ignore_keys(
    dict1: Dict[str, Any],
    dict2: Dict[str, Any],
    ignore_keys: List[str],
) -> bool:
    """
    Compare two dictionaries, ignoring specified keys.

    Args:
        dict1: First dictionary
        dict2: Second dictionary
        ignore_keys: Keys to ignore in comparison

    Returns:
        True if dictionaries match (excluding ignored keys)
    """
    filtered_dict1 = {k: v for k, v in dict1.items() if k not in ignore_keys}
    filtered_dict2 = {k: v for k, v in dict2.items() if k not in ignore_keys}

    return filtered_dict1 == filtered_dict2


@contextmanager
def postgres_aborts(db):
    """Make the test connection behave like Postgres after a failed statement:
    every later statement fails until a ``ROLLBACK`` (to a savepoint)."""
    connection = db.connection()
    state = {'running': False, 'aborted': False}

    def _before(conn, cursor, statement, *args):
        if state['running']:  # the previous statement raised
            state['aborted'] = True
        if state['aborted']:
            if not statement.lstrip().upper().startswith('ROLLBACK'):
                raise RuntimeError('current transaction is aborted')
            state['aborted'] = False
        state['running'] = True

    def _after(*args):
        state['running'] = False

    event.listen(connection, 'before_cursor_execute', _before)
    event.listen(connection, 'after_cursor_execute', _after)
    try:
        yield
    finally:
        event.remove(connection, 'before_cursor_execute', _before)
        event.remove(connection, 'after_cursor_execute', _after)


def llm_reply(content, finish_reason='stop', refusal=None):
    """A chat completion as the OpenAI client returns it, with one choice."""
    from types import SimpleNamespace

    message = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


class FakeLlm:
    """An OpenAI-like client for LLM tests.

    ``chat.completions.create`` records its arguments in ``calls`` and answers
    with the given replies in turn (the last one repeats), or with
    ``answer(kwargs)`` when given. An exception reply is raised.
    """

    def __init__(self, *replies, answer=None):
        from types import SimpleNamespace

        self.replies = list(replies)
        self.answer = answer
        self.calls: List[Dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.answer is not None:
            return self.answer(kwargs)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply
