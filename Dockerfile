# Python 3.10 is the minimum (stomp.py 9); 3.12 is a maintained release
FROM python:3.12-slim

# All dependencies install as prebuilt wheels or pure Python, so no compiler is needed
# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the wlcgConverter script together with its wlcg package; Python resolves
# the symlink, so the script finds wlcg/ next to its real location
COPY wlcgConverterPackage/wlcgConverter.py /opt/wlcgConverter/wlcgConverter.py
COPY wlcgConverterPackage/wlcg /opt/wlcgConverter/wlcg
RUN chmod +x /opt/wlcgConverter/wlcgConverter.py \
    && ln -s /opt/wlcgConverter/wlcgConverter.py /usr/local/bin/wlcgConverter

# Create directories for configuration and logs
RUN mkdir -p /etc/wlcg_converter /var/log

# Create a non-root user for security
RUN useradd -r -s /bin/false wlcgconverter
RUN chown -R wlcgconverter:wlcgconverter /etc/wlcg_converter /var/log

# Switch to non-root user
USER wlcgconverter

# Set the default command
CMD ["/usr/local/bin/wlcgConverter", "/etc/wlcg_converter/wlcgConverter_config.yaml"]
