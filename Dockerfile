# Multi-stage: as dependencias sao instaladas num estagio descartavel e so o
# necessario vai para a imagem final, que roda com usuario sem privilegio.
FROM python:3.12-slim AS dependencias
WORKDIR /instalacao
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/opt/deps -r requirements.txt

FROM python:3.12-slim
# A imagem so existe para rodar em container, entao o default dela precisa
# ser o de container. Sem isso, um docker run sem env cai nos defaults de
# host e tenta localhost:3305 - que dentro do container e ele mesmo.
ENV ENVIRONMENT=docker \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/opt/deps/lib/python3.12/site-packages \
    PATH=/opt/deps/bin:$PATH \
    CVM_CACHE_DIR=/var/cache/cvm

COPY --from=dependencias /opt/deps /opt/deps

WORKDIR /app
COPY main.py ./
COPY app ./app

RUN useradd --create-home --uid 10001 etl \
    && mkdir -p /var/cache/cvm \
    && chown -R etl:etl /var/cache/cvm /app
USER etl

# Job em lote: roda, reporta e encerra.
ENTRYPOINT ["python", "main.py"]
