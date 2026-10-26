"""file_name: file_path with the longest configured prefix removed."""

import pytest

from conftest import PFN, billing_record, make_config
from wlcg.schema import build_record, strip_prefix

CMS = "/pnfs/desy.de/cms/tier2/store/mc/Run3/NANOAODSIM/x.root"


@pytest.mark.parametrize("path, prefixes, expected", [
    (CMS, [], CMS),                                                   # nothing configured
    (CMS, ["/pnfs/desy.de/cms/tier2"], "/store/mc/Run3/NANOAODSIM/x.root"),
    (CMS, ["/pnfs/desy.de/cms/tier2", "/pnfs/desy.de"], "/store/mc/Run3/NANOAODSIM/x.root"),  # longest first
    (CMS, ["/pnfs/desy.de/atlas"], CMS),                              # no match
    ("/a/bc/x.root", ["/a/b"], "/a/bc/x.root"),                       # whole components only
    ("/a/b", ["/a/b"], "/"),                                          # the prefix itself
    ("", ["/a/b"], ""),
])
def test_strip_prefix(path, prefixes, expected):
    assert strip_prefix(path, prefixes) == expected


def test_file_name_without_prefixes_is_the_pfn(conf):
    record = build_record(billing_record(), conf)
    assert record["file_name"] == record["file_path"] == PFN


def test_file_name_uses_the_configured_prefixes():
    # the config sorts the prefixes longest first and drops trailing slashes
    conf = make_config(file_name_strip_prefixes=["/pnfs/desy.de/", "/pnfs/desy.de/atlas/dq2/"])
    record = build_record(billing_record(), conf)
    assert record["file_path"] == PFN
    assert record["file_name"] == "/atlasdatadisk/rucio/mc23/4e/5b/DAOD_PHYS.000347.pool.root.1"
