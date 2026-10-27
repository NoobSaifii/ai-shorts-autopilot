# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Use GitHub's
[private vulnerability reporting](../../security/advisories/new) instead.
You'll get a reply within a few days.

## If you leaked a key

1. **Revoke / rotate it immediately** at the provider (Google AI Studio, Google Cloud,
   Meta, Cloudflare, GitHub). Deleting the commit is *not* enough — bots scrape new
   commits within minutes.
2. Then remove it from git history (e.g. `git filter-repo`) and force-push.

## How this project keeps secrets safe

- Real credentials live only in `config.yaml` / credential JSONs, all gitignored.
- In CI they are restored from encrypted GitHub Secrets, every sensitive value is
  registered with `::add-mask::`, and the files are deleted at the end of the job.
- A Gitleaks scan runs on every push and pull request.
