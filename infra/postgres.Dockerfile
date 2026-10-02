# PostgreSQL 16 with pgvector for dev (ADR-058 item 5): the same alpine base as before, so the
# existing data volume and its collations are unchanged. pgvector is compiled without LLVM bitcode
# (with_llvm=no), so no compiler toolchain for JIT is needed.
FROM postgres:16-alpine
ARG PGVECTOR_VERSION=v0.8.0
RUN apk add --no-cache --virtual .pgvector-build git build-base \
    && git clone --depth 1 --branch "$PGVECTOR_VERSION" https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector with_llvm=no OPTFLAGS="" \
    && make -C /tmp/pgvector with_llvm=no install \
    && rm -rf /tmp/pgvector \
    && apk del .pgvector-build
