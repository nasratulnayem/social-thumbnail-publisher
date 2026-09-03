# Security Policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, exposed credential, authentication problem, or privacy concern.

Send a private report to **devnayem30@gmail.com** with the affected component, safe reproduction steps, observed impact, and suggested remediation if available. Remove real credentials, customer data, and unnecessary personal information.

## Responsible testing

Only test systems you own or have explicit permission to assess. Do not access or change another person's data. Avoid destructive tests, denial of service, automated high-volume requests, and attempts to bypass provider limits.

## Credential safety

Production passwords, API keys, OAuth tokens, private certificates, customer exports, and live databases must not be committed. Use environment variables or a secret manager. If a credential is committed, revoke it immediately because deleting it from the latest commit does not remove it from Git history.

## Supported versions

Security fixes target the latest maintained version on the default branch unless a release states otherwise.
