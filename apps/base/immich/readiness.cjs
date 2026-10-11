const { createRequire } = require("node:module");

// Use the clients bundled with the pinned server image.
const serverRequire = createRequire("/usr/src/app/server/package.json");
const { Client } = serverRequire("pg");
const Redis = serverRequire("ioredis");

const database = new Client({
  connectionTimeoutMillis: 2000,
  database: process.env.DB_DATABASE_NAME,
  host: process.env.DB_HOSTNAME,
  password: process.env.DB_PASSWORD,
  port: Number(process.env.DB_PORT),
  query_timeout: 2000,
  // Match DB_SSL_MODE=require for CloudNativePG's self-signed certificate.
  ssl: { rejectUnauthorized: false },
  user: process.env.DB_USERNAME,
});
const redis = new Redis({
  commandTimeout: 2000,
  connectTimeout: 2000,
  host: process.env.REDIS_HOSTNAME,
  lazyConnect: true,
  maxRetriesPerRequest: 0,
  retryStrategy: () => null,
});
database.on("error", () => {});
redis.on("error", () => {});

async function check() {
  try {
    await Promise.all([
      fetch("http://127.0.0.1:2283/api/server/ping", {
        signal: AbortSignal.timeout(2000),
      }).then((response) => {
        if (!response.ok) throw new Error("Server unavailable");
      }),
      database.connect().then(() => database.query("SELECT 1")),
      redis.connect().then(() => redis.ping()),
    ]);
  } catch {
    process.exitCode = 1;
  } finally {
    redis.disconnect();
    await database.end();
  }
}

// Probe processes must exit without waiting for HTTP keep-alive timers.
void check().then(
  () => process.exit(process.exitCode || 0),
  () => process.exit(1),
);
