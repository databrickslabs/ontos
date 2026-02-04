"""Tests for SPARQL query security and validation."""

import pytest
from src.common.sparql_validator import SPARQLQueryValidator


class TestSPARQLQueryValidator:
    """Test SPARQL query validation for security."""
    
    def test_valid_select_query(self):
        """Test that valid SELECT queries pass validation."""
        query = """
        SELECT ?subject ?predicate ?object
        WHERE {
            ?subject ?predicate ?object .
        }
        LIMIT 10
        """
        error = SPARQLQueryValidator.validate(query)
        assert error is None, f"Valid query should pass: {error}"
    
    def test_valid_ask_query(self):
        """Test that valid ASK queries pass validation."""
        query = "ASK { ?s ?p ?o }"
        error = SPARQLQueryValidator.validate(query)
        assert error is None, f"Valid ASK query should pass: {error}"
    
    def test_valid_describe_query(self):
        """Test that valid DESCRIBE queries pass validation."""
        query = "DESCRIBE <http://example.org/resource>"
        error = SPARQLQueryValidator.validate(query)
        assert error is None, f"Valid DESCRIBE query should pass: {error}"
    
    def test_valid_construct_query(self):
        """Test that valid CONSTRUCT queries pass validation."""
        query = """
        CONSTRUCT { ?s ?p ?o }
        WHERE { ?s ?p ?o }
        LIMIT 100
        """
        error = SPARQLQueryValidator.validate(query)
        assert error is None, f"Valid CONSTRUCT query should pass: {error}"
    
    def test_empty_query(self):
        """Test that empty queries are rejected."""
        error = SPARQLQueryValidator.validate("")
        assert error is not None
        assert "empty" in error.lower()
    
    def test_insert_query_rejected(self):
        """Test that INSERT queries are rejected."""
        query = """
        INSERT DATA {
            <http://example.org/subject> <http://example.org/predicate> "value" .
        }
        """
        error = SPARQLQueryValidator.validate(query)
        assert error is not None
        assert "INSERT" in error
        assert "forbidden" in error.lower()
    
    def test_delete_query_rejected(self):
        """Test that DELETE queries are rejected."""
        query = """
        DELETE WHERE {
            ?s ?p "old_value"
        }
        """
        error = SPARQLQueryValidator.validate(query)
        assert error is not None
        assert "DELETE" in error
        assert "forbidden" in error.lower()
    
    def test_drop_query_rejected(self):
        """Test that DROP queries are rejected."""
        query = "DROP GRAPH <http://example.org/graph>"
        error = SPARQLQueryValidator.validate(query)
        assert error is not None
        assert "DROP" in error
        assert "forbidden" in error.lower()
    
    def test_update_query_rejected(self):
        """Test that UPDATE queries are rejected."""
        query = """
        DELETE { ?s ?p ?old }
        INSERT { ?s ?p ?new }
        WHERE { ?s ?p ?old }
        """
        error = SPARQLQueryValidator.validate(query)
        assert error is not None
        # Should catch either DELETE or INSERT
        assert any(kw in error for kw in ["DELETE", "INSERT"])
    
    def test_query_too_long(self):
        """Test that overly long queries are rejected."""
        # Create a query longer than MAX_QUERY_LENGTH
        long_query = "SELECT * WHERE { " + ("?s ?p ?o . " * 2000) + "}"
        error = SPARQLQueryValidator.validate(long_query)
        assert error is not None
        assert "too long" in error.lower()
    
    def test_too_many_unions(self):
        """Test that queries with too many UNION clauses are rejected."""
        # Create query with excessive UNIONs
        unions = " UNION ".join(["{ ?s ?p ?o }"] * 25)
        query = f"SELECT * WHERE {{ {unions} }}"
        error = SPARQLQueryValidator.validate(query)
        assert error is not None
        assert "UNION" in error
    
    def test_too_many_optionals(self):
        """Test that queries with too many OPTIONAL clauses are rejected."""
        # Create query with excessive OPTIONALs
        optionals = "\n".join([f"OPTIONAL {{ ?s{i} ?p{i} ?o{i} }}" for i in range(35)])
        query = f"SELECT * WHERE {{ ?s ?p ?o . {optionals} }}"
        error = SPARQLQueryValidator.validate(query)
        assert error is not None
        assert "OPTIONAL" in error
    
    def test_query_without_valid_type(self):
        """Test that queries without valid type keywords are rejected."""
        query = "{ ?s ?p ?o }"  # Missing SELECT/ASK/etc
        error = SPARQLQueryValidator.validate(query)
        assert error is not None
        assert "must contain one of" in error.lower() or "must start with" in error.lower() or "must be" in error.lower()
    
    def test_case_insensitive_keyword_detection(self):
        """Test that forbidden keywords are detected case-insensitively."""
        queries = [
            "insert data { <s> <p> <o> }",
            "INSERT data { <s> <p> <o> }",
            "InSeRt data { <s> <p> <o> }",
        ]
        for query in queries:
            error = SPARQLQueryValidator.validate(query)
            assert error is not None, f"Should reject: {query}"
            assert "INSERT" in error
    
    def test_complex_query_estimation(self):
        """Test that overly complex queries are rejected."""
        # Create a query with many triple patterns - need enough to exceed MAX_TRIPLE_PATTERNS (100)
        # Each pattern has 3 '?' chars, estimate = brace_count + (question_count // 2)
        # For 1 brace pair and N patterns: estimate = 1 + (3N // 2) > 100 means N > 66
        patterns = "\n".join([f"?s{i} ?p{i} ?o{i} ." for i in range(80)])
        query = f"SELECT * WHERE {{ {patterns} }}"
        error = SPARQLQueryValidator.validate(query)
        assert error is not None
        assert "complex" in error.lower() or "patterns" in error.lower()
    
    def test_sanitize_for_logging(self):
        """Test that queries are sanitized for logging."""
        query = "SELECT * WHERE { ?s ?p ?o } LIMIT 10"
        sanitized = SPARQLQueryValidator.sanitize_for_logging(query, max_length=30)
        assert len(sanitized) <= 33  # 30 + "..."
        assert "SELECT" in sanitized
    
    def test_sanitize_empty_query(self):
        """Test sanitizing empty query."""
        sanitized = SPARQLQueryValidator.sanitize_for_logging("")
        assert sanitized == "<empty>"
    
    def test_valid_query_with_prefixes(self):
        """Test that queries with common prefixes pass validation."""
        query = """
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        
        SELECT ?concept ?label
        WHERE {
            ?concept a skos:Concept .
            ?concept rdfs:label ?label .
        }
        LIMIT 50
        """
        error = SPARQLQueryValidator.validate(query)
        assert error is None, f"Valid query with prefixes should pass: {error}"
    
    def test_valid_query_with_filter(self):
        """Test that queries with FILTER clauses pass validation."""
        query = """
        SELECT ?subject ?label
        WHERE {
            ?subject rdfs:label ?label .
            FILTER(CONTAINS(?label, "test"))
        }
        """
        error = SPARQLQueryValidator.validate(query)
        assert error is None, f"Valid query with FILTER should pass: {error}"
    
    def test_valid_query_with_optional(self):
        """Test that queries with reasonable OPTIONAL clauses pass validation."""
        query = """
        SELECT ?subject ?label ?comment
        WHERE {
            ?subject a rdfs:Class .
            OPTIONAL { ?subject rdfs:label ?label }
            OPTIONAL { ?subject rdfs:comment ?comment }
        }
        """
        error = SPARQLQueryValidator.validate(query)
        assert error is None, f"Valid query with OPTIONAL should pass: {error}"


def test_validator_constants():
    """Test that validator constants are set to reasonable values."""
    assert SPARQLQueryValidator.MAX_QUERY_LENGTH > 0
    assert SPARQLQueryValidator.MAX_TRIPLE_PATTERNS > 0
    assert SPARQLQueryValidator.MAX_UNIONS > 0
    assert SPARQLQueryValidator.MAX_OPTIONALS > 0
    assert len(SPARQLQueryValidator.ALLOWED_QUERY_TYPES) > 0
    assert len(SPARQLQueryValidator.FORBIDDEN_KEYWORDS) > 0
    
    # Check that forbidden keywords are all uppercase
    for keyword in SPARQLQueryValidator.FORBIDDEN_KEYWORDS:
        assert keyword.isupper(), f"Keyword should be uppercase: {keyword}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

