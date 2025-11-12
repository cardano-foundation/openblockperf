# Publishing to PyPI

A few notes on  how to publish to PyPI. With uv this actually is
suprisingly simple. You need to have an account on pypi. Besides the
live one there is a testing one, so if you want to develop/publish stuff
you might want to create accounts in both.

* https://pypi.org/
* https://test.pypi.org/

Once logged in, go to your settings and create long lived api tokens.

## Build and publish

To publish something you need to build it first. `uv build` will
do that. Then you can publish using `ub publish`. you need provide that api
token from above. You can do that in different ways. See https://docs.astral.sh/uv/guides/package/

I use env variables:

```bash
UV_PUBLISH_USERNAME="__token__"
UV_PUBLISH_PASSWORD="YOUR API TOKEN"
```

Now you can

```bash
uv build # Builds artefacts in dist/
uv publish # publisheds to an index
```

By default `uv publish` will upload to the main index. Which is probably
not what you want. The pyproject.toml file has the test pypi configured
such that you can easily specify that in the publish command like this
`uv publish --index testpypi`. Remember to provide the correct tokens
for the used index.

## Versions

The pyproject.toml file has a version string which specifies the applications
version. This is required by pypi. It is by design that you can not publish
the same version twice. Meaning if you change something and want that to
get published you must change the version. For that same reason pypi does
not accept dynamic versions as setuptools-scm would produce. So every
change will require to set a new version in pyproject.toml, build that and
publish that new version.
