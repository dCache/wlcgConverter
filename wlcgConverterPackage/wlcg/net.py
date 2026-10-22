"""IP address and network helpers used by the schema builder."""

from ipaddress import ip_address, ip_network


def split_endpoint(endpoint):
    """
    Strip the port from a pool endpoint.

    '[2001:db8::1]:33147' -> '2001:db8::1', '10.0.0.1:33147' -> '10.0.0.1'.
    A bare address (v4 or v6) is returned unchanged; None/empty -> None.
    """
    if not endpoint:
        return None
    endpoint = str(endpoint).strip()
    if endpoint.startswith('['):
        end = endpoint.find(']')
        return endpoint[1:end] if end > 0 else endpoint
    if endpoint.count(':') == 1:
        return endpoint.split(':')[0]
    return endpoint


def parse_ip(value):
    """Return an ip_address object, unwrapping IPv4-mapped IPv6; None if unparsable."""
    if value is None:
        return None
    try:
        addr = ip_address(str(value).strip())
    except ValueError:
        return None
    if addr.version == 6 and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def canonical_ip(value):
    """RFC 5952 form of an address; unparsable input is passed through raw, None -> ''."""
    if value is None:
        return ""
    addr = parse_ip(value)
    return addr.compressed if addr is not None else str(value)


def ip_version(value):
    """'ipv4' / 'ipv6' / 'unknown'."""
    addr = parse_ip(value)
    return "ipv%d" % addr.version if addr is not None else "unknown"


def parse_network(cidr):
    """Parse a CIDR string; raises ValueError naming the offending value on bad input."""
    try:
        return ip_network(str(cidr).strip(), strict=False)
    except ValueError as e:
        raise ValueError("invalid CIDR '%s': %s" % (cidr, e))


def match_networks(value, networks):
    """
    Longest-prefix match of an address against pre-parsed networks.

    :param value: address string or ip_address object
    :param networks: list of ip_network objects
    :return: the most specific matching network, or None
    """
    addr = value if hasattr(value, 'version') else parse_ip(value)
    if addr is None:
        return None
    best = None
    for network in networks:
        if addr.version == network.version and addr in network:
            if best is None or network.prefixlen > best.prefixlen:
                best = network
    return best
