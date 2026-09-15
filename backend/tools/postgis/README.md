# Live PostGIS contract test

The default backend suite remains service-free. This harness supplies a disposable, real
PostgreSQL/PostGIS engine (compiled to WebAssembly), exposes it over PostgreSQL's wire protocol,
and runs `PostgisGeo.workers_within` through the application's SQLAlchemy + asyncpg path.

```bash
cd karma/backend/tools/postgis
npm ci
npm test
```

The test exercises the geography casts, `ST_DWithin`, `ST_Distance`, three-decimal distances,
proof counts, result keys, and every worker eligibility filter. The dependency versions are
locked so the check is repeatable.

To use a native PostgreSQL server instead, install PostGIS in the target database and run:

```bash
cd karma/backend
KARMA_POSTGIS_TEST_URL='postgresql+asyncpg://user:password@host/database' \
  pytest tests/test_postgis_integration.py -q -s
```

The test creates and drops a uniquely named schema; it does not touch application tables.
