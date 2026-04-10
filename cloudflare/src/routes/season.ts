import type { Env } from "../db/postgres";
import type { SeasonData } from "../db/queries";
import { json } from "../lib/http";

const EMPTY_SEASON: SeasonData = {
  season: "",
  weeks: [],
};

export async function handleSeason(_request: Request, env: Env): Promise<Response> {
  const assetUrl = new URL(env.SEASON_ASSET_PATH || "/data/season.json", "https://assets.local");
  const response = await env.ASSETS.fetch(assetUrl.toString());
  if (!response.ok) {
    return json(EMPTY_SEASON);
  }

  try {
    const body = (await response.json()) as SeasonData;
    return json(body);
  } catch {
    return json(EMPTY_SEASON);
  }
}
