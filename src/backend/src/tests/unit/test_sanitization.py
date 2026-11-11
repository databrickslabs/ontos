"""
Unit tests for sanitization utilities

Tests HTML/Markdown sanitization including:
- XSS prevention
- Allowed tags preservation
- Malicious script removal
"""
import pytest

from src.common.sanitization import (
    APP_DISPLAY_NAME_MAX_LEN,
    APP_SHORT_NAME_MAX_LEN,
    coerce_hex_color,
    sanitize_app_display_name,
    sanitize_markdown_input,
    validate_branding_url,
    validate_hex_color,
)


class TestSanitization:
    """Test suite for sanitization utilities"""

    def test_sanitize_simple_text(self):
        """Test sanitization of plain text."""
        result = sanitize_markdown_input("Hello World")
        assert result == "Hello World"

    def test_sanitize_allowed_tags(self):
        """Test that allowed tags are preserved."""
        input_text = "<b>bold</b> <i>italic</i> <strong>strong</strong>"
        result = sanitize_markdown_input(input_text)
        assert "<b>bold</b>" in result
        assert "<i>italic</i>" in result
        assert "<strong>strong</strong>" in result

    def test_sanitize_script_tag(self):
        """Test that script tags are removed."""
        input_text = "<script>alert('xss')</script>Safe text"
        result = sanitize_markdown_input(input_text)
        assert "<script>" not in result
        # Note: bleach strips tags but keeps text content
        assert "Safe text" in result

    def test_sanitize_onclick_attribute(self):
        """Test that onclick attributes are removed."""
        input_text = '<a href="#" onclick="alert(\'xss\')">Click</a>'
        result = sanitize_markdown_input(input_text)
        assert "onclick" not in result
        assert "Click" in result

    def test_sanitize_allowed_link(self):
        """Test that allowed link attributes are preserved."""
        input_text = '<a href="https://example.com" title="Example">Link</a>'
        result = sanitize_markdown_input(input_text)
        assert "href" in result
        assert "https://example.com" in result
        assert "title" in result

    def test_sanitize_iframe_tag(self):
        """Test that iframe tags are removed."""
        input_text = '<iframe src="malicious.com"></iframe>Safe content'
        result = sanitize_markdown_input(input_text)
        assert "<iframe" not in result
        assert "Safe content" in result

    def test_sanitize_img_tag(self):
        """Test that img tags are removed (not in allowed list)."""
        input_text = '<img src="image.png" onerror="alert(\'xss\')">Text'
        result = sanitize_markdown_input(input_text)
        assert "<img" not in result
        assert "Text" in result

    def test_sanitize_list_tags(self):
        """Test that list tags are preserved."""
        input_text = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        result = sanitize_markdown_input(input_text)
        assert "<ul>" in result
        assert "<li>Item 1</li>" in result

    def test_sanitize_code_tags(self):
        """Test that code and pre tags are preserved."""
        input_text = "<pre><code>print('hello')</code></pre>"
        result = sanitize_markdown_input(input_text)
        assert "<pre>" in result
        assert "<code>" in result
        assert "print" in result

    def test_sanitize_blockquote(self):
        """Test that blockquote tags are preserved."""
        input_text = "<blockquote>Quoted text</blockquote>"
        result = sanitize_markdown_input(input_text)
        assert "<blockquote>Quoted text</blockquote>" in result

    def test_sanitize_empty_string(self):
        """Test sanitization of empty string."""
        result = sanitize_markdown_input("")
        assert result == ""

    def test_sanitize_mixed_content(self):
        """Test sanitization of mixed safe and unsafe content."""
        input_text = """
        <h1>Title</h1>
        <p>Safe paragraph</p>
        <script>malicious()</script>
        <b>Bold text</b>
        <a href="javascript:void(0)">Bad link</a>
        """
        result = sanitize_markdown_input(input_text)
        assert "<script>" not in result
        # Note: bleach strips tags but keeps text content
        assert "<p>Safe paragraph</p>" in result
        assert "<b>Bold text</b>" in result
        # h1 is not in allowed tags
        assert "<h1>" not in result

    def test_sanitize_nested_tags(self):
        """Test sanitization of nested tags."""
        input_text = "<p><strong><em>Nested text</em></strong></p>"
        result = sanitize_markdown_input(input_text)
        assert "<p>" in result
        assert "<strong>" in result
        assert "<em>" in result
        assert "Nested text" in result


class TestAppDisplayNameSanitization:
    """Unit tests for sanitize_app_display_name (issue #240)."""

    def test_none_returns_none(self):
        assert sanitize_app_display_name(None) is None

    def test_empty_returns_none(self):
        assert sanitize_app_display_name("") is None

    def test_whitespace_only_returns_none(self):
        assert sanitize_app_display_name("   \t \n ") is None

    def test_trims_surrounding_whitespace(self):
        assert sanitize_app_display_name("  Acme Catalog  ") == "Acme Catalog"

    def test_strips_control_characters(self):
        assert sanitize_app_display_name("Acme\x00Catalog\x07") == "AcmeCatalog"

    def test_max_length_default(self):
        ok = "X" * APP_DISPLAY_NAME_MAX_LEN
        assert sanitize_app_display_name(ok) == ok

    def test_max_length_default_exceeded_raises(self):
        with pytest.raises(ValueError):
            sanitize_app_display_name("X" * (APP_DISPLAY_NAME_MAX_LEN + 1))

    def test_short_name_max_length_enforced(self):
        with pytest.raises(ValueError):
            sanitize_app_display_name(
                "X" * (APP_SHORT_NAME_MAX_LEN + 1),
                max_len=APP_SHORT_NAME_MAX_LEN,
            )

    def test_non_string_raises(self):
        with pytest.raises(ValueError):
            sanitize_app_display_name(123)  # type: ignore[arg-type]


class TestBrandingUrlValidation:
    """Unit tests for validate_branding_url (issue #240)."""

    def test_none_returns_none(self):
        assert validate_branding_url(None) is None

    def test_empty_returns_none(self):
        assert validate_branding_url("") is None

    def test_whitespace_only_returns_none(self):
        assert validate_branding_url("   ") is None

    def test_http_allowed(self):
        url = "http://example.com/favicon.svg"
        assert validate_branding_url(url) == url

    def test_https_allowed(self):
        url = "https://example.com/favicon.svg"
        assert validate_branding_url(url) == url

    def test_strips_surrounding_whitespace(self):
        assert (
            validate_branding_url("  https://example.com/x.png  ")
            == "https://example.com/x.png"
        )

    def test_rejects_javascript_scheme(self):
        with pytest.raises(ValueError):
            validate_branding_url("javascript:alert(1)")

    def test_rejects_data_scheme(self):
        with pytest.raises(ValueError):
            validate_branding_url("data:image/png;base64,AAAA")

    def test_rejects_file_scheme(self):
        with pytest.raises(ValueError):
            validate_branding_url("file:///etc/passwd")

    def test_rejects_missing_host(self):
        with pytest.raises(ValueError):
            validate_branding_url("https://")

    def test_rejects_scheme_only(self):
        with pytest.raises(ValueError):
            validate_branding_url("not-a-url")

    def test_non_string_raises(self):
        with pytest.raises(ValueError):
            validate_branding_url(123)  # type: ignore[arg-type]



class TestBrandingAssetPath:
    """Root-relative app asset paths are accepted as branding URLs."""

    def test_root_relative_path_allowed(self):
        path = "/branding/acme/logo.svg"
        assert validate_branding_url(path) == path

    @pytest.mark.parametrize("value", [
        "//evil.example/x.svg", "/a b.svg", "/a\\b.svg",
        "/../etc/x.svg", "/branding/../../x.svg", "/branding/%2e%2e/x.svg",
        "/a\tb.svg",
    ])
    def test_rejects_other_origin_or_odd_paths(self, value):
        with pytest.raises(ValueError):
            validate_branding_url(value)

    def test_dots_inside_a_file_name_are_fine(self):
        assert validate_branding_url("/branding/logo..v2.svg") == "/branding/logo..v2.svg"


class TestHexColorValidation:
    """Theme colors end up in injected CSS, so only #rgb / #rrggbb pass."""

    def test_none_and_empty_return_none(self):
        assert validate_hex_color(None) is None
        assert validate_hex_color("  ") is None

    def test_normalizes_case_and_short_form(self):
        assert validate_hex_color(" #2563eb ") == "#2563eb"
        assert validate_hex_color("#F0a") == "#ff00aa"

    @pytest.mark.parametrize(
        "value", ["red", "#12345", "#gggggg", "2563eb", "#fff;}body{x:y", "rgb(1,2,3)"]
    )
    def test_rejects_non_hex(self, value):
        with pytest.raises(ValueError):
            validate_hex_color(value)

    def test_coerce_returns_none_for_invalid(self):
        assert coerce_hex_color("#fff;}") is None
        assert coerce_hex_color("#ABCDEF") == "#abcdef"
