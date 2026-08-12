"""Tests for OntologyGeneratorManager with mocked LLM responses."""
import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.controller.ontology_generator_manager import (
    OntologyGeneratorManager,
    _tool_get_metadata,
    _tool_get_table_detail,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_METADATA = {
    "tables": [
        {
            "name": "customers",
            "full_name": "catalog.schema.customers",
            "comment": "Customer records",
            "columns": [
                {"name": "id", "type": "INT", "comment": "Primary key"},
                {"name": "first_name", "type": "STRING", "comment": "First name"},
                {"name": "email", "type": "STRING", "comment": "Email address"},
            ],
        },
        {
            "name": "orders",
            "full_name": "catalog.schema.orders",
            "comment": "Order records",
            "columns": [
                {"name": "order_id", "type": "INT", "comment": "Primary key"},
                {"name": "customer_id", "type": "INT", "comment": "Foreign key"},
                {"name": "total", "type": "DECIMAL", "comment": "Order total"},
            ],
        },
    ]
}

GENERATED_TURTLE = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix : <http://ontos.example.org/ontology#> .

<http://ontos.example.org/ontology> a owl:Ontology ;
    rdfs:label "E-commerce Ontology" .

:Customer a owl:Class ;
    rdfs:label "Customer" ;
    rdfs:comment "Represents a customer" .

:Order a owl:Class ;
    rdfs:label "Order" ;
    rdfs:comment "Represents an order" .

:firstName a owl:DatatypeProperty ;
    rdfs:label "firstName" ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string .

:email a owl:DatatypeProperty ;
    rdfs:label "email" ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string .

:hasOrder a owl:ObjectProperty ;
    rdfs:label "hasOrder" ;
    rdfs:domain :Customer ;
    rdfs:range :Order .
"""


def _make_settings(**overrides):
    s = MagicMock()
    s.LLM_ENABLED = overrides.get("llm_enabled", True)
    s.LLM_ENDPOINT = overrides.get("llm_endpoint", "databricks-claude-sonnet")
    s.LLM_BASE_URL = overrides.get("llm_base_url", "https://test.databricks.com/serving-endpoints")
    s.DATABRICKS_TOKEN = overrides.get("token", "dapi-fake-token")
    s.DATABRICKS_HOST = overrides.get("host", "https://test.databricks.com")
    return s


# ---------------------------------------------------------------------------
# Tool unit tests
# ---------------------------------------------------------------------------

class TestMetadataTools:
    def test_get_metadata_returns_tables(self):
        result = json.loads(_tool_get_metadata(SAMPLE_METADATA))
        assert "tables" in result
        assert len(result["tables"]) == 2
        assert result["tables"][0]["name"] == "customers"

    def test_get_metadata_empty(self):
        result = json.loads(_tool_get_metadata({"tables": []}))
        assert result["tables"] == []
        assert "error" in result

    def test_get_table_detail_found(self):
        result = json.loads(_tool_get_table_detail(SAMPLE_METADATA, table_name="customers"))
        assert result["name"] == "customers"
        assert len(result["columns"]) == 3

    def test_get_table_detail_by_full_name(self):
        result = json.loads(_tool_get_table_detail(SAMPLE_METADATA, table_name="catalog.schema.orders"))
        assert result["name"] == "orders"

    def test_get_table_detail_not_found(self):
        result = json.loads(_tool_get_table_detail(SAMPLE_METADATA, table_name="nonexistent"))
        assert "error" in result

    def test_get_table_detail_missing_name(self):
        result = json.loads(_tool_get_table_detail(SAMPLE_METADATA))
        assert "error" in result


# ---------------------------------------------------------------------------
# Manager tests with mocked LLM
# ---------------------------------------------------------------------------

@dataclass
class _FakeMessage:
    content: str = ""
    tool_calls: list = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


@dataclass
class _FakeToolCallFunction:
    name: str
    arguments: str


@dataclass
class _FakeToolCall:
    id: str
    function: _FakeToolCallFunction


@dataclass
class _FakeUsage:
    prompt_tokens: int = 100
    completion_tokens: int = 200


@dataclass
class _FakeChoice:
    message: _FakeMessage
    finish_reason: str = "stop"


@dataclass
class _FakeResponse:
    choices: list
    usage: _FakeUsage = None

    def __post_init__(self):
        if self.usage is None:
            self.usage = _FakeUsage()


class TestOntologyGeneratorManager:
    def test_disabled_llm(self):
        settings = _make_settings(llm_enabled=False)
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(SAMPLE_METADATA)
        assert not result.success
        assert "disabled" in result.error.lower()

    def test_no_endpoint(self):
        settings = _make_settings(llm_endpoint="")
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(SAMPLE_METADATA)
        assert not result.success
        assert "endpoint" in result.error.lower()

    @patch("src.common.llm_client.create_openai_client")
    def test_direct_turtle_output(self, mock_create_client):
        """LLM directly outputs Turtle without tool calls."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))]
        )
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(SAMPLE_METADATA)

        assert result.success
        assert "@prefix" in result.owl_content
        assert len(result.classes) == 2
        class_names = {c["name"] for c in result.classes}
        assert "Customer" in class_names
        assert "Order" in class_names
        assert result.iterations == 1
        mock_create_client.assert_called_once_with(settings, user_token=None)

    @patch("src.common.llm_client.create_openai_client")
    def test_tool_call_then_output(self, mock_create_client):
        """LLM calls get_metadata, then outputs Turtle on second iteration."""
        tool_call = _FakeToolCall(
            id="call_1",
            function=_FakeToolCallFunction(name="get_metadata", arguments="{}"),
        )

        responses = [
            _FakeResponse(choices=[_FakeChoice(message=_FakeMessage(content="", tool_calls=[tool_call]))]),
            _FakeResponse(choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))]),
        ]

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = responses
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(SAMPLE_METADATA)

        assert result.success
        assert result.iterations == 2
        step_types = [s.step_type for s in result.steps]
        assert "tool_call" in step_types
        assert "tool_result" in step_types
        assert "output" in step_types

    @patch("src.common.llm_client.create_openai_client")
    def test_selected_tables_filter(self, mock_create_client):
        """Only selected tables should reach the agent."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))]
        )
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(
            SAMPLE_METADATA,
            selected_tables=["catalog.schema.customers"],
        )

        assert result.success
        call_kwargs = mock_client.chat.completions.create.call_args
        user_msg = call_kwargs[1]["messages"][1]["content"] if "messages" in call_kwargs[1] else ""
        assert "catalog.schema.customers" in user_msg

    @patch("src.common.llm_client.create_openai_client")
    def test_token_usage_tracked(self, mock_create_client):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))],
            usage=_FakeUsage(prompt_tokens=500, completion_tokens=1000),
        )
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(SAMPLE_METADATA)

        assert result.usage["prompt_tokens"] == 500
        assert result.usage["completion_tokens"] == 1000

    @patch("src.common.llm_client.create_openai_client")
    def test_user_token_passed_through(self, mock_create_client):
        """user_token kwarg is forwarded to create_openai_client."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))]
        )
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        mgr.generate_ontology(SAMPLE_METADATA, user_token="obo-token-123")

        mock_create_client.assert_called_once_with(settings, user_token="obo-token-123")

    def test_extract_turtle_plain(self):
        content = "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n:A a owl:Class ."
        assert OntologyGeneratorManager._extract_turtle(content) == content

    def test_extract_turtle_with_preamble(self):
        content = "Here is the ontology:\n\n@prefix owl: <http://www.w3.org/2002/07/owl#> ."
        result = OntologyGeneratorManager._extract_turtle(content)
        assert result.startswith("@prefix")

    def test_extract_turtle_with_markdown_fence(self):
        content = "Some text\n```turtle\n@prefix : <http://example.org#> .\n:A a owl:Class .\n```\nmore text"
        result = OntologyGeneratorManager._extract_turtle(content)
        assert result.startswith("@prefix")
        assert "```" not in result


    @patch("src.common.llm_client.create_openai_client")
    def test_non_usable_output_triggers_repair(self, mock_create_client):
        """Test Fix 1: leaked-tool-call output triggers repair attempt."""
        # Simulating the exact leaked-tool-call output from the bug
        leaked_tool_call = 'get_table_detail(table_name=journal_entries)assistant\n\nget_table_detail(table_name="journal_entries")'

        responses = [
            _FakeResponse(choices=[_FakeChoice(message=_FakeMessage(content=leaked_tool_call))]),
            # Second attempt (repair): model returns valid Turtle
            _FakeResponse(choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))]),
        ]

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = responses
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(SAMPLE_METADATA)

        # Should succeed after repair
        assert result.success
        assert len(result.classes) > 0
        # Should have called LLM twice (initial + repair)
        assert mock_client.chat.completions.create.call_count >= 2

    @patch("src.common.llm_client.create_openai_client")
    def test_empty_ontology_fails(self, mock_create_client):
        """Test Fix 1: Turtle with 0 classes and 0 properties is not usable."""
        empty_turtle = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix : <http://ontos.example.org/ontology#> .

<http://ontos.example.org/ontology> a owl:Ontology ;
    rdfs:label "Empty Ontology" .
"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=empty_turtle))]
        )
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(SAMPLE_METADATA)

        # Should fail because ontology has no classes/properties
        assert not result.success
        assert "no classes or properties" in result.error.lower()

    @patch("src.common.llm_client.create_openai_client")
    def test_truncated_output_continuation(self, mock_create_client):
        """Test Fix 2: truncated output (finish_reason='length') triggers continuation."""
        # First response is truncated (finish_reason='length')
        response1 = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))]
        )
        response1.choices[0].finish_reason = "length"

        # Second response (continuation) also returns valid Turtle
        response2 = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))]
        )
        response2.choices[0].finish_reason = "stop"

        mock_client = MagicMock()
        # First call returns truncated, second call (continuation) returns complete
        mock_client.chat.completions.create.side_effect = [response1, response2]
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(SAMPLE_METADATA)

        # Should succeed after continuation
        assert result.success
        assert len(result.classes) >= 2
        # Should have called LLM twice (initial + continuation)
        assert mock_client.chat.completions.create.call_count == 2

    def test_is_usable_turtle_valid(self):
        """Test _is_usable_turtle with valid Turtle."""
        usable, error = OntologyGeneratorManager._is_usable_turtle(GENERATED_TURTLE)
        assert usable is True
        assert error is None

    def test_is_usable_turtle_invalid_syntax(self):
        """Test _is_usable_turtle with invalid Turtle syntax."""
        invalid_turtle = "this is not turtle @@@"
        usable, error = OntologyGeneratorManager._is_usable_turtle(invalid_turtle)
        assert usable is False
        assert error is not None

    def test_is_usable_turtle_no_classes_or_properties(self):
        """Test _is_usable_turtle with empty ontology."""
        empty_turtle = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<http://example.org/ontology> a owl:Ontology .
"""
        usable, error = OntologyGeneratorManager._is_usable_turtle(empty_turtle)
        assert usable is False
        assert "no classes or properties" in error.lower()

    @patch("src.common.llm_client.create_openai_client")
    def test_caps_note_populated(self, mock_create_client):
        """Test Fix 4: caps_hit and caps_note are populated when tables exceed cap."""
        # Create metadata with more tables than _MAX_TABLES_IN_METADATA
        large_metadata = {
            "tables": [
                {
                    "name": f"table_{i}",
                    "full_name": f"cat.schema.table_{i}",
                    "comment": f"Table {i}",
                    "columns": [
                        {"name": "id", "type": "INT", "comment": "ID"},
                        {"name": "name", "type": "STRING", "comment": "Name"},
                    ],
                }
                for i in range(100)  # Way more than _MAX_TABLES_IN_METADATA (50)
            ]
        }

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=GENERATED_TURTLE))]
        )
        mock_create_client.return_value = mock_client

        settings = _make_settings()
        mgr = OntologyGeneratorManager(settings)
        result = mgr.generate_ontology(large_metadata)

        # Should have populated cap fields
        assert result.tables_resolved == 100
        assert result.tables_used <= 50
        assert result.caps_hit is True
        assert result.caps_note != ""


class TestResolveTablesFromConnector:
    def test_resolves_table_paths(self):
        connector = MagicMock()
        meta = MagicMock()
        meta.name = "my_table"
        meta.identifier = "cat.schema.my_table"
        meta.description = "A table"
        meta.comment = ""
        col = MagicMock()
        col.name = "col1"
        col.data_type = "STRING"
        col.description = "a col"
        meta.schema_info.columns = [col]
        connector.get_asset_metadata.return_value = meta

        result = OntologyGeneratorManager.resolve_tables_from_connector(
            connector, ["cat.schema.my_table"]
        )

        assert len(result) == 1
        assert result[0]["name"] == "my_table"
        assert result[0]["columns"][0]["name"] == "col1"

    def test_respects_max_depth(self):
        connector = MagicMock()
        connector.get_asset_metadata.return_value = None
        connector.list_containers.return_value = [{"path": "deep/nested"}]
        connector.list_assets.return_value = []

        result = OntologyGeneratorManager.resolve_tables_from_connector(
            connector, ["root"], max_depth=0,
        )

        assert result == []
