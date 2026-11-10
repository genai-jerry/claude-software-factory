FROM python:3.12-slim
COPY log_reader.py /app/log_reader.py
# Docker's log files are root-owned, so this runs as root, with every
# capability dropped in the compose file, a read-only root filesystem, a
# read-only mount of the logs, and no Docker socket.
WORKDIR /app
EXPOSE 8099
CMD ["python", "/app/log_reader.py"]
