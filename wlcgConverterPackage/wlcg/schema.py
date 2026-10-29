"""
Builds the v2 WLCG transfer record from a dCache billing record.

docs/RECORD.md describes the fields and how each is derived. String fields are
never None (empty string or 'unknown'); numeric fields are None only when the
billing record lacks them.
"""

import logging

from dateutil.parser import parse as parse_date

from .net import canonical_ip, ip_version, match_networks, split_endpoint

logger = logging.getLogger('wlcgConverter')

PROTOCOL_NAMES = {
    "xrootd": "xroot",
    "xroot": "xroot",
    "http": "https",
    "https": "https",
}

TOKEN_PRINCIPALS = {
    "OidcSubjectPrincipal",
    "JwtJtiPrincipal",
    "JwtSubPrincipal",
    "OpenIdGroupPrincipal",
    "OpenIdClientPrincipal",
    "OAuthProviderPrincipal",
}

UNKNOWN = "unknown"


def build_record(raw, conf, registry=None):
    """
    Convert one billing door record to the v2 WLCG record.

    :param raw: billing record dict as consumed from Kafka
    :param conf: wlcg.config.Config
    :param registry: wlcg.scitags.SciTagRegistry; without it activity is 'unknown'
    """
    mover = raw.get("moverInfo") or {}
    protocol_info = mover.get("protocolInfo") or {}

    record = {}
    record.update(_timing(raw, mover))
    record.update(_protocol(mover, protocol_info, conf))
    record.update(_endpoints(mover, protocol_info))
    record.update(_identity(raw, protocol_info, registry))
    record.update(_file_and_status(raw, mover, conf))
    record.update(_sites(mover, protocol_info, conf))
    logger.debug(record)
    return record


def _timing(raw, mover):
    """end = billing date, start = end - transferTime, both in ms."""
    start_time = end_time = None
    date = raw.get("date")
    if date is not None:
        try:
            end_millis = parse_date(date).timestamp() * 1000
        except (ValueError, OverflowError, TypeError):
            logger.debug("'date' is not a parsable timestamp: %r", date)
        else:
            # round, not int(): 1789396298.362 * 1000 is 1789396298361.9998
            end_time = int(round(end_millis))
            transfer_time = mover.get("transferTime")
            if transfer_time is not None:
                try:
                    start_time = end_time - int(transfer_time)
                except (TypeError, ValueError):
                    logger.debug("'transferTime' is not a number: %r", transfer_time)
    return {"start_time": start_time, "end_time": end_time}


def _protocol(mover, protocol_info, conf):
    """operation, protocol, protocol_version and the server_* fields from the config."""
    is_write = mover.get("isWrite")
    protocol = str(protocol_info.get("protocol") or "").lower()
    major, minor = protocol_info.get("versionMajor"), protocol_info.get("versionMinor")
    if major is None:
        version = ""
    elif minor is None:
        version = str(major)
    else:
        version = "%s.%s" % (major, minor)
    return {
        "operation": is_write if is_write in ("read", "write") else UNKNOWN,
        "protocol": PROTOCOL_NAMES.get(protocol, protocol),
        "protocol_version": version,
        "server_technology": conf.server_technology,
        "server_site": conf.server_site,
        "server_version": conf.server_version,
        "storage_instance": conf.storage_instance,
    }


def _endpoints(mover, protocol_info):
    """read: pool -> client; write: client -> pool. Unknown direction leaves both empty."""
    client = protocol_info.get("host")
    pool = split_endpoint(mover.get("localEndpoint"))
    direction = mover.get("isWrite")
    if direction == "read":
        src, dst = pool, client
    elif direction == "write":
        src, dst = client, pool
    else:
        src = dst = None
        logger.warning("WLCGConverter: transfer direction unknown (isWrite=%r); src/dst left empty", direction)
    src_ip, dst_ip = canonical_ip(src), canonical_ip(dst)
    return {
        "ipver": ip_version(client),
        "src_hostname": src_ip,
        "src_ip": src_ip,
        "dst_hostname": dst_ip,
        "dst_ip": dst_ip,
    }


def _sites(mover, protocol_info, conf):
    """
    The pool end is server_site. The client end is server_site when the client IP is in
    local_networks, otherwise it resolves to the client IP.
    """
    client = protocol_info.get("host")
    lan = match_networks(client, conf.local_networks) is not None
    client_site = conf.server_site if lan else canonical_ip(client)

    direction = mover.get("isWrite")
    if direction == "read":
        src_site, dst_site = conf.server_site, client_site
    elif direction == "write":
        src_site, dst_site = client_site, conf.server_site
    else:
        src_site = dst_site = ""

    if lan:
        return {"src_site": src_site, "dst_site": dst_site, "traffic_scope": "LAN", "remote_access": False}
    # an IP is not a site name, so whether the client is remote is not known:
    # traffic_scope says UNKNOWN and remote_access is not set
    return {"src_site": src_site, "dst_site": dst_site, "traffic_scope": "UNKNOWN"}


def _principal(entry):
    """'FQANPrincipal[/atlas,primary]' -> ('FQANPrincipal', '/atlas,primary'); a bare DN -> (None, dn)."""
    entry = str(entry)
    bracket = entry.find('[')
    if bracket > 0 and entry.endswith(']'):
        return entry[:bracket], entry[bracket + 1:-1]
    return None, entry


def vo_from_subject(subject):
    """
    VO of the primary FQAN, else of the first FQAN; None if there is none.
    Only the VO name is returned, never the FQAN's groups or roles.
    """
    first = None
    for entry in subject:
        name, value = _principal(entry)
        if name != "FQANPrincipal":
            continue
        parts = value.split(',')
        vo = parts[0].strip('/').split('/')[0].lower()
        if not vo:
            continue
        if "primary" in parts[1:]:
            return vo
        if first is None:
            first = vo
    return first


def auth_method(subject):
    """token / x509 / none / unknown, from the principals in the billing subject."""
    names = [_principal(entry) for entry in subject]
    if any(name in TOKEN_PRINCIPALS for name, _ in names):
        return "token"
    if any(name == "FQANPrincipal" or (name is None and value.startswith('/')) for name, value in names):
        return "x509"
    if all(name == "Origin" for name, _ in names):
        return "none"
    return UNKNOWN


def _identity(raw, protocol_info, registry):
    """vo, activity and auth_method, from the subject and the SciTag."""
    experiment, activity = (None, None)
    if registry is not None:
        experiment, activity = registry.decode(protocol_info.get("transferTag"))
    # 'default' is the registry's catch-all experiment, not a VO
    tag_vo = experiment.lower() if experiment and experiment != "default" else None

    subject = raw.get("subject")
    if not isinstance(subject, list):
        # no subject at all says nothing about how the client authenticated
        return {"vo": tag_vo or UNKNOWN, "activity": activity or UNKNOWN, "auth_method": UNKNOWN}
    return {
        # the FQAN is what dCache authorised; the tag is what the client declared
        "vo": vo_from_subject(subject) or tag_vo or UNKNOWN,
        "activity": activity or UNKNOWN,
        "auth_method": auth_method(subject),
    }


def _status(raw, mover):
    """The door's status is the result the client saw; the mover's is the fallback."""
    for status in (raw.get("status"), mover.get("status")):
        if isinstance(status, dict) and status.get("code") is not None:
            return status
    return {}


def strip_prefix(path, prefixes):
    """
    Remove the first matching prefix, keeping the leading '/'. Prefixes match whole
    path components only, and come sorted longest first, so the longest one wins.
    """
    for prefix in prefixes:
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix):]
    return path


def _file_and_status(raw, mover, conf):
    """The file, size and status fields, and storage_internal_traffic."""
    status = _status(raw, mover)
    file_path = raw.get("transferPath") or mover.get("transferPath") or ""
    return {
        "file_path": file_path,
        "file_name": strip_prefix(file_path, conf.strip_prefixes),
        "file_size": raw.get("fileSize"),
        "transferred_volume": mover.get("transferSize"),
        "status_code": status.get("code"),
        "error_message": status.get("msg") or "",
        "storage_internal_traffic": mover.get("isP2p") is True,
    }
