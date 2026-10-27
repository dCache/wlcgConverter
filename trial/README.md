# Trial run

Run the v2 converter against the production Kafka billing topic **without sending anything to CERN**, then analyse what it wrote. It only reads from Kafka, and dCache is not touched.

You need:

- a Linux host that can reach the dCache billing Kafka brokers
- the brokers' addresses and the billing topic name
- the `python3.12` package (on EL9; any Python 3.10 or newer works)
- a clone of this repository's `trial-run` branch: the converter plus this `trial/` directory
- about 1 GB of disk for a day (about 1 KB per transfer)

No root is needed except to install `python3.12`, no systemd, and no certificates. `pip` downloads the four pinned packages from PyPI.

## 1. Install, as a normal user

```bash
git clone -b trial-run <repository URL> ~/wlcgConverter
mkdir ~/wlcg-trial && cd ~/wlcg-trial
python3.12 -m venv venv
venv/bin/pip install -r ~/wlcgConverter/requirements.txt
cp -r ~/wlcgConverter/wlcgConverterPackage/wlcgConverter.py ~/wlcgConverter/wlcgConverterPackage/wlcg .
cp ~/wlcgConverter/trial/trial-config.yaml ~/wlcgConverter/trial/analyze_output.py .
```

The run happens in `~/wlcg-trial`, so its output never lands in the clone.

## 2. Configure

Edit `trial-config.yaml` and fill in every `FILL IN`:

- the Kafka brokers and topic
- `server_version`
- `storage_instance`
- `local_networks`

To check the config without starting the run, start the converter (step 3) and stop it with `Ctrl-C` after `Connection to Kafka established.`. A wrong setting stops it at once with a message naming the setting (exit code 2).

## 3. Run, in the foreground, for about a day

In `tmux` or `screen`, from `~/wlcg-trial`:

```bash
timeout 24h venv/bin/python wlcgConverter.py trial-config.yaml
```

It starts with records that arrive after it started. You can watch it in a second terminal:

```bash
tail -f trial.log             # warnings and errors
tail -f trial-output.json     # converted records, one JSON object per line
```

`Ctrl-C` stops it early. If it stops by itself, `trial.log` says why. With `send_data: False`, that happens only if Kafka is unreachable at startup or the output file cannot be written.

## 4. Analyse

```bash
python3 analyze_output.py trial-output.json > trial-report.md
```

By default the report masks every example (letters become `x`, digits become `9`), so it can be shared. Add `--examples` to see the real values; keep that version local.

| Report section | Question it answers |
| --- | --- |
| Fields and types | Does every record have the 28 fields (27 when `traffic_scope` is `UNKNOWN`) with the right types? |
| Value distributions | Are `vo`, `activity`, `auth_method` and `traffic_scope` plausible? How often is something `unknown`? |
| Consistency checks | Are times, sizes, IPs, sites and status consistent? Does `fileSize` look right on uploads? |
| Privacy scan | Are there DNs, emails, user areas in paths, host names or IPs in fields where they don't belong? A host name in `file_path` such as `desy.de` in `/pnfs/desy.de/...` is expected. |
| Error messages | What do real dCache error messages contain: paths, pool names, identities? |

Also compare a few records with Kibana by hand. Find the same transfer by `file_path` and `end_time`, and check direction, sizes, status and the client IP.

## 5. Clean up

`trial-output.json` and `trial.log` contain real IPs and paths. Delete them, or the whole `~/wlcg-trial` directory, when done. The Kafka consumer group can be removed with Kafka's tools:

```bash
kafka-consumer-groups.sh --bootstrap-server <broker> --delete --group wlcgConverter-trial-consumer
```

## Later, before sending to CERN: certificate check

This is not part of the trial run. It needs, on the host that will send:

- a host certificate and key whose DN CERN has whitelisted (request via wlcgmon-tf@cern.ch)
- a PEM file with the CERN Grid CA and CERN Root CA 2 certificates (`amq_ca_certs`)

With those files in place, this command opens a TLS connection to the broker and sends no data:

```bash
openssl s_client -connect dashb-lb-mb.cern.ch:61123 \
    -CAfile <CA file> -cert <host certificate> -key <host key> \
    -verify_hostname dashb-lb-mb.cern.ch -verify_return_error </dev/null
```

`Verify return code: 0 (ok)` means the broker's certificate and name check out, and the broker accepted the host certificate. Whether the certificate may *publish* shows at the first real start: the converter logs in before it reads anything, and stops with an error if the login is refused.
