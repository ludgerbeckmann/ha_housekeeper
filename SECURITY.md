# Security policy

## Supported versions
Only the latest release receives fixes.

## Reporting a vulnerability
Please report a vulnerability privately through GitHub's
[private vulnerability reporting](https://github.com/ludgerbeckmann/ha_housekeeper/security/advisories/new)
instead of opening a public issue. Include the version, a short description,
and how to reproduce it. Remove private details from any logs first.

## Scope
Home Assistant Hausmeister is a custom integration that runs inside your own
Home Assistant. It stores its state in Home Assistant's own storage and sends
notifications only through the notify services you select. It collects no
telemetry and opens no network ports. If you use the LLM usage function it
contacts the Anthropic or OpenAI cost API with the admin key you enter; the key
stays in your Home Assistant configuration and is redacted from diagnostics.
