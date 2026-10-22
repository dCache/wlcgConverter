"""WlcgConverter.execute: the request/protocol gate, the outputs and the error handling."""

import json
from collections import namedtuple

import pytest

import wlcgConverter
from conftest import billing_record, make_config

Message = namedtuple("Message", "value")


class FakeAmq:

    def __init__(self):
        self.sent = []

    def send(self, destination, body, content_type):
        self.sent.append((destination, json.loads(body)))


@pytest.fixture
def amq():
    return FakeAmq()


def converter(amq, **overrides):
    settings = {"send_data": True, "amq_topic": "/topic/test"}
    settings.update(overrides)
    conf = make_config(**settings)
    return wlcgConverter.WlcgConverter(conf, activemq_connection=amq)


def test_request_record_is_sent(amq):
    converter(amq).execute(Message(billing_record()))
    assert len(amq.sent) == 1
    destination, record = amq.sent[0]
    assert destination == "/topic/test"
    assert record["protocol"] == "xroot"


def test_failed_transfer_is_sent(amq):
    status = {"code": 10007, "msg": "Pool not available"}
    converter(amq).execute(Message(billing_record(top={"status": status}, mover={"status": status})))
    assert [record["status_code"] for _, record in amq.sent] == [10007]


@pytest.mark.parametrize("raw", [
    billing_record(top={"msgType": "transfer"}),
    billing_record(protocol={"protocol": "Http"}),
])
def test_gate_skips_other_records(amq, raw):
    converter(amq).execute(Message(raw))
    assert amq.sent == []


def test_nothing_sent_without_send_data(amq):
    conf = make_config(send_data=False)
    wlcgConverter.WlcgConverter(conf, activemq_connection=amq).execute(Message(billing_record()))
    assert amq.sent == []


def test_local_dump_appends_json_lines(amq, tmp_path):
    dump = tmp_path / "out.json"
    conv = converter(amq, send_data=False, local_dump=True, path_to_converted_json_file=str(dump))
    conv.execute(Message(billing_record()))
    conv.execute(Message(billing_record(mover={"isWrite": "write"})))
    lines = [json.loads(line) for line in dump.read_text().splitlines()]
    assert [line["operation"] for line in lines] == ["read", "write"]


def test_conversion_error_is_logged_and_skipped(amq, monkeypatch, caplog):
    def broken(raw, conf):
        raise ValueError("boom")

    monkeypatch.setattr(wlcgConverter, "build_record", broken)
    converter(amq).execute(Message(billing_record()))
    assert amq.sent == []
    assert "could not be converted" in caplog.text


def test_amq_errors_still_propagate(amq):
    class DeadAmq:
        def send(self, **kwargs):
            raise ConnectionError("broker gone")

    with pytest.raises(ConnectionError):
        converter(DeadAmq()).execute(Message(billing_record()))
