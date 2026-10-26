# WlcgConverter setup guide
#### Version: 2.0 (2026-10-26) 
**Important Note:** dCache v9.2 is a minimum requirement for the successful operation of the wlcgConverter. <br>
Additionally a running Apache Kafka installation is required. More information on configuring dCache for the use with Kafka can be found [here](https://www.dcache.org/manuals/Book-9.2/kafkaproducer.shtml).
<br>

The "wlcgConverter" reads dCache billing records from Kafka and converts each xroot transfer into one record of the WLCG transfer-monitoring format. The fields of that record and how each is derived are described in [docs/RECORD.md](docs/RECORD.md).  
It is run as a systemd service on any linux machine, that has a network connection to Kafka brokers providing the billing records.<br>
The tool also offers further functionalities, such as:
- sending the converted records to CERN's message broker over TLS, after verifying the broker's certificate
- ip filtering of configurable subnets, that are to be excluded from transmission
- writing the converted records to a local file

**Version 2.0 changes the record format.** The v1 fields `bytes_in`, `bytes_out`, `status`, `error_category` and `ipv6` are no longer sent; see [CHANGELOG.md](CHANGELOG.md).

To send records to CERN, these must be provided beforehand:
- a DN has to be whitelisted at Cern (Mail your request together with a DN to: [wlcgmon-tf@cern.ch](mailto:wlcgmon-tf@cern.ch))
- a certificate file
- a corresponding key file
- a file with the CA certificates that signed the broker's certificate, in PEM format (setting `amq_ca_certs`)

## Getting started

Before you can start using the "wlcgConverter" some prerequisites have to be met.

1. [Make sure you have python3 and the necessary python libraries installed.](#python-prerequisites)
2. [Fill in all obligatory information into the "wlcgConverter_config.yaml" configuration file.](#how-to-configure-the-wlcgconverter-service)
3. [Place files from "wlcgConverterPackage" directory into specified locations.](#where-to-locate-the-provided-files)
4. [Start the service.](#how-to-start-the-wlcgconverter-service)


## Python prerequisites
The wlcgConverter needs **Python 3.10 or newer** (tested with 3.10, 3.12 and 3.14) and the python packages listed, with their exact versions, in `requirements.txt`:

- stomp.py 9.0.0
- PyYAML 6.0.3
- python-dateutil 3.0.0
- kafka-python 3.0.11

In case you **DO NOT** have them installed, run the following commands as root on the command line.

Depending on your linux distro, e.g.:
```
yum install python3
yum install python3-pip   
```
and then, from the repository root:
```
pip3 install -r requirements.txt
```

## How to configure the "wlcgConverter" service
- Please open the "wlcgConverter_config.yaml" file and provide the fields denoted with ''obligatory".  
- You may configure the ones denoted "optional " as well if needed. 
- Read the commentaries carefully. Since changing some optional
fields may make others obligatory.
- Please do not enter or change information in fields that do not have commentaries indicating to do so.  
- Version 2.0 adds obligatory settings: `server_site` (the WLCG site name of this storage) and `server_version` (the dCache release). With `send_data: True`, `amq_port_tls` and `amq_ca_certs` are obligatory as well; records are only sent over TLS.
- The converter checks the configuration at startup and exits with code 2, naming the setting, if one is missing or invalid.



## Where to locate the provided files
In the "wlcgConverterPackage" directory you will find the script `wlcgConverter.py`, the `wlcg` package it imports, the systemd unit and the config file. These must be copied to the following locations.  
The script and the `wlcg` directory must stay together; never copy the script on its own.  
Run these commands as root from within the directory:
```
mkdir -p /opt/wlcgConverter
cp -r wlcgConverter.py wlcg /opt/wlcgConverter/
chmod 755 /opt/wlcgConverter/wlcgConverter.py
ln -sf /opt/wlcgConverter/wlcgConverter.py /usr/bin/wlcgConverter

cp wlcgConverter.service /etc/systemd/system/

mkdir /etc/wlcg_converter/
cp wlcgConverter_config.yaml  /etc/wlcg_converter/
```
The service runs as the user `wlcgconverter`, not as root. Create it, and let it read the configuration and the certificate files, which may contain secrets:
```
useradd -r -s /sbin/nologin wlcgconverter
chown root:wlcgconverter /etc/wlcg_converter/wlcgConverter_config.yaml
chmod 640 /etc/wlcg_converter/wlcgConverter_config.yaml
```
Give the certificate, key and CA files the same group and mode. systemd creates `/var/log/wlcg_converter/` for the log file and `/var/lib/wlcg_converter/` for the optional `scitags_cache_file`, owned by that user; files the service writes there are readable by that user only. With `local_dump: True`, put `path_to_converted_json_file` in a directory the user can write, e.g. `/var/lib/wlcg_converter/`.
## How to start the wlcgConverter service
Run the following commands as root:
```
systemctl daemon-reload
systemctl start wlcgConverter.service 
systemctl status wlcgConverter.service 
```
The latter command simply outputs the status of the service. If the shown status is "active (running)", everything is working 
as expected. 
## Troubleshooting
Troubleshooting the service is best done with the information provided by the following command:
```
journalctl -u wlcgConverter.service
```

You can file an issue via [github](https://github.com/dCache/wlcgConverter/issues). 

NOTE: A more convenient packaging option for this software tool is currently being developed. Any help and contribution regarding this is most appreciated. 

## License
This software is licensed under Apache License 2.0. Find more information [here.](https://www.apache.org/licenses/LICENSE-2.0)

