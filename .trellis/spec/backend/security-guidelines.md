# Security Guidelines

> Identity, Broker permissions, secret handling, and AI safety for the cloud backend.

---

## Trust Boundaries

- The device connects only to the MQTT Broker for cloud capabilities; the AI Bridge is another Broker client.
- MiMo, TTS, ASR, and manual parsing are cloud-side integrations reached from the AI Bridge over HTTPS.
- Device input, uploaded manuals, provider output, MQTT topics, and MQTT payloads cross trust boundaries and require validation.
- AI output is advisory. The cloud must not represent a suggestion as an authorized device write.

## Device Identity and Token Contract

Production `device_id` is derived by firmware from the STM32 UID. Production firmware provides no runtime UI, MQTT, serial CLI, or HTTP interface for changing it. `display_name` is mutable but never participates in authorization.

The confirmed v1 token formula is:

```text
mqtt_token = base64url(
  HMAC-SHA256(PRODUCT_AUTH_SECRET, "velaguard:mqtt:v1:" + device_id)
)
```

The formula is versioned. The cloud must support controlled overlap during a secret/version migration and a denylist capable of blocking one leaked `device_id`.

Do not replace HMAC with a plain hash. Do not use `display_name` as an identity or ACL key.

How credentials are provisioned, verified, and stored is not yet confirmed. Select a secret-management approach before production; never hard-code production secrets in source or ordinary configuration files.

## Broker and ACL Policy

Production requires:

- MQTT over TLS.
- Per-device account or token.
- Broker ACL limiting each device to its own `vg/{device_id}/...` topics.
- A separate AI Bridge account limited to required request subscriptions and response publications.
- Closed access for denylisted devices.

Plaintext MQTT is permitted only for controlled-LAN testing and must be disabled for production. The backend must reject or flag topic/payload `device_id` mismatches even when Broker ACLs are expected to prevent them.

## Secret Handling

Protect at least:

- Product authentication secrets and versioned derivatives.
- Complete device tokens.
- MiMo API keys.
- TTS/ASR/manual-service credentials.
- Network credentials and TLS private material controlled by the backend.
- OTA private signing keys and production artifact credentials.
- User-uploaded manuals and diagnosis data.

Never expose complete secrets in MQTT payloads, logs, errors, metrics labels, tracing attributes, admin UI responses, or test snapshots. The root documents explicitly forbid complete token, product key, MiMo API key, and OTA private key exposure.

The OTA signing private key is cloud/build infrastructure material. Devices receive only the verification material required by the firmware design.

## AI and Operational Safety

AI may generate diagnosis, reports, troubleshooting steps, and candidate sensor configurations. It may not directly:

- Write registers.
- Activate configuration changes.
- Control actuators.
- Clear alarms.
- Override local safety rules.

Backend responses must preserve the device-side sequence: schema validation, risk checks, preview, test read where applicable, local confirmation, then application. Remote candidates enter a pending confirmation flow and must not be marked active by the cloud.

## Upload and Large-Artifact Safety

- Validate upload type, size, and metadata before forwarding or parsing manuals.
- Keep parsing isolated from ordinary request handling and do not return complete documents to the device.
- Validate chunk/session identifiers and hashes for voice and OTA transfers.
- Do not allow user-controlled object names or topic fragments to escape a device/session namespace.
- Define malware scanning, content retention, tenant isolation, and deletion policy before production manual uploads; the root documents do not currently select implementations or values.

## Test and Production Boundary

The device build contract explicitly distinguishes:

```text
VG_BUILD_MODE=test
VG_BUILD_MODE=production
```

`test` firmware may override `DEVID`, use controlled-LAN plaintext MQTT, emit detailed debug logs, and accept development-signed OTA. `production` firmware derives identity from STM32 UID, requires MQTTS/token/ACL, redacts complete tokens, and accepts only production-signed OTA.

This does **not** confirm `VG_BUILD_MODE` as the backend's own environment variable. The backend needs an explicit, validated environment/security mode chosen during implementation and must not silently downgrade production policy.

## Security Review Checklist

- Is identity based on immutable `device_id`, not `display_name` or untrusted payload alone?
- Are topic permissions least privilege for both device and AI Bridge accounts?
- Are all secrets supplied through an approved secret channel and redacted from every output?
- Is plaintext MQTT impossible in production policy?
- Are retries and duplicate requests unable to execute provider work or side effects twice?
- Are uploaded content and large artifacts bounded, verified, isolated, and auditable?
- Does every AI-generated write-like result remain only a candidate for device-side confirmation?
- Can a single leaked device be denylisted without rotating every device immediately?

## Source References

- `VelaGuard_项目手册.md`: sections 2.2, 11.1-11.4, 16.1-16.2, 16.4, 16.8-16.10.
- `VelaGuard_推进方案.md`: sections 1, 6.2, 8.2, 9.2, and 16.2-16.3, 16.7-16.10.
