# WlcgConverter setup guide
#### Version: 1.0 (2024-01-10) 

The "wlcgConverter" is a software tool that converts "site"-formatted json billing records to wlcg-formatted json billing records (providing for new 'key:value' mappings in the converted records).  
It is run as a systemd service on linux machines.
The tool also provides further functionalities, such as:
- sending the converted data via an encrypted channel (provided that a certificate and key file have been configured)
- ip filtering of configurable subnets, that are to be excluded from transmission



To establish an encrypted transmission channel, three essential things must be provided beforehand:
- a DN has to be whitelisted at Cern (Mail your request together with a DN to: [wlcgmon-tf@cern.ch](mailto:wlcgmon-tf@cern.ch))
- a certificate file
- a corresponding key file

## Getting started

Before you can start using the "wlcgConverter" some prerequisites have to be met.

1. [Make sure you have python3 and the necessary python libraries installed.](#python-prerequisites)
2. [Fill in all obligatory information into the "wlcgConverter_config.yaml" configuration file.](#how-to-configure-the-wlcgconverter-service)
3. [Place files from "wlcgConverterPackage" directory into specified locations.](#where-to-locate-the-provided-files)
4. [Start the service.](#how-to-start-the-wlcgconverter-service)


## Python prerequisites
The following python packages must be installed on the machine running the wlcgConverter:

- python3                 &ensp;&thinsp;&ensp;&thinsp;&ensp;&thinsp;&ensp;&thinsp;&ensp;&thinsp;#tested with version 3.6.8
- stomp.py               &ensp;&thinsp;&ensp;&thinsp;&ensp;&thinsp;&ensp;&thinsp;&ensp;#tested with version 8.1.0
- PyYAML==5.4.1
- python-dateutil    &ensp;&thinsp;&ensp;&thinsp;&ensp;&thinsp;#tested with version 2.8.2
-  kafka-python    &ensp;&thinsp;&ensp;&thinsp;&ensp;&thinsp;&ensp;#tested with version  2.0.2

In case you **DO NOT** have these packages installed, run the following commands as root on the command line:

Depending on your linux distro, e.g.:
```
yum install python3
yum install python3-pip   
```
and then:
```
pip3 install stomp.py
pip3 install PyYAML==5.4.1
pip3 install python-dateutil 
pip3 install kafka-python
```

## How to configure the "wlcgConverter" service
- Please open the "wlcgConverter_config.yaml" file and provide the fields denoted with ''obligatory".  
- You may configure the ones denoted "optional " as well if needed. 
- Read the commentaries carefully. Since changing some optional
fields may make others obligatory.
- Please do not enter or change information in fields that do not have commentaries indicating to do so.  



## Where to locate the provided files
In the "wlcgConverterPackage" directory you will find 3 files. These must be copied to the following locations.  
Run these commands as root from within the directory:
```
cp wlcgConverter  /usr/bin/
chmod 755 /usr/bin/wlcgConverter

cp wlcgConverter.service /etc/systemd/system/

mkdir /etc/wlcg_converter/
cp wlcgConverter_config.yaml  /etc/wlcg_converter/
```
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

