# Monitor Quote Calcio Pre-Match 1X2

Dashboard professionale per monitorare solo quote pre-match 1/X/2, confrontare la prima quota rilevata con la quota attuale e mostrare la Top 20 delle maggiori diminuzioni percentuali.

## Cosa fa

- Monitora solo mercati 1/X/2 (`h2h`)
- Esclude il live/in-play tramite finestra pre-match configurabile
- Salva la prima quota rilevata come quota uscita
- Aggiorna i dati ogni ora con GitHub Actions
- Mostra dashboard Streamlit accessibile da iPhone
- Permette filtri per area, campionato/coppa, bookmaker, esito e percentuale minima di discesa

## File importanti

- `streamlit_app.py` — dashboard
- `collector.py` — raccolta quote
- `leagues_config.json` — campionati, coppe, filtri e impostazioni
- `.github/workflows/update_odds.yml` — aggiornamento automatico ogni ora
- `data/` — storico quote e ranking

## Variabile segreta richiesta

Nel repository GitHub inserire:

`ODDS_API_KEY = la_tua_chiave_api`

## Pubblicazione

1. Caricare questi file in un repository GitHub.
2. Aggiungere `ODDS_API_KEY` nei repository secrets.
3. Collegare il repository a Streamlit Community Cloud.
4. Impostare file principale: `streamlit_app.py`.
5. Aprire il link da Safari su iPhone e fare “Aggiungi a schermata Home”.

## Nota su quote di apertura

La quota uscita è la prima quota rilevata dal sistema. Per opening odds ufficiali serve un feed premium che fornisca storico e opening odds certificati.
