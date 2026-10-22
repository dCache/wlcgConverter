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
import ssl
import sys
from ipaddress import ip_address, ip_network

import stomp
import yaml
from kafka import KafkaConsumer

from wlcg.config import Config, ConfigError
from wlcg.schema import build_record

logger = logging.getLogger('wlcgConverter')


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

    def __init__(self, conf={}, activemq_connection=None):
        self.conf = conf
        self.activemq_connection = activemq_connection

    def execute(self, message):
        message_data = message.value
        if not isinstance(message_data, dict):
            # not JSON at all (decode_message gave None), or JSON that is not an object
            logger.warning("Skipped a Kafka message that is not a JSON object.")
            return
        # failed transfers are sent too, with their native status code and message
        if is_wanted(message_data, self.conf["protocol"]):

            try:
                wlcg_dict = build_record(message_data, self.conf)
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
                    logger.debug("Message_data: %s", message_data)

            if self.conf["send_data"]:
                if self.conf["ip_filter_is_active"]:
                    client_ip = message_data.get("moverInfo", {}).get("protocolInfo", {}).get("host")
                    if not self.__ip_matches_subnet(client_ip,
                                                self.conf["ipv4_network_address"],
                                                self.conf["ipv4_cidr"]) \
                                                or not self.__ip_matches_subnet(client_ip,
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


def __connect_2_activemq(conf) -> object:

    amq_host = conf["amq_host"]
    # empty YAML values are dropped from conf, so amq_port_tls may be absent
    amq_port = conf.get("amq_port_tls") or conf["amq_port"]

    conn = stomp.Connection12([(amq_host, int(amq_port))])

    if "path_to_cert" in conf and "path_to_key" in conf:
        conn.set_ssl(
            for_hosts=[(amq_host, int(amq_port))],
            key_file=conf["path_to_key"],
            cert_file=conf["path_to_cert"],
            ssl_version=ssl.PROTOCOL_TLSv1_2)
        conn.connect(wait=True)
        logger.info("AMQ SSL: certificate based authentication is used.")

    elif "username" in conf and "password" in conf:
        conn.connect(conf["username"], conf["password"], wait=True)
        logger.info("AMQ Plain: user-password based authentication is used.")
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
            self.consumer = KafkaConsumer(self.topic_name,
                                          auto_offset_reset=self.msg_offset,
                                          group_id=self.group_id,
                                          bootstrap_servers=self.servers,
                                          value_deserializer=decode_message)
            logger.info("Connection to Kafka established.")
        except Exception as e:
            logger.error("Error initializing KafkaConsumer: {}".format(e))

    def getMessage(self, analyser):
        for message in self.consumer:
            try:
                analyser.execute(message)
            except IOError:
                pass


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

    # create a kafka consumer object #
    kafka_consumer = CustomKafkaConsumer(topic_name=conf["topic"],
                                    msg_offset='latest',
                                    servers=conf["kafka_broker_incoming"],
                                    group_id="wlcgConverter-{}-consumer".format(conf["instance"]))

    connection = None
    # connect to active_mq if send_date is True in config#
    if conf["send_data"]:
        connection = __connect_2_activemq(conf)
        logger.info("Producer: Connection to amq broker established successfully.")

    # create a converter object #
    wlgc_converter = WlcgConverter(conf, activemq_connection=connection)
    # and start working until Ctrl-c is pressed.#
    try:
        kafka_consumer.getMessage(analyser=wlgc_converter)
    except KeyboardInterrupt:
        logger.info("\nWlcgConverter was terminated by user (CTRL-C).")
    finally:
        if connection is not None:
            logger.info("Disconnecting...")
            connection.disconnect()
            logger.info("AMQ connection was disconnected successfully.")


if __name__ == "__main__":
    main()
