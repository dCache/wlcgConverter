# Use Python 3.8 as base image (compatible with 3.6+ requirement)
FROM python:3.8-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the wlcgConverter script
COPY wlcgConverterPackage/wlcgConverter /usr/local/bin/wlcgConverter
RUN chmod +x /usr/local/bin/wlcgConverter

# Create directories for configuration and logs
RUN mkdir -p /etc/wlcg_converter /var/log

# Create a non-root user for security
RUN useradd -r -s /bin/false wlcgconverter
RUN chown -R wlcgconverter:wlcgconverter /etc/wlcg_converter /var/log

# Switch to non-root user
USER wlcgconverter

# Set the default command
CMD ["/usr/local/bin/wlcgConverter", "/etc/wlcg_converter/wlcgConverter_config.yaml"]
