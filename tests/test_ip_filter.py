"""The v1 IP filter: clients in the configured IPv4 or IPv6 subnet are not sent to AMQ."""

import json
from collections import namedtuple

import pytest

import wlcgConverter
from conftest import billing_record, make_config

Message = namedtuple("Message", "value")

FILTER = {
    "ip_filter_is_active": True,
    "ipv4_network_address": "131.169.0.0", "ipv4_cidr": "16",
    "ipv6_network_address": "2001:638:700::", "ipv6_cidr": "48",
}


class FakeAmq:

    def __init__(self):
        self.sent = []

    def send(self, destination, body, content_type):
        self.sent.append(json.loads(body))


def run(client, tmp_path, **overrides):
    settings = dict(FILTER, send_data=True, amq_host="localhost", amq_port_tls="61123", amq_topic="/topic/test",
                    amq_ca_certs=__file__, username="u", password="p",
                    local_dump=True, path_to_converted_json_file=str(tmp_path / "dump.json"))
    settings.update(overrides)
    amq = FakeAmq()
    converter = wlcgConverter.WlcgConverter(make_config(**settings), amq)
    converter.process(Message(billing_record(protocol={"host": client})))
    dumped = (tmp_path / "dump.json").read_text().splitlines()
    return len(amq.sent), len(dumped)


@pytest.mark.parametrize("client", ["131.169.5.5", "2001:638:700:10a0:0:0:1:479"])
def test_client_in_a_filtered_subnet_is_not_sent(client, tmp_path):
    sent, dumped = run(client, tmp_path)
    assert sent == 0
    assert dumped == 1      # the local dump keeps every record


@pytest.mark.parametrize("client", ["188.184.1.1", "2001:1458:d00:1:0:0:100:f5"])
def test_client_outside_both_subnets_is_sent(client, tmp_path):
    assert run(client, tmp_path) == (1, 1)


def test_filter_off_sends_everything(tmp_path):
    assert run("131.169.5.5", tmp_path, ip_filter_is_active=False) == (1, 1)
