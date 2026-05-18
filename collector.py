import os
import json
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)

CONFIG_PATH = BASE / "leagues_config.json"
SNAPSHOTS_PATH = DATA / "odds_snapshots.csv"
BASELINE_PATH = DATA / "opening_odds.csv"
RANKING_PATH = DATA / "current_top20_decreases.csv"
RUNLOG_PATH = DATA / "last_run.json"

API_BASE = "https://api.the-odds-api.com/v4"

def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def get_api_key():
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Manca ODDS_API_KEY nei secrets/variabili ambiente.")
    return key

def get_available_sports(api_key):
    r = requests.get(f"{API_BASE}/sports", params={"apiKey": api_key, "all": "false"}, timeout=40)
    r.raise_for_status()
    return {item["key"]: item for item in r.json() if item.get("group", "").lower() == "soccer"}

def flatten_event(event, league_name, area, fetched_at):
    rows = []
    commence_time = event.get("commence_time")
    home = event.get("home_team")
    away = event.get("away_team")
    event_name = f"{home} - {away}"
    for bookmaker in event.get("bookmakers", []):
        bookmaker_key = bookmaker.get("key")
        bookmaker_title = bookmaker.get("title")
        bookmaker_last_update = bookmaker.get("last_update")
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                name = outcome.get("name")
                # Soccer h2h includes home/draw/away. Normalize to 1/X/2.
                if name == home:
                    sign = "1"
                elif name == away:
                    sign = "2"
                elif str(name).lower() in ["draw", "tie"]:
                    sign = "X"
                else:
                    sign = name
                rows.append({
                    "fetched_at": fetched_at,
                    "event_id": event.get("id"),
                    "sport_key": event.get("sport_key"),
                    "league": league_name,
                    "area": area,
                    "commence_time": commence_time,
                    "home_team": home,
                    "away_team": away,
                    "event": event_name,
                    "bookmaker_key": bookmaker_key,
                    "bookmaker": bookmaker_title,
                    "bookmaker_last_update": bookmaker_last_update,
                    "market": "1X2",
                    "selection": sign,
                    "outcome_name": name,
                    "price": float(outcome.get("price")) if outcome.get("price") is not None else None
                })
    return rows

def fetch_league_odds(api_key, sport_key, league_name, area, cfg):
    now = datetime.now(timezone.utc)
    from_time = now + timedelta(minutes=int(cfg.get("min_minutes_before_kickoff", 10)))
    to_time = now + timedelta(days=int(cfg.get("days_ahead", 14)))

    params = {
        "apiKey": api_key,
        "regions": ",".join(cfg.get("regions", ["eu", "uk"])),
        "markets": "h2h",
        "oddsFormat": cfg.get("odds_format", "decimal"),
        "dateFormat": "iso",
        "commenceTimeFrom": from_time.isoformat().replace("+00:00", "Z"),
        "commenceTimeTo": to_time.isoformat().replace("+00:00", "Z"),
    }
    r = requests.get(f"{API_BASE}/sports/{sport_key}/odds", params=params, timeout=60)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for event in r.json():
        rows.extend(flatten_event(event, league_name, area, fetched_at))
    time.sleep(0.25)
    return rows

def read_csv(path):
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path)
    return pd.DataFrame()

def save_csv(df, path):
    df.to_csv(path, index=False)

def update_baseline(current_df):
    key_cols = ["event_id", "bookmaker_key", "selection"]
    baseline = read_csv(BASELINE_PATH)
    if baseline.empty:
        baseline = current_df.copy()
        baseline = baseline.rename(columns={"price": "opening_price", "fetched_at": "opening_seen_at"})
        keep = key_cols + ["sport_key", "league", "area", "commence_time", "event", "bookmaker", "outcome_name", "opening_price", "opening_seen_at"]
        save_csv(baseline[keep], BASELINE_PATH)
        return baseline[keep]

    existing_keys = set(map(tuple, baseline[key_cols].astype(str).values.tolist()))
    new = current_df[~current_df[key_cols].astype(str).apply(tuple, axis=1).isin(existing_keys)].copy()
    if not new.empty:
        new = new.rename(columns={"price": "opening_price", "fetched_at": "opening_seen_at"})
        keep = key_cols + ["sport_key", "league", "area", "commence_time", "event", "bookmaker", "outcome_name", "opening_price", "opening_seen_at"]
        baseline = pd.concat([baseline, new[keep]], ignore_index=True)
        save_csv(baseline, BASELINE_PATH)
    return baseline

def build_ranking(current_df, baseline):
    key_cols = ["event_id", "bookmaker_key", "selection"]
    merged = current_df.merge(
        baseline[key_cols + ["opening_price", "opening_seen_at"]],
        on=key_cols,
        how="left"
    )
    merged["current_price"] = merged["price"]
    merged["decrease_pct"] = ((merged["current_price"] - merged["opening_price"]) / merged["opening_price"]) * 100
    merged = merged.dropna(subset=["opening_price", "current_price", "decrease_pct"])
    decreases = merged[merged["decrease_pct"] < 0].copy()
    decreases = decreases.sort_values("decrease_pct", ascending=True)
    cols = [
        "league", "area", "commence_time", "event", "bookmaker",
        "selection", "opening_price", "current_price", "decrease_pct",
        "opening_seen_at", "fetched_at", "event_id", "bookmaker_key"
    ]
    ranking = decreases[cols].head(20)
    save_csv(ranking, RANKING_PATH)
    return ranking

def main():
    cfg = load_config()
    api_key = get_api_key()
    available = get_available_sports(api_key)

    enabled = [x for x in cfg["leagues"] if x.get("enabled", True)]
    rows = []
    skipped = []
    for league in enabled:
        key = league["key"]
        if key not in available:
            skipped.append({"key": key, "name": league["name"], "reason": "non disponibile dal provider in questo momento"})
            continue
        try:
            rows.extend(fetch_league_odds(api_key, key, league["name"], league["area"], cfg))
        except Exception as e:
            skipped.append({"key": key, "name": league["name"], "reason": str(e)})

    current = pd.DataFrame(rows)
    if current.empty:
        RUNLOG_PATH.write_text(json.dumps({
            "last_run": datetime.now(timezone.utc).isoformat(),
            "status": "no_data",
            "skipped": skipped
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        return

    history = read_csv(SNAPSHOTS_PATH)
    history = pd.concat([history, current], ignore_index=True)
    save_csv(history, SNAPSHOTS_PATH)

    baseline = update_baseline(current)
    ranking = build_ranking(current, baseline)

    RUNLOG_PATH.write_text(json.dumps({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "rows_current": len(current),
        "ranking_rows": len(ranking),
        "skipped": skipped
    }, indent=2, ensure_ascii=False), encoding="utf-8")

if __name__ == "__main__":
    main()
