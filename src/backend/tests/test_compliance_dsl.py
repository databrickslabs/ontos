"""Unit tests for Compliance DSL Parser and Evaluator."""

import pytest
from src.common.compliance_dsl import (
    Lexer,
    Parser,
    Evaluator,
    TokenType,
    evaluate_rule_on_object,
    parse_rule,
    Literal,
    PropertyAccess,
    BinaryOp,
    UnaryOp,
    FunctionCall,
    CaseExpression,
)


class TestLexer:
    """Test DSL lexer."""

    def test_tokenize_simple_assertion(self):
        """Test tokenizing a simple assertion."""
        lexer = Lexer("obj.name = 'test'")
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == 'obj'
        assert tokens[1].type == TokenType.DOT
        assert tokens[2].type == TokenType.IDENTIFIER
        assert tokens[2].value == 'name'
        assert tokens[3].type == TokenType.EQ
        assert tokens[4].type == TokenType.STRING
        assert tokens[4].value == 'test'

    def test_tokenize_regex_match(self):
        """Test tokenizing MATCHES operator."""
        lexer = Lexer("obj.name MATCHES '^[a-z]+$'")
        tokens = lexer.tokenize()

        assert any(t.type == TokenType.MATCHES for t in tokens)
        assert any(t.type == TokenType.STRING and '^[a-z]+$' in t.value for t in tokens)

    def test_tokenize_comparison_operators(self):
        """Test tokenizing comparison operators."""
        lexer = Lexer("a > 5 AND b <= 10 AND c != 3")
        tokens = lexer.tokenize()

        types = [t.type for t in tokens]
        assert TokenType.GT in types
        assert TokenType.LTE in types
        assert TokenType.NEQ in types
        assert TokenType.AND in types

    def test_tokenize_list_literal(self):
        """Test tokenizing list literals."""
        lexer = Lexer("['table', 'view', 'schema']")
        tokens = lexer.tokenize()

        types = [t.type for t in tokens]
        assert TokenType.LBRACKET in types
        assert TokenType.RBRACKET in types
        assert TokenType.COMMA in types

    def test_tokenize_function_call(self):
        """Test tokenizing function calls."""
        lexer = Lexer("HAS_TAG('data-product')")
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.HAS_TAG
        assert tokens[1].type == TokenType.LPAREN
        assert tokens[2].type == TokenType.STRING
        assert tokens[3].type == TokenType.RPAREN

    def test_tokenize_comments(self):
        """Test that comments are ignored."""
        lexer = Lexer("obj.name = 'test' # This is a comment")
        tokens = lexer.tokenize()

        # Comment should not appear in tokens
        assert all(t.type != TokenType.IDENTIFIER or 'comment' not in t.value.lower() for t in tokens)


class TestParser:
    """Test DSL parser."""

    def test_parse_property_access(self):
        """Test parsing property access."""
        lexer = Lexer("obj.name")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse_primary()

        assert isinstance(ast, PropertyAccess)
        assert ast.object == 'obj'
        assert ast.property == 'name'

    def test_parse_comparison(self):
        """Test parsing comparisons."""
        lexer = Lexer("obj.name = 'test'")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse_expression()

        assert isinstance(ast, BinaryOp)
        assert ast.op == TokenType.EQ
        assert isinstance(ast.left, PropertyAccess)
        assert isinstance(ast.right, Literal)

    def test_parse_boolean_and(self):
        """Test parsing AND expressions."""
        lexer = Lexer("obj.a = 1 AND obj.b = 2")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse_expression()

        assert isinstance(ast, BinaryOp)
        assert ast.op == TokenType.AND

    def test_parse_boolean_or(self):
        """Test parsing OR expressions."""
        lexer = Lexer("obj.a = 1 OR obj.b = 2")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse_expression()

        assert isinstance(ast, BinaryOp)
        assert ast.op == TokenType.OR

    def test_parse_not_expression(self):
        """Test parsing NOT expressions."""
        lexer = Lexer("NOT obj.active")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse_expression()

        assert isinstance(ast, UnaryOp)
        assert ast.op == TokenType.NOT

    def test_parse_list_literal(self):
        """Test parsing list literals."""
        lexer = Lexer("['a', 'b', 'c']")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse_primary()

        from src.common.compliance_dsl import ListLiteral
        assert isinstance(ast, ListLiteral)
        assert len(ast.values) == 3

    def test_parse_function_call(self):
        """Test parsing function calls."""
        lexer = Lexer("HAS_TAG('key')")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse_primary()

        assert isinstance(ast, FunctionCall)
        assert ast.name == 'HAS_TAG'
        assert len(ast.args) == 1

    def test_parse_case_expression(self):
        """Test parsing CASE expressions."""
        lexer = Lexer("CASE obj.type WHEN 'table' THEN 1 WHEN 'view' THEN 2 ELSE 0 END")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse_primary()

        assert isinstance(ast, CaseExpression)
        assert len(ast.when_clauses) == 2
        assert ast.else_clause is not None


class TestEvaluator:
    """Test DSL evaluator."""

    def test_evaluate_property_access(self):
        """Test evaluating property access."""
        obj = {'name': 'test_table'}
        evaluator = Evaluator(obj)
        ast = PropertyAccess('obj', 'name')

        result = evaluator.evaluate(ast)
        assert result == 'test_table'

    def test_evaluate_equality(self):
        """Test evaluating equality comparison."""
        obj = {'type': 'table'}
        evaluator = Evaluator(obj)
        ast = BinaryOp(
            TokenType.EQ,
            PropertyAccess('obj', 'type'),
            Literal('table')
        )

        result = evaluator.evaluate(ast)
        assert result is True

    def test_evaluate_regex_match(self):
        """Test evaluating MATCHES operator."""
        obj = {'name': 'valid_name'}
        evaluator = Evaluator(obj)
        ast = BinaryOp(
            TokenType.MATCHES,
            PropertyAccess('obj', 'name'),
            Literal('^[a-z_]+$')
        )

        result = evaluator.evaluate(ast)
        assert result is True

    def test_evaluate_in_operator(self):
        """Test evaluating IN operator."""
        obj = {'type': 'view'}
        evaluator = Evaluator(obj)

        from src.common.compliance_dsl import ListLiteral
        ast = BinaryOp(
            TokenType.IN,
            PropertyAccess('obj', 'type'),
            ListLiteral([Literal('table'), Literal('view')])
        )

        result = evaluator.evaluate(ast)
        assert result is True

    def test_evaluate_and_operator(self):
        """Test evaluating AND operator."""
        obj = {'a': 1, 'b': 2}
        evaluator = Evaluator(obj)
        ast = BinaryOp(
            TokenType.AND,
            BinaryOp(TokenType.EQ, PropertyAccess('obj', 'a'), Literal(1)),
            BinaryOp(TokenType.EQ, PropertyAccess('obj', 'b'), Literal(2))
        )

        result = evaluator.evaluate(ast)
        assert result is True

    def test_evaluate_or_operator(self):
        """Test evaluating OR operator."""
        obj = {'a': 1, 'b': 3}
        evaluator = Evaluator(obj)
        ast = BinaryOp(
            TokenType.OR,
            BinaryOp(TokenType.EQ, PropertyAccess('obj', 'a'), Literal(1)),
            BinaryOp(TokenType.EQ, PropertyAccess('obj', 'b'), Literal(2))
        )

        result = evaluator.evaluate(ast)
        assert result is True

    def test_evaluate_not_operator(self):
        """Test evaluating NOT operator."""
        obj = {'active': False}
        evaluator = Evaluator(obj)
        ast = UnaryOp(
            TokenType.NOT,
            PropertyAccess('obj', 'active')
        )

        result = evaluator.evaluate(ast)
        assert result is True

    def test_evaluate_has_tag_function(self):
        """Test evaluating HAS_TAG function."""
        obj = {'tags': {'key1': 'value1', 'key2': 'value2'}}
        evaluator = Evaluator(obj)
        ast = FunctionCall('HAS_TAG', [Literal('key1')])

        result = evaluator.evaluate(ast)
        assert result is True

    def test_evaluate_tag_function(self):
        """Test evaluating TAG function."""
        obj = {'tags': {'data-product': 'my-product'}}
        evaluator = Evaluator(obj)
        ast = FunctionCall('TAG', [Literal('data-product')])

        result = evaluator.evaluate(ast)
        assert result == 'my-product'

    def test_evaluate_length_function(self):
        """Test evaluating LENGTH function."""
        obj = {'name': 'test'}
        evaluator = Evaluator(obj)
        ast = FunctionCall('LENGTH', [PropertyAccess('obj', 'name')])

        result = evaluator.evaluate(ast)
        assert result == 4

    def test_evaluate_upper_function(self):
        """Test evaluating UPPER function."""
        obj = {'name': 'test'}
        evaluator = Evaluator(obj)
        ast = FunctionCall('UPPER', [PropertyAccess('obj', 'name')])

        result = evaluator.evaluate(ast)
        assert result == 'TEST'

    def test_evaluate_case_expression(self):
        """Test evaluating CASE expression."""
        obj = {'type': 'view'}
        evaluator = Evaluator(obj)

        ast = CaseExpression(
            subject=PropertyAccess('obj', 'type'),
            when_clauses=[
                (Literal('table'), Literal('is_table')),
                (Literal('view'), Literal('is_view')),
            ],
            else_clause=Literal('unknown')
        )

        result = evaluator.evaluate(ast)
        assert result == 'is_view'


class TestRuleEvaluation:
    """Test complete rule evaluation."""

    def test_simple_naming_convention(self):
        """Test naming convention rule."""
        rule = "ASSERT obj.name MATCHES '^[a-z][a-z0-9_]*$'"

        # Valid name
        obj1 = {'name': 'valid_table_name'}
        passed, msg = evaluate_rule_on_object(rule, obj1)
        assert passed is True
        assert msg is None

        # Invalid name (starts with uppercase)
        obj2 = {'name': 'InvalidName'}
        passed, msg = evaluate_rule_on_object(rule, obj2)
        assert passed is False
        assert msg is not None

    def test_type_filtering(self):
        """Test type filtering rule."""
        rule = "ASSERT obj.type IN ['table', 'view']"

        obj1 = {'type': 'table'}
        passed, msg = evaluate_rule_on_object(rule, obj1)
        assert passed is True

        obj2 = {'type': 'function'}
        passed, msg = evaluate_rule_on_object(rule, obj2)
        assert passed is False

    def test_tag_requirement(self):
        """Test tag requirement rule."""
        rule = "ASSERT HAS_TAG('data-product')"

        obj1 = {'tags': {'data-product': 'my-product'}}
        passed, msg = evaluate_rule_on_object(rule, obj1)
        assert passed is True

        obj2 = {'tags': {}}
        passed, msg = evaluate_rule_on_object(rule, obj2)
        assert passed is False

    def test_complex_boolean_expression(self):
        """Test complex boolean expression."""
        rule = "ASSERT obj.type = 'table' AND obj.owner != 'unknown' AND HAS_TAG('domain')"

        obj1 = {
            'type': 'table',
            'owner': 'user@example.com',
            'tags': {'domain': 'finance'}
        }
        passed, msg = evaluate_rule_on_object(rule, obj1)
        assert passed is True

        obj2 = {
            'type': 'table',
            'owner': 'unknown',
            'tags': {'domain': 'finance'}
        }
        passed, msg = evaluate_rule_on_object(rule, obj2)
        assert passed is False


class TestBooleanLiterals:
    """Test boolean literal parsing and evaluation (issue #684)."""

    def test_lexer_bool_keywords(self):
        """True/False (any case) lex as TRUE/FALSE keyword tokens, not identifiers."""
        for text, expected in [
            ("True", TokenType.TRUE),
            ("False", TokenType.FALSE),
            ("true", TokenType.TRUE),
            ("false", TokenType.FALSE),
        ]:
            tokens = Lexer(text).tokenize()
            assert tokens[0].type == expected

    def test_parse_bool_literal_is_python_bool(self):
        """A bare True/False parses to a Literal holding a real Python bool."""
        for text, expected in [("True", True), ("False", False),
                               ("true", True), ("false", False)]:
            parser = Parser(Lexer(text).tokenize())
            ast = parser.parse_primary()
            assert isinstance(ast, Literal)
            assert ast.value is expected

    def test_eq_true_against_bool_field(self):
        """`field = True` evaluates True when field is bool True, False when bool False."""
        rule = "ASSERT obj.has_owner = True"
        passed, _ = evaluate_rule_on_object(rule, {'has_owner': True})
        assert passed is True
        passed, _ = evaluate_rule_on_object(rule, {'has_owner': False})
        assert passed is False

    def test_eq_false_against_bool_field(self):
        """`field = False` evaluates True when field is bool False, False when bool True."""
        rule = "ASSERT obj.has_pii = False"
        passed, _ = evaluate_rule_on_object(rule, {'has_pii': False})
        assert passed is True
        passed, _ = evaluate_rule_on_object(rule, {'has_pii': True})
        assert passed is False

    def test_neq_true_against_bool_field(self):
        """`field != True` behaves as bool-to-bool inequality."""
        rule = "ASSERT obj.has_owner != True"
        passed, _ = evaluate_rule_on_object(rule, {'has_owner': False})
        assert passed is True
        passed, _ = evaluate_rule_on_object(rule, {'has_owner': True})
        assert passed is False

    def test_neq_false_against_bool_field(self):
        """`field != False` behaves as bool-to-bool inequality."""
        rule = "ASSERT obj.has_pii != False"
        passed, _ = evaluate_rule_on_object(rule, {'has_pii': True})
        assert passed is True
        passed, _ = evaluate_rule_on_object(rule, {'has_pii': False})
        assert passed is False

    def test_lowercase_bool_matches_bool_field(self):
        """Lowercase true/false evaluate the same as True/False."""
        passed, _ = evaluate_rule_on_object("ASSERT obj.has_owner = true", {'has_owner': True})
        assert passed is True
        passed, _ = evaluate_rule_on_object("ASSERT obj.has_pii = false", {'has_pii': False})
        assert passed is True

    def test_bool_literal_not_equal_to_string(self):
        """Regression: bool literal is a real bool, so True != the string 'True'."""
        evaluator = Evaluator({})
        ast = Parser(Lexer("True").tokenize()).parse_primary()
        assert evaluator.evaluate(ast) is True
        assert evaluator.evaluate(ast) != "True"


class TestRuleParsing:
    """Test full rule parsing."""

    def test_parse_full_rule_with_actions(self):
        """Test parsing complete rule with actions."""
        rule = """
        MATCH (obj:Object)
        WHERE obj.type IN ['table', 'view']
        ASSERT obj.name MATCHES '^[a-z][a-z0-9_]*$'
        ON_FAIL FAIL 'Name must be lowercase with underscores'
        """

        parsed = parse_rule(rule)

        assert parsed['match_type'] == 'Object'
        assert parsed['where_clause'] is not None
        assert parsed['assert_clause'] is not None
        assert len(parsed['on_fail_actions']) == 1
        assert parsed['on_fail_actions'][0]['type'] == 'FAIL'

    def test_parse_rule_with_assign_tag(self):
        """Test parsing rule with ASSIGN_TAG action."""
        rule = """
        MATCH (obj:table)
        ASSERT obj.owner != 'unknown'
        ON_FAIL ASSIGN_TAG compliance_issue: 'missing_owner'
        """

        parsed = parse_rule(rule)

        assert parsed['match_type'] == 'table'
        assert len(parsed['on_fail_actions']) == 1
        assert parsed['on_fail_actions'][0]['type'] == 'ASSIGN_TAG'
        assert parsed['on_fail_actions'][0]['key'] == 'compliance_issue'
        assert parsed['on_fail_actions'][0]['value'] == 'missing_owner'

    def test_parse_rule_with_notify(self):
        """Test parsing rule with NOTIFY action."""
        rule = """
        MATCH (obj:table)
        ASSERT obj.encryption = 'AES256'
        ON_FAIL NOTIFY 'security-team@example.com'
        """

        parsed = parse_rule(rule)

        assert len(parsed['on_fail_actions']) == 1
        assert parsed['on_fail_actions'][0]['type'] == 'NOTIFY'
        assert 'security-team@example.com' in parsed['on_fail_actions'][0]['recipients']


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_property(self):
        """Test evaluation with missing property."""
        rule = "ASSERT obj.missing_prop = 'value'"
        obj = {'name': 'test'}

        passed, msg = evaluate_rule_on_object(rule, obj)
        # Should handle gracefully
        assert isinstance(passed, bool)

    def test_null_value_comparison(self):
        """Test comparison with null values."""
        rule = "ASSERT obj.owner != 'unknown'"
        obj = {'owner': None}

        passed, msg = evaluate_rule_on_object(rule, obj)
        assert passed is True  # None != 'unknown'

    def test_empty_tags(self):
        """Test tag functions with empty tags."""
        rule = "ASSERT HAS_TAG('key')"
        obj = {}

        passed, msg = evaluate_rule_on_object(rule, obj)
        assert passed is False

    def test_invalid_regex(self):
        """Test with invalid regex pattern."""
        rule = "ASSERT obj.name MATCHES '[invalid'"
        obj = {'name': 'test'}

        # Should handle regex error gracefully
        passed, msg = evaluate_rule_on_object(rule, obj)
        assert isinstance(passed, bool)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
