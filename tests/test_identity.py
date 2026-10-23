"""vo and auth_method from the billing subject (hand-made subjects in dCache's format)."""

import pytest

from conftest import billing_record
from wlcg.schema import auth_method, build_record, vo_from_subject

DN = "/DC=org/DC=example/OU=Users/CN=test-user"
ORIGIN = "Origin[2001:638:700:10a0::1:479]"
POSIX = ["UidPrincipal[40001]", "GidPrincipal[4000,primary]", "UserNamePrincipal[atlasusr001]"]
TOKEN = ["UidPrincipal[1000]", "OidcSubjectPrincipal[abc@https://cms-auth.cern.ch/]", ORIGIN]


@pytest.mark.parametrize("subject, expected", [
    # the primary FQAN wins, wherever it is
    (["FQANPrincipal[/cms/becms]", DN, "FQANPrincipal[/cms,primary]"], "cms"),
    (["FQANPrincipal[/atlas/usatlas]", "FQANPrincipal[/dteam,primary]"], "dteam"),
    # no primary: the first FQAN
    (["FQANPrincipal[/atlas/usatlas]", "FQANPrincipal[/cms]"], "atlas"),
    # groups and roles are never part of the VO
    (["FQANPrincipal[/cms/Role=production/Capability=NULL,primary]"], "cms"),
    (["FQANPrincipal[/ATLAS,primary]"], "atlas"),
    # no usable FQAN
    ([DN, ORIGIN] + POSIX, None),
    (["FQANPrincipal[]", "FQANPrincipal[/,primary]"], None),
    ([], None),
])
def test_vo_from_subject(subject, expected):
    assert vo_from_subject(subject) == expected


@pytest.mark.parametrize("subject, expected", [
    (POSIX + [ORIGIN, DN, "FQANPrincipal[/atlas,primary]"], "x509"),
    (POSIX + [ORIGIN, DN], "x509"),                    # DN without VOMS extension
    (TOKEN, "token"),
    (TOKEN + ["FQANPrincipal[/cms,primary]"], "token"),  # a token principal decides
    ([ORIGIN], "none"),                                 # anonymous
    ([], "none"),
    (POSIX + [ORIGIN], "unknown"),                      # e.g. Kerberos or password login
])
def test_auth_method(subject, expected):
    assert auth_method(subject) == expected


@pytest.mark.parametrize("subject", [None, "FQANPrincipal[/cms,primary]", 42])
def test_missing_or_malformed_subject(subject, conf):
    record = build_record(billing_record(top={"subject": subject}), conf)
    assert (record["vo"], record["auth_method"]) == ("unknown", "unknown")


def test_identity_never_leaks_into_the_record(conf):
    record = build_record(billing_record(), conf)
    text = repr(record)
    assert "/DC=" not in text and "CN=" not in text
    assert "usatlas" not in text and "atlasusr001" not in text
