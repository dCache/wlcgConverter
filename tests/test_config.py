import logging
import os
import sys

import pytest
import yaml

import wlcgConverter
from wlcg.config import Config, ConfigError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_CONFIG = os.path.join(ROOT, 'wlcgConverterPackage', 'wlcgConverter_config.yaml')

MINIMAL = {"instance": "cms", "server_site": "DESY-HH", "server_version": "10.2.5"}


def make(**overrides):
    raw = dict(MINIMAL)
    raw.update(overrides)
    return Config(raw)


def test_defaults():
    conf = make()
    assert conf.server_technology == "dcache"
    assert conf.server_site == "DESY-HH"
    assert conf.server_version == "10.2.5"
    assert conf.storage_instance == "cms"
    assert conf.local_networks == []
    assert conf.strip_prefixes == []


def test_v1_keys_still_work_and_empty_values_are_dropped():
    conf = make(amq_topic="/topic/xrootd.dcache", amq_port_tls=None)
    assert conf["amq_topic"] == "/topic/xrootd.dcache"
    assert conf.get("instance") == "cms"
    assert "amq_port_tls" not in conf


def test_explicit_values_are_stripped():
    conf = make(server_technology="dcache ", server_site=" DESY-ZN ", storage_instance="cms-t2")
    assert (conf.server_technology, conf.server_site, conf.storage_instance) == ("dcache", "DESY-ZN", "cms-t2")


def test_storage_instance_without_instance_is_empty():
    assert Config({"server_site": "DESY-HH", "server_version": "10.2.5"}).storage_instance == ""


@pytest.mark.parametrize("key", ["server_site", "server_version"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_obligatory_keys(key, value):
    with pytest.raises(ConfigError, match=key):
        make(**{key: value})


def test_unquoted_version_is_rejected():
    # YAML reads an unquoted 10.10 as the float 10.1
    with pytest.raises(ConfigError, match="quoted string"):
        make(server_version=10.1)


@pytest.mark.parametrize("raw", [[], "server_site: DESY-HH"])
def test_config_must_be_a_mapping(raw):
    with pytest.raises(ConfigError, match="mapping"):
        Config(raw)


def test_empty_file_reports_the_missing_site():
    with pytest.raises(ConfigError, match="server_site"):
        Config(None)


def test_local_networks_are_parsed():
    conf = make(local_networks=["131.169.0.0/16", "2001:638:700::/48"])
    assert [str(n) for n in conf.local_networks] == ["131.169.0.0/16", "2001:638:700::/48"]


@pytest.mark.parametrize("value, message", [
    ("131.169.0.0/16", "must be a list"),
    (["131.169.0.0/33"], "131.169.0.0/33"),
    (["not-a-network"], "not-a-network"),
])
def test_bad_local_networks(value, message):
    with pytest.raises(ConfigError, match=message):
        make(local_networks=value)


def test_prefixes_are_cleaned_and_sorted_longest_first():
    conf = make(file_name_strip_prefixes=["/pnfs/desy.de/", "/pnfs/desy.de/cms/tier2", "/pnfs/desy.de"])
    assert conf.strip_prefixes == ["/pnfs/desy.de/cms/tier2", "/pnfs/desy.de"]


@pytest.mark.parametrize("value", ["/pnfs", ["pnfs/desy.de"], ["/"], [42]])
def test_bad_prefixes(value):
    with pytest.raises(ConfigError, match="file_name_strip_prefixes"):
        make(file_name_strip_prefixes=value)


def test_example_config_only_lacks_the_obligatory_values():
    with open(EXAMPLE_CONFIG) as f:
        raw = yaml.safe_load(f)
    conf = Config(dict(raw, server_site="DESY-HH", server_version="10.2.5"))
    assert conf.server_technology == "dcache"
    assert conf.strip_prefixes == []


def test_main_exits_2_on_bad_config(tmp_path, monkeypatch, caplog):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump({
        "server_version": "10.2.5",
        "config::logging": {"version": 1, "disable_existing_loggers": False},
    }))
    monkeypatch.setattr(sys, "argv", ["wlcgConverter", str(config_file)])
    with caplog.at_level(logging.ERROR, logger="wlcgConverter"), pytest.raises(SystemExit) as exit_info:
        wlcgConverter.main()
    assert exit_info.value.code == 2
    assert "server_site" in caplog.text
