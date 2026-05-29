# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from unittest.mock import MagicMock, patch

from src.common.workflow_executor import (
    WebhookStepHandler,
    StepContext,
)


def _ctx(**overrides) -> StepContext:
    """Build a StepContext with rich defaults for webhook param tests."""
    defaults = dict(
        entity={'name': 'sales_kpis', 'status': 'draft', 'owner': 'alice@co.com'},
        entity_type='data_product',
        entity_id='dp-abc-123',
        entity_name='sales_kpis',
        user_email='requester@co.com',
        trigger_context=None,
        execution_id='exec-xyz-789',
        workflow_id='wf-1',
        workflow_name='Subscribe On Behalf',
        step_results={},
        on_behalf_of=None,
    )
    defaults.update(overrides)
    return StepContext(**defaults)


def _make_handler(config):
    """Construct a WebhookStepHandler with a mock DB session."""
    return WebhookStepHandler(db=MagicMock(), config=config)


# =========================================================================
# Path composition helper
# =========================================================================


class TestComposePath:
    """`_compose_path` joins base path + suffix + query string correctly."""

    def test_empty_returns_root(self):
        assert WebhookStepHandler._compose_path('', '', {}) == '/'

    def test_base_only(self):
        assert WebhookStepHandler._compose_path('/api/foo', '', {}) == '/api/foo'

    def test_suffix_only(self):
        assert WebhookStepHandler._compose_path('', '/bar', {}) == '/bar'

    def test_join_no_duplicate_slash(self):
        assert WebhookStepHandler._compose_path('/api/foo', '/123', {}) == '/api/foo/123'

    def test_join_inserts_missing_slash(self):
        assert WebhookStepHandler._compose_path('/api/foo', '123', {}) == '/api/foo/123'

    def test_join_keeps_single_slash_when_base_ends_with_slash(self):
        assert WebhookStepHandler._compose_path('/api/foo/', '123', {}) == '/api/foo/123'

    def test_query_string_appended(self):
        out = WebhookStepHandler._compose_path('/api', '', {'a': '1', 'b': '2'})
        assert out.startswith('/api?')
        # urlencode order is preserved (Python 3.7+ dict insertion order).
        assert 'a=1' in out and 'b=2' in out

    def test_query_string_url_encoded(self):
        out = WebhookStepHandler._compose_path('/api', '', {'q': 'hello world & co'})
        assert 'q=hello+world+%26+co' in out

    def test_query_string_merges_with_existing(self):
        out = WebhookStepHandler._compose_path('/api?x=1', '', {'y': '2'})
        assert out == '/api?x=1&y=2'


# =========================================================================
# Config plumbing — UC Connection mode
# =========================================================================


class TestWebhookExtraParamsUcConnection:
    """Caller-supplied extras are substituted and forwarded to the UC SDK."""

    @patch('src.common.workspace_client.get_workspace_client')
    def test_additional_headers_merged_and_substituted(self, mock_get_ws):
        mock_ws = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_ws.serving_endpoints.http_request.return_value = mock_response
        mock_get_ws.return_value = mock_ws

        handler = _make_handler({
            'connection_name': 'servicenow-prod',
            'method': 'POST',
            'path': '/api/now/table/incident',
            'headers': {'Content-Type': 'application/json'},
            'additional_headers': {
                'X-Trace-Id': '${execution_id}',
                'X-Entity': '${entity_name}',
            },
        })
        result = handler.execute(_ctx())

        assert result.passed is True
        kwargs = mock_ws.serving_endpoints.http_request.call_args.kwargs
        sent_headers = kwargs['headers']
        assert sent_headers['Content-Type'] == 'application/json'
        assert sent_headers['X-Trace-Id'] == 'exec-xyz-789'
        assert sent_headers['X-Entity'] == 'sales_kpis'

    @patch('src.common.workspace_client.get_workspace_client')
    def test_additional_headers_override_base_headers_on_collision(self, mock_get_ws):
        """When the same header is in both `headers` and `additional_headers`,
        the additional (caller-supplied) value wins."""
        mock_ws = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_ws.serving_endpoints.http_request.return_value = mock_response
        mock_get_ws.return_value = mock_ws

        handler = _make_handler({
            'connection_name': 'svc',
            'headers': {'X-Source': 'static-default'},
            'additional_headers': {'X-Source': 'override-${entity_name}'},
        })
        handler.execute(_ctx())

        kwargs = mock_ws.serving_endpoints.http_request.call_args.kwargs
        assert kwargs['headers']['X-Source'] == 'override-sales_kpis'

    @patch('src.common.workspace_client.get_workspace_client')
    def test_additional_query_params_appended_to_path(self, mock_get_ws):
        mock_ws = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_ws.serving_endpoints.http_request.return_value = mock_response
        mock_get_ws.return_value = mock_ws

        handler = _make_handler({
            'connection_name': 'svc',
            'path': '/api/v1/items',
            'additional_query_params': {
                'caller': 'ontos',
                'entity': '${entity_name}',
            },
        })
        handler.execute(_ctx())

        kwargs = mock_ws.serving_endpoints.http_request.call_args.kwargs
        sent_path = kwargs['path']
        assert sent_path.startswith('/api/v1/items?')
        assert 'caller=ontos' in sent_path
        assert 'entity=sales_kpis' in sent_path

    @patch('src.common.workspace_client.get_workspace_client')
    def test_path_suffix_appended_and_substituted(self, mock_get_ws):
        mock_ws = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_ws.serving_endpoints.http_request.return_value = mock_response
        mock_get_ws.return_value = mock_ws

        handler = _make_handler({
            'connection_name': 'svc',
            'path': '/api/items',
            'path_suffix': '/${entity_id}',
        })
        handler.execute(_ctx())

        kwargs = mock_ws.serving_endpoints.http_request.call_args.kwargs
        assert kwargs['path'] == '/api/items/dp-abc-123'

    @patch('src.common.workspace_client.get_workspace_client')
    def test_path_suffix_and_query_params_combine(self, mock_get_ws):
        mock_ws = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_ws.serving_endpoints.http_request.return_value = mock_response
        mock_get_ws.return_value = mock_ws

        handler = _make_handler({
            'connection_name': 'svc',
            'path': '/api/items',
            'path_suffix': '/${entity_id}',
            'additional_query_params': {'caller': 'ontos'},
        })
        handler.execute(_ctx())

        sent_path = mock_ws.serving_endpoints.http_request.call_args.kwargs['path']
        assert sent_path == '/api/items/dp-abc-123?caller=ontos'

    @patch('src.common.workspace_client.get_workspace_client')
    def test_legacy_config_without_extras_still_works(self, mock_get_ws):
        """Existing webhook configs without the new fields must keep working."""
        mock_ws = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_ws.serving_endpoints.http_request.return_value = mock_response
        mock_get_ws.return_value = mock_ws

        handler = _make_handler({
            'connection_name': 'svc',
            'method': 'POST',
            'path': '/api/foo',
            'headers': {'X-Y': 'z'},
            'body_template': '{"name": "${entity_name}"}',
        })
        result = handler.execute(_ctx())

        assert result.passed is True
        kwargs = mock_ws.serving_endpoints.http_request.call_args.kwargs
        # Path unchanged when no suffix/query params provided.
        assert kwargs['path'] == '/api/foo'
        # Headers untouched.
        assert kwargs['headers'] == {'X-Y': 'z'}


# =========================================================================
# Config plumbing — inline URL mode (httpx fallback path)
# =========================================================================


class TestWebhookExtraParamsInlineMode:
    """Inline mode appends query params to the URL and merges headers."""

    @patch('httpx.Client')
    def test_inline_mode_appends_query_params_and_headers(self, mock_client_cls):
        # Set up httpx.Client context manager -> client.request -> response.
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = 'ok'
        mock_client.request.return_value = mock_response

        handler = _make_handler({
            'url': 'https://api.example.com/hook',
            'method': 'POST',
            'headers': {'X-Static': 'a'},
            'additional_headers': {'X-Dyn': '${entity_name}'},
            'additional_query_params': {'src': 'ontos'},
            'body_template': '{"hi": "${entity_name}"}',
        })
        result = handler.execute(_ctx())

        assert result.passed is True
        call_kwargs = mock_client.request.call_args.kwargs
        assert call_kwargs['url'] == 'https://api.example.com/hook?src=ontos'
        assert call_kwargs['headers']['X-Static'] == 'a'
        assert call_kwargs['headers']['X-Dyn'] == 'sales_kpis'

    @patch('httpx.Client')
    def test_inline_mode_appends_path_suffix_with_substitution(self, mock_client_cls):
        """path_suffix must land in the URL path BEFORE the query string in inline mode."""
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = 'ok'
        mock_client.request.return_value = mock_response

        handler = _make_handler({
            'url': 'https://api.example.com/hook',
            'method': 'POST',
            'path_suffix': '/extra/${entity_name}',
            'additional_query_params': {'tag': '${entity_name}'},
            'body_template': '{}',
        })
        result = handler.execute(_ctx())

        assert result.passed is True
        # Suffix substituted, joined with single slash, query string appended last.
        assert mock_client.request.call_args.kwargs['url'] == (
            'https://api.example.com/hook/extra/sales_kpis?tag=sales_kpis'
        )
