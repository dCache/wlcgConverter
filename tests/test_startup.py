"""Startup and shutdown of main(): Kafka unreachable, and the broker connection when send_data is on."""

import logging
import sys

import pytest
import yaml

import wlcgConverter


def test_unreachable_kafka_exits_1_with_a_clear_message(monkeypatch, tmp_path, caplog):
    def unreachable(*args, **kwargs):
        raise RuntimeError("Unable to bootstrap from ['localhost:1']")

    monkeypatch.setattr(wlcgConverter, "KafkaConsumer", unreachable)
    monkeypatch.setattr(wlcgConverter, "load_registry", lambda url, cache_file: None)
    raw = {"kafka_broker_incoming": ["localhost:1"], "topic": "t", "instance": "i",
           "server_site": "DESY-HH", "server_version": "10.2.5",
           "config::logging": {"version": 1, "disable_existing_loggers": False}}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(raw))
    monkeypatch.setattr(sys, "argv", ["wlcgConverter", str(config)])

    with caplog.at_level(logging.ERROR, logger="wlcgConverter"), pytest.raises(SystemExit) as exit_info:
        wlcgConverter.main()
    assert exit_info.value.code == 1
    assert "Could not connect to Kafka at ['localhost:1']: Unable to bootstrap" in caplog.text
    assert "batch" not in caplog.text


def test_main_connects_to_the_broker_and_disconnects_at_the_end(monkeypatch, tmp_path):
    calls = []

    class FakeStomp:
        def __init__(self, hosts):
            calls.append(("connection", hosts))

        def set_listener(self, name, listener):
            calls.append(("listener", type(listener).__name__))

        def set_ssl(self, **kwargs):
            calls.append(("set_ssl", kwargs["ca_certs"]))

        def connect(self, *args, **kwargs):
            calls.append(("connect", args))

        def is_connected(self):
            return True

        def disconnect(self):
            calls.append(("disconnect",))

    class StoppedByCtrlC:
        def __init__(self, **kwargs):
            pass

        def run(self, converter):
            calls.append(("run", type(converter.sender).__name__))
            raise KeyboardInterrupt()

    monkeypatch.setattr(wlcgConverter.stomp, "Connection12", FakeStomp)
    monkeypatch.setattr(wlcgConverter, "BillingConsumer", StoppedByCtrlC)
    monkeypatch.setattr(wlcgConverter, "load_registry", lambda url, cache_file: None)
    ca = tmp_path / "ca.pem"
    ca.write_text("dummy")
    raw = {"kafka_broker_incoming": ["localhost:9092"], "topic": "t", "instance": "i",
           "server_site": "DESY-HH", "server_version": "10.2.5",
           "send_data": True, "amq_host": "broker.example.org", "amq_port_tls": "61123",
           "amq_topic": "/topic/test", "amq_ca_certs": str(ca), "username": "u", "password": "p",
           "config::logging": {"version": 1, "disable_existing_loggers": False}}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(raw))
    monkeypatch.setattr(sys, "argv", ["wlcgConverter", str(config)])

    wlcgConverter.main()
    assert calls == [
        ("connection", [("broker.example.org", 61123)]),
        ("set_ssl", str(ca)),
        ("connect", ("u", "p")),
        ("listener", "AmqSender"),
        ("run", "AmqSender"),
        ("disconnect",),
    ]
