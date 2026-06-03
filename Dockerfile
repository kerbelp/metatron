# Use a slim Python 3.12 image
FROM python:3.12-slim

# Install git (required by Metatron to parse git history)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Unbuffered stdio so the MCP server (stdio transport) streams cleanly
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Copy the project files
COPY . .

# Install the package locally
RUN pip install --no-cache-dir .

# Entrypoint is the CLI; default command serves the MCP server over stdio (what
# Glama / an MCP client launches). Override the command to run other subcommands,
# e.g. `docker run --rm -v ...:/data getmetatron ingest /repo`.
ENTRYPOINT ["metatron"]
CMD ["serve"]
