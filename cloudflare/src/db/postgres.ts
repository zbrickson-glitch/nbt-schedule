import pg from "pg";

export interface Env {
  ASSETS: Fetcher;
  HYPERDRIVE: { connectionString: string };
  CORS_ALLOW_ORIGIN: string;
  NBT_SCHEMA: string;
  SEASON_ASSET_PATH: string;
  SITE_ORIGIN: string;
  DISCORD_WEBHOOK_URL?: string;
}

const { Client } = pg;

export async function withClient<T>(env: Env, fn: (client: pg.Client) => Promise<T>): Promise<T> {
  const client = new Client({
    connectionString: env.HYPERDRIVE.connectionString,
  });

  await client.connect();
  try {
    if (env.NBT_SCHEMA) {
      await client.query(`SET search_path TO ${quoteIdentifier(env.NBT_SCHEMA)}`);
    }
    return await fn(client);
  } finally {
    await client.end();
  }
}

function quoteIdentifier(identifier: string): string {
  return `"${identifier.replaceAll('"', '""')}"`;
}
