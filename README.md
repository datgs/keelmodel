# KeelModel

KeelModel is a strict, synchronous Python data SDK for business applications. It targets PostgreSQL first and uses SQLAlchemy beneath its public contracts.

The project also contains `keelpolicy`, a separate Python package for policy logic. Applications own model and policy YAML files, provide trusted subject/context, and explicitly register modules.

## Development

Requires Python 3.12+ and uv.

```sh
uv sync --dev
uv run pytest
uv run ruff check .
```

Core decisions and implementation planning are recorded under `history/` until they are promoted to stable product documentation.
