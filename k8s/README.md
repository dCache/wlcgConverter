# Kubernetes Deployment for wlcgConverter

## Quick Start

1. **Create a Secret with your complete configuration file:**
   ```bash
   # Create secret with your config file (contains all settings)
   kubectl create secret generic wlcg-converter-config \
     --from-file=wlcgConverter_config.yaml=/path/to/your/wlcgConverter_config.yaml
   ```

2. **Create a Secret with your certificates:**
   ```bash
   # Create secret with your certificate files
   kubectl create secret generic wlcg-converter-certs \
     --from-file=cert.pem=/path/to/your/cert.pem \
     --from-file=key.pem=/path/to/your/key.pem
   ```

3. **Deploy the application:**
   ```bash
   kubectl apply -f deployment.yaml
   ```

## Configuration

### Configuration
The entire `wlcgConverter_config.yaml` file is provided as a Secret, which is mounted to `/etc/wlcg_converter/`. This includes all settings:
- `kafka_broker_incoming`: Your Kafka broker addresses
- `topic`: Kafka topic name
- `instance`: Your site instance name
- `send_data`: Set to `true` to enable data transmission
- `amq_host`, `amq_port`, `amq_topic`: AMQ configuration

### Certificate-based Authentication
Certificates are mounted separately to `/etc/wlcg_converter/certs/`. Update your config file to reference the mounted certificate files:

```yaml
path_to_cert: /etc/wlcg_converter/certs/cert.pem
path_to_key: /etc/wlcg_converter/certs/key.pem
```

**Note:** The wlcgConverter application reads the YAML config file directly, so put all your actual values in the config file. The certificates are mounted as separate files that you can reference by path.

## Monitoring

Check the deployment status:
```bash
kubectl get pods -l app=wlcg-converter
kubectl logs -l app=wlcg-converter
```
