# Checklist Van Campen & Dijkstra

Alles wat per klant verschilt staat in `client.config.json`. Vul de velden met `TODO` of een lege waarde in
(`python3 tools/new_client.py check` laat zien welke nog open staan) en draai daarna
`python3 tools/new_client.py sync-config`.

## 1. GitHub
- [ ] Maak een **eigen** repo (liefst onder een eigen organisatie, niet onder die van een andere klant): `OWNER/REPO`
- [ ] Push deze map naar `main` en zet GitHub Pages aan (Settings > Pages > Deploy from branch > main, / root)
- [ ] Zet de URL van de site in `pagesUrl` (nu ``)

## 2. Inloggen (Supabase), een **eigen project per klant**
- [ ] Maak een nieuw Supabase-project. Deel het NIET met een andere klant: iedereen met een account in een project kan het bijbehorende dashboard openen.
- [ ] Zet `supabase.url` en `supabase.anonKey` (de publishable key) in de config
- [ ] Authentication > URL Configuration: Site URL en Redirect URL = de `pagesUrl`
- [ ] Authentication > Email Templates: pas de teksten en het logo aan naar Van Campen & Dijkstra
- [ ] Zet "Allow new users to sign up" uit en nodig gebruikers uit, anders kan iedereen met een e-mailadres een account maken

## 3. Secrets (GitHub > Settings > Secrets and variables > Actions)
- [ ] `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_ORG_ID` (Zoho Desk van deze klant; regio in `zoho.regio`, nu `eu`)
- [ ] `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` (Server-to-Server OAuth-app; scopes `phone:read:list_call_logs:admin` en `phone:read:call_log:admin`)
- [ ] `GRANOLA_API_KEY` en `ANTHROPIC_API_KEY`
- [ ] Zet `zoom.queueDid` en `zoom.queueExt` (de wachtrij van deze klant) en `granolaMap` (de Granola-map met de gesprekken)

## 4. Inhoud
- [ ] `team`: naam en e-mailadres van de medewerkers (het lokale deel van het adres wordt gebruikt om Zoom-gebruikers te herkennen)
- [ ] `managementEmails`, `avatars` en eventueel `aliassen` (bijnamen of veelvoorkomende verhoorde namen)
- [ ] `doorverwijzing.naam`: hoe heet de partij waar naar wordt doorverwezen? (nu `rechtsbijstand`)
- [ ] `prompt.bedrijfsregels`: de regels van deze klant voor de AI-analyse (dekking, franchise, verplichte doorverwijzingen). Zonder die regels beoordeelt de AI alleen op algemene kwaliteit.

## 5. Elke 10 minuten laten draaien (cron-job.org)
GitHub's eigen `schedule` is onbetrouwbaar. Maak op cron-job.org een job:
- URL: `https://api.github.com/repos/OWNER/REPO/actions/workflows/update-dagrapport.yml/dispatches`
- Methode POST, headers `Authorization: Bearer <fine-grained token, alleen deze repo, Actions: write>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`
- Body `{"ref": "main"}`, schema `*/10 7-18 * * 1-5` (Europe/Amsterdam)

## 6. Historie ophalen (optioneel)
- [ ] Actions > "Backfill Zoom-historie (per medewerker)" > Run workflow, met de startdatum waarvanaf je de Zoom-historie wilt

## Bijwerken met nieuwe functies
Vanuit de template-repo: `python3 tools/new_client.py update <pad naar deze map>`. Config, logo en data blijven staan.
