"""
Builds the v2 WLCG transfer record from a dCache billing record.

See docs/SCHEMA.md for the field table and resolution rules. String fields are
never None (empty string or 'unknown'); numeric fields are None only when the
billing record lacks them.
"""

import logging

from dateutil.parser import parse as parse_date

from .net import canonical_ip, ip_version, split_endpoint

logger = logging.getLogger('wlcgConverter')

PROTOCOL_NAMES = {
    "xrootd": "xroot",
    "xroot": "xroot",
    "http": "https",
    "https": "https",
}

UNKNOWN = "unknown"


def build_record(raw, conf):
    """
    Convert one billing door record to the v2 WLCG record.

    :param raw: billing record dict as consumed from Kafka
    :param conf: wlcg.config.Config
    """
    mover = raw.get("moverInfo") or {}
    protocol_info = mover.get("protocolInfo") or {}

    record = {}
    record.update(_timing(raw, mover))
    record.update(_protocol(mover, protocol_info, conf))
    record.update(_endpoints(mover, protocol_info))
    # filled in by later steps of the v2 plan
    record["vo"] = UNKNOWN
    record["activity"] = UNKNOWN
    record["auth_method"] = UNKNOWN
    record.update(_file_and_status(raw, mover))
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


def _status(raw, mover):
    """The door's status is the result the client saw; the mover's is the fallback."""
    for status in (raw.get("status"), mover.get("status")):
        if isinstance(status, dict) and status.get("code") is not None:
            return status
    return {}


def _file_and_status(raw, mover):
    status = _status(raw, mover)
    file_path = raw.get("transferPath") or mover.get("transferPath") or ""
    return {
        "file_path": file_path,
        # prefix stripping comes with a later step; until then the PFN
        "file_name": file_path,
        "file_size": raw.get("fileSize"),
        "transferred_volume": mover.get("transferSize"),
        "status_code": status.get("code"),
        "error_message": status.get("msg") or "",
        "storage_internal_traffic": mover.get("isP2p") is True,
    }
