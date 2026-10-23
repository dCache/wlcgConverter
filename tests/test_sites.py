"""src_site / dst_site, traffic_scope and remote_access."""

import pytest

from conftest import billing_record, make_config
from wlcg.schema import build_record

DESY = ["131.169.0.0/16", "2001:638:700::/48"]
LOCAL_CLIENT = "2001:638:700:10a0:0:0:1:479"
REMOTE_CLIENT = "2001:1458:d00:1:0:0:100:f5"


def record_for(client, direction="read", local_networks=DESY):
    conf = make_config(local_networks=local_networks)
    return build_record(billing_record(mover={"isWrite": direction}, protocol={"host": client}), conf)


def sites(record):
    return record["src_site"], record["dst_site"], record["traffic_scope"], record.get("remote_access")


def test_local_read_is_lan():
    assert sites(record_for(LOCAL_CLIENT)) == ("DESY-HH", "DESY-HH", "LAN", False)


def test_lan_record_ends_with_the_scope_fields():
    assert list(record_for(LOCAL_CLIENT))[-4:] == ["src_site", "dst_site", "traffic_scope", "remote_access"]


def test_local_write_is_lan():
    assert sites(record_for(LOCAL_CLIENT, "write")) == ("DESY-HH", "DESY-HH", "LAN", False)


def test_remote_client_resolves_to_its_ip():
    record = record_for(REMOTE_CLIENT)
    assert sites(record) == ("DESY-HH", "2001:1458:d00:1::100:f5", "UNKNOWN", None)
    assert "remote_access" not in record


def test_remote_write_swaps_the_sites():
    assert sites(record_for(REMOTE_CLIENT, "write"))[:2] == ("2001:1458:d00:1::100:f5", "DESY-HH")


def test_ipv4_mapped_client_matches_an_ipv4_network():
    assert record_for("::ffff:131.169.5.5")["traffic_scope"] == "LAN"


def test_without_local_networks_everything_is_unknown():
    assert sites(record_for(LOCAL_CLIENT, local_networks=None))[2:] == ("UNKNOWN", None)


@pytest.mark.parametrize("direction", [None, "copy"])
def test_unknown_direction_leaves_sites_empty_but_keeps_the_scope(direction):
    # the scope only needs the client, not the direction
    assert sites(record_for(LOCAL_CLIENT, direction)) == ("", "", "LAN", False)


@pytest.mark.parametrize("client", [None, "", "not-an-ip"])
def test_missing_or_unparsable_client_is_unknown(client):
    record = record_for(client)
    assert record["traffic_scope"] == "UNKNOWN"
    assert record["src_site"] == "DESY-HH"
