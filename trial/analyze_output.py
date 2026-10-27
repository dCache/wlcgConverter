#!/usr/bin/env python3
"""
Report on a wlcgConverter output file (one JSON record per line), to find gaps and bugs
after a trial run. Read-only; standard library only.

    python3 analyze_output.py trial-output.json                 # report, examples masked: safe to share
    python3 analyze_output.py trial-output.json --examples      # also show unmasked examples: keep local
"""

import argparse
import ipaddress
import json
import re
import sys
from collections import Counter

FIELDS = [
    "start_time", "end_time", "operation", "protocol", "protocol_version",
    "server_technology", "server_site", "server_version", "storage_instance",
    "ipver", "src_hostname", "src_ip", "dst_hostname", "dst_ip",
    "vo", "activity", "auth_method",
    "file_path", "file_name", "file_size", "transferred_volume",
    "status_code", "error_message", "storage_internal_traffic",
    "src_site", "dst_site", "traffic_scope", "remote_access",
]
TYPES = {
    "start_time": int, "end_time": int, "file_size": int, "transferred_volume": int,
    "status_code": int, "storage_internal_traffic": bool, "remote_access": bool,
}
CATEGORICAL = [
    "operation", "protocol", "protocol_version", "server_technology", "server_site",
    "server_version", "storage_instance", "ipver", "vo", "activity", "auth_method",
    "traffic_scope", "remote_access", "storage_internal_traffic", "status_code",
]

# what must never be in a record, or should be looked at
PRIVACY = {
    "DN": re.compile(r"/DC=|/CN=|\bCN="),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+"),
    "user area in path": re.compile(r"/user/[^/]+|/users/[^/]+|/home/[^/]+|/user\.[^/]+"),
    "host name": re.compile(r"\b[a-z0-9-]+(\.[a-z0-9-]+)*\.(de|ch|org|net|edu|gov|com|uk|fr|it|es|nl)\b", re.I),
    "IP address": re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b|\b[0-9a-f]{1,4}(:[0-9a-f]{0,4}){3,7}\b", re.I),
}


def mask(text):
    """Keep the shape of a value, hide its content: letters -> x, digits -> 9."""
    return re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "x", str(text)))


def is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


class Report:

    def __init__(self, show_examples):
        self.show = show_examples
        self.lines = []

    def out(self, text=""):
        self.lines.append(text)

    def example(self, value):
        return repr(value) if self.show else mask(value)


def analyze(path, show_examples):
    r = Report(show_examples)
    records, broken = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                broken += 1
                continue
            if isinstance(record, dict):
                records.append(record)
            else:
                broken += 1

    n = len(records)
    r.out("# Trial run report: %s" % path)
    r.out("")
    r.out("records: %d   lines that are not a JSON object: %d" % (n, broken))
    if not n:
        return r

    # --- fields and types ---
    r.out("")
    r.out("## Fields and types")
    field_sets = Counter(tuple(k for k in rec) for rec in records)
    for keys, count in field_sets.most_common():
        missing = [k for k in FIELDS if k not in keys]
        extra = [k for k in keys if k not in FIELDS]
        r.out("- %d records: %d fields; missing %s; extra %s" % (count, len(keys), missing or "-", extra or "-"))
    for field in FIELDS:
        values = [rec.get(field) for rec in records if field in rec]
        nulls = sum(v is None for v in values)
        empty = sum(v == "" for v in values)
        unknown = sum(v == "unknown" for v in values)
        wrong = 0
        if field in TYPES:
            wrong = sum(1 for v in values if v is not None and not (type(v) is TYPES[field]))
        elif values:
            wrong = sum(1 for v in values if v is not None and not isinstance(v, str))
        if nulls or empty or unknown or wrong:
            r.out("- %-24s null %6d   empty %6d   unknown %6d   wrong type %6d" % (field, nulls, empty, unknown, wrong))

    # --- value distributions ---
    r.out("")
    r.out("## Value distributions (top 10)")
    for field in CATEGORICAL:
        counts = Counter(json.dumps(rec.get(field, "<absent>")) for rec in records)
        top = ", ".join("%s: %d" % (value, count) for value, count in counts.most_common(10))
        r.out("- %s (%d distinct): %s" % (field, len(counts), top))

    # --- consistency ---
    r.out("")
    r.out("## Consistency checks")
    checks = Counter()
    durations = []
    for rec in records:
        start, end = rec.get("start_time"), rec.get("end_time")
        if isinstance(start, int) and isinstance(end, int):
            if start > end:
                checks["start_time after end_time"] += 1
            durations.append(end - start)
            if not 1500000000000 < end < 2500000000000:
                checks["end_time outside 2017-2049"] += 1
        for field in ("file_size", "transferred_volume"):
            if isinstance(rec.get(field), int) and rec[field] < 0:
                checks["negative " + field] += 1
        size, volume = rec.get("file_size"), rec.get("transferred_volume")
        if isinstance(size, int) and isinstance(volume, int) and volume > size:
            checks["transferred_volume > file_size (%s)" % rec.get("operation")] += 1
        if rec.get("operation") == "write" and size == 0 and rec.get("status_code") == 0:
            checks["successful write with file_size 0"] += 1
        status = rec.get("status_code")
        if status == 0 and rec.get("error_message"):
            checks["status_code 0 with an error_message"] += 1
        if status not in (0, None) and not rec.get("error_message"):
            checks["failure without error_message"] += 1
        for end_name in ("src", "dst"):
            ip = rec.get(end_name + "_ip")
            if ip and not is_ip(ip):
                checks[end_name + "_ip is not an IP address"] += 1
            if ip == "":
                checks[end_name + "_ip empty"] += 1
            if rec.get(end_name + "_hostname") != ip:
                checks[end_name + "_hostname differs from " + end_name + "_ip"] += 1
        if rec.get("traffic_scope") == "LAN" and rec.get("src_site") != rec.get("dst_site"):
            checks["LAN with different src_site and dst_site"] += 1
        if rec.get("traffic_scope") == "UNKNOWN" and "remote_access" in rec:
            checks["UNKNOWN with remote_access set"] += 1
        if rec.get("file_name") == rec.get("file_path"):
            checks["file_name equals file_path (no prefix stripped)"] += 1
        if rec.get("vo") == "unknown" and rec.get("auth_method") == "token":
            checks["token login without vo"] += 1
    for name, count in sorted(checks.items()):
        r.out("- %-52s %6d  (%.1f%%)" % (name, count, 100.0 * count / n))
    if not checks:
        r.out("- no problems found")
    if durations:
        durations.sort()
        r.out("- duration ms: min %d, median %d, max %d" % (durations[0], durations[len(durations) // 2], durations[-1]))

    # --- privacy ---
    r.out("")
    r.out("## Privacy scan")
    r.out("Examples are %s." % ("shown unmasked: keep this report local" if show_examples
                                else "masked (letters -> x, digits -> 9); rerun with --examples locally to see them"))
    expected_ip_fields = {"src_ip", "dst_ip", "src_hostname", "dst_hostname", "src_site", "dst_site"}
    for name, pattern in PRIVACY.items():
        hits = Counter()
        examples = {}
        for rec in records:
            for field, value in rec.items():
                if not isinstance(value, str) or (name == "IP address" and field in expected_ip_fields):
                    continue
                match = pattern.search(value)
                if match:
                    hits[field] += 1
                    examples.setdefault(field, match.group(0))
        if hits:
            for field, count in hits.most_common():
                r.out("- %-18s in %-15s %6d records, e.g. %s" % (name, field, count, r.example(examples[field])))
        else:
            r.out("- %-18s none" % name)

    # --- error messages ---
    r.out("")
    r.out("## Error messages (top 15)")
    messages = Counter(rec.get("error_message") for rec in records if rec.get("error_message"))
    lengths = [len(m) for m in messages.elements()]
    if messages:
        r.out("- %d records with a message, %d distinct, longest %d characters" % (sum(messages.values()), len(messages), max(lengths)))
        for message, count in messages.most_common(15):
            r.out("  - %6d  %s" % (count, r.example(message[:120])))
    else:
        r.out("- none")
    return r


def main():
    parser = argparse.ArgumentParser(description="Report on a wlcgConverter output file.")
    parser.add_argument("output_file")
    parser.add_argument("--examples", action="store_true", help="show unmasked examples (keep the report local)")
    args = parser.parse_args()
    print("\n".join(analyze(args.output_file, args.examples).lines))


if __name__ == "__main__":
    sys.exit(main())
