# Disabled workflow examples

These workflows are kept as reference but renamed from `.github/workflows/` to
`.github/workflows.example/` so GitHub Actions does NOT auto-run them.

If you fork this repo and want to enable scheduled audits + ingest:

1. Rename this directory back: `mv .github/workflows.example .github/workflows`
2. Configure the required repository secrets (Neon DB URL, OAuth refresh token, etc.)
3. Commit and push.

Be aware: `audit.yml` writes results back to the repo. On a public repo this means
your audit output (numbers, account IDs, finding details) becomes public.
For private data, switch the repo to private OR change the workflow to commit
results to a separate private artifact location.
