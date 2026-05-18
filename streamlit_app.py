import json
from pathlib import Path
import pandas as pd
import streamlit as st
from datetime import datetime

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
RANKING_PATH = DATA / "current_top20_decreases.csv"
SNAPSHOTS_PATH = DATA / "odds_snapshots.csv"
RUNLOG_PATH = DATA / "last_run.json"
CONFIG_PATH = BASE / "leagues_config.json"

st.set_page_config(page_title="Monitor Quote Pre-Match", page_icon="⚽", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
.metric-card {
  background: #ffffff; border: 1px solid #e5e7eb; border-radius: 18px;
  padding: 16px 18px; box-shadow: 0 4px 14px rgba(0,0,0,.04);
}
.big-title {font-size: 34px; font-weight: 800; letter-spacing: -0.03em;}
.subtle {color: #6b7280;}
.badge {background:#eef2ff; color:#1e3a8a; border-radius:999px; padding: 4px 10px; font-weight:600;}
</style>
""", unsafe_allow_html=True)

def load_csv(path):
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path)
    return pd.DataFrame()

def fmt_pct(x):
    try:
        return f"{x:.2f}%"
    except Exception:
        return ""

def fmt_price(x):
    try:
        return f"{x:.2f}"
    except Exception:
        return ""

cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
ranking = load_csv(RANKING_PATH)
snapshots = load_csv(SNAPSHOTS_PATH)

col_title, col_badge = st.columns([0.78, 0.22])
with col_title:
    st.markdown('<div class="big-title">Monitor Quote Calcio Pre-Match 1X2</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtle">Classifica automatica delle 20 maggiori diminuzioni percentuali dalla prima quota rilevata alla quota attuale.</div>', unsafe_allow_html=True)
with col_badge:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<span class="badge">Solo quote pre-match</span>', unsafe_allow_html=True)

runlog = {}
if RUNLOG_PATH.exists():
    try:
        runlog = json.loads(RUNLOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        runlog = {}

last_run = runlog.get("last_run", "Non ancora disponibile")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Eventi/righe monitorate", f"{len(snapshots):,}".replace(",", "."))
c2.metric("Movimenti in classifica", len(ranking))
c3.metric("Aggiornamento", last_run[:16].replace("T", " "))
max_drop = ranking["decrease_pct"].min() if not ranking.empty and "decrease_pct" in ranking.columns else 0
c4.metric("Discesa massima", fmt_pct(max_drop))

st.divider()

if ranking.empty:
    st.warning("Non ci sono ancora dati sufficienti. Dopo il primo aggiornamento vengono fissate le quote iniziali; dai run successivi compariranno le variazioni.")
    if runlog.get("skipped"):
        with st.expander("Competizioni non disponibili dal provider in questo momento"):
            st.json(runlog.get("skipped"))
    st.stop()

ranking["commence_time"] = pd.to_datetime(ranking["commence_time"], errors="coerce")
ranking["decrease_pct"] = pd.to_numeric(ranking["decrease_pct"], errors="coerce")
ranking["opening_price"] = pd.to_numeric(ranking["opening_price"], errors="coerce")
ranking["current_price"] = pd.to_numeric(ranking["current_price"], errors="coerce")

with st.sidebar:
    st.header("Filtri")
    areas = sorted(ranking["area"].dropna().unique().tolist())
    leagues = sorted(ranking["league"].dropna().unique().tolist())
    books = sorted(ranking["bookmaker"].dropna().unique().tolist())
    selections = ["1", "X", "2"]

    selected_areas = st.multiselect("Area", areas, default=areas)
    selected_leagues = st.multiselect("Campionato/coppa", leagues, default=leagues)
    selected_books = st.multiselect("Bookmaker", books, default=books)
    selected_sel = st.multiselect("Esito", selections, default=selections)
    min_drop_abs = st.slider("Mostra solo diminuzioni almeno del", 0, 50, 0, 1)

filtered = ranking[
    ranking["area"].isin(selected_areas)
    & ranking["league"].isin(selected_leagues)
    & ranking["bookmaker"].isin(selected_books)
    & ranking["selection"].isin(selected_sel)
    & (ranking["decrease_pct"] <= -min_drop_abs)
].copy()
filtered = filtered.sort_values("decrease_pct", ascending=True).head(20)

display = filtered.copy()
display.insert(0, "Posizione", range(1, len(display) + 1))
display["Data evento"] = display["commence_time"].dt.strftime("%d/%m/%Y %H:%M")
display["Quota uscita"] = display["opening_price"].map(fmt_price)
display["Quota attuale"] = display["current_price"].map(fmt_price)
display["Variazione"] = display["decrease_pct"].map(fmt_pct)

cols = ["Posizione", "area", "league", "Data evento", "event", "bookmaker", "selection", "Quota uscita", "Quota attuale", "Variazione"]
display = display[cols].rename(columns={
    "area": "Area", "league": "Campionato", "event": "Partita", "bookmaker": "Bookmaker", "selection": "Esito"
})

st.subheader("Top 20 maggiori diminuzioni quota")
st.dataframe(
    display,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Variazione": st.column_config.TextColumn("Variazione %"),
        "Quota uscita": st.column_config.TextColumn("Quota uscita"),
        "Quota attuale": st.column_config.TextColumn("Quota attuale"),
    }
)

st.caption("Nota: la “quota uscita” è la prima quota rilevata dal sistema. Per quote di apertura ufficiali storiche serve un feed premium con opening odds.")
if runlog.get("skipped"):
    with st.expander("Competizioni configurate ma non disponibili dal provider/API in questo momento"):
        st.json(runlog.get("skipped"))
