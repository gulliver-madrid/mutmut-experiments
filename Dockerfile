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

# Alias to type checking
RUN echo 'alias tc="echo Checking types && poetry run mypy"' >> ~/.bashrc
# Alias to run tests
RUN echo 'alias test="echo Running tests && poetry run pytest"' >> ~/.bashrc
# Alias to type checking + tests
RUN echo 'alias check="tc --strict && test"' >> ~/.bashrc
# Alias to install vim
RUN echo 'alias ivim="apt-get update && apt-get install -y vim"' >> ~/.bashrc

# Add the current path to PYTHONPATH
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Copy the rest of the source code to the container
COPY . .


COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
