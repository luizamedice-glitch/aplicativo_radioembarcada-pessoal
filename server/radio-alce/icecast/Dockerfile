FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends icecast2 ca-certificates media-types && rm -rf /var/lib/apt/lists/*
RUN useradd -r -s /usr/sbin/nologin radioicecast || true
RUN mkdir -p /var/log/icecast2 && chown -R radioicecast:radioicecast /var/log/icecast2
COPY icecast.xml /etc/icecast2/icecast.xml
RUN chown radioicecast:radioicecast /etc/icecast2/icecast.xml
USER radioicecast
CMD ["icecast2","-c","/etc/icecast2/icecast.xml"]
