# Security Guidelines

## Trust and Read-Only Boundaries

- Devices and the dashboard are independent MQTT broker clients.
- Broker payloads are untrusted: validate topic identity, JSON shape and size.
- The dashboard account may only subscribe to its approved device filters.
- The collector never publishes configuration, alarm acknowledgement or controls.
- Browser clients use HTTP only and never receive MQTT credentials.
- The HTTP server has no built-in authentication or HTTPS. Production must
  provide access controls and TLS externally before exposing device data.

## Broker and TLS Policy

Production requires MQTTS, per-device credentials/tokens and least-privilege ACLs.
Plaintext anonymous Mosquitto is permitted only for controlled development.
Never silently downgrade TLS or disable certificate verification.

`MQTT_TLS=true` uses the system trust store unless `MQTT_CA_PATH` is set.
Optional `MQTT_CLIENT_CERT_PATH`/`MQTT_CLIENT_KEY_PATH` must be paired and all
configured files must exist. Blank paths are unset. Plaintext mode ignores
certificate paths.

The synthetic publisher is a development tool for a controlled test broker,
not a production credential provisioning or TLS administration client.

## Device Identity Contract

External production firmware derives immutable `device_id` from STM32 UID.
Mutable `display_name` is never an authorization key.

The documented versioned device token is:

```text
base64url(HMAC-SHA256(PRODUCT_AUTH_SECRET, "velaguard:mqtt:v1:" + device_id))
```

Token verification, version overlap during rotation and per-device denylisting
belong to broker administration; they are not implemented by this dashboard.

## Secrets and Stored Data

- Inject broker credentials through the deployment environment or untracked `.env`.
- Never commit credentials, tokens, product secrets or TLS private keys.
- Keep complete secrets out of logs, HTTP errors and device JSON payloads.
- Protect the SQLite database and raw-message API as device data.
- Use `dashboard.observability` for shared redaction and test its behavior.

## Review Checklist

- Is the collector still subscribe-only, including reconnect and error paths?
- Are topic/payload identities validated?
- Are configured TLS paths checked without an insecure bypass?
- Are secrets absent from logs, errors, docs, fixtures and package artifacts?
- Is HTTP access protected by deployment policy?
- Can cloud failures leave device collection and local alarms running?
