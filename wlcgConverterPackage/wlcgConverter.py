#!/usr/bin/env python3
"""
wlcgConverter reads dCache billing records from Kafka, converts each xroot transfer into
one WLCG transfer-monitoring record (docs/RECORD.md) and sends the records to the AMQ
broker over verified TLS.

Version 2.0. Author: anastasiia.chub@desy.de
Original author (version 1): sandro.grizzo@desy.de
"""

import argparse
import json
import logging
import logging.config
import sys
import threading
import uuid
from ipaddress import ip_address, ip_network

import stomp
import yaml
from kafka import KafkaConsumer

from wlcg.config import Config, ConfigError
from wlcg.schema import build_record
from wlcg.scitags import load_registry

logger = logging.getLogger('wlcgConverter')

# Kafka messages read and confirmed together; one broker round trip per batch
KAFKA_BATCH_SIZE = 500
RECEIPT_TIMEOUT_SECONDS = 60


class DeliveryError(Exception):
    """The AMQ broker did not confirm a batch of records."""


def decode_message(value):
    """Kafka value deserializer: the billing JSON, or None if the message is not JSON."""
    try:
        return json.loads(value.decode('utf-8'))
    except (AttributeError, UnicodeDecodeError, ValueError):
        # raising here would kill the consumer loop, and a restart would hit the same offset
        return None


def is_wanted(record, protocol):
    """A door request record of the configured protocol; null levels count as absent."""
    mover = record.get("moverInfo") or {}
    protocol_info = mover.get("protocolInfo") if isinstance(mover, dict) else None
    protocol_info = protocol_info if isinstance(protocol_info, dict) else {}
    return record.get("msgType") == "request" and protocol_info.get("protocol") == protocol


class WlcgConverter:
    """
    Turns Kafka messages into WLCG records and hands them to the outputs.

    process() converts one message, appends the record to the local file and queues it
    with the sender; deliver() makes the sender send the queued records of the batch and
    wait for the broker's confirmation. sender is an AmqSender, or None without send_data.
    """

    def __init__(self, conf, sender=None, registry=None):
        self.conf = conf
        self.sender = sender
        self.registry = registry

    def process(self, message):
        """Convert one Kafka message and pass the record to the outputs; other messages are skipped."""
        billing = message.value
        if not isinstance(billing, dict):
            # not JSON at all (decode_message gave None), or JSON that is not an object
            logger.warning("Skipped a Kafka message that is not a JSON object.")
            return
        # failed transfers are converted too, with their native status code and message
        if not is_wanted(billing, self.conf["protocol"]):
            return

        try:
            record = build_record(billing, self.conf, self.registry)
        except Exception:
            # one malformed record must not stop the converter; output errors below still do.
            # Log only non-personal context: the billing record holds the user's DN and email.
            logger.exception("Skipped a billing record that could not be converted "
                             "(pnfsid=%s, date=%s, cell=%s)", billing.get("pnfsid"),
                             billing.get("date"), billing.get("cellName"))
            return

        if self.conf["local_dump"]:
            with open(self.conf["path_to_converted_json_file"], 'a') as dump_file:
                json.dump(record, dump_file)
                dump_file.write('\n')

        if self.conf["send_data"] and self._passes_ip_filter(billing):
            body = json.dumps(record)
            self.sender.send(destination=self.conf["amq_topic"], body=body, content_type='application/json')
            logger.debug("Queued for the AMQ broker: %s", body)

    def deliver(self):
        """Send the records of the current batch and wait until the broker confirms them."""
        if self.conf["send_data"]:
            self.sender.confirm()

    def _passes_ip_filter(self, billing):
        """False when ip_filter_is_active and the client is in the IPv4 or the IPv6 filter subnet."""
        if not self.conf["ip_filter_is_active"]:
            return True
        client_ip = billing.get("moverInfo", {}).get("protocolInfo", {}).get("host")
        return not self._ip_matches_subnet(client_ip, self.conf["ipv4_network_address"], self.conf["ipv4_cidr"]) \
            and not self._ip_matches_subnet(client_ip, self.conf["ipv6_network_address"], self.conf["ipv6_cidr"])

    def _ip_matches_subnet(self, client_ip, network_address, cidr):
        """
        True if client_ip is in network_address/cidr, e.g. "131.169.0.0" and "16".
        An invalid address or subnet logs a warning and gives None, which counts as no match.
        """
        try:
            subnet = ip_network(network_address + "/" + str(cidr))
            return ip_address(client_ip) in subnet
        except ValueError as e:
            logger.warning("Invalid Argument: %s", e)


class AmqSender(stomp.ConnectionListener):
    """
    Collects the records of one Kafka batch and sends them in confirm(). The last record
    asks the broker for a receipt; the broker handles the frames of a connection in order,
    so that receipt confirms the whole batch. A send into a dropped connection can look
    successful, so only the receipt counts as delivered.
    """

    def __init__(self, connection, timeout=RECEIPT_TIMEOUT_SECONDS):
        self.connection = connection
        self.timeout = timeout
        self.pending = []
        self._receipt = None
        self._problem = None
        self._answered = threading.Event()
        connection.set_listener("wlcgConverter-receipts", self)

    def send(self, destination, body, content_type):
        """Queue a record; confirm() sends it."""
        self.pending.append((destination, body, content_type))

    def confirm(self):
        """Send the pending records; raise DeliveryError unless the broker confirms them."""
        if not self.pending:
            return
        frames, self.pending = self.pending, []
        self._receipt = "wlcgConverter-%s" % uuid.uuid4().hex
        self._problem = None
        self._answered.clear()
        try:
            if not self.connection.is_connected():
                raise DeliveryError("not connected to the broker")
            for i, (destination, body, content_type) in enumerate(frames):
                headers = {"receipt": self._receipt} if i == len(frames) - 1 else {}
                self.connection.send(destination=destination, body=body, content_type=content_type, headers=headers)
        except DeliveryError:
            raise
        except Exception as e:
            raise DeliveryError("sending failed: %s" % e)
        if not self._answered.wait(self.timeout):
            raise DeliveryError("the broker did not confirm %d records within %d s" % (len(frames), self.timeout))
        if self._problem:
            raise DeliveryError(self._problem)
        logger.debug("The broker confirmed %d records.", len(frames))

    def on_receipt(self, frame):
        """stomp.py callback: the broker confirmed a frame."""
        if frame.headers.get("receipt-id") == self._receipt:
            self._answered.set()

    def on_error(self, frame):
        """stomp.py callback: the broker answered with an ERROR frame."""
        if not self._answered.is_set():
            self._problem = "the broker answered with an error: %s" % frame.headers.get("message", "")
            self._answered.set()

    def on_disconnected(self):
        """stomp.py callback: the connection to the broker is gone."""
        if not self._answered.is_set():
            self._problem = "the connection to the broker was lost"
            self._answered.set()


def connect_to_broker(conf):
    """
    Open the STOMP connection to the AMQ broker: always TLS to amq_port_tls, with the
    broker's certificate and host name verified against amq_ca_certs. Logs in with the
    host certificate if path_to_cert and path_to_key are set, else with username and
    password. Config has checked these settings at startup.
    """
    broker = [(conf["amq_host"], int(conf["amq_port_tls"]))]
    connection = stomp.Connection12(broker)

    # ssl_version is left to stomp.py: its default (PROTOCOL_TLS_CLIENT) checks the host name,
    # while an explicit PROTOCOL_TLSv1_2 context does not. Without ca_certs, stomp.py skips
    # the certificate and host name checks.
    if "path_to_cert" in conf and "path_to_key" in conf:
        connection.set_ssl(for_hosts=broker, key_file=conf["path_to_key"], cert_file=conf["path_to_cert"],
                           ca_certs=conf["amq_ca_certs"])
        connection.connect(wait=True)
        logger.info("Connected to the AMQ broker %s:%s with the host certificate.", *broker[0])
    elif "username" in conf and "password" in conf:
        # the password, like the records, is only sent over TLS
        connection.set_ssl(for_hosts=broker, ca_certs=conf["amq_ca_certs"])
        connection.connect(conf["username"], conf["password"], wait=True)
        logger.info("Connected to the AMQ broker %s:%s with username and password.", *broker[0])
    else:
        raise ConfigError("no broker login configured: set path_to_cert and path_to_key, or username and password")
    return connection


class BillingConsumer:
    """Reads the billing topic from Kafka in batches and commits a batch only after it is delivered."""

    def __init__(self, servers, topic, group_id, offset_reset='latest'):
        logger.info("Trying to connect to Kafka...")
        # A failure here is raised to main(), which stops with a clear message instead of
        # running without a consumer. Offsets are committed by run(), not automatically.
        self.consumer = KafkaConsumer(topic,
                                      auto_offset_reset=offset_reset,
                                      group_id=group_id,
                                      bootstrap_servers=servers,
                                      enable_auto_commit=False,
                                      value_deserializer=decode_message)
        logger.info("Connection to Kafka established.")

    def run(self, converter):
        """
        Process Kafka messages batch by batch. A batch's offsets are committed only after
        its records are written and confirmed by the broker. Any error ends the loop before
        the commit, so after a restart the batch is read and sent again: a batch can arrive
        twice, but no record is lost.
        """
        while True:
            batch = self.consumer.poll(timeout_ms=1000, max_records=KAFKA_BATCH_SIZE)
            if not batch:
                continue
            for messages in batch.values():
                for message in messages:
                    converter.process(message)
            converter.deliver()
            self.consumer.commit()


def main():
    """
    Start the converter. Exit codes: 2 for an invalid configuration (a restart cannot fix
    it), 1 when Kafka is unreachable at startup or a batch could not be delivered (a restart
    reads the batch again), 0 after Ctrl-C.
    """
    parser = argparse.ArgumentParser(
        description='Read dCache billing records from Kafka and send one WLCG transfer-monitoring '
                    'record per xroot transfer to the AMQ broker.'
    )
    parser.add_argument(dest='path_to_config', help='path to wlcgConverter_config.yaml', type=str)
    args = parser.parse_args()

    with open(args.path_to_config, 'r') as config_file:
        try:
            raw_config = yaml.safe_load(config_file) or {}
        except yaml.YAMLError as e:
            logger.error("Could not read %s: %s", args.path_to_config, e)
            sys.exit(1)

    logging.config.dictConfig(raw_config.get("config::logging"))

    # empty values are dropped, missing or invalid settings stop the converter
    try:
        conf = Config(raw_config)
    except ConfigError as e:
        logger.error("Invalid configuration in %s: %s", args.path_to_config, e)
        sys.exit(2)

    if conf["verbose"]:
        logger.setLevel('DEBUG')

    # SciTag names for the activity field; loaded once, never per record
    registry = load_registry(conf.scitags_url, conf.scitags_cache_file)

    try:
        consumer = BillingConsumer(servers=conf["kafka_broker_incoming"],
                                   topic=conf["topic"],
                                   group_id="wlcgConverter-{}-consumer".format(conf["instance"]))
    except Exception as e:
        # exit 1, not 2: Kafka may be back at the next start
        logger.error("Could not connect to Kafka at %s: %s", conf["kafka_broker_incoming"], e)
        sys.exit(1)

    connection = None
    sender = None
    if conf["send_data"]:
        connection = connect_to_broker(conf)
        sender = AmqSender(connection)

    converter = WlcgConverter(conf, sender=sender, registry=registry)
    # runs until Ctrl-C, or until a batch cannot be delivered
    exit_code = 0
    try:
        consumer.run(converter)
    except KeyboardInterrupt:
        logger.info("WlcgConverter was terminated by user (CTRL-C).")
    except DeliveryError as e:
        logger.error("Stopped: %s. The batch was not committed in Kafka; its records are read and "
                     "sent again at the next start.", e)
        exit_code = 1
    except Exception:
        logger.exception("Stopped by an unexpected error. The current batch was not committed in Kafka; "
                         "its records are read again at the next start.")
        exit_code = 1
    finally:
        # disconnecting a lost connection would wait for a receipt that never comes
        if connection is not None and connection.is_connected():
            connection.disconnect()
            logger.info("Disconnected from the AMQ broker.")
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
