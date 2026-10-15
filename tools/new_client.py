#!/usr/bin/env python3
"""Maakt (en onderhoudt) een dagrapport-dashboard voor een nieuwe klant, op basis van dit template.

Alles wat per klant verschilt staat in client.config.json. De rest (index.html, scripts/,
workflows) is gedeelde code die identiek blijft.

Gebruik
  python3 tools/new_client.py create --config klant.json --out ../dagrapport-klant [--logo logo.svg]
      Nieuwe klantmap: code uit het template, lege data, config, logo, CHECKLIST.md en git-repo.
  python3 tools/new_client.py update ../dagrapport-klant
      Nieuwste code uit het template in een bestaande klantmap zetten. Config, logo, data en
      de weekData-historie van die klant blijven ongemoeid.
  python3 tools/new_client.py sync-config [MAP]
      Na het wijzigen van client.config.json: config en logo opnieuw in index.html zetten.
  python3 tools/new_client.py check [MAP]
      Laat zien welke configvelden nog moeten worden ingevuld.
  python3 tools/new_client.py koppel [MAP] --zoom-did +31... --zoom-ext 8xx --granola-map "Naam" [...]
      Vult gegevens in zodra je ze hebt (alles optioneel, in willekeurige combinatie): past de config aan,
      zet die in index.html en ververst CHECKLIST.md. Duurt een paar seconden. --help toont alle opties.
  python3 tools/new_client.py demo [MAP] [--uit]
      Demo-modus: de site toont verzonnen voorbeeldgegevens zonder inloggen (om aan nieuwe klanten te laten
      zien hoe het eruitziet) en de automatische planning staat uit. --uit zet alles terug.
      `koppel` met echte gegevens (Zoom, Granola, Supabase, team) zet de demo vanzelf uit.
"""
import argparse
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TEMPLATE = os.path.abspath(os.path.join(HERE, '..'))

# Gedeelde code die bij een klant terechtkomt (alles daarbuiten is klantdata of template-intern).
CODE_FILES = [
    'index.html',
    'scripts/analyze_granola_ai.py',
    'scripts/fetch_zoho_tickets.py',
    'scripts/fetch_zoom_calls.py',
    'scripts/finalize_weekdata.py',
    'scripts/client_config.py',
    'tools/new_client.py',
    '.github/workflows/update-dagrapport.yml',
    '.github/workflows/zoom-backfill.yml',
    '.github/workflows/diagnose-zoom-calls.yml',
]

# Wat het dashboard in de browser mag weten. Prompts, Granola-map en Zoom-lijn blijven server-side.
PUBLIC_KEYS = [
    'id', 'naam', 'pagesUrl', 'repo', 'supabase', 'gemisteOproepenDomeinen', 'medewerkerDomeinen',
    'managementEmails', 'team', 'aliassen', 'doorverwijzing', 'topMedewerkerLabel', 'weekNormen',
    'doorverwijzingHistorie', 'verkeerdVerbondenBackfill', 'demo',
]

EMPTY_DAY = {
    'date': '1970-01-01', 'generated_at': '', 'drukte': 'rustig', 'gesprekken': 0,
    'stats': {'opgelost': 0, 'brandmeester': 0, 'afkoop': 0, 'terugbel': 0, 'geenDekking': 0, 'verkeerdNummer': 0},
    'score': 0, 'conversations': [], 'acties': [], 'analyse': {'goed': [], 'beter': []},
}
INITIAL_DATA = {
    'data/today.json': EMPTY_DAY,
    'data/zoho-tickets.json': {'date': '', 'tickets': [], 'channelCounts': {}, 'brandmeesterCount': 0, 'ticketStats': None, 'openTickets': []},
    'data/zoom-calls.json': {'date': '', 'totaalInbound': 0, 'totaalGemist': 0, 'terugGebeld': 0, 'nietTerugGebeld': 0,
                             'nietTerugGebeldNummers': [], 'alleGemistNummers': [], 'agenten': {}},
    'data/zoom-history.json': {},
    'data/zoho-ticket-history.json': {},
    'data/manual-entries.json': {},
}


# ----------------------------------------------------------------------------- hulpfuncties
def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def load_cfg(path):
    cfg = json.loads(read(path))
    for k in ('id', 'naam', 'titel', 'team', 'doorverwijzing', 'supabase', 'repo', 'granolaMap', 'zoom'):
        if k not in cfg:
            sys.exit(f'FOUT: veld "{k}" ontbreekt in {path}')
    if not re.fullmatch(r'[a-z0-9-]+', cfg['id']):
        sys.exit('FOUT: "id" mag alleen kleine letters, cijfers en streepjes bevatten')
    return cfg


def esc(s):
    return htmllib.escape(str(s), quote=True)


def public_config(cfg):
    return {k: cfg[k] for k in PUBLIC_KEYS if k in cfg}


def embed_config(index_html, cfg):
    blob = json.dumps(public_config(cfg), ensure_ascii=True, separators=(',', ':')).replace('</', '<\\/')
    new, n = re.subn(r'/\*CLIENT_CONFIG_START\*/.*?/\*CLIENT_CONFIG_END\*/',
                     lambda m: '/*CLIENT_CONFIG_START*/' + blob + '/*CLIENT_CONFIG_END*/', index_html, flags=re.S)
    if n != 1:
        sys.exit('FOUT: CLIENT-configblok niet gevonden in index.html')
    return new


def region(html, name, content):
    pat = re.compile(r'(<!--CLIENT:%s-->).*?(<!--/CLIENT:%s-->)' % (re.escape(name), re.escape(name)), re.S)
    new, n = pat.subn(lambda m: m.group(1) + content + m.group(2), html)
    if n != 1:
        sys.exit(f'FOUT: marker CLIENT:{name} niet gevonden in index.html')
    return new


def render_static(html, cfg):
    logo = cfg.get('klantLogo', {})
    h = int(logo.get('hoogte', 22))
    img = '<img src="%s" alt="%s" style="height:%dpx;width:auto;display:block;margin-top:2px;">' % (esc(logo.get('src', '')), esc(logo.get('alt', cfg['naam'])), h)
    av = ['    <div class="avatar-stack">']
    avatars = cfg.get('avatars')
    if avatars is None:  # standaard: de eerste drie teamleden
        kleuren = ['', '#8a7356', '#6b8f71']
        avatars = [{'naam': t['naam'], 'initialen': ''.join(w[0] for w in t['naam'].split()[:2]).upper(), 'kleur': kleuren[i]}
                   for i, t in enumerate(cfg.get('team', [])[:3])]
    for i, a in enumerate(avatars):
        style = ' style="background:%s"' % esc(a['kleur']) if a.get('kleur') else ''
        av.append('      <div class="av" title="%s"%s>%s</div>' % (esc(a['naam']), style, esc(a['initialen'])))
    av.append('    </div>')
    login = cfg.get('loginLogoHtml') or ('<img src="%s" alt="%s" style="height:%dpx;width:auto;display:block;margin-top:2px;">'
                                         % (esc(logo.get('src', '')), esc(logo.get('alt', cfg['naam'])), int(logo.get('loginHoogte', 30))))
    html = region(html, 'title', '<title>%s</title>' % esc(cfg['titel']))
    html = region(html, 'topbar-logo', img)
    html = region(html, 'avatars', '\n'.join(av))
    html = region(html, 'footer', '<div class="footer-left">%s</div>' % cfg.get('footerOperator', 'HTJZ &middot; Het Team Juridische Zaken'))
    html = region(html, 'login-logo', login)
    html, n = re.subn(r'("name": ")[^"]*(",\s*"schemaVersion")', lambda m: m.group(1) + cfg.get('artifactNaam', cfg['naam'] + ' Dagrapport') + m.group(2), html, count=1)
    return html


def weekdata_bounds(html):
    s = html.index('const weekData = {')
    e = html.index('const MANUAL_OUTCOMES')
    return s, e


def reset_weekdata(html):
    s, e = weekdata_bounds(html)
    return html[:s] + 'const weekData = {\n}\n\n' + html[e:]


def keep_weekdata(new_html, old_html):
    s, e = weekdata_bounds(new_html)
    os_, oe = weekdata_bounds(old_html)
    return new_html[:s] + old_html[os_:oe] + new_html[e:]


def demo_workflow(text, demo):
    """Demo aan: de planning vervangen door een datum die niet bestaat (31 feb), zodat de workflow in een
    demo-repo nooit zelf draait en dus ook geen 'run failed'-mails stuurt. Demo uit: het origineel terugzetten."""
    if demo:
        return re.sub(r"- cron: '(?!0 0 31 2 \*)([^']+)'[ \t]*(?=\n)", r"- cron: '0 0 31 2 *'  # DEMO-UIT: origineel '\1'", text)
    return re.sub(r"- cron: '0 0 31 2 \*'  # DEMO-UIT: origineel '([^']+)'", r"- cron: '\1'", text)


def workflow_text(text, cfg):
    """Zet de klantnamen in de workflows om. De bronwaarden worden uit de workflow zelf gelezen,
    zodat dit werkt vanuit elk template (en ook voor een eerder omgezette klantmap)."""
    m = re.search(r'^name: Update (.+?) Dagrapport$', text, re.M)
    if m:
        text = text.replace('Update %s Dagrapport' % m.group(1), 'Update %s Dagrapport' % cfg['naam'])
    m = re.search(r'git config user\.name\s+"([^"]+)"', text)
    if m:
        text = text.replace('"%s"' % m.group(1), '"%s"' % cfg.get('botNaam', cfg['naam'] + ' Bot'))
    m = re.search(r'auto: (\S+) dagrapport', text)
    if m:
        text = text.replace('auto: %s dagrapport' % m.group(1), 'auto: %s dagrapport' % cfg['id'])
    text = demo_workflow(text, bool(cfg.get('demo')))
    text = re.sub(r"(  van:\n(?:.*\n){1,3}?\s+default: )'[^']*'", lambda mm: mm.group(1) + "'%s'" % date.today().isoformat(), text)
    return text


def todo_fields(cfg):
    out = []

    def walk(prefix, v):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(prefix + '.' + k if prefix else k, x)
        elif isinstance(v, list):
            if not v and prefix in ('team', 'managementEmails'):
                out.append(prefix)
            for i, x in enumerate(v):
                walk('%s[%d]' % (prefix, i), x)
        elif isinstance(v, str) and ('TODO' in v or (v == '' and prefix in (
                'supabase.url', 'supabase.anonKey', 'zoom.queueDid', 'zoom.queueExt', 'pagesUrl', 'repo.owner', 'repo.naam',
                'granolaMap', 'prompt.bedrijfsregels'))):
            out.append(prefix)
    walk('', cfg)
    return out


def checklist(cfg):
    owner = cfg['repo'].get('owner') or 'OWNER'
    repo = cfg['repo'].get('naam') or 'REPO'
    return f'''# Checklist {cfg['naam']}

## Snel invullen zodra je de gegevens hebt
Alles in een keer (elk onderdeel is optioneel, je kunt het ook in delen doen); duurt een paar seconden:
```bash
python3 tools/new_client.py koppel \\
  --zoom-did "+31..." --zoom-ext "8.." --granola-map "Naam van de Granola-map" \\
  --repo "eigenaar/repo-naam" --supabase-url "https://....supabase.co" --supabase-key "sb_publishable_..." \\
  --team "Naam <mail@domein.nl>; Naam2 <mail2@domein.nl>" --management "a@domein.nl,b@domein.nl" \\
  --bedrijfsregels-bestand regels.txt --commit
```
`python3 tools/new_client.py check` laat zien wat nog open staat. Weet je het Zoom-nummer nog niet? Draai eenmaal de workflow
"Diagnose Zoom call history": die toont in de log alle lijnen op het Zoom-account met hun nummer en extensie.
Zolang iets nog niet is ingesteld slaan de scripts het netjes over (de runs falen niet en er wordt niets weggeschreven).

## Handmatig in client.config.json
Alles wat per klant verschilt staat in `client.config.json`. Vul de velden met `TODO` of een lege waarde in en draai daarna
`python3 tools/new_client.py sync-config`.

## 1. GitHub
- [ ] Maak een **eigen** repo (liefst onder een eigen organisatie, niet onder die van een andere klant): `{owner}/{repo}`
- [ ] Push deze map naar `main` en zet GitHub Pages aan (Settings > Pages > Deploy from branch > main, / root)
- [ ] Zet de URL van de site in `pagesUrl` (nu `{cfg.get('pagesUrl')}`)

## 2. Inloggen (Supabase), een **eigen project per klant**
- [ ] Maak een nieuw Supabase-project. Deel het NIET met een andere klant: iedereen met een account in een project kan het bijbehorende dashboard openen.
- [ ] Zet `supabase.url` en `supabase.anonKey` (de publishable key) in de config
- [ ] Authentication > URL Configuration: Site URL en Redirect URL = de `pagesUrl`
- [ ] Authentication > Email Templates: pas de teksten en het logo aan naar {cfg['naam']}
- [ ] Zet "Allow new users to sign up" uit en nodig gebruikers uit, anders kan iedereen met een e-mailadres een account maken

## 3. Secrets (GitHub > Settings > Secrets and variables > Actions)
- [ ] `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_ORG_ID` (Zoho Desk van deze klant; regio in `zoho.regio`, nu `{cfg.get('zoho', {}).get('regio', 'eu')}`)
- [ ] `ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` (Server-to-Server OAuth-app; scopes `phone:read:list_call_logs:admin` en `phone:read:call_log:admin`)
- [ ] `GRANOLA_API_KEY` en `ANTHROPIC_API_KEY`
- [ ] Zet `zoom.queueDid` en `zoom.queueExt` (de wachtrij van deze klant) en `granolaMap` (de Granola-map met de gesprekken)

## 4. Inhoud
- [ ] `team`: naam en e-mailadres van de medewerkers (het lokale deel van het adres wordt gebruikt om Zoom-gebruikers te herkennen)
- [ ] `managementEmails`, `avatars` en eventueel `aliassen` (bijnamen of veelvoorkomende verhoorde namen)
- [ ] `doorverwijzing.naam`: hoe heet de partij waar naar wordt doorverwezen? (nu `{cfg['doorverwijzing']['naam']}`)
- [ ] `prompt.bedrijfsregels`: de regels van deze klant voor de AI-analyse (dekking, franchise, verplichte doorverwijzingen). Zonder die regels beoordeelt de AI alleen op algemene kwaliteit.

## 5. Elke 10 minuten laten draaien (cron-job.org)
GitHub's eigen `schedule` is onbetrouwbaar. Maak op cron-job.org een job:
- URL: `https://api.github.com/repos/{owner}/{repo}/actions/workflows/update-dagrapport.yml/dispatches`
- Methode POST, headers `Authorization: Bearer <fine-grained token, alleen deze repo, Actions: write>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`
- Body `{{"ref": "main"}}`, schema `*/10 7-18 * * 1-5` (Europe/Amsterdam)

## 6. Historie ophalen (optioneel)
- [ ] Actions > "Backfill Zoom-historie (per medewerker)" > Run workflow, met de startdatum waarvanaf je de Zoom-historie wilt

## Bijwerken met nieuwe functies
Vanuit de template-repo: `python3 tools/new_client.py update <pad naar deze map>`. Config, logo en data blijven staan.
'''


# ----------------------------------------------------------------------------- hoofdacties
def write_code(template, out, cfg):
    for rel in CODE_FILES:
        src = os.path.join(template, rel)
        if not os.path.exists(src):
            sys.exit(f'FOUT: {rel} ontbreekt in het template ({template})')
        text = read(src)
        if rel.startswith('.github/workflows/'):
            text = workflow_text(text, cfg)
        write(os.path.join(out, rel), text)


def sync_index(out, cfg):
    p = os.path.join(out, 'index.html')
    h = read(p)
    h = embed_config(h, cfg)
    h = render_static(h, cfg)
    write(p, h)


def cmd_create(a):
    template = os.path.abspath(a.template)
    out = os.path.abspath(a.out)
    if os.path.exists(out) and os.listdir(out):
        sys.exit(f'FOUT: {out} bestaat al en is niet leeg (gebruik "update" om een bestaande klant bij te werken)')
    cfg = load_cfg(a.config)
    cfg.pop('_leesmij', None)
    cfg = {'_leesmij': json.loads(read(os.path.join(template, 'client.config.json')))['_leesmij'], **cfg}
    os.makedirs(out, exist_ok=True)
    write_code(template, out, cfg)
    if a.logo:
        ext = os.path.splitext(a.logo)[1].lower() or '.svg'
        dest = 'assets/klant-logo' + ext
        os.makedirs(os.path.join(out, 'assets'), exist_ok=True)
        shutil.copyfile(a.logo, os.path.join(out, dest))
        cfg.setdefault('klantLogo', {})['src'] = dest
    write(os.path.join(out, 'client.config.json'), json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    for rel, data in INITIAL_DATA.items():
        write(os.path.join(out, rel), json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    h = reset_weekdata(read(os.path.join(out, 'index.html')))
    write(os.path.join(out, 'index.html'), h)
    sync_index(out, cfg)
    write(os.path.join(out, 'CHECKLIST.md'), checklist(cfg))
    write(os.path.join(out, '.gitignore'), '.DS_Store\n*.bak*\ndebug.jsonl\n')
    if not a.no_git:
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=out, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=out, check=True)
        subprocess.run(['git', '-c', 'user.name=Dagrapport Generator', '-c', 'user.email=bot@htjz.nl', 'commit', '-q', '-m',
                        'Dagrapport voor %s aangemaakt met tools/new_client.py' % cfg['naam']], cwd=out, check=True)
    print(f'Klaar: {out}')
    todo = todo_fields(cfg)
    if todo:
        print('Nog in te vullen in client.config.json:\n  - ' + '\n  - '.join(todo))
    print('Zie CHECKLIST.md voor de stappen (GitHub, Supabase, secrets, cron-job.org).')


def cmd_update(a):
    template = os.path.abspath(a.template)
    out = os.path.abspath(a.map)
    cfg = load_cfg(os.path.join(out, 'client.config.json'))
    old = read(os.path.join(out, 'index.html'))
    write_code(template, out, cfg)
    h = keep_weekdata(read(os.path.join(out, 'index.html')), old)
    write(os.path.join(out, 'index.html'), h)
    sync_index(out, cfg)
    write(os.path.join(out, 'CHECKLIST.md'), checklist(cfg))
    print(f'{out} bijgewerkt met de code uit {template}. Config, logo en data zijn behouden.')


def cmd_sync(a):
    out = os.path.abspath(a.map)
    cfg = load_cfg(os.path.join(out, 'client.config.json'))
    sync_index(out, cfg)
    print('Config en logo zijn opnieuw in index.html gezet.')


def parse_team(tekst):
    """'Naam <mail>; Naam2 <mail2>' of 'Naam=mail; ...' -> [{'naam':..,'email':..}]"""
    out = []
    for deel in re.split(r'[;\n]+', tekst):
        deel = deel.strip()
        if not deel:
            continue
        m = re.fullmatch(r'(.+?)\s*<([^>]+)>', deel) or re.fullmatch(r'(.+?)\s*=\s*(\S+@\S+)', deel)
        if not m:
            sys.exit(f'FOUT: kan teamlid niet lezen: "{deel}" (gebruik: Naam <mail@domein.nl>; Naam2 <mail2@domein.nl>)')
        out.append({'naam': m.group(1).strip(), 'email': m.group(2).strip().lower()})
    return out


def cmd_koppel(a):
    out = os.path.abspath(a.map)
    path = os.path.join(out, 'client.config.json')
    cfg = load_cfg(path)
    gedaan = []

    def zet(sectie, sleutel, waarde, label):
        if waarde is None:
            return
        if sectie:
            cfg.setdefault(sectie, {})[sleutel] = waarde
        else:
            cfg[sleutel] = waarde
        gedaan.append(label)

    zet('zoom', 'queueDid', a.zoom_did, 'Zoom-nummer')
    zet('zoom', 'queueExt', a.zoom_ext, 'Zoom-extensie')
    zet(None, 'granolaMap', a.granola_map, 'Granola-map')
    zet('supabase', 'url', a.supabase_url, 'Supabase-URL')
    zet('supabase', 'anonKey', a.supabase_key, 'Supabase-sleutel')
    zet('zoho', 'regio', a.zoho_regio, 'Zoho-regio')
    zet('doorverwijzing', 'naam', a.doorverwijzing, 'naam van de doorverwijzing')
    if a.repo:
        if '/' not in a.repo:
            sys.exit('FOUT: --repo moet de vorm eigenaar/naam hebben, bijvoorbeeld VCD-Org/dagrapport')
        eigenaar, naam = a.repo.split('/', 1)
        cfg['repo'] = {'owner': eigenaar, 'naam': naam}
        gedaan.append('GitHub-repo')
        if a.pages_url is None:
            # Een repo met de naam <x>.github.io is de hoofdsite van de eigenaar en staat op https://<x>.github.io/
            cfg['pagesUrl'] = (f'https://{naam.lower()}/' if naam.lower().endswith('.github.io')
                               else f'https://{eigenaar.lower()}.github.io/{naam}/')
            gedaan.append('site-URL (afgeleid uit de repo)')
    zet(None, 'pagesUrl', a.pages_url, 'site-URL')
    if a.team:
        cfg['team'] = parse_team(a.team)
        cfg.pop('avatars', None)
        gedaan.append(f"team ({len(cfg['team'])} personen)")
    if a.management:
        cfg['managementEmails'] = [x.strip().lower() for x in re.split(r'[,;\s]+', a.management) if x.strip()]
        gedaan.append('management-adressen')
    if a.bedrijfsregels_bestand:
        cfg.setdefault('prompt', {})['bedrijfsregels'] = read(a.bedrijfsregels_bestand).strip()
        gedaan.append('bedrijfsregels')

    if cfg.get('demo') and any(x is not None for x in (a.zoom_did, a.granola_map, a.supabase_url, a.supabase_key, a.team)):
        zet_demo(out, cfg, False)
        gedaan.append('demo-modus uitgezet (er zijn echte gegevens)')

    if not gedaan:
        print('Niets opgegeven om in te vullen. Gebruik --help voor de opties.')
    else:
        write(path, json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
        sync_index(out, cfg)
        write(os.path.join(out, 'CHECKLIST.md'), checklist(cfg))
        print('Ingevuld: ' + ', '.join(gedaan) + '.')
        if a.commit:
            subprocess.run(['git', 'add', '-A'], cwd=out, check=True)
            subprocess.run(['git', '-c', 'user.name=Dagrapport Generator', '-c', 'user.email=bot@htjz.nl', 'commit', '-q', '-m',
                            'Klantgegevens ingevuld: ' + ', '.join(gedaan)], cwd=out, check=True)
            print('Gecommit.')
    todo = todo_fields(cfg)
    if todo:
        print('Nog open in client.config.json:\n  - ' + '\n  - '.join(todo))
    else:
        print('Alle verplichte velden zijn ingevuld. Resterend: secrets in GitHub en de cron-job.org-job (zie CHECKLIST.md).')


def zet_demo(out, cfg, aan):
    """Zet demo aan of uit in de config en in de workflows (de config wordt hier niet opgeslagen; dat doet de aanroeper)."""
    if aan:
        cfg['demo'] = True
    else:
        cfg.pop('demo', None)
    wf = os.path.join(out, '.github/workflows/update-dagrapport.yml')
    if os.path.exists(wf):
        write(wf, demo_workflow(read(wf), aan))


def cmd_demo(a):
    out = os.path.abspath(a.map)
    path = os.path.join(out, 'client.config.json')
    cfg = load_cfg(path)
    zet_demo(out, cfg, not a.uit)
    write(path, json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    sync_index(out, cfg)
    if a.uit:
        print('Demo-modus staat uit: de site toont weer de echte gegevens en vraagt om in te loggen.')
        todo = todo_fields(cfg)
        if todo:
            print('Let op, hier moet nog iets voor worden ingevuld voordat het echt werkt:\n  - ' + '\n  - '.join(todo))
    else:
        print('Demo-modus staat aan: de site toont verzonnen voorbeeldgegevens, zonder inloggen. De automatische planning is uitgezet.')
    if a.commit:
        subprocess.run(['git', 'add', '-A'], cwd=out, check=True)
        subprocess.run(['git', '-c', 'user.name=Dagrapport Generator', '-c', 'user.email=bot@htjz.nl', 'commit', '-q', '-m',
                        'Demo-modus ' + ('uit' if a.uit else 'aan')], cwd=out, check=True)
        print('Gecommit.')


def cmd_check(a):
    out = os.path.abspath(a.map)
    todo = todo_fields(load_cfg(os.path.join(out, 'client.config.json')))
    if todo:
        print('Nog in te vullen:\n  - ' + '\n  - '.join(todo))
        sys.exit(1)
    print('Alle verplichte velden zijn ingevuld.')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('create'); c.add_argument('--config', required=True); c.add_argument('--out', required=True)
    c.add_argument('--logo'); c.add_argument('--template', default=DEFAULT_TEMPLATE); c.add_argument('--no-git', action='store_true')
    c.set_defaults(fn=cmd_create)
    u = sub.add_parser('update'); u.add_argument('map'); u.add_argument('--template', default=DEFAULT_TEMPLATE); u.set_defaults(fn=cmd_update)
    s = sub.add_parser('sync-config'); s.add_argument('map', nargs='?', default='.'); s.set_defaults(fn=cmd_sync)
    q = sub.add_parser('koppel', help='gegevens invullen zodra je ze hebt')
    q.add_argument('map', nargs='?', default='.')
    q.add_argument('--zoom-did', help='telefoonnummer van de Zoom-wachtrij, bv. +31201234567')
    q.add_argument('--zoom-ext', help='extensienummer van de wachtrij, bv. 812')
    q.add_argument('--granola-map', help='exacte naam van de Granola-map met de gesprekken')
    q.add_argument('--repo', help='GitHub-repo als eigenaar/naam (site-URL wordt afgeleid)')
    q.add_argument('--pages-url', help='site-URL, alleen nodig als die afwijkt van eigenaar.github.io/naam/')
    q.add_argument('--supabase-url'); q.add_argument('--supabase-key', help='de publishable key (begint met sb_publishable_ of eyJ)')
    q.add_argument('--zoho-regio', help='eu, com, in, com.au, jp ...')
    q.add_argument('--team', help='"Naam <mail>; Naam2 <mail2>"')
    q.add_argument('--management', help='e-mailadressen met managementtoegang, gescheiden door komma')
    q.add_argument('--doorverwijzing', help='hoe de partij heet waar naar wordt doorverwezen')
    q.add_argument('--bedrijfsregels-bestand', help='tekstbestand met de regels van de klant voor de AI-analyse')
    q.add_argument('--commit', action='store_true', help='daarna meteen committen')
    q.set_defaults(fn=cmd_koppel)
    d = sub.add_parser('demo', help='demo-modus aan of uit: verzonnen voorbeeldgegevens, zonder inloggen')
    d.add_argument('map', nargs='?', default='.'); d.add_argument('--uit', action='store_true'); d.add_argument('--commit', action='store_true')
    d.set_defaults(fn=cmd_demo)
    k = sub.add_parser('check'); k.add_argument('map', nargs='?', default='.'); k.set_defaults(fn=cmd_check)
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
