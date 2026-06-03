# Contributing

Thanks for contributing to AquaCam Pi Stream.

## How to contribute

1. Fork the repo
2. Create a feature branch
3. Make focused changes
4. Test on a non-production Pi if possible
5. Open a PR with:
   - what changed
   - why it changed
   - how it was tested

## Guidelines

- Keep secrets out of commits
- Prefer small, reviewable PRs
- Update `docs/TUTORIAL.md` when behavior changes
- Keep placeholder values in public templates

Before commit, run:

```bash
./scripts/scan_secrets.sh
```

Optional pre-commit hook:

```bash
cat > .git/hooks/pre-commit << 'EOF'
#!/usr/bin/env bash
./scripts/scan_secrets.sh
EOF
chmod +x .git/hooks/pre-commit
```

## Reporting issues

Please include:
- Pi model + OS version
- camera model
- relevant logs (redacted)
- exact steps to reproduce
