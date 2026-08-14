# Loader FinZuu — image de production.
#
# Cible : le serveur 152.53.118.110 (Ubuntu 24.04 ARM64) — l'image uv
# officielle est multi-arch, la construction se fait NATIVEMENT sur le
# serveur (pas de cross-build depuis la machine de dev, decision C-0 :
# heberger avant de charger).
#
# Le classeur `docs/reference/` est DANS l'image : les chemins du code sont
# relatifs (`docs/reference/Loader_Base_FinZuu_v1_1.xlsx`) et le referentiel
# enrichi est la richesse anti-corruption du Loader — sans lui, aucun run.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

# Les dependances d'abord — couche cachee tant que le lock ne change pas.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY scripts ./scripts
COPY docs/reference ./docs/reference

# Jamais root a l'execution — l'application n'ecrit rien sur le disque,
# sa memoire est MongoDB.
RUN useradd --create-home loader && chown -R loader:loader /app
USER loader

EXPOSE 8000

# La sonde du conteneur EST /health — la meme que le dashboard E1.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
