#! /usr/bin/env python3

#########################################
# This script converts json key:value mappings in billing records to a wlcg specific mapping scheme
# author: sandro.grizzo@desy.de
# date: 2024-01-10
# version: 1.0
#########################################

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

    def __init__(self, conf={}, activemq_connection=None, registry=None):
        self.conf = conf
        self.activemq_connection = activemq_connection
        self.registry = registry

    def execute(self, message):
        message_data = message.value
        if not isinstance(message_data, dict):
            # not JSON at all (decode_message gave None), or JSON that is not an object
            logger.warning("Skipped a Kafka message that is not a JSON object.")
            return
        # failed transfers are sent too, with their native status code and message
        if is_wanted(message_data, self.conf["protocol"]):

            try:
                wlcg_dict = build_record(message_data, self.conf, self.registry)
            except Exception:
                # one malformed record must not stop the converter; AMQ errors below still do.
                # Log only non-personal context: the record holds the user's DN and email.
                logger.exception("Skipped a billing record that could not be converted "
                                 "(pnfsid=%s, date=%s, cell=%s)", message_data.get("pnfsid"),
                                 message_data.get("date"), message_data.get("cellName"))
                return

            if self.conf["local_dump"]:
                with open(self.conf["path_to_converted_json_file"], 'a') as wlcg_json_output_file:
                    json.dump(wlcg_dict, wlcg_json_output_file)
                    wlcg_json_output_file.write('\n')

            if self.conf["send_data"]:
                if self.conf["ip_filter_is_active"]:
                    client_ip = message_data.get("moverInfo", {}).get("protocolInfo", {}).get("host")
                    if not self.__ip_matches_subnet(client_ip,
                                                self.conf["ipv4_network_address"],
                                                self.conf["ipv4_cidr"]) \
                                                and not self.__ip_matches_subnet(client_ip,
                                                self.conf["ipv6_network_address"],
                                                self.conf["ipv6_cidr"]):
                        self.activemq_connection.send(destination=self.conf["amq_topic"],
                                                  body=json.dumps(wlcg_dict),
                                                  content_type='application/json')
                        logger.debug("Message sent via AMQ: %s", json.dumps(wlcg_dict))
                else:
                    self.activemq_connection.send(destination=self.conf["amq_topic"],
                                              body=json.dumps(wlcg_dict),
                                              content_type='application/json')
                    logger.debug("Message sent via AMQ: %s", json.dumps(wlcg_dict))

    def deliver(self):
        """Send the records of the current batch and wait until the broker confirms them."""
        if self.conf["send_data"]:
            self.activemq_connection.confirm()

    def __ip_matches_subnet(self, client_ip_addr, network_addr, network_cidr):
        '''
        :param client_ip_addr: The IPv4 or IPv6 address of the requesting client (key: "host")
        :param network_addr: The subnet's base address in decimal notation, e.g. "135.170.0.0"
        :param network_cidr: The subnet mask in CIDR notation without a preceding '/' (slash), e.g. "24"
        :return: True if the given ip matches the subnet. False otherwise.
        :throws: A warning is printed and logged if any invalid arguments are passed. Nothing more.
        '''

        try:
            subnet = ip_network(network_addr + "/" + str(network_cidr))
            ip_addr = ip_address(client_ip_addr)

            if ip_addr in subnet:
                return True
            return False

        except ValueError as ve:
            logger.warning("Invalid Argument: %s", ve)

# ************************************************************************************************************


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
        if frame.headers.get("receipt-id") == self._receipt:
            self._answered.set()

    def on_error(self, frame):
        if not self._answered.is_set():
            self._problem = "the broker answered with an error: %s" % frame.headers.get("message", "")
            self._answered.set()

    def on_disconnected(self):
        if not self._answered.is_set():
            self._problem = "the connection to the broker was lost"
            self._answered.set()


def __connect_2_activemq(conf) -> object:

    # Always TLS, and the broker must prove who it is: without ca_certs stomp.py skips the
    # certificate and hostname checks. Config has checked these keys at startup.
    amq_host = conf["amq_host"]
    broker = [(amq_host, int(conf["amq_port_tls"]))]

    conn = stomp.Connection12(broker)

    # ssl_version is left to stomp.py: its default (PROTOCOL_TLS_CLIENT) checks the hostname,
    # while an explicit PROTOCOL_TLSv1_2 context does not
    if "path_to_cert" in conf and "path_to_key" in conf:
        conn.set_ssl(
            for_hosts=broker,
            key_file=conf["path_to_key"],
            cert_file=conf["path_to_cert"],
            ca_certs=conf["amq_ca_certs"])
        conn.connect(wait=True)
        logger.info("AMQ TLS: certificate based authentication is used.")

    elif "username" in conf and "password" in conf:
        # never send the password, or the records, without TLS
        conn.set_ssl(for_hosts=broker, ca_certs=conf["amq_ca_certs"])
        conn.connect(conf["username"], conf["password"], wait=True)
        logger.info("AMQ TLS: user-password based authentication is used.")
    else:
        raise IOError(
            "ERROR: The input arguments do not include a valid authentication tuple \
             (certificate, key) or (username, password)"
        )

    return conn

# ************************************************************************************************************


class CustomKafkaConsumer:
    """Initialize a custom Kafka-Consumer"""

    def __init__(self,
                 servers=[],
                 msg_offset='earliest',
                 topic_name='',
                 group_id='',
                 msg_format='json'):
        self.servers = servers
        self.group_id = group_id
        self.topic_name = topic_name
        self.msg_format = msg_format
        self.msg_offset = msg_offset
        self.consumer = None

        try:
            logger.info("Trying to connect to Kafka...")
            # offsets are committed by getMessage, after a batch is delivered
            self.consumer = KafkaConsumer(self.topic_name,
                                          auto_offset_reset=self.msg_offset,
                                          group_id=self.group_id,
                                          bootstrap_servers=self.servers,
                                          enable_auto_commit=False,
                                          value_deserializer=decode_message)
            logger.info("Connection to Kafka established.")
        except Exception as e:
            logger.error("Error initializing KafkaConsumer: {}".format(e))

    def getMessage(self, analyser):
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
                    analyser.execute(message)
            analyser.deliver()
            self.consumer.commit()


# ************************************************************************************************************

def main():
    parser = argparse.ArgumentParser(
        description='Script to convert desy-formatted billing json files to wlcg-formatted json files'
    )
    parser.add_argument(
        dest='path_to_config', help='Path to configuration file for wlcgConverter', type=str
    )
    args = parser.parse_args()

    # read the config yaml file #
    with open(args.path_to_config, 'r') as config:
        try:
            config_all = yaml.safe_load(config) or {}
        except yaml.YAMLError as exc:
            logger.error("An error occurred opening the wlcgConverter_config.yaml file: {}".format(exc))
            sys.exit(1)

    # logging setup #
    logging_conf = config_all.get("config::logging")
    logging.config.dictConfig(logging_conf)

    # validate the config; empty values are dropped #
    try:
        conf = Config(config_all)
    except ConfigError as e:
        logger.error("Invalid configuration in %s: %s", args.path_to_config, e)
        sys.exit(2)

    if conf["verbose"]:
        logger.setLevel('DEBUG')

    # SciTag names for the activity field; loaded once, never per record #
    registry = load_registry(conf.scitags_url, conf.scitags_cache_file)

    # create a kafka consumer object #
    kafka_consumer = CustomKafkaConsumer(topic_name=conf["topic"],
                                    msg_offset='latest',
                                    servers=conf["kafka_broker_incoming"],
                                    group_id="wlcgConverter-{}-consumer".format(conf["instance"]))

    connection = None
    sender = None
    # connect to active_mq if send_date is True in config#
    if conf["send_data"]:
        connection = __connect_2_activemq(conf)
        sender = AmqSender(connection)
        logger.info("Producer: Connection to amq broker established successfully.")

    # create a converter object #
    wlgc_converter = WlcgConverter(conf, activemq_connection=sender, registry=registry)
    # and start working until Ctrl-c is pressed.#
    exit_code = 0
    try:
        kafka_consumer.getMessage(analyser=wlgc_converter)
    except KeyboardInterrupt:
        logger.info("\nWlcgConverter was terminated by user (CTRL-C).")
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
            logger.info("Disconnecting...")
            connection.disconnect()
            logger.info("AMQ connection was disconnected successfully.")
    if exit_code:
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
