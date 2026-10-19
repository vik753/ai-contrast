# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Use GitHub private vulnerability reporting:

1. Open the **Security** tab of this repository.
2. Click **Report a vulnerability**.
3. Describe the problem, the impact and the steps to reproduce.

We aim to answer within 7 days.

## Scope

In scope:

- leaks of a client API key or contract text;
- SSRF through provider URLs or document links;
- XSS, CSP bypass, injection of HTML or scripts;
- malicious file handling (zip bombs, XXE, parser crashes);
- prompt injection that changes results in a way the defenses should catch;
- supply chain issues in this repository and its CI.

Out of scope:

- the security of third-party AI providers;
- attacks that need a compromised client device or a malicious browser extension;
- denial of service through high request volume on the free hosting tier.

## Security model

The server is stateless and keeps no secrets of its clients.
The full threat model and the rules for contributors: [`docs/security/threat-model.md`](docs/security/threat-model.md).
