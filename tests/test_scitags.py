"""The SciTag registry: decoding transferTag, loading the registry, activity and vo in the record."""

import io
import json

import pytest

from conftest import billing_record, make_config
from wlcg import scitags
from wlcg.config import ConfigError
from wlcg.schema import build_record
from wlcg.scitags import SciTagRegistry, load_registry, parse_registry

REGISTRY_JSON = {
    "experiments": [
        {"expName": "default", "expId": 1, "activities": [{"activityName": "default", "activityId": 1}]},
        {"expName": "atlas", "expId": 2, "activities": [{"activityName": "Analysis Input", "activityId": 17}]},
        {"expName": "cms", "expId": 3, "activities": [
            {"activityName": "Production Input", "activityId": 12},
            {"activityName": "Analysis Input", "activityId": 14},
        ]},
    ],
}
REGISTRY = SciTagRegistry(parse_registry(REGISTRY_JSON))
TOKEN_SUBJECT = ["UidPrincipal[1000]", "OidcSubjectPrincipal[abc@https://cms-auth.cern.ch/]", "Origin[2001:db8::1]"]


# --- decode ---------------------------------------------------------------------------------

@pytest.mark.parametrize("tag, expected", [
    ("206", ("cms", "Analysis Input")),        # 3 << 6 | 14
    ("204", ("cms", "Production Input")),
    (" 206 ", ("cms", "Analysis Input")),
    (145, ("atlas", "Analysis Input")),         # 2 << 6 | 17, as a number
])
def test_decode_valid_tags(tag, expected):
    assert REGISTRY.decode(tag) == expected


@pytest.mark.parametrize("tag", [
    "196664",   # IPv6 flow-label value sent by mistake (CMSSW bug, cms-sw/cmssw #51227)
    "63",       # below the valid range
    "65536",    # above it
    "215",      # cms, but activity 23 is not in this registry
    "1024",     # experiment 16 is not in the registry
    "abc", "", None, "2.5",
])
def test_decode_invalid_or_unknown_tags(tag):
    assert REGISTRY.decode(tag) == (None, None)


def test_bundled_registry_decodes_the_cmssw_defaults():
    registry = load_registry(url=None)
    assert registry.decode("204") == ("cms", "Production Input")
    assert registry.decode("206") == ("cms", "Analysis Input")
    assert registry.decode("215") == ("cms", "Secondary Input")
    assert registry.decode("216") == ("cms", "Simulation Pileup Input")


# --- parse_registry ---------------------------------------------------------------------------

@pytest.mark.parametrize("data", [
    [],
    {},
    {"experiments": []},
    {"experiments": [{"expName": "cms"}]},                                    # no id
    {"experiments": [{"expName": "cms", "expId": "3"}]},                      # id as string
    {"experiments": [{"expName": "cms", "expId": True}]},                     # bool is not an id
    {"experiments": [{"expName": "", "expId": 3}]},                           # empty name
    {"experiments": [{"expName": "cms", "expId": 3, "activities": [{"activityId": 14}]}]},
])
def test_parse_registry_rejects_unexpected_documents(data):
    with pytest.raises(ValueError):
        parse_registry(data)


# --- load_registry ----------------------------------------------------------------------------

class FakeResponse(io.BytesIO):

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.fixture
def fake_download(monkeypatch):
    """Serve body for every urlopen call and record the URLs; no network."""
    calls = []

    def serve(body):
        def urlopen(url, timeout):
            calls.append((url, timeout))
            if isinstance(body, Exception):
                raise body
            return FakeResponse(body)
        monkeypatch.setattr(scitags.urllib.request, "urlopen", urlopen)
        return calls
    return serve


def test_load_from_url_writes_the_cache(fake_download, tmp_path):
    calls = fake_download(json.dumps(REGISTRY_JSON).encode())
    cache = tmp_path / "scitags.json"
    registry = load_registry("https://scitags.org/api.json", str(cache))
    assert registry.decode("206") == ("cms", "Analysis Input")
    assert calls == [("https://scitags.org/api.json", scitags.FETCH_TIMEOUT_SECONDS)]
    assert json.loads(cache.read_text()) == REGISTRY_JSON
    assert [p.name for p in tmp_path.iterdir()] == ["scitags.json"]    # no temporary file left


def test_failed_download_falls_back_to_the_cache(fake_download, tmp_path):
    fake_download(OSError("network unreachable"))
    cache = tmp_path / "scitags.json"
    cache.write_text(json.dumps(REGISTRY_JSON))
    registry = load_registry("https://scitags.org/api.json", str(cache), bundled_file="/nonexistent")
    assert registry.decode("145") == ("atlas", "Analysis Input")


def test_damaged_download_falls_back_and_keeps_the_cache(fake_download, tmp_path):
    fake_download(b'{"experiments": "not a list"}')
    cache = tmp_path / "scitags.json"
    cache.write_text(json.dumps(REGISTRY_JSON))
    registry = load_registry("https://scitags.org/api.json", str(cache))
    assert registry.decode("145") == ("atlas", "Analysis Input")
    assert json.loads(cache.read_text()) == REGISTRY_JSON


def test_oversized_download_is_rejected(fake_download):
    fake_download(b" " * (scitags.MAX_REGISTRY_BYTES + 1))
    registry = load_registry("https://scitags.org/api.json")
    # falls back to the bundled copy
    assert registry.decode("206") == ("cms", "Analysis Input")


def test_only_https_is_fetched(fake_download):
    calls = fake_download(json.dumps(REGISTRY_JSON).encode())
    load_registry("http://scitags.org/api.json")
    assert calls == []


def test_without_url_cache_and_bundle_every_activity_is_unknown(fake_download, tmp_path):
    fake_download(OSError("offline"))
    registry = load_registry("https://scitags.org/api.json", str(tmp_path / "missing.json"),
                             bundled_file=str(tmp_path / "missing-too.json"))
    assert registry.decode("206") == (None, None)


def test_unwritable_cache_only_warns(fake_download, tmp_path, caplog):
    fake_download(json.dumps(REGISTRY_JSON).encode())
    registry = load_registry("https://scitags.org/api.json", str(tmp_path / "no-such-dir" / "scitags.json"))
    assert registry.decode("206") == ("cms", "Analysis Input")
    assert "could not write the cache file" in caplog.text


# --- config -----------------------------------------------------------------------------------

def test_config_defaults():
    conf = make_config()
    assert conf.scitags_url == "https://scitags.org/api.json"
    assert conf.scitags_cache_file is None


def test_config_requires_https():
    with pytest.raises(ConfigError, match="scitags_url"):
        make_config(scitags_url="http://scitags.org/api.json")


# --- activity and vo in the record ------------------------------------------------------------

def record(tag, subject=None, registry=REGISTRY):
    top = {} if subject is None else {"subject": subject}
    return build_record(billing_record(top=top, protocol={"transferTag": tag}), make_config(), registry)


def test_activity_comes_from_the_tag():
    assert record("206")["activity"] == "Analysis Input"


@pytest.mark.parametrize("tag", ["", "196664", "abc"])
def test_activity_unknown_without_a_valid_tag(tag):
    assert record(tag)["activity"] == "unknown"


def test_no_registry_means_unknown_activity():
    assert record("206", registry=None)["activity"] == "unknown"


def test_fqan_vo_wins_over_the_tag():
    # the test record's subject has FQANPrincipal[/atlas,primary]
    r = record("206")
    assert (r["vo"], r["activity"]) == ("atlas", "Analysis Input")


def test_tag_gives_the_vo_without_an_fqan():
    r = record("206", subject=TOKEN_SUBJECT)
    assert (r["vo"], r["auth_method"]) == ("cms", "token")


def test_tag_gives_the_vo_without_a_subject():
    assert record("206", subject=42)["vo"] == "cms"


def test_default_experiment_is_not_a_vo():
    r = record(str(1 << 6 | 1), subject=TOKEN_SUBJECT)
    assert (r["vo"], r["activity"]) == ("unknown", "default")
