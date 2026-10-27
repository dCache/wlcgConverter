"""Startup: an unreachable Kafka stops the converter with a clear message."""

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
