# Changelog

## 2.0 (2026-10-26)

### Record format

- Each xroot transfer is sent as one record in the WLCG transfer-monitoring format: times, operation, protocol and version, server technology, site, version and instance, source and destination IPs and sites, VO, activity, authentication method, file path, name and size, transferred volume, status code and message, storage-internal traffic and traffic scope. [docs/RECORD.md](docs/RECORD.md) describes every field.
- The v1 fields `bytes_in`, `bytes_out`, `status`, `error_category` and `ipv6` are no longer sent. `ipver` is now `ipv4`, `ipv6` or `unknown` instead of `4` or `6`. IPv6 addresses are written in their RFC 5952 form.
- Failed transfers are sent too, with their dCache status code and message. v1 sent successful transfers only.
- `activity` comes from the SciTag (`scitag.flow`) the client sent, looked up in the SciTags registry, which is loaded once at startup from scitags.org, a cache file or the copy included with the converter.

### Configuration

- New obligatory settings: `server_site` and `server_version`. New optional settings: `server_technology`, `storage_instance`, `local_networks`, `file_name_strip_prefixes`, `scitags_url`, `scitags_cache_file`.
- The configuration is checked at startup. A missing or invalid setting stops the converter with exit code 2 and a message naming the setting. Blank `local_dump`, `send_data`, `verbose` and `ip_filter_is_active` mean `False`; blank `protocol` means `Xrootd`.

### Sending to CERN

- Records are only sent over TLS, to `amq_port_tls`; `amq_port` is no longer used. This also applies to username/password logins, which v1 sent unencrypted.
- The broker's certificate and host name are verified against the CA certificates in the new obligatory setting `amq_ca_certs`. v1 did not verify the broker.
- The IP filter now works: a client in the configured IPv4 or IPv6 subnet is not sent. In v1 the condition was always true, so every record was sent.

### Robustness and privacy

- Kafka messages that are not JSON, or not a billing record, are skipped. In v1 a message that was not JSON stopped the converter.
- A record that cannot be converted is logged, by pnfsid, date and cell, and skipped.
- The debug log no longer contains the raw billing record, which holds the user's DN and email.

### Installation

- Python 3.10 or newer is required. `requirements.txt` pins stomp.py 9.0.0, PyYAML 6.0.3, python-dateutil 3.0.0 and kafka-python 3.0.11.
- The script imports the `wlcg` package next to it: install `wlcgConverter.py` and `wlcg/` together, as described in the README. The extensionless `wlcgConverter` is a symlink to `wlcgConverter.py`.
- The systemd unit runs the converter as the user `wlcgconverter` with `UMask=0077`, waits 30 seconds between restarts, and has systemd create `/var/log/wlcg_converter` and `/var/lib/wlcg_converter`.
- The Docker image is based on `python:3.12-slim`, no longer installs `gcc`, and has a writable `/var/lib/wlcg_converter`; the k8s deployment mounts a volume there.
