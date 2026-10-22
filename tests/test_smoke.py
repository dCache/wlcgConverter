import pytest

import wlcgConverter


class FakeConnection:

    def __init__(self, hosts):
        self.hosts = hosts

    def connect(self, *args, **kwargs):
        pass


@pytest.fixture
def fake_stomp(monkeypatch):
    monkeypatch.setattr(wlcgConverter.stomp, "Connection12", FakeConnection)


def test_script_imports():
    assert callable(wlcgConverter.main)


def test_amq_port_used_when_tls_port_absent(fake_stomp):
    # empty YAML values are dropped, so a blank amq_port_tls is simply missing
    conf = {"amq_host": "localhost", "amq_port": "61113", "username": "u", "password": "p"}
    conn = wlcgConverter.__dict__["__connect_2_activemq"](conf)
    assert conn.hosts == [("localhost", 61113)]


def test_amq_port_tls_wins_when_set(fake_stomp):
    conf = {"amq_host": "localhost", "amq_port": "61113", "amq_port_tls": "61123",
            "username": "u", "password": "p"}
    conn = wlcgConverter.__dict__["__connect_2_activemq"](conf)
    assert conn.hosts == [("localhost", 61123)]
