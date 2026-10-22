FROM python:3.12-slim-trixie

RUN apt-get update \
    && apt-get install --no-install-recommends -y openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/fre3nder-repository
COPY repositoryd.py ./repositoryd.py

# Compose runs this with the host's selected unprivileged UID/GID.
ENTRYPOINT ["python", "-u", "/opt/fre3nder-repository/repositoryd.py"]
CMD ["--loop"]
