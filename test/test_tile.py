import json
import os
import pytest
import test

from blackmagic import app
from blackmagic import db
from cassandra.cluster import Cluster
from cytoolz import get
from cytoolz import reduce


@pytest.fixture
def client():
    app.app.config['TESTING'] = True
    yield app.app.test_client()


@test.vcr.use_cassette(test.cassette)
def test_tile_runs_as_expected(client):
    '''
    As a blackmagic user, when I send tx, ty, date & chips
    via HTTP POST, an xgboost model is trained and saved
    to Cassandra so that change segments may be classified.
    '''

    tx    = test.tx
    ty    = test.ty
    chips = test.chips
    date  = test.date
    
    response = client.post('/tile',
                           json={'tx': tx,
                                 'ty': ty,
                                 'chips': chips,
                                 'date': date})

    assert response.status == '200 OK'
    assert get('tx', response.get_json()) == tx
    assert get('ty', response.get_json()) == ty
    assert get('date', response.get_json()) == date
    assert get('chips', response.get_json()) == chips
    assert get('exception', response.get_json(), None) == None


@test.vcr.use_cassette(test.cassette)
def test_tile_bad_parameters(client):
    '''
    As a blackmagic user, when I don't send tx, ty, date & chips
    via HTTP POST the HTTP status is 400 and the response body tells
    me the required parameters so that I can send a good request.
    '''

    tx    = test.tx
    ty    = test.ty
    chips = test.chips
    date  = test.date
    
    response = client.post('/tile',
                           json={'tx': tx,
                                 'ty': ty,
                                 'chips': chips,
                                 'date': date})

    assert response.status == '400 BAD REQUEST'
    assert get('tx', response.get_json()) == tx
    assert get('ty', response.get_json()) == ty
    assert get('date', response.get_json()) == date
    assert get('chips', response.get_json()) == chips
    assert type(get('exception', response.get_json())) is str
    assert len(get('exception', response.get_json())) > 0


@test.vcr.use_cassette(test.cassette)
def test_tile_data_exception(client):
    '''
    As a blackmagic user, when an exception occurs retrieving 
    and constructing training data, an HTTP 500 is issued with a 
    message describing the failure so that the issue may be resolved.
    '''

    tx    = test.tx
    ty    = test.ty
    chips = test.chips
    date  = test.date
    
    response = client.post('/tile',
                           json={'tx': tx,
                                 'ty': ty,
                                 'chips': chips,
                                 'date': date,
                                 'test_data_exception': True})

    assert response.status == '500 INTERNAL SERVER ERROR'
    assert get('tx', response.get_json()) == tx
    assert get('ty', response.get_json()) == ty
    assert get('date', response.get_json()) == date
    assert get('chips', response.get_json()) == chips
    assert type(get('exception', response.get_json())) is str
    assert len(get('exception', response.get_json())) > 0


@test.vcr.use_cassette(test.cassette)
def test_tile_training_exception(client):
    '''
    As a blackmagic user, when an exception occurs training 
    a model, an HTTP 500 is issued with a message describing 
    the failure so that the issue may be investigated & resolved.
    '''

    tx    = test.tx
    ty    = test.ty
    chips = test.chips
    date  = test.date
    
    response = client.post('/tile',
                           json={'tx': tx,
                                 'ty': ty,
                                 'chips': chips,
                                 'date': date,
                                 'test_training_exception': True})

    assert response.status == '500 INTERNAL SERVER ERROR'
    assert get('tx', response.get_json()) == tx
    assert get('ty', response.get_json()) == ty
    assert get('date', response.get_json()) == date
    assert get('chips', response.get_json()) == chips
    assert type(get('exception', response.get_json())) is str
    assert len(get('exception', response.get_json())) > 0


@test.vcr.use_cassette(test.cassette)
def test_tile_cassandra_exception(client):
    '''
    As a blackmagic user, when an exception occurs saving 
    models to Cassandra, an HTTP 500 is issued
    with a descriptive message so that the issue may be 
    investigated, corrected & retried.
    '''

    tx    = test.tx
    ty    = test.ty
    chips = test.chips
    date  = test.date
    
    response = client.post('/tile',
                           json={'tx': tx,
                                 'ty': ty,
                                 'chips': chips,
                                 'date': date,
                                 'test_cassandra_exception': True})

    assert response.status == '500 INTERNAL SERVER ERROR'
    assert get('tx', response.get_json()) == tx
    assert get('ty', response.get_json()) == ty
    assert get('date', response.get_json()) == date
    assert get('chips', response.get_json()) == chips
    assert type(get('exception', response.get_json())) is str
    assert len(get('exception', response.get_json())) > 0


def test_tile_aux():
    pass


def test_tile_segments():
    pass


def test_tile_datefilter():
    pass


def test_tile_combine():
    pass


def test_tile_format():
    pass


def test_tile_independent():
    pass


def test_tile_dependent():
    pass


def test_tile_watchlist():
    pass


def test_tile_pipeline():
    pass


def test_tile_parameters():
    pass


def test_tile_log_request():
    pass


def test_tile_exception_handler():
    pass


def test_tile_data():
    pass


def test_tile_counts():
    pass


def test_tile_statistics():
    pass


def test_tile_randomize():
    pass


def test_tile_sample():
    pass


def test_tile_train():
    pass


def test_tile_save():
    pass


def test_tile_respond():
    pass
