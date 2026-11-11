"""Server errors don't send an exception's text to the browser.

Many routes answer an unexpected failure with ``HTTPException(500,
detail=f"...: {e}")``. For a database error that text holds the SQL statement
and its parameters. The exception handler answers such an error with a generic
message, the code ``internal_error`` and an error id, and logs the original
text with that id. Errors whose text is written by the route, client errors
(4xx) and coded errors are answered as before.
"""
import logging
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.common.api_errors import (
    INTERNAL_ERROR_CODE,
    CodedValueError,
    coded_http_exception_handler,
)

SQL_TEXT = (
    'new row for relation "data_products" violates check constraint "leak_test"\n'
    "[SQL: INSERT INTO data_products (id, name) VALUES (%(id)s, %(name)s)]\n"
    "[parameters: {'id': 'p-1', 'name': 'Secret Product'}]"
)


def _db_error():
    return IntegrityError('INSERT INTO data_products ...', {'name': 'Secret Product'}, Exception(SQL_TEXT))


class _Coded(CodedValueError):
    code = 'some_code'


app = FastAPI()
app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)


@app.post('/fstring')
def fstring():
    try:
        raise _db_error()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Unexpected error creating data product: {e!s}')


@app.post('/indirect')
def indirect():
    try:
        raise _db_error()
    except Exception as e:
        error_msg = f'Error retrieving data contracts: {e}'
        raise HTTPException(status_code=500, detail=error_msg)


@app.post('/raise-from')
def raise_from():
    try:
        raise RuntimeError('/Users/someone/.databrickscfg has no profile configured')
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail={'message': str(e)}) from e


@app.post('/route-text')
def route_text():
    try:
        raise _db_error()
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to create contract')


@app.post('/no-cause')
def no_cause():
    raise HTTPException(status_code=500, detail='Data Products service is not available.')


@app.post('/client-error')
def client_error():
    try:
        raise ValueError('Product name is required')
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post('/coded')
def coded():
    try:
        raise _Coded('Something specific happened', entity='p-1')
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


client = TestClient(app)


@pytest.mark.parametrize('path', ['/fstring', '/indirect'])
def test_a_server_error_repeating_the_exception_text_gets_a_generic_message(path, caplog):
    with caplog.at_level(logging.ERROR, logger='src.common.api_errors'):
        response = client.post(path)

    assert response.status_code == 500
    body = response.json()
    assert body['code'] == INTERNAL_ERROR_CODE
    error_id = body['params']['errorId']
    assert body['detail'] == (
        f'An unexpected error occurred. The details are in the server log (error id {error_id}).'
    )
    assert 'INSERT INTO' not in response.text and 'Secret Product' not in response.text
    # The original text is in the log, with the same error id.
    logged = '\n'.join(r.getMessage() for r in caplog.records)
    assert error_id in logged and 'INSERT INTO data_products' in logged


def test_an_exception_raised_from_and_nested_in_a_dict_detail_is_hidden_too():
    response = client.post('/raise-from')

    assert response.status_code == 502
    assert response.json()['code'] == INTERNAL_ERROR_CODE
    assert '.databrickscfg' not in response.text


def test_each_server_error_gets_its_own_error_id():
    first = client.post('/fstring').json()['params']['errorId']
    second = client.post('/fstring').json()['params']['errorId']
    assert first != second


@pytest.mark.parametrize('path, detail', [
    ('/route-text', 'Failed to create contract'),
    ('/no-cause', 'Data Products service is not available.'),
])
def test_a_server_error_with_its_own_text_is_answered_as_before(path, detail):
    response = client.post(path)

    assert response.status_code == 500
    assert response.json() == {'detail': detail}


def test_a_client_error_keeps_the_exception_text():
    response = client.post('/client-error')

    assert response.status_code == 400
    assert response.json() == {'detail': 'Product name is required'}


def test_a_coded_error_keeps_its_code_and_parameters():
    response = client.post('/coded')

    assert response.status_code == 409
    assert response.json() == {'detail': {
        'code': 'some_code', 'message': 'Something specific happened', 'params': {'entity': 'p-1'},
    }}


def test_the_app_answers_http_errors_with_this_handler():
    from src.app import app as ontos_app

    assert ontos_app.exception_handlers[StarletteHTTPException] is coded_http_exception_handler
