"""The AMQ connection: TLS only, with the broker verified against amq_ca_certs."""

import pytest

import wlcgConverter
from conftest import make_config
from wlcg.config import ConfigError

connect_to_broker = wlcgConverter.connect_to_broker


class FakeConnection:

    def __init__(self, hosts):
        self.hosts = hosts
        self.calls = []

    def set_ssl(self, **kwargs):
        self.calls.append(("set_ssl", kwargs))

    def connect(self, *args, **kwargs):
        self.calls.append(("connect", args))


@pytest.fixture
def fake_stomp(monkeypatch):
    monkeypatch.setattr(wlcgConverter.stomp, "Connection12", FakeConnection)


@pytest.fixture
def files(tmp_path):
    paths = {}
    for name in ("ca.pem", "cert.pem", "key.pem"):
        path = tmp_path / name
        path.write_text("dummy")
        paths[name] = str(path)
    return paths


def amq_conf(files, **auth):
    settings = {"send_data": True, "amq_host": "broker.example.org", "amq_port": "61113",
                "amq_port_tls": "61123", "amq_topic": "/topic/test", "amq_ca_certs": files["ca.pem"]}
    settings.update(auth)
    return make_config(**settings)


def test_certificate_auth_verifies_the_broker(fake_stomp, files):
    conf = amq_conf(files, path_to_cert=files["cert.pem"], path_to_key=files["key.pem"])
    conn = connect_to_broker(conf)
    assert conn.hosts == [("broker.example.org", 61123)]
    (name, ssl_args), (second, _) = conn.calls
    assert (name, second) == ("set_ssl", "connect")
    assert ssl_args["ca_certs"] == files["ca.pem"]
    assert (ssl_args["cert_file"], ssl_args["key_file"]) == (files["cert.pem"], files["key.pem"])
    # an explicit PROTOCOL_TLSv1_2 context would skip the hostname check
    assert "ssl_version" not in ssl_args


def test_password_is_only_sent_over_verified_tls(fake_stomp, files):
    conn = connect_to_broker(amq_conf(files, username="u", password="p"))
    assert conn.hosts == [("broker.example.org", 61123)]
    assert [name for name, _ in conn.calls] == ["set_ssl", "connect"]
    assert conn.calls[0][1]["ca_certs"] == files["ca.pem"]
    assert conn.calls[1][1] == ("u", "p", )


@pytest.mark.parametrize("missing", ["amq_host", "amq_topic", "amq_port_tls", "amq_ca_certs"])
def test_send_data_needs_the_broker_settings(files, missing):
    settings = {"username": "u", "password": "p", missing: None}
    with pytest.raises(ConfigError, match=missing):
        amq_conf(files, **settings)


def test_send_data_needs_credentials(files):
    with pytest.raises(ConfigError, match="username"):
        amq_conf(files)
    with pytest.raises(ConfigError, match="path_to_key"):
        amq_conf(files, path_to_cert=files["cert.pem"])


@pytest.mark.parametrize("key", ["amq_ca_certs", "path_to_cert", "path_to_key"])
def test_tls_files_must_exist(files, key):
    settings = {"path_to_cert": files["cert.pem"], "path_to_key": files["key.pem"], key: "/nonexistent/file.pem"}
    with pytest.raises(ConfigError, match="no such file"):
        amq_conf(files, **settings)


def test_files_are_not_checked_without_send_data():
    conf = make_config(send_data=False, amq_ca_certs="/nonexistent/ca.pem")
    assert conf["send_data"] is False
