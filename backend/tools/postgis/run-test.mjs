import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { PGlite } from '@electric-sql/pglite';
import { postgis } from '@electric-sql/pglite-postgis';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';

const toolDirectory = dirname(fileURLToPath(import.meta.url));
const backendDirectory = resolve(toolDirectory, '../..');
const repositoryVenvPython = resolve(toolDirectory, '../../../../.venv/bin/python');
const python = process.env.PYTHON
  ?? (existsSync(repositoryVenvPython) ? repositoryVenvPython : 'python3');

const db = new PGlite({ extensions: { postgis } });
let server;
let exitCode = 1;
try {
  await db.exec('CREATE EXTENSION IF NOT EXISTS postgis;');
  const version = await db.query(`
    SELECT current_setting('server_version') AS postgres,
           postgis_lib_version() AS postgis
  `);

  server = new PGLiteSocketServer({
    db,
    host: '127.0.0.1',
    maxConnections: 4,
    port: 0,
  });
  await server.start();
  const port = Number(server.getServerConn().split(':').at(-1));
  if (!Number.isInteger(port) || port <= 0) {
    throw new Error(`Could not determine PGlite socket port: ${server.getServerConn()}`);
  }

  const runtime = version.rows[0];
  console.log(`Starting live contract test on PostgreSQL ${runtime.postgres} / PostGIS ${runtime.postgis}`);
  exitCode = await new Promise((resolveExit, reject) => {
    const child = spawn(
      python,
      ['-m', 'pytest', 'tests/test_postgis_integration.py', '-q', '-s'],
      {
        cwd: backendDirectory,
        env: {
          ...process.env,
          KARMA_POSTGIS_PGLITE: '1',
          KARMA_POSTGIS_TEST_URL:
            `postgresql+asyncpg://postgres:postgres@127.0.0.1:${port}/postgres`,
        },
        stdio: 'inherit',
      },
    );
    child.once('error', reject);
    child.once('exit', (code, signal) => {
      if (signal) {
        console.error(`PostGIS test process ended from signal ${signal}`);
      }
      resolveExit(code ?? 1);
    });
  });
} finally {
  if (server) {
    await server.stop();
  }
  await db.close();
}

process.exitCode = exitCode;
