import pytest

from conftest import PFN, billing_record, make_config
from wlcg.schema import build_record

CORE_FIELDS = [
    "start_time", "end_time", "operation", "protocol", "protocol_version",
    "server_technology", "server_site", "server_version", "storage_instance",
    "ipver", "src_hostname", "src_ip", "dst_hostname", "dst_ip",
    "vo", "activity", "auth_method",
    "file_path", "file_name", "file_size", "transferred_volume",
    "status_code", "error_message", "storage_internal_traffic",
]

POOL = "2001:638:700:1062::1:d8"
CLIENT = "2001:638:700:10a0::1:479"


def test_read_record(conf):
    assert build_record(billing_record(), conf) == {
        "start_time": 1789396298327,
        "end_time": 1789396298362,
        "operation": "read",
        "protocol": "xroot",
        "protocol_version": "5.0",
        "server_technology": "dcache",
        "server_site": "DESY-HH",
        "server_version": "10.2.5",
        "storage_instance": "atlas",
        "ipver": "ipv6",
        "src_hostname": POOL,
        "src_ip": POOL,
        "dst_hostname": CLIENT,
        "dst_ip": CLIENT,
        "vo": "unknown",
        "activity": "unknown",
        "auth_method": "unknown",
        "file_path": PFN,
        "file_name": PFN,
        "file_size": 2228698700,
        "transferred_volume": 12193,
        "status_code": 0,
        "error_message": "",
        "storage_internal_traffic": False,
    }


def test_fields_are_in_schema_order(conf):
    assert list(build_record(billing_record(), conf)) == CORE_FIELDS


def test_no_v1_fields(conf):
    record = build_record(billing_record(), conf)
    assert not {"bytes_in", "bytes_out", "status", "error_category", "ipv6"} & set(record)


def test_write_swaps_source_and_destination(conf):
    record = build_record(billing_record(mover={"isWrite": "write"}), conf)
    assert record["operation"] == "write"
    assert (record["src_ip"], record["dst_ip"]) == (CLIENT, POOL)
    assert (record["src_hostname"], record["dst_hostname"]) == (CLIENT, POOL)


@pytest.mark.parametrize("direction", [None, "", "copy"])
def test_unknown_direction_leaves_ends_empty(conf, direction):
    record = build_record(billing_record(mover={"isWrite": direction}), conf)
    assert record["operation"] == "unknown"
    assert record["src_ip"] == record["dst_ip"] == ""
    assert record["ipver"] == "ipv6"


def test_ipv4_client_and_pool(conf):
    record = build_record(billing_record(mover={"localEndpoint": "131.169.1.2:33147"},
                                         protocol={"host": "::ffff:131.169.5.5"}), conf)
    assert (record["src_ip"], record["dst_ip"], record["ipver"]) == ("131.169.1.2", "131.169.5.5", "ipv4")


def test_unparsable_client_is_passed_through(conf):
    record = build_record(billing_record(protocol={"host": "worker.example.org"}), conf)
    assert (record["dst_ip"], record["ipver"]) == ("worker.example.org", "unknown")


def test_failed_transfer_keeps_native_code_and_message(conf):
    status = {"code": 10007, "msg": "Pool not available"}
    record = build_record(billing_record(top={"status": status}, mover={"status": status}), conf)
    assert (record["status_code"], record["error_message"]) == (10007, "Pool not available")


def test_missing_mover_status(conf):
    record = build_record(billing_record(mover={"status": None}), conf)
    assert (record["status_code"], record["error_message"]) == (None, "")


def test_missing_transfer_time_keeps_end_time(conf):
    raw = billing_record()
    del raw["moverInfo"]["transferTime"]
    record = build_record(raw, conf)
    assert (record["start_time"], record["end_time"]) == (None, 1789396298362)


@pytest.mark.parametrize("date", [None, "yesterday-ish", 42])
def test_bad_date(conf, date):
    record = build_record(billing_record(top={"date": date}), conf)
    assert (record["start_time"], record["end_time"]) == (None, None)


def test_file_path_is_transfer_path_not_billing_path(conf):
    record = build_record(billing_record(), conf)
    assert record["file_path"] == PFN
    assert not record["file_path"].endswith(".rucio.upload")


def test_file_path_falls_back_to_mover(conf):
    raw = billing_record()
    del raw["transferPath"]
    assert build_record(raw, conf)["file_path"] == PFN


def test_file_path_missing_everywhere(conf):
    raw = billing_record(mover={"transferPath": None})
    del raw["transferPath"]
    record = build_record(raw, conf)
    assert record["file_path"] == record["file_name"] == ""


@pytest.mark.parametrize("protocol, expected", [("Xrootd", "xroot"), ("Http", "https"), ("NFS4", "nfs4"), (None, "")])
def test_protocol_names(conf, protocol, expected):
    assert build_record(billing_record(protocol={"protocol": protocol}), conf)["protocol"] == expected


@pytest.mark.parametrize("major, minor, expected", [(5, 0, "5.0"), (4, None, "4"), (None, None, "")])
def test_protocol_version(conf, major, minor, expected):
    raw = billing_record(protocol={"versionMajor": major, "versionMinor": minor})
    assert build_record(raw, conf)["protocol_version"] == expected


def test_p2p_flag(conf):
    assert build_record(billing_record(mover={"isP2p": True}), conf)["storage_internal_traffic"] is True


def test_server_fields_come_from_config():
    conf = make_config(server_technology="dcache", server_site="DESY-ZN", server_version="11.2.1",
                       storage_instance="desy-zn-atlas")
    record = build_record(billing_record(), conf)
    assert (record["server_site"], record["server_version"], record["storage_instance"]) == \
        ("DESY-ZN", "11.2.1", "desy-zn-atlas")


def test_record_without_mover_info_does_not_raise(conf):
    raw = billing_record()
    raw["moverInfo"] = None
    record = build_record(raw, conf)
    assert record["src_ip"] == record["dst_ip"] == ""
    assert record["transferred_volume"] is None
