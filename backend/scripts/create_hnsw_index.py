"""HNSW VEKTÖR İNDEKSİ — kontrollü bakım işi (2026-11-09)

NEDEN AYRI BETİK (migration değil)
----------------------------------
`migrations/001_pgvector_schema.sql:195-203` HNSW index'ini **bilinçli olarak
yorum satırında** bırakıyor:

    -- HNSW index is intentionally created after the first embedding model is
    -- configured. Creating it during the base migration can block on an existing
    -- PostgreSQL relation and is unnecessary while the table has no embeddings.
    -- ...
    -- CREATE INDEX CONCURRENTLY IF NOT EXISTS memory_embeddings_hnsw_idx
    --   ON memory_embeddings USING hnsw (embedding halfvec_cosine_ops);

İki teknik neden bunu destekliyor:
1. `CREATE INDEX CONCURRENTLY` **transaction içinde çalışamaz**; migration
   koşucusu (bkz. `scripts/run_postgres_migration.py`) şemayı tek idempotent
   transaction'da uygular → oraya konursa migration patlar.
2. Index boş tabloda gereksizdir; embedding backfill'inden SONRA kurulur.

Bu betik o bakım işini yapar: önce durumu ölçer, sonra `CONCURRENTLY` ile
kurar (canlı yazmayı bloklamaz) ve sonucu doğrular.

KULLANIM
--------
    python scripts/create_hnsw_index.py              # ölç, gerekirse kur
    ... --dry-run                                    # yalnız ölç
    ... --m 16 --ef-construction 64                  # HNSW parametreleri
    ... --drop                                       # index'i kaldır

NEDEN ÖNEMLİ: `memory_service` araması `1-(embedding <=> $1::halfvec)` ile
sıralıyor. Index yoksa bu **tam tarama** (sequential scan) demektir — embedding
sayısı büyüdükçe LLM bağlam kurma gecikmesi doğrusal büyür.
"""
from __future__ import annotations

import argparse
import asyncio
import os

INDEX_NAME = "memory_embeddings_hnsw_idx"
TABLE = "memory_embeddings"


async def _connect():
    import asyncpg

    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL gerekli (backend/.env veya ortam değişkeni).")
    return await asyncpg.connect(url)


async def inspect(conn) -> dict:
    ext = await conn.fetchval("SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'")
    table = await conn.fetchval("SELECT to_regclass($1)::text", f"public.{TABLE}")
    rows = await conn.fetchval(f"SELECT COUNT(*) FROM {TABLE}") if table else 0
    idx = await conn.fetchrow(
        """SELECT indexname, indexdef FROM pg_indexes
            WHERE tablename = $1 AND indexname = $2""", TABLE, INDEX_NAME)
    size = None
    if table:
        size = await conn.fetchval(f"SELECT pg_size_pretty(pg_total_relation_size('{TABLE}'))")
    return {
        "vector_extension": bool(ext),
        "table_exists": bool(table),
        "rows": int(rows or 0),
        "index_exists": bool(idx),
        "index_def": (idx or {}).get("indexdef"),
        "table_size": size,
    }


async def create_index(conn, m: int, ef_construction: int) -> None:
    # CONCURRENTLY: canlı yazmayı bloklamaz. Bu ifade TRANSACTION DIŞINDA
    # koşmalıdır; asyncpg varsayılan olarak autocommit modundadır.
    sql = (
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
        f"ON {TABLE} USING hnsw (embedding halfvec_cosine_ops) "
        f"WITH (m = {int(m)}, ef_construction = {int(ef_construction)})"
    )
    await conn.execute(sql)


async def drop_index(conn) -> None:
    await conn.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX_NAME}")


async def main_async(args) -> int:
    conn = await _connect()
    try:
        info = await inspect(conn)
        print("=" * 74)
        print("VEKTÖR ARAMA İNDEKSİ DURUMU")
        print("=" * 74)
        print(f"pgvector eklentisi : {'VAR' if info['vector_extension'] else 'YOK'}")
        print(f"{TABLE} tablosu  : {'VAR' if info['table_exists'] else 'YOK'} "
              f"({info['rows']} satır, {info['table_size']})")
        print(f"HNSW index         : {'VAR' if info['index_exists'] else 'YOK'}")
        if info["index_def"]:
            print(f"  tanım: {info['index_def']}")
        print()

        if not info["vector_extension"]:
            print("HATA: pgvector eklentisi yok — önce migration'ı koşun "
                  "(scripts/run_postgres_migration.py).")
            return 1
        if not info["table_exists"]:
            print("HATA: memory_embeddings tablosu yok — migration gerekli.")
            return 1

        if args.drop:
            if not info["index_exists"]:
                print("Index zaten yok.")
                return 0
            if args.dry_run:
                print("[dry-run] DROP INDEX CONCURRENTLY atlanacaktı.")
                return 0
            await drop_index(conn)
            print("Index kaldırıldı.")
            return 0

        if info["index_exists"]:
            print("Yapılacak iş yok: index zaten kurulu.")
            return 0

        if info["rows"] == 0:
            print("UYARI: tabloda hiç embedding yok. Boş tabloya index kurmak")
            print("       gereksizdir; embedding backfill'inden sonra tekrar koşun.")
            if not args.force:
                return 0

        if args.dry_run:
            print(f"[dry-run] CREATE INDEX CONCURRENTLY {INDEX_NAME} "
                  f"(m={args.m}, ef_construction={args.ef_construction}) atlanacaktı.")
            return 0

        print(f"Index kuruluyor (CONCURRENTLY, m={args.m}, ef_construction={args.ef_construction})…")
        await create_index(conn, args.m, args.ef_construction)
        after = await inspect(conn)
        if after["index_exists"]:
            print("KURULDU ✓")
            print(f"  tanım: {after['index_def']}")
            print()
            print("Not: HNSW index'i oluştururken/sorgularken `hnsw.ef_search`")
            print("     oturum parametresi geri çağırma/hız dengesini belirler.")
            return 0
        print("KURULAMADI ✗ — pg_indexes'te görünmüyor.")
        return 1
    finally:
        await conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="memory_embeddings HNSW index bakımı")
    ap.add_argument("--dry-run", action="store_true", help="yalnız ölç, DDL çalıştırma")
    ap.add_argument("--drop", action="store_true", help="index'i kaldır")
    ap.add_argument("--force", action="store_true", help="boş tabloda da kur")
    ap.add_argument("--m", type=int, default=16, help="HNSW komşu sayısı (varsayılan 16)")
    ap.add_argument("--ef-construction", type=int, default=64, help="HNSW inşa derinliği (64)")
    args = ap.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
