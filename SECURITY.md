# Security

NovelTea Engine is a local application with **no login**. It listens on `127.0.0.1` by default; exposing it to a network is an explicit
opt-in (`NOVELTEA_HOST=0.0.0.0`) and should only be done on a network you trust or behind a private tunnel.

**Reporting a problem:** please do not open a public issue for a security problem. Use GitHub's *Report a vulnerability* button on the
repository's Security tab (private advisory). Include what you found, how to reproduce it, and the version.

Things that are in scope: path traversal or unsafe file handling in project import/export, any way to read or write outside the project
and corpus folders, key or token leakage, and anything that lets a web page on another origin drive the local server.

Your API keys are stored in `~/.noveltea-engine/config.json`, outside the repository. If you think a key leaked, revoke it at the provider first.
