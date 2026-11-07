"""Genie Space instructions carry the rich-text notes of the products' contracts."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace

from src.common.genie_client import collect_contract_names, format_metadata_for_genie
from src.db_models.data_contracts import DataContractDb


def _note(title, content, short=None):
    return SimpleNamespace(title=title, short_description=short, content_markdown=content)


def _product(pid='p1', contract_ids=('c1',)):
    ports = [SimpleNamespace(contract_id=c) for c in contract_ids]
    return SimpleNamespace(id=pid, name='Orders', description='Orders data', output_ports=ports)


def test_contract_notes_are_written_under_the_product_with_the_contract_name():
    metadata_map = {
        'p1': [_note('Product note', 'about the product')],
        'c1': [_note('Revenue', 'revenue = price * quantity', short='How revenue is computed')],
    }

    text = format_metadata_for_genie(metadata_map, [_product()], contract_names={'c1': 'Orders v1'})

    assert '### Product note' in text
    assert '### Contract: Orders v1' in text
    assert '#### Revenue' in text
    assert 'How revenue is computed' in text
    assert 'revenue = price * quantity' in text
    assert text.index('Product note') < text.index('Contract: Orders v1') < text.index('Revenue')


def test_contract_heading_falls_back_to_the_contract_id():
    text = format_metadata_for_genie({'c1': [_note('N', 'body')]}, [_product()])

    assert '### Contract: c1' in text


def test_a_contract_shared_by_two_ports_is_written_once():
    product = _product(contract_ids=('c1', 'c1'))

    text = format_metadata_for_genie({'c1': [_note('N', 'body')]}, [product])

    assert text.count('### Contract:') == 1


def test_notes_of_a_contract_that_is_not_on_the_product_are_not_written():
    text = format_metadata_for_genie({'other': [_note('N', 'body')]}, [_product()])

    assert 'Contract:' not in text
    assert 'body' not in text


def test_contract_without_notes_has_no_heading():
    text = format_metadata_for_genie({'p1': [_note('P', 'x')]}, [_product()])

    assert 'Contract:' not in text


def test_each_product_gets_only_its_own_contracts():
    metadata_map = {'c1': [_note('One', 'first')], 'c2': [_note('Two', 'second')]}
    products = [_product('p1', ('c1',)), _product('p2', ('c2',))]

    text = format_metadata_for_genie(metadata_map, products, contract_names={'c1': 'A', 'c2': 'B'})

    first, second = text.split('## Data Product: Orders')[1:]
    assert 'first' in first and 'second' not in first
    assert 'second' in second and 'first' not in second


def test_contract_notes_follow_the_length_limit():
    metadata_map = {'c1': [_note(f'Note {i}', 'x' * 900) for i in range(10)]}

    text = format_metadata_for_genie(metadata_map, [_product()])

    assert len(text) == 5000
    assert text.endswith('...')
    assert '### Contract: c1' in text


def test_collect_contract_names_maps_ids_to_names(db_session):
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name='Orders v1', version='1.0.0', status='draft'))
    db_session.commit()

    assert collect_contract_names([cid, 'missing'], db_session) == {cid: 'Orders v1'}
    assert collect_contract_names([], db_session) == {}
