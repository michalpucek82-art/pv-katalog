import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

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


SKOLA = re.compile(r"skol|ucitel|pedagog|ziak|materske|riaditel")


def hlavny_okruh(kurzy):
    for k in kurzy.values():
        o = k["okruhy"]
        if len(o) >= 3 or not o:
            k["hlavny"] = "ine"
        elif "mzdy" in o:
            k["hlavny"] = "mzdy"
        elif "dane" in o:
            k["hlavny"] = "dane"
        elif k["skolstvo"] and SKOLA.search(k["slug"]):
            k["hlavny"] = "skolstvo"
        else:
            k["hlavny"] = "verejna_sprava"


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
    zadane = sablona["pisma"].get(druh) or ""
    kandidati = [
        zadane if os.path.isabs(zadane) else os.path.join(ROOT, zadane),
        os.path.join(ROOT, os.path.basename(zadane)),
        os.path.join(ROOT, "fonty", os.path.basename(zadane)),
        sablona["pisma"].get("zaloha_" + druh, ""),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if druh == "tucne" else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for cesta in kandidati:
        if cesta and os.path.isfile(cesta):
            return ImageFont.truetype(cesta, velkost)
    return ImageFont.load_default(velkost)


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
    f = sablona["farby"]
    img = Image.new("RGBA", (w, h), f["pozadie"])
    ziara = Image.new("L", (w, h), 0)
    ImageDraw.Draw(ziara).ellipse((int(w * 0.45), -int(h * 0.55), int(w * 1.45), int(h * 0.45)), fill=255)
    ziara = ziara.filter(ImageFilter.GaussianBlur(w // 6))
    img.paste(Image.new("RGBA", (w, h), f["ziara"]), (0, 0), ziara)
    return img


def logo(sablona):
    l = sablona["logo"]
    for cesta in (os.path.join(ROOT, l["subor"]), os.path.join(ROOT, os.path.basename(l["subor"]))):
        if os.path.isfile(cesta):
            img = Image.open(cesta).convert("RGBA")
            return img.resize((l["sirka"], round(img.height * l["sirka"] / img.width)), Image.LANCZOS)
    return None


def foto_kruh(foto_id, priemer, okraj, cache):
    cesta = os.path.join(cache, f"{foto_id}.png")
    if not os.path.exists(cesta):
        data = stiahni(FOTO_URL.format(foto_id), binarne=True)
        if not data:
            return None
        with open(cesta, "wb") as f:
            f.write(data)
    q = 4
    img = Image.open(cesta).convert("RGBA")
    img = ImageOps.fit(img, (priemer * q, priemer * q), Image.LANCZOS, centering=(0.5, 0.3))
    vonkajsi = priemer + 2 * okraj
    tien = 24
    velky = Image.new("RGBA", (vonkajsi * q, vonkajsi * q), (255, 255, 255, 0))
    kruh = Image.new("L", velky.size, 0)
    ImageDraw.Draw(kruh).ellipse((0, 0, vonkajsi * q - 1, vonkajsi * q - 1), fill=255)
    velky.paste(Image.new("RGBA", velky.size, "#ffffff"), (0, 0), kruh)
    maska = Image.new("L", img.size, 0)
    ImageDraw.Draw(maska).ellipse((0, 0, priemer * q - 1, priemer * q - 1), fill=255)
    velky.paste(img, (okraj * q, okraj * q), maska)
    maly = velky.resize((vonkajsi, vonkajsi), Image.LANCZOS)
    out = Image.new("RGBA", (vonkajsi + 2 * tien, vonkajsi + 2 * tien), (0, 0, 0, 0))
    st = Image.new("L", out.size, 0)
    ImageDraw.Draw(st).ellipse((tien, tien + 6, tien + vonkajsi, tien + vonkajsi + 6), fill=60)
    st = st.filter(ImageFilter.GaussianBlur(10))
    out.paste(Image.new("RGBA", out.size, (0, 0, 0, 255)), (0, 0), st)
    out.alpha_composite(maly, (tien, tien))
    return out, tien


def skrat(d, text, font, sirka):
    if d.textlength(text, font=font) <= sirka:
        return text
    while text and d.textlength(text + "…", font=font) > sirka:
        text = text[:-1]
    return text.rstrip(" ,") + "…"


def hladko(img, box, kresli, q=4):
    x0, y0, x1, y1 = box
    w, h = x1 - x0 + 4, y1 - y0 + 4
    vrstva = Image.new("RGBA", (w * q, h * q), (0, 0, 0, 0))
    kresli(ImageDraw.Draw(vrstva), q, 2 * q)
    img.alpha_composite(vrstva.resize((w, h), Image.LANCZOS), (x0 - 2, y0 - 2))


def vyrenderuj(k, sablona, cache):
    img = pozadie(sablona, k["okruh"])
    d = ImageDraw.Draw(img)
    p = sablona["prvky"]
    f = sablona["farby"]
    t = sablona["texty"]

    lg = logo(sablona)
    if lg:
        img.alpha_composite(lg, (sablona["logo"]["x"], sablona["logo"]["y"]))

    s = p["stitok"]
    fs = pismo(sablona, "normal", s["velkost"])
    text = t[k["format"]]
    v = s["vyska"]
    sirka = int(v * 0.42 + v * 0.55 + 14 + d.textlength(text, font=fs) + v * 0.5)
    r = int(v * 0.27)
    cx, cy = s["x"] + int(v * 0.5), s["y"] + v // 2

    def stitok(dd, q, o):
        dd.rounded_rectangle((o, o, o + sirka * q, o + v * q), radius=v * q // 2, fill=f["stitok_vypln"], outline=f["stitok_okraj"], width=2 * q)
        sx, sy = o + (cx - s["x"]) * q, o + (cy - s["y"]) * q
        dd.ellipse((sx - r * q, sy - r * q, sx + r * q, sy + r * q), fill=f["tlacidlo"])
        dd.polygon([(sx - r * q * 0.3, sy - r * q * 0.45), (sx - r * q * 0.3, sy + r * q * 0.45), (sx + r * q * 0.5, sy)], fill="#ffffff")

    hladko(img, (s["x"], s["y"], s["x"] + sirka, s["y"] + v), stitok)
    d.text((cx + r + 14, cy), text, font=fs, fill=f["text"], anchor="lm")

    s = p["okruh"]
    nazov_okruhu = sablona["nazvy_okruhov"].get(k["okruh"], "")
    if nazov_okruhu:
        d.text((s["x"], s["y"]), nazov_okruhu, font=pismo(sablona, "tucne", s["velkost"]), fill=f["akcent"])

    n = p["nazov"]
    velkost = n["velkost_max"]
    while True:
        fn = pismo(sablona, "tucne", velkost)
        riadky = zalom(d, k["nazov"], fn, n["sirka"])
        if len(riadky) <= n["max_riadkov"] or velkost <= n["velkost_min"]:
            break
        velkost -= 2
    if len(riadky) > n["max_riadkov"]:
        riadky = riadky[:n["max_riadkov"]]
        riadky[-1] = riadky[-1].rstrip(",;:") + "…"
    y = n["y"] if nazov_okruhu else p["okruh"]["y"]
    for riadok in riadky:
        d.text((n["x"], y), riadok, font=fn, fill=f["text"])
        y += int(velkost * n["riadkovanie"])

    s = p["lektor"]
    if k["lektor"]:
        tx = s["x"]
        if k["foto"]:
            vysledok = foto_kruh(k["foto"], s["priemer"], s["okraj"], cache)
            if vysledok:
                kruh, tien = vysledok
                img.alpha_composite(kruh, (s["x"] - tien, s["y"] - tien))
                tx = s["text_x"]
        stred = s["y"] + s["okraj"] + s["priemer"] // 2
        d.text((tx, stred - 30), t["skoli"], font=pismo(sablona, "tucne", 18), fill=f["akcent"], anchor="ls")
        fl = pismo(sablona, "tucne", s["velkost"])
        d.text((tx, stred + 18), skrat(d, k["lektor"], fl, s["sirka"] - (tx - s["x"])), font=fl, fill=f["text"], anchor="ls")

    d.line((p["datum"]["x"], p["ciara"]["y"], sablona["rozmer"][0] - p["datum"]["x"], p["ciara"]["y"]), fill=f["ciara"], width=2)

    s = p["datum"]
    d.text((s["x"], s["y"]), k["datum"], font=pismo(sablona, "tucne", s["velkost"]), fill=f["text"])
    s = p["poznamka"]
    poznamka = t["poznamka_online"] if k["format"] == "online" else t["poznamka_ine"]
    d.text((s["x"], s["y"]), poznamka, font=pismo(sablona, "normal", s["velkost"]), fill=f["seda"])

    s = p["tlacidlo"]
    hladko(img, (s["x"], s["y"], s["x"] + s["sirka"], s["y"] + s["vyska"]), lambda dd, q, o: dd.rounded_rectangle((o, o, o + s["sirka"] * q, o + s["vyska"] * q), radius=8 * q, fill=f["tlacidlo"]))
    d.text((s["x"] + s["sirka"] // 2, s["y"] + s["vyska"] // 2), s["text"], font=pismo(sablona, "tucne", s["velkost"]), fill="#ffffff", anchor="mm")
    return img.convert("RGB")


def nahlad(cesty, ciel, stlpce=5, velkost=300):
    riadky = (len(cesty) + stlpce - 1) // stlpce
    plocha = Image.new("RGB", (stlpce * velkost, max(1, riadky) * velkost), "white")
    for i, c in enumerate(cesty):
        plocha.paste(Image.open(c).resize((velkost, velkost)), ((i % stlpce) * velkost, (i // stlpce) * velkost))
    plocha.save(ciel, quality=85)


def galeria(polozky, ciel):
    karty = "".join(
        f'<figure><a href="img/{p["key"]}.png?v={p["verzia"]}"><img src="img/{p["key"]}.png?v={p["verzia"]}" loading="lazy"></a>'
        f'<figcaption><b>{p["okruh"]}</b> · {p["datum"]}<br>{p["nazov"]}</figcaption></figure>'
        for p in sorted(polozky, key=lambda x: (x["okruh"], x["dni_do"]))
    )
    html = (
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>PV katalóg</title><style>body{font-family:system-ui;margin:16px;background:#f4f4f5}"
        "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}"
        "figure{margin:0;background:#fff;padding:8px;border-radius:6px}img{width:100%;display:block}"
        "figcaption{font-size:12px;margin-top:6px}</style>"
        f"<h1>PV katalóg · {len(polozky)} školení · <a href='feed.csv'>feed.csv</a></h1><main>{karty}</main>"
    )
    with open(ciel, "w", encoding="utf-8") as f:
        f.write(html)


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

    riadky, obrazky, polozky = [], [], []
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
        with open(cesta, "rb") as f:
            k["verzia"] = hashlib.md5(f.read()).hexdigest()[:8]
        obrazky.append(cesta)
        polozky.append(k)
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
                "image_link": a.base_url.rstrip("/") + f"/img/{k['key']}.png?v={k['verzia']}",
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
    galeria(polozky, os.path.join(a.out, "index.html"))
    if a.nahlad and obrazky:
        nahlad(obrazky, os.path.join(a.out, "nahlad.jpg"))
    print(f"Hotovo: {len(obrazky)} obrázkov, {len(riadky)} riadkov feedu -> {a.out}")


if __name__ == "__main__":
    main()
