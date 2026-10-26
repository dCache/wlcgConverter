# wlcgConverter output record

This document describes the record wlcgConverter produces from a dCache billing record.

## When a record is produced

wlcgConverter reads dCache billing messages from Kafka. A message produces one record when it is a door request message (`msgType` is `request`) whose `moverInfo.protocolInfo.protocol` equals the configured `protocol` (default `Xrootd`). Successful and failed transfers both produce a record. All other messages, and messages that are not a JSON object, are skipped.

The record is a JSON object. It is sent to the AMQ topic `amq_topic` when `send_data` is `True`, and appended as one line to `path_to_converted_json_file` when `local_dump` is `True`. When `ip_filter_is_active` is `True`, records whose client address is in the configured IPv4 or IPv6 subnet are not sent to AMQ; they are still written to the local file.

## Fields

In the source column, `mi` stands for `moverInfo` and `pi` for `moverInfo.protocolInfo` of the billing message. String fields are never `null`. A numeric field is `null` when the billing message does not contain the value.

| Field | Type | Source | Value |
| --- | --- | --- | --- |
| `start_time` | integer | `date`, `mi.transferTime` | end of the transfer minus its duration, in milliseconds since the Unix epoch |
| `end_time` | integer | `date` | end of the transfer, in milliseconds since the Unix epoch |
| `operation` | string | `mi.isWrite` | `read`, `write` or `unknown` |
| `protocol` | string | `pi.protocol` | lowercase protocol name; `Xrootd` becomes `xroot`, `Http` becomes `https` |
| `protocol_version` | string | `pi.versionMajor`, `pi.versionMinor` | e.g. `5.0`; empty if not present |
| `server_technology` | string | config `server_technology` | default `dcache` |
| `server_site` | string | config `server_site` | |
| `server_version` | string | config `server_version` | |
| `storage_instance` | string | config `storage_instance` | default: config `instance` |
| `ipver` | string | `pi.host` | IP version of the client: `ipv4`, `ipv6` or `unknown` |
| `src_ip` | string | see Direction | IP address of the source |
| `dst_ip` | string | see Direction | IP address of the destination |
| `src_hostname` | string | | same as `src_ip` |
| `dst_hostname` | string | | same as `dst_ip` |
| `vo` | string | `subject` | see VO |
| `activity` | string | | always `unknown` |
| `auth_method` | string | `subject` | `x509`, `token`, `none` or `unknown`; see Authentication method |
| `file_path` | string | `transferPath`, else `mi.transferPath` | path of the file in the dCache namespace |
| `file_name` | string | | same as `file_path` |
| `file_size` | integer | `fileSize` | size of the file in bytes |
| `transferred_volume` | integer | `mi.transferSize` | bytes transferred |
| `status_code` | integer | `status.code`, else `mi.status.code` | `0` on success, the dCache error code otherwise |
| `error_message` | string | `status.msg`, else `mi.status.msg` | the dCache error message; empty on success |
| `storage_internal_traffic` | boolean | `mi.isP2p` | `true` for pool-to-pool transfers |
| `src_site` | string | see Sites | site of the source |
| `dst_site` | string | see Sites | site of the destination |
| `traffic_scope` | string | see Sites | `LAN` or `UNKNOWN` |
| `remote_access` | boolean | see Sites | `false`; only present when `traffic_scope` is `LAN` |

## Rules

**Direction.** For a read, the pool (`mi.localEndpoint`) is the source and the client (`pi.host`) the destination. For a write, the client is the source and the pool the destination. For any other `mi.isWrite` value, `src_*` and `dst_*` are empty strings.

**IP addresses.** Addresses are written in the canonical form of RFC 5952, e.g. `2001:638:700:10a0::1:479`. An IPv4-mapped IPv6 address (`::ffff:a.b.c.d`) is written as the IPv4 address. The port is removed from the pool endpoint. A value that is not an IP address is passed through unchanged, and `ipver` is then `unknown`.

**Sites.** The pool end has the site `server_site`. The client end has the site `server_site` when the client address is in one of the networks in `local_networks`, and the client IP address otherwise. `traffic_scope` is `LAN`, with `remote_access` `false`, when the client address is in `local_networks`, and `UNKNOWN` otherwise.

**Status.** `status_code` and `error_message` come from the door's `status`, the final result of the request. When it has no code, the pool's `mi.status` is used.

**VO.** The VO comes from the VOMS FQANs in the billing `subject`: the VO of the primary FQAN (`FQANPrincipal[/cms,primary]` → `cms`), else of the first FQAN, in lowercase. Groups and roles are not included. Without an FQAN, `vo` is `unknown`.

**Authentication method.** From the principals in the billing `subject`:

| Subject contains | `auth_method` |
| --- | --- |
| `OidcSubjectPrincipal`, `JwtJtiPrincipal`, `JwtSubPrincipal`, `OpenIdGroupPrincipal`, `OpenIdClientPrincipal` or `OAuthProviderPrincipal` | `token` |
| otherwise, a DN or an `FQANPrincipal` | `x509` |
| only `Origin` entries, or nothing | `none` |
| anything else, or no `subject` | `unknown` |

## Configuration

These settings in `wlcgConverter_config.yaml` determine the record's values:

| Setting | Required | Effect |
| --- | --- | --- |
| `protocol` | no, default `Xrootd` | which transfers produce a record |
| `server_site` | yes | `server_site`, and the site of the pool end |
| `server_version` | yes | `server_version` |
| `server_technology` | no, default `dcache` | `server_technology` |
| `storage_instance` | no, default `instance` | `storage_instance` |
| `local_networks` | no | list of CIDR networks; see Sites |

Values that YAML reads as numbers, such as a version `10.10`, must be quoted. The converter checks these settings at startup and exits with code 2 if one is missing or invalid.
