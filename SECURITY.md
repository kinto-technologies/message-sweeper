# Security Policy

## Reporting a vulnerability

If you believe you have found a security vulnerability in Message Sweeper, **please do not open a public GitHub Issue.** Public disclosure before a fix is available can put users at risk.

Instead, report it privately by email to <message-sweeper@kinto-technologies.com> with:

- a description of the vulnerability and its potential impact,
- steps to reproduce it (a proof of concept if possible),
- the add-on version, NVDA version, and Slack / Teams version where you observed it.

We will acknowledge your report, investigate, and keep you informed of our progress. We ask that you give us a reasonable opportunity to address the issue before any public disclosure.

## Supported versions

Message Sweeper is distributed through the NVDA Add-on Store. We provide security fixes for the latest released version, so please make sure you are running the most recent version before reporting.

## Design notes

Message Sweeper fetches page titles for URLs found in messages. To reduce the risk of abuse, the add-on:

- blocks requests to private, loopback, and link-local address ranges (including IPv6 and carrier-grade NAT ranges),
- refuses redirects that would reach those internal address ranges,
- treats URL shorteners such as `t.co` conservatively,
- fails silently instead of announcing fetch errors that could leak information.

To protect the user's own privacy when a title is fetched, the add-on also:

- sends a generic `User-Agent` that does not reveal the request comes from a screen-reader (NVDA) user and includes no project URL,
- sends no `Referer` header.

Fetching a title still exposes the user's IP address to the destination server, because the request originates from the user's own machine. Repeated lookups of the same URL are served from an in-memory cache, which reduces but does not eliminate this exposure. An option to disable client-side fetching entirely is tracked as a separate enhancement.

If you find a way to bypass these protections, we would like to hear about it via the private contact above.
