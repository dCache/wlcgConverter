import re
from ipaddress import ip_address

import pytest

from wlcg.net import canonical_ip, ip_version, match_networks, parse_ip, parse_network, split_endpoint


@pytest.mark.parametrize("endpoint, expected", [
    ("[2001:638:700:1062::1:d8]:33147", "2001:638:700:1062::1:d8"),
    ("131.169.5.5:33147", "131.169.5.5"),
    ("2001:638:700:1062::1:d8", "2001:638:700:1062::1:d8"),
    ("131.169.5.5", "131.169.5.5"),
    (" 131.169.5.5:1 ", "131.169.5.5"),
    ("[2001:db8::1", "[2001:db8::1"),
    ("", None),
    (None, None),
])
def test_split_endpoint(endpoint, expected):
    assert split_endpoint(endpoint) == expected


@pytest.mark.parametrize("value, expected", [
    # RFC 5952: longest zero run compressed, lowercase
    ("2001:638:700:10a0:0:0:1:479", "2001:638:700:10a0::1:479"),
    ("2001:0DB8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
    ("131.169.5.5", "131.169.5.5"),
    # IPv4-mapped IPv6 is unwrapped
    ("::ffff:131.169.5.5", "131.169.5.5"),
    # garbage passes through raw, missing becomes empty
    ("not-an-ip", "not-an-ip"),
    (None, ""),
])
def test_canonical_ip(value, expected):
    assert canonical_ip(value) == expected


@pytest.mark.parametrize("value, expected", [
    ("2001:638:700:10a0:0:0:1:479", "ipv6"),
    ("131.169.5.5", "ipv4"),
    ("::ffff:131.169.5.5", "ipv4"),
    ("not-an-ip", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_ip_version(value, expected):
    assert ip_version(value) == expected


def test_parse_ip_strips_whitespace():
    assert parse_ip(" 131.169.5.5 ") == ip_address("131.169.5.5")


def test_parse_network_accepts_host_bits():
    assert str(parse_network("131.169.5.5/16")) == "131.169.0.0/16"


@pytest.mark.parametrize("cidr", ["131.169.0.0/33", "nonsense", "2001:638:700::/129"])
def test_parse_network_names_bad_value(cidr):
    with pytest.raises(ValueError, match=re.escape(cidr)):
        parse_network(cidr)


NETWORKS = [parse_network(c) for c in ("131.169.0.0/16", "131.169.5.0/24", "2001:638:700::/48")]


@pytest.mark.parametrize("value, expected", [
    ("131.169.5.5", "131.169.5.0/24"),      # longest prefix wins
    ("131.169.9.9", "131.169.0.0/16"),
    ("2001:638:700:10a0::1:479", "2001:638:700::/48"),
    ("::ffff:131.169.9.9", "131.169.0.0/16"),
    ("2001:1458:d00:1::100:f5", None),
    ("10.0.0.1", None),
    ("not-an-ip", None),
    (None, None),
])
def test_match_networks(value, expected):
    match = match_networks(value, NETWORKS)
    assert (str(match) if match else None) == expected


def test_match_networks_accepts_address_object():
    assert str(match_networks(ip_address("131.169.9.9"), NETWORKS)) == "131.169.0.0/16"


def test_match_networks_empty_list():
    assert match_networks("131.169.5.5", []) is None
