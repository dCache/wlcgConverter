"""Delivery: records are committed in Kafka only after the broker confirms them."""

import json
import logging
import sys
from collections import namedtuple

import pytest
import yaml

import wlcgConverter
from conftest import billing_record, make_config
from wlcgConverter import AmqSender, DeliveryError

Message = namedtuple("Message", "value")
Frame = namedtuple("Frame", "headers")


class FakeStomp:
    """A stomp connection; 'broker' decides how the fake broker reacts to a frame with a receipt."""

    def __init__(self, broker="confirm", connected=True):
        self.broker = broker
        self.connected = connected
        self.frames = []
        self.listener = None

    def set_listener(self, name, listener):
        self.listener = listener

    def is_connected(self):
        return self.connected

    def send(self, destination, body, content_type, headers):
        if self.broker == "raise":
            raise RuntimeError("socket closed")
        self.frames.append((destination, json.loads(body), headers))
        receipt = headers.get("receipt")
        if receipt is None:
            return
        if self.broker == "confirm":
            self.listener.on_receipt(Frame({"receipt-id": receipt}))
        elif self.broker == "confirm-other":
            self.listener.on_receipt(Frame({"receipt-id": "someone-else"}))
        elif self.broker == "disconnect":
            self.listener.on_disconnected()
        elif self.broker == "error":
            self.listener.on_error(Frame({"message": "User is not authorized to write to: topic://x"}))
        # "silent": no answer at all


def sender_with(broker, **kwargs):
    stomp = FakeStomp(broker, **kwargs)
    return AmqSender(stomp, timeout=0.2), stomp


def queue(sender, n):
    for i in range(n):
        sender.send(destination="/topic/test", body=json.dumps({"n": i}), content_type="application/json")


# --- AmqSender ---------------------------------------------------------------------------------

def test_confirmed_batch_asks_one_receipt_on_the_last_record():
    sender, stomp = sender_with("confirm")
    queue(sender, 3)
    sender.confirm()
    assert [body["n"] for _, body, _ in stomp.frames] == [0, 1, 2]
    assert [("receipt" in headers) for _, _, headers in stomp.frames] == [False, False, True]
    assert sender.pending == []


def test_nothing_pending_sends_nothing():
    sender, stomp = sender_with("silent")
    sender.confirm()
    assert stomp.frames == []


@pytest.mark.parametrize("broker, message", [
    ("silent", "did not confirm 2 records"),
    ("confirm-other", "did not confirm 2 records"),
    ("disconnect", "connection to the broker was lost"),
    ("error", "User is not authorized"),
    ("raise", "sending failed: socket closed"),
])
def test_unconfirmed_batch_raises(broker, message):
    sender, _ = sender_with(broker)
    queue(sender, 2)
    with pytest.raises(DeliveryError, match=message):
        sender.confirm()


def test_lost_connection_sends_nothing():
    sender, stomp = sender_with("confirm", connected=False)
    queue(sender, 2)
    with pytest.raises(DeliveryError, match="not connected"):
        sender.confirm()
    assert stomp.frames == []


def test_disconnect_after_the_receipt_keeps_the_batch_confirmed():
    sender, _ = sender_with("confirm")
    queue(sender, 1)
    sender.confirm()
    sender.on_disconnected()        # e.g. at shutdown


def test_a_new_batch_after_a_lost_connection_fails():
    sender, stomp = sender_with("confirm")
    queue(sender, 1)
    sender.confirm()
    stomp.connected = False
    sender.on_disconnected()
    queue(sender, 1)
    with pytest.raises(DeliveryError, match="not connected"):
        sender.confirm()


# --- the batch loop ----------------------------------------------------------------------------

class EndOfTest(Exception):
    pass


class FakeConsumer:
    """Returns the given batches from poll(), then ends the loop; records commit() calls."""

    def __init__(self, batches):
        self.batches = list(batches)
        self.commits = 0

    def poll(self, timeout_ms, max_records):
        if not self.batches:
            raise EndOfTest()
        return self.batches.pop(0)

    def commit(self):
        self.commits += 1


def kafka_batch(*records):
    return {"partition-0": [Message(r) for r in records]}


def run_loop(conf, sender, batches):
    consumer = wlcgConverter.CustomKafkaConsumer.__new__(wlcgConverter.CustomKafkaConsumer)
    consumer.consumer = FakeConsumer(batches)
    converter = wlcgConverter.WlcgConverter(conf, activemq_connection=sender)
    try:
        consumer.getMessage(converter)
    except EndOfTest:
        pass
    return consumer.consumer


def amq_config(**overrides):
    settings = {"send_data": True, "amq_host": "localhost", "amq_port_tls": "61123", "amq_topic": "/topic/test",
                "amq_ca_certs": __file__, "username": "u", "password": "p"}
    settings.update(overrides)
    return make_config(**settings)


def test_each_confirmed_batch_is_committed():
    sender, stomp = sender_with("confirm")
    consumer = run_loop(amq_config(), sender, [kafka_batch(billing_record(), billing_record()), {},
                                               kafka_batch(billing_record())])
    assert consumer.commits == 2          # the empty poll commits nothing
    assert len(stomp.frames) == 3


def test_unconfirmed_batch_is_not_committed():
    sender, _ = sender_with("silent")
    consumer = wlcgConverter.CustomKafkaConsumer.__new__(wlcgConverter.CustomKafkaConsumer)
    consumer.consumer = FakeConsumer([kafka_batch(billing_record())])
    with pytest.raises(DeliveryError):
        consumer.getMessage(wlcgConverter.WlcgConverter(amq_config(), activemq_connection=sender))
    assert consumer.consumer.commits == 0


def test_batch_without_records_to_send_is_committed():
    sender, stomp = sender_with("silent")
    consumer = run_loop(amq_config(), sender, [kafka_batch(billing_record(top={"msgType": "transfer"}), None)])
    assert (consumer.commits, stomp.frames) == (1, [])


def test_local_dump_failure_stops_before_sending_or_committing(tmp_path):
    # before, an unwritable dump file made the record vanish without a log line
    sender, stomp = sender_with("confirm")
    conf = amq_config(local_dump=True, path_to_converted_json_file=str(tmp_path / "missing-dir" / "out.json"))
    consumer = wlcgConverter.CustomKafkaConsumer.__new__(wlcgConverter.CustomKafkaConsumer)
    consumer.consumer = FakeConsumer([kafka_batch(billing_record())])
    with pytest.raises(OSError):
        consumer.getMessage(wlcgConverter.WlcgConverter(conf, activemq_connection=sender))
    assert (consumer.consumer.commits, stomp.frames) == (0, [])


def test_without_send_data_the_batch_is_committed_after_the_dump(tmp_path):
    dump = tmp_path / "out.json"
    conf = make_config(local_dump=True, path_to_converted_json_file=str(dump))
    consumer = run_loop(conf, None, [kafka_batch(billing_record(), billing_record())])
    assert consumer.commits == 1
    assert len(dump.read_text().splitlines()) == 2


# --- main --------------------------------------------------------------------------------------

def run_main(monkeypatch, tmp_path, failure):
    class StoppingConsumer:
        def __init__(self, **kwargs):
            pass

        def getMessage(self, analyser):
            raise failure

    monkeypatch.setattr(wlcgConverter, "CustomKafkaConsumer", StoppingConsumer)
    monkeypatch.setattr(wlcgConverter, "load_registry", lambda url, cache_file: None)
    raw = {"kafka_broker_incoming": ["localhost:9092"], "topic": "t", "instance": "i",
           "server_site": "DESY-HH", "server_version": "10.2.5",
           "config::logging": {"version": 1, "disable_existing_loggers": False}}
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(raw))
    monkeypatch.setattr(sys, "argv", ["wlcgConverter", str(config)])
    wlcgConverter.main()


def test_main_exits_1_when_a_batch_is_not_confirmed(monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="wlcgConverter"), pytest.raises(SystemExit) as exit_info:
        run_main(monkeypatch, tmp_path, DeliveryError("the connection to the broker was lost"))
    assert exit_info.value.code == 1
    assert "connection to the broker was lost" in caplog.text
    assert "not committed" in caplog.text


def test_main_exits_1_on_an_unexpected_error(monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.ERROR, logger="wlcgConverter"), pytest.raises(SystemExit) as exit_info:
        run_main(monkeypatch, tmp_path, OSError("No space left on device"))
    assert exit_info.value.code == 1
    assert "No space left on device" in caplog.text


def test_ctrl_c_ends_main_normally(monkeypatch, tmp_path):
    run_main(monkeypatch, tmp_path, KeyboardInterrupt())
