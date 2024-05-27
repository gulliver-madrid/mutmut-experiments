#!/bin/bash

echo "Checking types"
poetry run mypy --strict

echo "Running tests"
poetry run pytest

# Iniciar Bash
exec "/bin/bash"
