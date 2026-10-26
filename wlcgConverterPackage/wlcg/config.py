"""Validated configuration for wlcgConverter."""

import os

from .net import parse_network


class ConfigError(Exception):
    pass


# v1 switches; a blank one counts as absent and falls back to its default
SWITCH_DEFAULTS = {
    "local_dump": False,
    "send_data": False,
    "verbose": False,
    "ip_filter_is_active": False,
}

KAFKA_KEYS = ("kafka_broker_incoming", "topic", "instance")
AMQ_KEYS = ("amq_host", "amq_topic", "amq_port_tls", "amq_ca_certs")
DEFAULT_SCITAGS_URL = "https://scitags.org/api.json"


class Config(dict):
    """
    The YAML config as a dict (empty values dropped, so every v1 key keeps working via
    conf["key"] / conf.get("key")), plus the checked and pre-parsed v2 schema settings
    as attributes. Bad settings raise ConfigError here, at startup, not per record.
    """

    def __init__(self, raw):
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ConfigError("the config file must hold a YAML mapping")
        super().__init__({k: v for k, v in raw.items() if v is not None})
        self._check_v1_keys()

        self.server_technology = self._string("server_technology", "dcache")
        self.server_site = self._required("server_site", "the WLCG site name, e.g. 'DESY-HH'")
        self.server_version = self._required("server_version", "the dCache release, e.g. '10.2.5'")
        self.storage_instance = self._string("storage_instance", str(self.get("instance", "")))
        self.local_networks = self._networks("local_networks")
        self.strip_prefixes = self._prefixes("file_name_strip_prefixes")

        self.scitags_url = self._string("scitags_url", DEFAULT_SCITAGS_URL)
        if not self.scitags_url.startswith("https://"):
            raise ConfigError("'scitags_url' must be an https:// URL, got %r" % self.scitags_url)
        # no cache file by default: the bundled copy is the fallback
        self.scitags_cache_file = self._string("scitags_cache_file", "") or None

    def _check_v1_keys(self):
        """Defaults for the v1 switches, and the keys the enabled outputs need."""
        for key, default in SWITCH_DEFAULTS.items():
            self.setdefault(key, default)
            if not isinstance(self[key], bool):
                raise ConfigError("'%s' must be True or False, got %r" % (key, self[key]))
        self["protocol"] = self._string("protocol", "Xrootd")

        missing = [key for key in KAFKA_KEYS if key not in self]
        if self["local_dump"] and "path_to_converted_json_file" not in self:
            missing.append("path_to_converted_json_file")
        if self["send_data"]:
            # records go to the broker over TLS only, verified against amq_ca_certs
            missing += [key for key in AMQ_KEYS if key not in self]
            has_cert = "path_to_cert" in self and "path_to_key" in self
            has_password = "username" in self and "password" in self
            if not (has_cert or has_password):
                missing.append("path_to_cert + path_to_key, or username + password")
        if missing:
            raise ConfigError("obligatory settings missing: %s" % ", ".join(missing))

        if self["send_data"]:
            for key in ("amq_ca_certs", "path_to_cert", "path_to_key"):
                if key in self and not os.path.isfile(str(self[key])):
                    raise ConfigError("'%s': no such file: %s" % (key, self[key]))

    def _string(self, key, default):
        value = self.get(key, default)
        if not isinstance(value, str):
            # an unquoted 10.10 would silently become the float 10.1
            raise ConfigError("'%s' must be a quoted string, got %r" % (key, value))
        # a blank value means "use the default", like an empty one
        return value.strip() or default

    def _required(self, key, what):
        value = self._string(key, "")
        if not value:
            raise ConfigError("'%s' is obligatory: set it to %s" % (key, what))
        return value

    def _networks(self, key):
        cidrs = self.get(key, [])
        if not isinstance(cidrs, list):
            raise ConfigError("'%s' must be a list of CIDRs" % key)
        try:
            return [parse_network(cidr) for cidr in cidrs]
        except ValueError as e:
            raise ConfigError("'%s': %s" % (key, e))

    def _prefixes(self, key):
        prefixes = self.get(key, [])
        if not isinstance(prefixes, list):
            raise ConfigError("'%s' must be a list of absolute paths" % key)
        cleaned = set()
        for prefix in prefixes:
            if not isinstance(prefix, str) or not prefix.startswith('/') or not prefix.rstrip('/'):
                raise ConfigError("'%s': %r is not an absolute path below '/'" % (key, prefix))
            cleaned.add(prefix.rstrip('/'))
        # longest first, so the first prefix that matches is the longest one
        return sorted(cleaned, key=len, reverse=True)
