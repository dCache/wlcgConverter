import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'wlcgConverterPackage'))

from wlcg.config import Config  # noqa: E402

PFN = "/pnfs/desy.de/atlas/dq2/atlasdatadisk/rucio/mc23/4e/5b/DAOD_PHYS.000347.pool.root.1"

# Hand-made door 'request' record shaped like dCache billing output: the pool's
# record nested under moverInfo, uncompressed IPv6, '[v6]:port' pool endpoint,
# and a billingPath that differs from transferPath.
DOOR_RECORD = {
    "date": "2026-09-14T16:31:38.362+02:00",
    "msgType": "request",
    "cellName": "xrootd-door01",
    "cellType": "door",
    "subject": [
        "UidPrincipal[40001]",
        "GidPrincipal[4000,primary]",
        "Origin[2001:638:700:10a0::1:479]",
        "/DC=org/DC=example/OU=Users/CN=test-user",
        "FQANPrincipal[/atlas,primary]",
        "FQANPrincipal[/atlas/usatlas]",
    ],
    "client": "2001:638:700:10a0:0:0:1:479",
    "transferPath": PFN,
    "billingPath": PFN + ".rucio.upload",
    "fileSize": 2228698700,
    "status": {"code": 0, "msg": ""},
    "moverInfo": {
        "date": "2026-09-14T16:31:38.36+02:00",
        "msgType": "transfer",
        "cellType": "pool",
        "transferTime": 35,
        "transferPath": PFN,
        "transferSize": 12193,
        "localEndpoint": "[2001:638:700:1062::1:d8]:33147",
        "isP2p": False,
        "isWrite": "read",
        "status": {"code": 0, "msg": ""},
        "protocolInfo": {
            "protocol": "Xrootd",
            "port": 35236,
            "host": "2001:638:700:10a0:0:0:1:479",
            "transferTag": "",
            "versionMajor": 5,
            "versionMinor": 0,
        },
    },
}

BASE_CONFIG = {
    "protocol": "Xrootd",
    "kafka_broker_incoming": ["localhost:9092"],
    "topic": "billing-test",
    "instance": "atlas",
    "server_site": "DESY-HH",
    "server_version": "10.2.5",
    "local_dump": False,
    "send_data": False,
    "ip_filter_is_active": False,
}


def billing_record(top=None, mover=None, protocol=None):
    """A copy of DOOR_RECORD with keys of the door, moverInfo and protocolInfo levels overridden."""
    record = copy.deepcopy(DOOR_RECORD)
    record.update(top or {})
    record["moverInfo"].update(mover or {})
    record["moverInfo"]["protocolInfo"].update(protocol or {})
    return record


def make_config(**overrides):
    raw = dict(BASE_CONFIG)
    raw.update(overrides)
    return Config(raw)


@pytest.fixture
def conf():
    return make_config()
