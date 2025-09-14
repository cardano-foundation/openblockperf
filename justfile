
# Credentials come from env variables
#   UV_PUBLISH_USERNAME="__token__"
#   UV_PUBLISH_PASSWORD="xxx"
#
build:
    rm -rf dist/*
    uv build

publish:
    uv publish

# That other index is defined in pyproject.toml
pubtesting:
    uv publish --index testpypi

