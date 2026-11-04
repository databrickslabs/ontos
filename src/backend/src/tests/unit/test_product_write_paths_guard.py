"""Guard: every data product write goes through the manager, which fires the triggers.

The product workflow triggers (``on_create``, ``on_update``, ``on_delete``,
``on_certify``, ..., and the blocking ``before_*`` gates) fire in
``DataProductsManager``'s write methods, so an entry point that changes a product
some other way skips them. These tests fail when a product write route or tool:

- fires a trigger itself, or calls a ``fire_*_trigger`` helper (the call belongs in
  the manager, once);
- writes the product itself: a session ``add`` / ``commit`` / ``delete``, a
  repository ``create`` / ``update`` / ``remove``, or a field set on a stored row;
- (routes) calls no ``DataProductsManager`` method at all;
- (tools) doesn't reach the manager write method it stands for, or is a new product
  write tool missing from ``TOOL_CASES`` here.

The entry points are found, not listed: every route with a POST / PUT / PATCH /
DELETE on ``/data-products...`` (but ``NOT_PRODUCT_WRITES``) and every registered tool
that needs data-products write access, with the module-level helpers they call. The
manager methods themselves are covered by
``test_product_manager_triggers``.
"""
import ast
import asyncio
import inspect
import re
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.features import FeatureAccessLevel
from src.controller import audit_manager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import DataProductDb
from src.models.process_workflows import TriggerType
from src.tools.base import ToolCaller, ToolContext
from src.tools.registry import create_default_registry

SRC = Path(__file__).resolve().parents[2]
ROUTES_DIR = SRC / 'routes'
WRITE_VERBS = {'post', 'put', 'patch', 'delete'}

TRIGGER_FUNCTIONS = {'fire_trigger_safe', 'get_trigger_registry', 'TriggerRegistry',
                     'run_status_gates'}
TRIGGER_METHODS = {t.value for t in TriggerType if t.value.startswith(('on_', 'before_'))}
FIRE_HELPER = re.compile(r'^_?fire_\w*trigger$')
SESSION_NAMES = {'db', 'session', 'db_session', '_db'}
SESSION_WRITES = {'add', 'add_all', 'commit', 'delete', 'merge', 'flush', 'execute',
                  'bulk_save_objects', 'bulk_insert_mappings', 'bulk_update_mappings'}
REPO_WRITE = re.compile(r'^(create|update|remove|delete|upsert|bulk_\w+|set_\w+|'
                        r'add_\w+|remove_\w+|delete_\w+|update_\w+|create_\w+)$')
# Attribute targets that aren't stored rows.
ASSIGNABLE = {'request', 'response'}


# POST routes under /data-products that change no product (no trigger to fire).
NOT_PRODUCT_WRITES = {
    ('POST', '/data-products/compare'): 'compares two payloads',
    ('POST', '/data-products/{product_id}/maturity/evaluate'):
        'stores a maturity snapshot (the evaluator fires on_maturity_change)',
}


def _write_routes(tree):
    """The top-level route functions of a module with a write verb on /data-products..."""
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in WRITE_VERBS and dec.args
                    and isinstance(dec.args[0], ast.Constant)
                    and str(dec.args[0].value).startswith('/data-products')):
                yield dec.func.attr.upper(), dec.args[0].value, node


def _product_write_routes():
    """(verb, path, function, module tree, file) of each product write route."""
    found = []
    for path in sorted(ROUTES_DIR.glob('*.py')):
        tree = ast.parse(path.read_text(), filename=str(path))
        for verb, route_path, func in _write_routes(tree):
            if (verb, route_path) not in NOT_PRODUCT_WRITES:
                found.append((verb, route_path, func, tree, path))
    return found


def _is_product_write_tool(tool):
    perm = getattr(tool, 'required_permission', None)
    return tool.required_scope == 'data-products:write' or bool(
        perm and perm[0] == 'data-products'
        and perm[1] in (FeatureAccessLevel.READ_WRITE, FeatureAccessLevel.ADMIN)
    )


def _product_write_tools():
    registry = create_default_registry()
    return {t.name: t for t in registry.list_tools() if _is_product_write_tool(t)}


def _reached(roots, tree):
    """The nodes in ``roots`` and the module-level functions they call, transitively."""
    helpers = {n.name: n for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    seen, todo, out = set(), list(roots), []
    while todo:
        node = todo.pop()
        out.append(node)
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id in helpers and sub.func.id not in seen):
                seen.add(sub.func.id)
                todo.append(helpers[sub.func.id])
    return out


def _violations(nodes, path):
    """Each direct trigger call or product write in ``nodes``, as ``file:line what``."""
    out = set()

    def add(node, what):
        out.add(f'{path.relative_to(SRC)}:{node.lineno} {what}')

    for root in nodes:
        for node in ast.walk(root):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in TRIGGER_FUNCTIONS:
                    add(node, f'calls {func.id}')
                elif isinstance(func, ast.Attribute):
                    name, receiver = func.attr, ast.unparse(func.value)
                    if name in TRIGGER_FUNCTIONS or name in TRIGGER_METHODS:
                        add(node, f'fires a trigger: {receiver}.{name}')
                    elif FIRE_HELPER.match(name):
                        add(node, f'calls a trigger helper: {receiver}.{name}')
                    elif name in SESSION_WRITES and receiver.split('.')[-1] in SESSION_NAMES:
                        add(node, f'writes through the session: {receiver}.{name}')
                    elif REPO_WRITE.match(name) and 'repo' in receiver:
                        add(node, f'writes through a repository: {receiver}.{name}')
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if (isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id not in ASSIGNABLE | {'self'}):
                        add(node, f'sets a field: {ast.unparse(target)}')
    return sorted(out)


def _calls_on(nodes, names):
    return {
        n.func.attr for root in nodes for n in ast.walk(root)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name) and n.func.value.id in names
    }


def _manager_params(func_node):
    """Parameters given the DataProductsManager (by annotation or dependency)."""
    names = set()
    args = func_node.args
    positional = args.posonlyargs + args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(positional + args.kwonlyargs, defaults + list(args.kw_defaults)):
        if default is not None and 'get_data_products_manager' in ast.unparse(default):
            names.add(arg.arg)
        if arg.annotation is not None and 'DataProductsManager' in ast.unparse(arg.annotation):
            names.add(arg.arg)
    return names


def _route_id(route):
    verb, route_path, func, _, path = route
    return f'{verb} {route_path} ({path.name}:{func.lineno})'


def _tool_nodes(tool):
    """The class of ``tool`` and the module-level helpers it calls."""
    path = Path(inspect.getfile(type(tool))).resolve()
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == type(tool).__name__)
    return _reached([cls], tree), path


class TestStaticGuard:
    def test_the_product_write_entry_points_are_found(self):
        routes = {(verb, p) for verb, p, *_ in _product_write_routes()}
        assert {('POST', '/data-products'), ('PUT', '/data-products/{product_id}'),
                ('DELETE', '/data-products/{product_id}')} <= routes
        assert {'create_draft_data_product', 'update_data_product',
                'delete_data_product'} <= set(_product_write_tools())

    @pytest.mark.parametrize('route', _product_write_routes(), ids=_route_id)
    def test_a_product_write_route_neither_fires_nor_writes(self, route):
        _, _, func, tree, path = route
        assert _violations(_reached([func], tree), path) == []

    @pytest.mark.parametrize('route', _product_write_routes(), ids=_route_id)
    def test_a_product_write_route_calls_the_manager(self, route):
        _, _, func, tree, _ = route
        public = {n for n in dir(DataProductsManager) if not n.startswith('_')}
        params = _manager_params(func)
        assert params and _calls_on(_reached([func], tree), params) & public

    @pytest.mark.parametrize('name', sorted(_product_write_tools()))
    def test_a_product_write_tool_neither_fires_nor_writes(self, name):
        nodes, path = _tool_nodes(_product_write_tools()[name])
        assert _violations(nodes, path) == []


# --- Tools reach the manager write method -------------------------------------

RW = {'data-products': FeatureAccessLevel.ADMIN}
CALLER = ToolCaller(email='ann@example.com', auth_path='test', permissions=RW,
                    products_admin=True)

# Each product write tool: its arguments (``{id}`` = the stored product) and the
# manager method that writes and fires its trigger.
TOOL_CASES = {
    'create_draft_data_product': (
        {'name': 'Chat draft', 'description': 'd', 'domain': 'Sales'},
        'create_product', 'on_create'),
    'update_data_product': (
        {'product_id': '{id}', 'description': 'changed'}, 'update_product', 'on_update'),
    'delete_data_product': ({'product_id': '{id}'}, 'delete_product', 'on_delete'),
}


def test_every_product_write_tool_has_a_case():
    assert set(_product_write_tools()) == set(TOOL_CASES)


@pytest.fixture
def world(db_session, monkeypatch):
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: None)
    row = DataProductDb(id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
                        name='Stored', version='1.0.0', status='active',
                        draft_owner_id=CALLER.email)
    db_session.add(row)
    db_session.commit()
    products = DataProductsManager(db=db_session, ws_client=MagicMock(),
                                   notifications_manager=MagicMock(), tags_manager=MagicMock())
    products._update_search_index = lambda *a, **k: None
    return SimpleNamespace(db=db_session, row=row, products=products)


@pytest.mark.parametrize('tool', sorted(TOOL_CASES))
def test_each_product_write_tool_goes_through_the_manager(world, monkeypatch, tool):
    args, method, trigger = TOOL_CASES[tool]
    args = {k: (world.row.id if v == '{id}' else v) for k, v in args.items()}
    calls = []
    real = getattr(world.products, method)

    def spy(*a, **kw):
        calls.append((a, kw))
        return real(*a, **kw)

    monkeypatch.setattr(world.products, method, spy)
    ctx = ToolContext(db=world.db, settings=MagicMock(), caller=CALLER,
                      data_products_manager=world.products)
    registry = MagicMock()
    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=registry):
        res = asyncio.run(create_default_registry().execute(tool, ctx, args))

    assert res.success is True, res.error
    assert len(calls) == 1, f'{tool} did not call DataProductsManager.{method}'
    fired = getattr(registry, trigger).call_args_list
    assert [c.kwargs['user_email'] for c in fired] == [CALLER.email]
