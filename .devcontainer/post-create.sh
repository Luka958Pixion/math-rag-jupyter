#!/bin/sh
set -e

poetry install --no-root --with dev
poetry run pre-commit install