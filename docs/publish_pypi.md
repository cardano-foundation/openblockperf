# Publishing to PyPI

The OpenBlockperf client is a pure Python package. The wheel is
`py3-none-any`, so you can build and upload from Windows or Linux. The
Linux-only check is a runtime guard in the CLI (`sys.platform != "linux"`),
not a packaging constraint. You do not need a Linux builder for the release.

Install `uv` on this Windows machine if it is not already on PATH:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Or: `winget install astral-sh.uv`

You need accounts and API tokens on both indexes if you want to dry-run first:

* https://pypi.org/  (Account settings -> API tokens)
* https://test.pypi.org/

Use a project-scoped token when possible. Username is always `__token__`.
The password is the token string, including the `pypi-` prefix.

See also: https://docs.astral.sh/uv/guides/package/

## Version

Bump `version` in `pyproject.toml` before every upload. PyPI rejects a
version that already exists. Current package version is set there; `uv.lock`
should match the local package version.

## Build

From the repository root, on a clean tree of the commit you want to ship
(usually `main` after merging `develop`):

```powershell
Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
uv build
Get-ChildItem dist
```

Confirm you have both (version from `pyproject.toml`):

* `openblockperf-<version>.tar.gz`
* `openblockperf-<version>-py3-none-any.whl`

If the wheel name contains `win_amd64` or another platform tag, stop. That
would mean a native build leaked in. This project should always be `py3-none-any`.

Optional check that the PyPI page text is the dedicated release file:

```powershell
uv run python -c "import zipfile, pathlib; z=zipfile.ZipFile(list(pathlib.Path('dist').glob('*.whl'))[0]); print([n for n in z.namelist() if n.endswith('METADATA')][0])"
```

The wheel METADATA should contain the contents of `pypi-release.md`.

## Publish to TestPyPI (optional but recommended)

PowerShell:

```powershell
$env:UV_PUBLISH_USERNAME = "__token__"
$env:UV_PUBLISH_PASSWORD = "pypi-..."   # TestPyPI token
uv publish --index testpypi
```

`pyproject.toml` already defines the `testpypi` index.

## Publish to live PyPI

Use the live PyPI token, not the TestPyPI one:

```powershell
$env:UV_PUBLISH_USERNAME = "__token__"
$env:UV_PUBLISH_PASSWORD = "pypi-..."   # live PyPI token
uv publish
```

Default `uv publish` uploads to https://pypi.org/. Check
https://pypi.org/project/openblockperf/ after a short delay.

Then tag and make a GitHub Release for the same version, and upgrade a test
relay with `sudo ./blockperf-install.sh --update`.
