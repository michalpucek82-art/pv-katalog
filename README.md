# PV Meta katalóg: generátor obrázkov a feedu

Každú noc (3:30 UTC) GitHub spustí `generator.py`: prejde katalóg profivzdelavanie.sk, ku každému budúcemu školeniu vyrobí obrázok 1080 × 1080 podľa šablóny a zapíše `feed.csv` pre Meta katalóg. Výsledok je verejne na GitHub Pages:

- feed: `https://<používateľ>.github.io/pv-katalog/feed.csv`
- obrázok: `https://<používateľ>.github.io/pv-katalog/img/<id kurzu>.png`

Návrh a súvislosti: `PV/FB-Profivzdelavanie/navrhy/mp_META-KATALOG-NAVOD.md`.

## Súbory

| Súbor | Čo |
|---|---|
| `generator.py` | stiahne kurzy, vyrenderuje obrázky, zapíše feed |
| `sablona.json` | rozmiestnenie textov a fotky, farby okruhov, vylúčené témy, prepis okruhu |
| `sablony/<okruh>.png` | pozadia 1080 × 1080 od Michala (`dane`, `mzdy`, `verejna_sprava`, `skolstvo`, `ine`); kým chýbajú, použije sa farba |
| `fonty/` | Montserrat (licencia OFL) |
| `.github/workflows/katalog.yml` | nočné spustenie a zverejnenie na GitHub Pages |

Lokálny test: `python generator.py --limit 10 --nahlad --out out` (obrázky v `out/img`, náhľad `out/nahlad.jpg`).

## Prvé nastavenie na GitHube (len cez web)

1. **Nový repozitár:** github.com, vpravo hore **+**, **New repository**. Názov `pv-katalog`, **Public**, nič nezaškrtávať, **Create repository**.
2. **Nahrať súbory:** na stránke repozitára odkaz **uploading an existing file**. Z priečinka `PV/meta-katalog` pretiahnuť `generator.py`, `sablona.json`, `README.md` a priečinky `fonty` a `sablony`. Dole **Commit changes**.
3. **Workflow:** **Add file**, **Create new file**, do názvu napísať presne `.github/workflows/katalog.yml`, obsah skopírovať z rovnomenného súboru v `PV/meta-katalog/.github/workflows/`. **Commit changes**.
4. **Zapnúť Pages:** **Settings**, vľavo **Pages**, **Build and deployment**, **Source: GitHub Actions**.
5. **Prvé spustenie:** záložka **Actions**, vľavo **PV Meta katalog**, vpravo **Run workflow**. Po 3 až 6 minútach zelená fajka.
6. **Kontrola:** otvoriť `https://<používateľ>.github.io/pv-katalog/feed.csv`.

## Zmena šablóny alebo pravidiel

V repozitári otvoriť súbor (napr. `sablona.json` alebo `sablony/mzdy.png`), ikona ceruzky alebo **Add file, Upload files** s rovnakým názvom (prepíše sa), **Commit changes**. Najbližšie nočné spustenie (alebo **Run workflow**) použije novú verziu.

## Meta

Commerce Manager, Katalógy, nový katalóg (E-commerce), **Zdroje dát**, **Dátový feed**, **Plánovaný feed**, URL `feed.csv`, denne, mena EUR. Skupiny produktov podľa `custom_label_0` (`okruh_hlavny_mzdy` …).
