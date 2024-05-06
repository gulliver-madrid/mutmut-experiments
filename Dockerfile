# Use a base image of python 3.10
FROM python:3.10

# Set the working directory in the container
WORKDIR /app

# Copy the pyproject.toml file and poetry.lock (if exists) to the container
COPY pyproject.toml .

# Install Poetry
RUN pip install poetry

# Install dependencies
RUN poetry install --no-interaction --no-ansi

# Copy the rest of the source code to the container
COPY . .

# Add the current path to PYTHONPATH
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Install the Vim text editor
RUN apt-get update && apt-get install -y vim

CMD echo "Checking types" && poetry run mypy && echo "Running tests" && poetry run pytest -x; /bin/bash
