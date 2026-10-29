"""
SciTag registry: turns the transferTag of a billing record into experiment and activity names.

transferTag holds the scitag.flow value the client sent, experiment << 6 | activity.
The names come from the scitags.org registry, loaded once at startup: from the URL,
else from the cache file the last successful download wrote, else from the copy
bundled with the code. No network call happens per record.
"""

import json
import logging
import os
import tempfile
import urllib.request

logger = logging.getLogger('wlcgConverter')

BUNDLED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scitags_bundled.json')
FETCH_TIMEOUT_SECONDS = 10
# the registry is a few kB; anything far larger is not the registry
MAX_REGISTRY_BYTES = 1024 * 1024

# valid scitag.flow values: experiment ids from 1, activity ids 0-63, 16 bits in total
MIN_FLOW, MAX_FLOW = 64, 65535


def parse_registry(data):
    """
    Turn the registry JSON into {expId: (expName, {activityId: activityName})}.
    Raises ValueError unless every entry has the expected types, so a damaged or
    unexpected document is rejected as a whole.
    """
    if not isinstance(data, dict) or not isinstance(data.get("experiments"), list):
        raise ValueError("no 'experiments' list")
    table = {}
    for exp in data["experiments"]:
        if not isinstance(exp, dict) or not _is_id(exp.get("expId")) or not _is_name(exp.get("expName")):
            raise ValueError("malformed experiment entry: %r" % (exp,))
        activities = {}
        for activity in exp.get("activities", []):
            if not isinstance(activity, dict) or not _is_id(activity.get("activityId")) \
                    or not _is_name(activity.get("activityName")):
                raise ValueError("malformed activity entry: %r" % (activity,))
            activities[activity["activityId"]] = activity["activityName"]
        table[exp["expId"]] = (exp["expName"], activities)
    if not table:
        raise ValueError("no experiments")
    return table


def _is_id(value):
    """A non-negative integer, as registry ids are."""
    # bool is a subclass of int in Python, but true/false is not an id
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_name(value):
    """A non-empty string."""
    return isinstance(value, str) and value.strip() != ""


class SciTagRegistry:
    """The parsed registry: {expId: (expName, {activityId: activityName})}."""

    def __init__(self, table):
        self.table = table

    def decode(self, tag):
        """(experiment name, activity name) for a transferTag, or (None, None) if it is not valid."""
        try:
            flow = int(str(tag).strip())
        except ValueError:
            return None, None
        if not MIN_FLOW <= flow <= MAX_FLOW:
            return None, None
        experiment = self.table.get(flow >> 6)
        if experiment is None:
            return None, None
        activity = experiment[1].get(flow & 0x3F)
        if activity is None:
            return None, None
        return experiment[0], activity


def load_registry(url, cache_file=None, bundled_file=BUNDLED_FILE):
    """Load the registry from url, else cache_file, else bundled_file."""
    if url:
        try:
            data = _fetch(url)
            table = parse_registry(data)
        except Exception as e:
            logger.warning("SciTag registry: could not load %s: %s", url, e)
        else:
            logger.info("SciTag registry loaded from %s", url)
            if cache_file:
                _write_cache(cache_file, data)
            return SciTagRegistry(table)

    for path in (cache_file, bundled_file):
        if not path:
            continue
        try:
            with open(path) as f:
                table = parse_registry(json.load(f))
        except (OSError, ValueError) as e:
            logger.warning("SciTag registry: could not load %s: %s", path, e)
            continue
        logger.info("SciTag registry loaded from %s", path)
        return SciTagRegistry(table)

    logger.error("SciTag registry not available; activity is 'unknown' for every record.")
    return SciTagRegistry({})


def _fetch(url):
    """Download and parse the registry JSON; https only, at most MAX_REGISTRY_BYTES."""
    if not url.startswith("https://"):
        raise ValueError("only https URLs are used")
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(MAX_REGISTRY_BYTES + 1)
    if len(body) > MAX_REGISTRY_BYTES:
        raise ValueError("response larger than %d bytes" % MAX_REGISTRY_BYTES)
    return json.loads(body.decode("utf-8"))


def _write_cache(cache_file, data):
    """Replace the cache file in one step, so a reader never sees half a file."""
    tmp_path = None
    try:
        directory = os.path.dirname(os.path.abspath(cache_file))
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".scitags-")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, cache_file)
    except OSError as e:
        logger.warning("SciTag registry: could not write the cache file %s: %s", cache_file, e)
        if tmp_path is not None and os.path.exists(tmp_path):
            os.remove(tmp_path)
