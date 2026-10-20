import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE = "https://profivzdelavanie.sk"
FOTO_URL = "https://wcm.prod.pp.sk/media/people/{}"
UA = "Mozilla/5.0 (compatible; PV-MetaKatalogBot)"
KATEGORIE = {
    "Dane a účtovníctvo": "dane",
    "Mzdy a personalistika": "mzdy",
    "Verejná správa": "verejna_sprava",
}
PREFIXY = ("Online školenie:", "Zážitkové školenie:", "Prezenčné školenie:", "Školenie:", "Konferencia:")
UTM = "utm_source=facebook&utm_medium=paid_social&utm_campaign=mp_SALES_okruhy&utm_content=katalog"
STLPCE = ["id", "item_group_id", "title", "description", "availability", "condition", "price", "link",
          "image_link", "brand", "custom_label_0", "custom_label_1", "custom_label_2", "custom_label_3"]

ROOT = os.path.dirname(os.path.abspath(__file__))


def stiahni(url, binarne=False, pokusy=3):
    for i in range(pokusy):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            return data if binarne else data.decode("utf-8", errors="replace")
        except Exception as e:
            if i == pokusy - 1:
                print(f"CHYBA {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2 * (i + 1))


def next_data(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html or "", re.S)
    return json.loads(m.group(1))["props"]["pageProps"] if m else None


def zoznam(query):
    out, videne, strana = [], set(), 1
    while strana <= 30:
        pp = next_data(stiahni(f"{BASE}/skolenia?{query}strana={strana}"))
        tr = (pp or {}).get("trainings") or []
        nove = [t for t in tr if t["course"]["_key"] not in videne]
        if not nove:
            break
        for t in nove:
            videne.add(t["course"]["_key"])
            out.append(t)
        strana += 1
    return out, pp


def zber_kurzov():
    vsetky, pp = zoznam("")
    kurzy = {t["course"]["_key"]: {"slug": t["course"]["slug"], "okruhy": set(), "skolstvo": False} for t in vsetky}
    for t in vsetky:
        if any((g.get("title") or "") == "Školstvo" for g in t.get("tags") or []):
            kurzy[t["course"]["_key"]]["skolstvo"] = True
    for kat in (pp or {}).get("categoryFilters") or []:
        okruh = KATEGORIE.get(kat.get("name", "").strip())
        if not okruh:
            continue
        clenovia, _ = zoznam(f"kategoria={kat['_key']}&")
        for t in clenovia:
            k = t["course"]["_key"]
            kurzy.setdefault(k, {"slug": t["course"]["slug"], "okruhy": set(), "skolstvo": False})["okruhy"].add(okruh)
    return kurzy


def hlavny_okruh(kurzy):
    pocet = {}
    for k in kurzy.values():
        for o in k["okruhy"]:
            pocet[o] = pocet.get(o, 0) + 1
    for k in kurzy.values():
        if k["skolstvo"]:
            k["hlavny"] = "skolstvo"
        elif k["okruhy"]:
            k["hlavny"] = min(k["okruhy"], key=lambda o: (pocet[o], o))
        else:
            k["hlavny"] = "ine"


def cisty_nazov(nazov):
    nazov = re.sub(r"[   ]", " ", nazov)
    for p in PREFIXY:
        if nazov.startswith(p):
            return nazov[len(p):].strip()
    return nazov.strip()


def format_kurzu(nazov, online):
    if nazov.startswith("Zážitkové"):
        return "zazitkove"
    return "online" if online else "prezencne"


def datum_text(dni):
    dni = sorted(set(dni))
    if len(dni) == 1:
        d = dni[0]
        return f"{d.day}. {d.month}. {d.year}"
    a, b = dni[0], dni[-1]
    if a.month == b.month:
        return f"{a.day}. až {b.day}. {b.month}. {b.year}"
    return f"{a.day}. {a.month}. až {b.day}. {b.month}. {b.year}"


def naliehavost(dni_do):
    if dni_do <= 21:
        return "do_14_dni"
    if dni_do <= 56:
        return "do_30_dni"
    return "nad_30_dni"


def meno_lektora(p):
    t = p.get("titles") or {}
    casti = [t.get("before_name"), p.get("name"), p.get("surname")]
    meno = " ".join(x.strip() for x in casti if x and x.strip())
    if t.get("after_name"):
        meno += ", " + t["after_name"].strip()
    return meno


def detail(kurz, teraz):
    html = stiahni(f"{BASE}/skolenie/{kurz['slug']}")
    pp = next_data(html)
    if not pp or not pp.get("training"):
        return None
    tr = pp["training"]
    c = tr["course"]
    if c.get("state") != 1:
        return None
    buduce = []
    for d in tr.get("dates") or []:
        od = (d.get("date") or {}).get("from")
        if not od:
            continue
        dt = datetime.fromisoformat(od.replace("Z", "+00:00"))
        if dt > teraz:
            buduce.append((dt, d))
    if not buduce:
        return None
    buduce.sort(key=lambda x: x[0])
    prvy_dt, prvy = buduce[0]
    vstupenky = []
    for m in prvy.get("modules") or []:
        karta = (m.get("eso9") or {}).get("stock_card")
        if m.get("type") == 0 and karta:
            vstupenky.append({"id": karta, "cena": m.get("price_with_vat") or m.get("price")})
    if not vstupenky:
        return None
    lektori = [l.get("person") or {} for l in tr.get("lecturers") or []]
    og = re.search(r'<meta property="og:description" content="([^"]*)"', html)
    popis = (c.get("seo") or {}).get("description") or (og.group(1) if og else "")
    dni = [x[0].astimezone().date() for x in buduce if x[1] is prvy or (x[0] - prvy_dt).days < 3]
    return {
        "key": c["_key"],
        "nazov": cisty_nazov(c["title"]),
        "format": format_kurzu(c["title"], prvy.get("isOnline")),
        "popis": re.sub(r"\s+", " ", popis).strip()[:5000],
        "link": f"{BASE}/skolenie/{kurz['slug']}?{UTM}",
        "datum": datum_text(dni),
        "dni_do": (prvy_dt - teraz).days,
        "lektor": ", ".join(meno_lektora(p) for p in lektori[:2] if p),
        "foto": next((p.get("photo") for p in lektori if p.get("photo")), None),
        "vstupenky": vstupenky,
        "okruh": kurz["hlavny"],
    }


def pismo(sablona, druh, velkost):
    cesta = sablona["pisma"].get(druh)
    if cesta and not os.path.isabs(cesta):
        cesta = os.path.join(ROOT, cesta)
    if not cesta or not os.path.exists(cesta):
        cesta = sablona["pisma"]["zaloha_" + druh]
    return ImageFont.truetype(cesta, velkost)


def zalom(draw, text, font, sirka):
    riadky, riadok = [], ""
    for slovo in text.split():
        skusba = (riadok + " " + slovo).strip()
        if draw.textlength(skusba, font=font) <= sirka:
            riadok = skusba
        else:
            if riadok:
                riadky.append(riadok)
            riadok = slovo
    if riadok:
        riadky.append(riadok)
    return riadky


def pozadie(sablona, okruh):
    w, h = sablona["rozmer"]
    cesta = os.path.join(ROOT, sablona["pozadie"].get(okruh, sablona["pozadie"]["ine"]))
    if os.path.exists(cesta):
        return Image.open(cesta).convert("RGBA").resize((w, h))
    farba = sablona["pozadie_farba_ak_chyba_png"].get(okruh, "#334155")
    return Image.new("RGBA", (w, h), farba)


def foto_kruh(foto_id, priemer, okraj, okraj_farba, cache):
    cesta = os.path.join(cache, f"{foto_id}.png")
    if not os.path.exists(cesta):
        data = stiahni(FOTO_URL.format(foto_id), binarne=True)
        if not data:
            return None
        with open(cesta, "wb") as f:
            f.write(data)
    img = Image.open(cesta).convert("RGBA")
    img = ImageOps.fit(img, (priemer, priemer), centering=(0.5, 0.3))
    maska = Image.new("L", (priemer, priemer), 0)
    ImageDraw.Draw(maska).ellipse((0, 0, priemer, priemer), fill=255)
    vonkajsi = priemer + 2 * okraj
    out = Image.new("RGBA", (vonkajsi, vonkajsi), (0, 0, 0, 0))
    ImageDraw.Draw(out).ellipse((0, 0, vonkajsi, vonkajsi), fill=okraj_farba)
    out.paste(img, (okraj, okraj), maska)
    return out


def vyrenderuj(k, sablona, cache):
    img = pozadie(sablona, k["okruh"])
    d = ImageDraw.Draw(img)
    p = sablona["prvky"]

    s = p["stitok"]
    d.text((s["x"], s["y"]), sablona["texty"][k["format"]], font=pismo(sablona, s["pismo"], s["velkost"]), fill=s["farba"])

    n = p["nazov"]
    velkost = n["velkost_max"]
    while True:
        f = pismo(sablona, n["pismo"], velkost)
        riadky = zalom(d, k["nazov"], f, n["sirka"])
        if len(riadky) <= n["max_riadkov"] or velkost <= n["velkost_min"]:
            break
        velkost -= 2
    if len(riadky) > n["max_riadkov"]:
        riadky = riadky[:n["max_riadkov"]]
        riadky[-1] = riadky[-1].rstrip(",;:") + "…"
    y = n["y"]
    for r in riadky:
        d.text((n["x"], y), r, font=f, fill=n["farba"])
        y += int(velkost * n["riadkovanie"])

    s = p["datum"]
    d.text((s["x"], s["y"]), k["datum"], font=pismo(sablona, s["pismo"], s["velkost"]), fill=s["farba"])

    s = p["lektor"]
    fl = pismo(sablona, s["pismo"], s["velkost"])
    lektor = k["lektor"]
    if d.textlength(lektor, font=fl) > s["sirka"]:
        while lektor and d.textlength(lektor + "…", font=fl) > s["sirka"]:
            lektor = lektor[:-1]
        lektor = lektor.rstrip(" ,") + "…"
    d.text((s["x"], s["y"]), lektor, font=fl, fill=s["farba"])

    s = p["foto"]
    if k["foto"]:
        kruh = foto_kruh(k["foto"], s["priemer"], s["okraj"], s["okraj_farba"], cache)
        if kruh:
            img.alpha_composite(kruh, (s["x"], s["y"]))
    return img.convert("RGB")


def nahlad(cesty, ciel, stlpce=5, velkost=300):
    riadky = (len(cesty) + stlpce - 1) // stlpce
    plocha = Image.new("RGB", (stlpce * velkost, max(1, riadky) * velkost), "white")
    for i, c in enumerate(cesty):
        plocha.paste(Image.open(c).resize((velkost, velkost)), ((i % stlpce) * velkost, (i // stlpce) * velkost))
    plocha.save(ciel, quality=85)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    ap.add_argument("--base-url", default="https://DOPLNIT.github.io/pv-katalog/")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--nahlad", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    sablona = json.load(open(os.path.join(ROOT, "sablona.json"), encoding="utf-8"))
    os.makedirs(os.path.join(a.out, "img"), exist_ok=True)
    cache = os.path.join(a.out, ".foto")
    os.makedirs(cache, exist_ok=True)
    teraz = datetime.now(timezone.utc)

    kurzy = zber_kurzov()
    hlavny_okruh(kurzy)
    print(f"Kurzov v katalógu: {len(kurzy)}")

    riadky, obrazky = [], []
    for i, kurz in enumerate(kurzy.values()):
        if a.limit and len(obrazky) >= a.limit:
            break
        k = detail(kurz, teraz)
        if not k:
            continue
        maly = k["nazov"].lower()
        if any(s.lower() in maly for s in sablona.get("vylucit_ak_nazov_obsahuje", [])):
            print(f"  VYLÚČENÉ   {k['nazov'][:70]}")
            continue
        for s, okruh in sablona.get("prepis_okruhu", {}).items():
            if s.lower() in maly:
                k["okruh"] = okruh
                break
        cesta = os.path.join(a.out, "img", f"{k['key']}.png")
        vyrenderuj(k, sablona, cache).save(cesta, optimize=True)
        obrazky.append(cesta)
        for v in k["vstupenky"]:
            riadky.append({
                "id": v["id"],
                "item_group_id": k["key"],
                "title": k["nazov"][:200],
                "description": k["popis"] or k["nazov"],
                "availability": "in stock",
                "condition": "new",
                "price": f"{float(v['cena']):.2f} EUR",
                "link": k["link"],
                "image_link": a.base_url.rstrip("/") + f"/img/{k['key']}.png",
                "brand": "Profivzdelávanie",
                "custom_label_0": "okruh_hlavny_" + k["okruh"],
                "custom_label_1": naliehavost(k["dni_do"]),
                "custom_label_2": k["format"],
                "custom_label_3": k["datum"],
            })
        print(f"  {k['okruh']:15} {k['datum']:22} {k['nazov'][:70]}")

    with open(os.path.join(a.out, "feed.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STLPCE)
        w.writeheader()
        w.writerows(riadky)
    if a.nahlad and obrazky:
        nahlad(obrazky, os.path.join(a.out, "nahlad.jpg"))
    print(f"Hotovo: {len(obrazky)} obrázkov, {len(riadky)} riadkov feedu -> {a.out}")


if __name__ == "__main__":
    main()
