# Loader FinZuu — image de production.
#
# Cible : le serveur 152.53.118.110 (Ubuntu 24.04 ARM64). Base sur l'image
# officielle Python de Docker Hub (multi-arch, tiree anonymement) — PAS sur
# ghcr.io : le Docker du serveur porte des identifiants ghcr perimes (images
# privees d'un autre projet) qui cassent meme les tirages publics ghcr
# (mesure du 14/08 : `failed to fetch oauth token: denied`). `uv` s'installe
# depuis PyPI. La construction est NATIVE sur le serveur (decision C-0).
#
# Le classeur `docs/reference/` est DANS l'image : les chemins du code sont
# relatifs et le referentiel enrichi est la richesse anti-corruption du
# Loader — sans lui, aucun run.
FROM python:3.12-slim-bookworm

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app

# uv depuis PyPI (pas de ghcr). Couche cachee tant que la version ne bouge pas.
RUN pip install --no-cache-dir uv

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

# La sonde du conteneur EST /health — la meme que le dashboard E1. Pur Python
# (pas de curl a installer dans l'image slim).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
