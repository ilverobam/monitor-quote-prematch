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

def log(msg):
    print(msg, flush=True)

def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def get_api_key():
    key = os.getenv("ODDS_API_KEY")
    if not key:
        raise RuntimeError("Manca ODDS_API_KEY nei secrets/variabili ambiente.")
    return key

def read_csv(path):
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path)
    return pd.DataFrame()

def save_csv(df, path):
    df.to_csv(path, index=False)

def get_available_sports(api_key):
    log("1) Controllo gli sport disponibili su The Odds API...")
    r = requests.get(f"{API_BASE}/sports", params={"apiKey": api_key, "all": "false"}, timeout=40)
    log(f"   Risposta sports API: {r.status_code}")
    r.raise_for_status()
    data = r.json()
    soccer = {item["key"]: item for item in data if item.get("group", "").lower() == "soccer"}
    log(f"   Sport totali ricevuti: {len(data)}")
    log(f"   Competizioni calcio disponibili: {len(soccer)}")
    log(f"   Prime competizioni disponibili: {list(soccer.keys())[:15]}")
    return soccer

def normalize_selection(outcome_name, home, away):
    if outcome_name == home:
        return "1"
    if outcome_name == away:
        return "2"
    if str(outcome_name).lower() in ["draw", "tie"]:
        return "X"
    return outcome_name

def flatten_event(event, league_name, area, fetched_at):
    rows = []
    home = event.get("home_team")
    away = event.get("away_team")
    event_name = f"{home} - {away}"
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                price = outcome.get("price")
                if price is None:
                    continue
                rows.append({
                    "fetched_at": fetched_at,
                    "event_id": event.get("id"),
                    "sport_key": event.get("sport_key"),
                    "league": league_name,
                    "area": area,
                    "commence_time": event.get("commence_time"),
                    "home_team": home,
                    "away_team": away,
                    "event": event_name,
                    "bookmaker_key": bookmaker.get("key"),
                    "bookmaker": bookmaker.get("title"),
                    "bookmaker_last_update": bookmaker.get("last_update"),
                    "market": "1X2",
                    "selection": normalize_selection(outcome.get("name"), home, away),
                    "outcome_name": outcome.get("name"),
                    "price": float(price),
                })
    return rows

def fetch_league_odds(api_key, sport_key, league_name, area, cfg):
    now = datetime.now(timezone.utc)
    from_time = now + timedelta(minutes=int(cfg.get("min_minutes_before_kickoff", 10)))
    to_time = now + timedelta(days=int(cfg.get("days_ahead", 14)))

    params = {
        "apiKey": api_key,
        "regions": ",".join(cfg.get("regions", ["eu", "uk", "us", "au"])),
        "markets": "h2h",
        "oddsFormat": cfg.get("odds_format", "decimal"),
        "dateFormat": "iso",
        "commenceTimeFrom": from_time.isoformat().replace("+00:00", "Z"),
        "commenceTimeTo": to_time.isoformat().replace("+00:00", "Z"),
    }

    log(f"2) Scarico quote: {league_name} ({sport_key})")
    r = requests.get(f"{API_BASE}/sports/{sport_key}/odds", params=params, timeout=60)
    log(f"   Status odds: {r.status_code}")
    if r.status_code == 404:
        log("   Non disponibile dal provider.")
        return []
    r.raise_for_status()

    data = r.json()
    log(f"   Eventi trovati: {len(data)}")
    fetched_at = datetime.now(timezone.utc).isoformat()

    rows = []
    for event in data:
        rows.extend(flatten_event(event, league_name, area, fetched_at))

    log(f"   Quote 1X2 estratte: {len(rows)}")
    time.sleep(0.25)
    return rows

def update_baseline(current_df):
    key_cols = ["event_id", "bookmaker_key", "selection"]
    baseline = read_csv(BASELINE_PATH)

    if baseline.empty:
        baseline = current_df.copy()
        baseline = baseline.rename(columns={"price": "opening_price", "fetched_at": "opening_seen_at"})
        keep = key_cols + ["sport_key", "league", "area", "commence_time", "event", "bookmaker", "outcome_name", "opening_price", "opening_seen_at"]
        save_csv(baseline[keep], BASELINE_PATH)
        log(f"3) Prima raccolta: salvate {len(baseline)} quote iniziali.")
        return baseline[keep]

    existing_keys = set(map(tuple, baseline[key_cols].astype(str).values.tolist()))
    new = current_df[~current_df[key_cols].astype(str).apply(tuple, axis=1).isin(existing_keys)].copy()

    if not new.empty:
        new = new.rename(columns={"price": "opening_price", "fetched_at": "opening_seen_at"})
        keep = key_cols + ["sport_key", "league", "area", "commence_time", "event", "bookmaker", "outcome_name", "opening_price", "opening_seen_at"]
        baseline = pd.concat([baseline, new[keep]], ignore_index=True)
        save_csv(baseline, BASELINE_PATH)
        log(f"3) Nuove quote iniziali aggiunte: {len(new)}")
    else:
        log("3) Nessuna nuova quota iniziale da aggiungere.")
    return baseline

def build_ranking(current_df, baseline):
    key_cols = ["event_id", "bookmaker_key", "selection"]
    merged = current_df.merge(
        baseline[key_cols + ["opening_price", "opening_seen_at"]],
        on=key_cols,
        how="left",
    )
    merged["current_price"] = merged["price"]
    merged["decrease_pct"] = ((merged["current_price"] - merged["opening_price"]) / merged["opening_price"]) * 100
    merged = merged.dropna(subset=["opening_price", "current_price", "decrease_pct"])
    decreases = merged[merged["decrease_pct"] < 0].copy()
    decreases = decreases.sort_values("decrease_pct", ascending=True)

    cols = ["league", "area", "commence_time", "event", "bookmaker", "selection", "opening_price", "current_price", "decrease_pct", "opening_seen_at", "fetched_at", "event_id", "bookmaker_key"]
    ranking = decreases[cols].head(20)
    save_csv(ranking, RANKING_PATH)
    log(f"4) Movimenti in diminuzione trovati: {len(decreases)}")
    log(f"5) Top 20 salvata: {len(ranking)} righe")
    return ranking

def main():
    log("========== AVVIO MONITOR QUOTE PRE-MATCH ==========")
    cfg = load_config()
    api_key = get_api_key()
    log("API key caricata correttamente.")

    available = get_available_sports(api_key)
    enabled = [x for x in cfg["leagues"] if x.get("enabled", True)]
    log(f"Campionati configurati e attivi: {len(enabled)}")

    rows = []
    skipped = []
    for league in enabled:
        key = league["key"]
        name = league["name"]
        area = league["area"]
        if key not in available:
            skipped.append({"key": key, "name": name, "reason": "non disponibile dal provider in questo momento"})
            log(f"   SKIP: {name} ({key}) non disponibile.")
            continue
        try:
            rows.extend(fetch_league_odds(api_key, key, name, area, cfg))
        except Exception as e:
            skipped.append({"key": key, "name": name, "reason": str(e)})
            log(f"   ERRORE su {name}: {e}")

    log(f"Totale quote raccolte: {len(rows)}")
    log(f"Competizioni saltate: {len(skipped)}")

    current = pd.DataFrame(rows)
    if current.empty:
        RUNLOG_PATH.write_text(json.dumps({
            "last_run": datetime.now(timezone.utc).isoformat(),
            "status": "no_data",
            "rows_current": 0,
            "ranking_rows": 0,
            "skipped": skipped,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        pd.DataFrame(columns=["league", "area", "commence_time", "event", "bookmaker", "selection", "opening_price", "current_price", "decrease_pct", "opening_seen_at", "fetched_at", "event_id", "bookmaker_key"]).to_csv(RANKING_PATH, index=False)

        log("NESSUN DATO RACCOLTO. Probabile limite/disponibilita API o campionati non disponibili.")
        log("========== FINE ==========")
        return

    history = read_csv(SNAPSHOTS_PATH)
    history = pd.concat([history, current], ignore_index=True)
    save_csv(history, SNAPSHOTS_PATH)
    log(f"Storico totale salvato: {len(history)} righe")

    baseline = update_baseline(current)
    ranking = build_ranking(current, baseline)

    RUNLOG_PATH.write_text(json.dumps({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
        "rows_current": len(current),
        "ranking_rows": len(ranking),
        "skipped": skipped,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    log("========== FINE MONITOR QUOTE PRE-MATCH ==========")

if __name__ == "__main__":
    main()
