# Contributing

Thanks for helping with AIL Context Compressor.

## Sign-off required

Every commit must be signed off under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).
Add the line with `git commit -s`:

    Signed-off-by: Your Name <you@example.com>

By signing off, you confirm you wrote the change or have the right to submit
it under this project's MIT license. Pull requests with unsigned commits are
not merged.

## How to contribute

1. Fork the repo and branch from `dev`.
2. Keep changes small and focused. Standard library only in
   `skills/ail-context-compressor/scripts/`.
3. Run the tests: `python -m unittest discover -s tests`.
4. Never commit secrets, real chat logs, or personal data. Use invented samples.
5. Open a pull request into `dev`. A maintainer reviews it before it reaches `main`.

## Security issues

Do not open a public issue. Follow [SECURITY.md](SECURITY.md).
