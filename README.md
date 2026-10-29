# WlcgConverter setup guide
#### Version: 2.0 (2026-10-26) 
**Important Note:** dCache v9.2 is a minimum requirement for the successful operation of the wlcgConverter. <br>
Additionally a running Apache Kafka installation is required. More information on configuring dCache for the use with Kafka can be found [here](https://www.dcache.org/documentation/Book-9.2/kafkaproducer.shtml).
<br>

The "wlcgConverter" reads dCache billing records from Kafka and converts each xroot transfer into one record of the WLCG transfer-monitoring format. The fields of that record and how each is derived are described in [docs/RECORD.md](docs/RECORD.md).  
It is run as a systemd service on any linux machine, that has a network connection to Kafka brokers providing the billing records.<br>
The tool also offers further functionalities, such as:
- sending the converted records to CERN's message broker over TLS, after verifying the broker's certificate
- ip filtering of configurable subnets, that are to be excluded from transmission
- writing the converted records to a local file

**Version 2.0 changes the record format.** The v1 fields `bytes_in`, `bytes_out`, `status`, `error_category` and `ipv6` are no longer sent; see [CHANGELOG.md](CHANGELOG.md).

To send records to MONIT, these must be provided beforehand:
- a DN has to be whitelisted at CERN (Mail your request together with a DN to: [wlcgmon-tf@cern.ch](mailto:wlcgmon-tf@cern.ch))
- a certificate file
- a corresponding key file
- a file with the CA certificates that signed the broker's certificate, in PEM format (setting `amq_ca_certs`)

## Getting started

Before you can start using the "wlcgConverter" some prerequisites have to be met.

1. [Install Python 3.10 or newer and the necessary python libraries in a virtual environment.](#python-prerequisites)
2. [Fill in all obligatory information into the "wlcgConverter_config.yaml" configuration file.](#how-to-configure-the-wlcgconverter-service)
3. [Place files from "wlcgConverterPackage" directory into specified locations.](#where-to-locate-the-provided-files)
4. [Start the service.](#how-to-start-the-wlcgconverter-service)


## Python prerequisites
The wlcgConverter needs **Python 3.10 or newer** (tested with 3.10, 3.12 and 3.14) and the python packages listed, with their exact versions, in `requirements.txt`:

- stomp.py 9.0.0
- PyYAML 6.0.3
- python-dateutil 3.0.0
- kafka-python 3.0.11

The packages are installed into their own virtual environment, `/opt/wlcgConverter/venv`, so they do not depend on or change the system's Python packages. Create it with a Python 3.10 or newer. On EL9 (RHEL, AlmaLinux, Rocky) the default `python3` is 3.9, which is too old; install the `python3.12` package instead (`yum` works the same as `dnf` there). Run as root, from the repository root:
```
dnf install python3.12
mkdir -p /opt/wlcgConverter
python3.12 -m venv /opt/wlcgConverter/venv
/opt/wlcgConverter/venv/bin/pip install -r requirements.txt
```
On other distributions, use any Python 3.10 or newer in place of `python3.12`.

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
cp -r wlcgConverter.py wlcg /opt/wlcgConverter/

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

The systemd unit starts the converter with the Python of the virtual environment. To run it by hand, e.g. to check a configuration, use the same command:
```
/opt/wlcgConverter/venv/bin/python /opt/wlcgConverter/wlcgConverter.py /etc/wlcg_converter/wlcgConverter_config.yaml
```
A missing or invalid setting stops it with exit code 2; systemd does not restart it in that case, so fix the configuration and start the service again.
## How to start the wlcgConverter service
Run the following commands as root:
```
systemctl daemon-reload
systemctl start wlcgConverter.service 
systemctl status wlcgConverter.service 
```
The latter command simply outputs the status of the service. If the shown status is "active (running)", everything is working 
as expected. 

If the broker does not confirm a batch of records, the converter logs the reason and stops with exit code 1 without marking the batch as processed in Kafka. systemd starts it again after 30 seconds, and it sends that batch again. A record can therefore arrive twice, but it is not lost. When running the Docker image without systemd or Kubernetes, start the container with a restart policy, e.g. `docker run --restart unless-stopped …`, so it is started again after such a stop.
## Troubleshooting
Troubleshooting the service is best done with the information provided by the following command:
```
journalctl -u wlcgConverter.service
```

You can file an issue via [github](https://github.com/dCache/wlcgConverter/issues). 

NOTE: A more convenient packaging option for this software tool is currently being developed. Any help and contribution regarding this is most appreciated. 

## License
This software is licensed under Apache License 2.0. Find more information [here.](https://www.apache.org/licenses/LICENSE-2.0)

