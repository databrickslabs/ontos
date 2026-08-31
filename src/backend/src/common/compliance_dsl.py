"""Compliance DSL Parser and Evaluator.

This module provides a Domain-Specific Language (DSL) for defining compliance rules
that can be evaluated against various entities (catalogs, schemas, tables, data products, etc.).

Syntax Overview:
    MATCH (entity:Type)
    WHERE entity.property OP value [AND/OR ...]
    ASSERT condition
    ON_PASS action
    ON_FAIL action

Supported Operators:
    =, !=, >, <, >=, <=, MATCHES (regex), IN, CONTAINS, HAS_TAG, TAG

Actions:
    PASS
    FAIL <message>
    ASSIGN_TAG <key>: <value>
    REMOVE_TAG <key>
    NOTIFY <recipients>

Example:
    MATCH (obj:Object)
    WHERE obj.type IN ['table', 'view']
    ASSERT obj.name MATCHES '^[a-z][a-z0-9_]*$'
    ON_FAIL FAIL 'Name must be lowercase with underscores'
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
import re


class TokenType(Enum):
    """Token types for DSL lexer."""
    # Keywords
    MATCH = "MATCH"
    WHERE = "WHERE"
    ASSERT = "ASSERT"
    ON_PASS = "ON_PASS"
    ON_FAIL = "ON_FAIL"
    CASE = "CASE"
    WHEN = "WHEN"
    THEN = "THEN"
    ELSE = "ELSE"
    END = "END"

    # Operators
    EQ = "="
    NEQ = "!="
    GT = ">"
    LT = "<"
    GTE = ">="
    LTE = "<="
    MATCHES = "MATCHES"
    IN = "IN"
    CONTAINS = "CONTAINS"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"

    # Functions
    HAS_TAG = "HAS_TAG"
    TAG = "TAG"
    LENGTH = "LENGTH"
    UPPER = "UPPER"
    LOWER = "LOWER"

    # Actions
    PASS = "PASS"
    FAIL = "FAIL"
    ASSIGN_TAG = "ASSIGN_TAG"
    REMOVE_TAG = "REMOVE_TAG"
    NOTIFY = "NOTIFY"

    # Literals and identifiers
    IDENTIFIER = "IDENTIFIER"
    STRING = "STRING"
    NUMBER = "NUMBER"
    TRUE = "TRUE"
    FALSE = "FALSE"

    # Punctuation
    LPAREN = "("
    RPAREN = ")"
    LBRACKET = "["
    RBRACKET = "]"
    COMMA = ","
    COLON = ":"
    DOT = "."

    # Special
    EOF = "EOF"
    NEWLINE = "NEWLINE"


@dataclass
class Token:
    """Token representation."""
    type: TokenType
    value: Any
    line: int
    column: int


class Lexer:
    """Tokenize DSL input."""

    KEYWORDS = {
        'MATCH', 'WHERE', 'ASSERT', 'ON_PASS', 'ON_FAIL',
        'CASE', 'WHEN', 'THEN', 'ELSE', 'END',
        'MATCHES', 'IN', 'CONTAINS', 'AND', 'OR', 'NOT',
        'HAS_TAG', 'TAG', 'LENGTH', 'UPPER', 'LOWER',
        'PASS', 'FAIL', 'ASSIGN_TAG', 'REMOVE_TAG', 'NOTIFY',
        'TRUE', 'FALSE'
    }

    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.line = 1
        self.column = 1

    def error(self, msg: str) -> Exception:
        return ValueError(f"Lexer error at line {self.line}, column {self.column}: {msg}")

    def peek(self, offset: int = 0) -> Optional[str]:
        """Look ahead at character without consuming."""
        pos = self.pos + offset
        return self.text[pos] if pos < len(self.text) else None

    def advance(self) -> Optional[str]:
        """Consume and return current character."""
        if self.pos >= len(self.text):
            return None
        char = self.text[self.pos]
        self.pos += 1
        if char == '\n':
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return char

    def skip_whitespace(self):
        """Skip whitespace except newlines."""
        while self.peek() and self.peek() in ' \t\r':
            self.advance()

    def read_string(self, quote: str) -> str:
        """Read a quoted string."""
        value = []
        self.advance()  # consume opening quote
        while True:
            char = self.peek()
            if char is None:
                raise self.error("Unterminated string")
            if char == quote:
                self.advance()  # consume closing quote
                break
            if char == '\\':
                self.advance()
                escaped = self.advance()
                if escaped == 'n':
                    value.append('\n')
                elif escaped == 't':
                    value.append('\t')
                elif escaped == '\\':
                    value.append('\\')
                elif escaped == quote:
                    value.append(quote)
                else:
                    value.append(escaped or '')
            else:
                value.append(char)
                self.advance()
        return ''.join(value)

    def read_number(self) -> Union[int, float]:
        """Read a number."""
        value = []
        has_dot = False
        while self.peek() and (self.peek().isdigit() or self.peek() == '.'):
            char = self.peek()
            if char == '.':
                if has_dot:
                    break
                has_dot = True
            value.append(char)
            self.advance()
        num_str = ''.join(value)
        return float(num_str) if has_dot else int(num_str)

    def read_identifier(self) -> str:
        """Read an identifier or keyword."""
        value = []
        while self.peek() and (self.peek().isalnum() or self.peek() == '_'):
            value.append(self.peek())
            self.advance()
        return ''.join(value)

    def tokenize(self) -> List[Token]:
        """Tokenize the entire input."""
        tokens = []

        while self.pos < len(self.text):
            self.skip_whitespace()

            if self.pos >= len(self.text):
                break

            line, column = self.line, self.column
            char = self.peek()

            # Newlines
            if char == '\n':
                self.advance()
                continue

            # Comments
            if char == '#':
                while self.peek() and self.peek() != '\n':
                    self.advance()
                continue

            # Strings
            if char in '"\'':
                quote = char
                value = self.read_string(quote)
                tokens.append(Token(TokenType.STRING, value, line, column))
                continue

            # Numbers
            if char.isdigit():
                value = self.read_number()
                tokens.append(Token(TokenType.NUMBER, value, line, column))
                continue

            # Identifiers and keywords
            if char.isalpha() or char == '_':
                value = self.read_identifier()
                value_upper = value.upper()
                if value_upper in self.KEYWORDS:
                    tokens.append(Token(TokenType[value_upper], value_upper, line, column))
                else:
                    tokens.append(Token(TokenType.IDENTIFIER, value, line, column))
                continue

            # Two-character operators
            if char == '!' and self.peek(1) == '=':
                self.advance()
                self.advance()
                tokens.append(Token(TokenType.NEQ, '!=', line, column))
                continue

            if char == '>' and self.peek(1) == '=':
                self.advance()
                self.advance()
                tokens.append(Token(TokenType.GTE, '>=', line, column))
                continue

            if char == '<' and self.peek(1) == '=':
                self.advance()
                self.advance()
                tokens.append(Token(TokenType.LTE, '<=', line, column))
                continue

            # Single-character operators
            single_char_tokens = {
                '=': TokenType.EQ,
                '>': TokenType.GT,
                '<': TokenType.LT,
                '(': TokenType.LPAREN,
                ')': TokenType.RPAREN,
                '[': TokenType.LBRACKET,
                ']': TokenType.RBRACKET,
                ',': TokenType.COMMA,
                ':': TokenType.COLON,
                '.': TokenType.DOT,
            }

            if char in single_char_tokens:
                self.advance()
                tokens.append(Token(single_char_tokens[char], char, line, column))
                continue

            raise self.error(f"Unexpected character: {char}")

        tokens.append(Token(TokenType.EOF, None, self.line, self.column))
        return tokens


class ASTNode:
    """Base class for AST nodes."""
    pass


@dataclass
class BinaryOp(ASTNode):
    """Binary operation node."""
    op: TokenType
    left: ASTNode
    right: ASTNode


@dataclass
class UnaryOp(ASTNode):
    """Unary operation node."""
    op: TokenType
    operand: ASTNode


@dataclass
class PropertyAccess(ASTNode):
    """Property access node (e.g., obj.name)."""
    object: str
    property: str


@dataclass
class FunctionCall(ASTNode):
    """Function call node."""
    name: str
    args: List[ASTNode]


@dataclass
class Literal(ASTNode):
    """Literal value node."""
    value: Any


@dataclass
class ListLiteral(ASTNode):
    """List literal node."""
    values: List[ASTNode]


@dataclass
class CaseExpression(ASTNode):
    """CASE WHEN expression node."""
    subject: Optional[ASTNode]
    when_clauses: List[Tuple[ASTNode, ASTNode]]  # (condition, result)
    else_clause: Optional[ASTNode]


class Parser:
    """Parse tokenized DSL input into AST."""

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def error(self, msg: str) -> Exception:
        token = self.current()
        return ValueError(f"Parser error at line {token.line}, column {token.column}: {msg}")

    def current(self) -> Token:
        """Get current token."""
        return self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]

    def peek(self, offset: int = 1) -> Token:
        """Look ahead at token."""
        pos = self.pos + offset
        return self.tokens[pos] if pos < len(self.tokens) else self.tokens[-1]

    def advance(self) -> Token:
        """Consume and return current token."""
        token = self.current()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return token

    def expect(self, token_type: TokenType) -> Token:
        """Consume token of expected type or raise error."""
        token = self.current()
        if token.type != token_type:
            raise self.error(f"Expected {token_type.value}, got {token.type.value}")
        return self.advance()

    def parse_primary(self) -> ASTNode:
        """Parse primary expression."""
        token = self.current()

        # String literal
        if token.type == TokenType.STRING:
            self.advance()
            return Literal(token.value)

        # Number literal
        if token.type == TokenType.NUMBER:
            self.advance()
            return Literal(token.value)

        # Boolean literals (case-insensitive: True/False/true/false)
        if token.type == TokenType.TRUE:
            self.advance()
            return Literal(True)

        if token.type == TokenType.FALSE:
            self.advance()
            return Literal(False)

        # List literal
        if token.type == TokenType.LBRACKET:
            return self.parse_list()

        # Parenthesized expression
        if token.type == TokenType.LPAREN:
            self.advance()
            expr = self.parse_or_expression()
            self.expect(TokenType.RPAREN)
            return expr

        # CASE expression
        if token.type == TokenType.CASE:
            return self.parse_case_expression()

        # Function call
        if token.type in (TokenType.HAS_TAG, TokenType.TAG, TokenType.LENGTH,
                          TokenType.UPPER, TokenType.LOWER):
            return self.parse_function_call()

        # Property access or identifier
        if token.type == TokenType.IDENTIFIER:
            name = token.value
            self.advance()

            # Check for property access
            if self.current().type == TokenType.DOT:
                self.advance()
                prop = self.expect(TokenType.IDENTIFIER).value
                return PropertyAccess(name, prop)

            return Literal(name)

        raise self.error(f"Unexpected token: {token.type.value}")

    def parse_list(self) -> ListLiteral:
        """Parse list literal [a, b, c]."""
        self.expect(TokenType.LBRACKET)
        values = []

        while self.current().type != TokenType.RBRACKET:
            values.append(self.parse_primary())
            if self.current().type == TokenType.COMMA:
                self.advance()
            elif self.current().type != TokenType.RBRACKET:
                raise self.error("Expected ',' or ']' in list")

        self.expect(TokenType.RBRACKET)
        return ListLiteral(values)

    def parse_function_call(self) -> FunctionCall:
        """Parse function call."""
        name = self.advance().value
        self.expect(TokenType.LPAREN)

        args = []
        while self.current().type != TokenType.RPAREN:
            args.append(self.parse_or_expression())
            if self.current().type == TokenType.COMMA:
                self.advance()
            elif self.current().type != TokenType.RPAREN:
                raise self.error("Expected ',' or ')' in function call")

        self.expect(TokenType.RPAREN)
        return FunctionCall(name, args)

    def parse_case_expression(self) -> CaseExpression:
        """Parse CASE WHEN expression."""
        self.expect(TokenType.CASE)

        # Optional subject (for CASE subject WHEN ...)
        subject = None
        if self.current().type != TokenType.WHEN:
            subject = self.parse_primary()

        # WHEN clauses
        when_clauses = []
        while self.current().type == TokenType.WHEN:
            self.advance()
            condition = self.parse_or_expression()
            self.expect(TokenType.THEN)
            result = self.parse_or_expression()
            when_clauses.append((condition, result))

        # ELSE clause
        else_clause = None
        if self.current().type == TokenType.ELSE:
            self.advance()
            else_clause = self.parse_or_expression()

        self.expect(TokenType.END)
        return CaseExpression(subject, when_clauses, else_clause)

    def parse_comparison(self) -> ASTNode:
        """Parse comparison expression."""
        left = self.parse_primary()

        comp_ops = {
            TokenType.EQ, TokenType.NEQ, TokenType.GT, TokenType.LT,
            TokenType.GTE, TokenType.LTE, TokenType.MATCHES,
            TokenType.IN, TokenType.CONTAINS
        }

        if self.current().type in comp_ops:
            op = self.advance().type
            right = self.parse_primary()
            return BinaryOp(op, left, right)

        return left

    def parse_not_expression(self) -> ASTNode:
        """Parse NOT expression."""
        if self.current().type == TokenType.NOT:
            self.advance()
            return UnaryOp(TokenType.NOT, self.parse_comparison())
        return self.parse_comparison()

    def parse_and_expression(self) -> ASTNode:
        """Parse AND expression."""
        left = self.parse_not_expression()

        while self.current().type == TokenType.AND:
            self.advance()
            right = self.parse_not_expression()
            left = BinaryOp(TokenType.AND, left, right)

        return left

    def parse_or_expression(self) -> ASTNode:
        """Parse OR expression."""
        left = self.parse_and_expression()

        while self.current().type == TokenType.OR:
            self.advance()
            right = self.parse_and_expression()
            left = BinaryOp(TokenType.OR, left, right)

        return left

    def parse_expression(self) -> ASTNode:
        """Parse full expression."""
        return self.parse_or_expression()


class Evaluator:
    """Evaluate AST against an object."""

    def __init__(self, obj: Dict[str, Any]):
        self.obj = obj

    def error(self, msg: str) -> Exception:
        return ValueError(f"Evaluation error: {msg}")

    def evaluate(self, node: ASTNode) -> Any:
        """Evaluate AST node."""
        if isinstance(node, Literal):
            return node.value

        if isinstance(node, ListLiteral):
            return [self.evaluate(v) for v in node.values]

        if isinstance(node, PropertyAccess):
            return self.obj.get(node.property)

        if isinstance(node, FunctionCall):
            return self.evaluate_function(node)

        if isinstance(node, UnaryOp):
            return self.evaluate_unary_op(node)

        if isinstance(node, BinaryOp):
            return self.evaluate_binary_op(node)

        if isinstance(node, CaseExpression):
            return self.evaluate_case(node)

        raise self.error(f"Unknown node type: {type(node)}")

    def evaluate_function(self, node: FunctionCall) -> Any:
        """Evaluate function call."""
        if node.name == 'HAS_TAG':
            if len(node.args) != 1:
                raise self.error("HAS_TAG expects 1 argument")
            key = self.evaluate(node.args[0])
            tags = self.obj.get('tags', {})
            return key in tags

        if node.name == 'TAG':
            if len(node.args) != 1:
                raise self.error("TAG expects 1 argument")
            key = self.evaluate(node.args[0])
            tags = self.obj.get('tags', {})
            return tags.get(key)

        if node.name == 'LENGTH':
            if len(node.args) != 1:
                raise self.error("LENGTH expects 1 argument")
            value = self.evaluate(node.args[0])
            return len(value) if value else 0

        if node.name == 'UPPER':
            if len(node.args) != 1:
                raise self.error("UPPER expects 1 argument")
            value = self.evaluate(node.args[0])
            return str(value).upper() if value else ''

        if node.name == 'LOWER':
            if len(node.args) != 1:
                raise self.error("LOWER expects 1 argument")
            value = self.evaluate(node.args[0])
            return str(value).lower() if value else ''

        raise self.error(f"Unknown function: {node.name}")

    def evaluate_unary_op(self, node: UnaryOp) -> Any:
        """Evaluate unary operation."""
        if node.op == TokenType.NOT:
            return not self.evaluate(node.operand)
        raise self.error(f"Unknown unary operator: {node.op}")

    def evaluate_binary_op(self, node: BinaryOp) -> Any:
        """Evaluate binary operation."""
        op = node.op

        # Boolean operators
        if op == TokenType.AND:
            return self.evaluate(node.left) and self.evaluate(node.right)
        if op == TokenType.OR:
            return self.evaluate(node.left) or self.evaluate(node.right)

        # Comparison operators
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)

        if op == TokenType.EQ:
            return left == right
        if op == TokenType.NEQ:
            return left != right
        if op == TokenType.GT:
            return left > right if left is not None and right is not None else False
        if op == TokenType.LT:
            return left < right if left is not None and right is not None else False
        if op == TokenType.GTE:
            return left >= right if left is not None and right is not None else False
        if op == TokenType.LTE:
            return left <= right if left is not None and right is not None else False

        if op == TokenType.MATCHES:
            if left is None:
                return False
            pattern = str(right)
            return re.match(pattern, str(left)) is not None

        if op == TokenType.IN:
            if not isinstance(right, list):
                raise self.error("IN operator requires list on right side")
            return left in right

        if op == TokenType.CONTAINS:
            if left is None:
                return False
            if isinstance(left, (list, dict)):
                return right in left
            return str(right) in str(left)

        raise self.error(f"Unknown binary operator: {op}")

    def evaluate_case(self, node: CaseExpression) -> Any:
        """Evaluate CASE expression."""
        subject_value = self.evaluate(node.subject) if node.subject else None

        for condition, result in node.when_clauses:
            # If subject exists, compare it to condition
            if node.subject:
                if subject_value == self.evaluate(condition):
                    return self.evaluate(result)
            # Otherwise, evaluate condition as boolean
            else:
                if self.evaluate(condition):
                    return self.evaluate(result)

        # ELSE clause
        if node.else_clause:
            return self.evaluate(node.else_clause)

        return None


def evaluate_rule_on_object(rule: str, obj: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Evaluate a Compliance DSL rule against a single object.

    Args:
        rule: DSL rule string
        obj: Object to evaluate against

    Returns:
        Tuple of (passed, error_message)
        - passed: True if rule passed, False otherwise
        - error_message: Error message if failed, None if passed

    Example:
        >>> rule = "ASSERT obj.name MATCHES '^[a-z][a-z0-9_]*$'"
        >>> obj = {"name": "valid_table"}
        >>> evaluate_rule_on_object(rule, obj)
        (True, None)
    """
    try:
        # Extract ASSERT clause
        if 'ASSERT' not in rule:
            return False, "Rule must contain ASSERT clause"

        assert_part = rule.split('ASSERT', 1)[1].strip()

        # Tokenize
        lexer = Lexer(assert_part)
        tokens = lexer.tokenize()

        # Parse
        parser = Parser(tokens)
        ast = parser.parse_expression()

        # Evaluate
        evaluator = Evaluator(obj)
        result = evaluator.evaluate(ast)

        # Convert to boolean
        passed = bool(result)

        if passed:
            return True, None
        else:
            # Generate helpful error message
            return False, f"Assertion failed: {assert_part}"

    except Exception as e:
        return False, f"DSL evaluation error: {str(e)}"


def parse_rule(rule: str) -> Dict[str, Any]:
    """Parse a full DSL rule into components.

    Returns dict with keys:
        - match_type: Entity type to match
        - where_clause: Optional WHERE condition AST
        - assert_clause: ASSERT condition AST
        - on_pass_actions: List of actions on success
        - on_fail_actions: List of actions on failure
    """
    try:
        lexer = Lexer(rule)
        tokens = lexer.tokenize()
        parser = Parser(tokens)

        result: Dict[str, Any] = {
            'match_type': None,
            'where_clause': None,
            'assert_clause': None,
            'on_pass_actions': [],
            'on_fail_actions': [],
        }

        # Parse MATCH clause
        if parser.current().type == TokenType.MATCH:
            parser.advance()
            parser.expect(TokenType.LPAREN)
            parser.expect(TokenType.IDENTIFIER)  # entity name
            parser.expect(TokenType.COLON)
            match_type = parser.expect(TokenType.IDENTIFIER).value
            parser.expect(TokenType.RPAREN)
            result['match_type'] = match_type

        # Parse WHERE clause
        if parser.current().type == TokenType.WHERE:
            parser.advance()
            result['where_clause'] = parser.parse_expression()

        # Parse ASSERT clause
        if parser.current().type == TokenType.ASSERT:
            parser.advance()
            result['assert_clause'] = parser.parse_expression()

        # Parse ON_PASS actions
        if parser.current().type == TokenType.ON_PASS:
            parser.advance()
            result['on_pass_actions'] = parse_actions(parser)

        # Parse ON_FAIL actions
        if parser.current().type == TokenType.ON_FAIL:
            parser.advance()
            result['on_fail_actions'] = parse_actions(parser)

        return result

    except Exception as e:
        raise ValueError(f"Failed to parse rule: {str(e)}")


def parse_actions(parser: Parser) -> List[Dict[str, Any]]:
    """Parse action list from current parser position."""
    actions = []

    while parser.current().type in (TokenType.PASS, TokenType.FAIL,
                                     TokenType.ASSIGN_TAG, TokenType.REMOVE_TAG,
                                     TokenType.NOTIFY):
        action_type = parser.advance().type

        if action_type == TokenType.PASS:
            actions.append({'type': 'PASS'})

        elif action_type == TokenType.FAIL:
            # FAIL can have optional message
            message = None
            if parser.current().type == TokenType.STRING:
                message = parser.advance().value
            actions.append({'type': 'FAIL', 'message': message})

        elif action_type == TokenType.ASSIGN_TAG:
            # ASSIGN_TAG key: value
            key = parser.expect(TokenType.IDENTIFIER).value
            parser.expect(TokenType.COLON)
            value = parser.expect(TokenType.STRING).value
            actions.append({'type': 'ASSIGN_TAG', 'key': key, 'value': value})

        elif action_type == TokenType.REMOVE_TAG:
            # REMOVE_TAG key
            key = parser.expect(TokenType.IDENTIFIER).value
            actions.append({'type': 'REMOVE_TAG', 'key': key})

        elif action_type == TokenType.NOTIFY:
            # NOTIFY recipients
            recipients = parser.expect(TokenType.STRING).value
            actions.append({'type': 'NOTIFY', 'recipients': recipients})

    return actions
