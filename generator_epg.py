import urllib.request
import gzip
import xml.etree.ElementTree as ET
import json
import re
from datetime import datetime

# Zdroje EPG pre slovenský a český trh
SOURCES = [
    "https://epgshare01.online/epgshare01/epg_ripper_CZ1.xml.gz",
    "https://epgshare01.online/epgshare01/epg_ripper_SK1.xml.gz"
]

# PRESNÉ IDčka vytiahnuté z tvojho pátračského testu
TARGET_CHANNELS = {
    "Minimax.cz": "Minimax",
    "Prima.cz": "Prima",
    "Prima.Star.cz": "Prima star",
    "Prima.LOVE.cz": "Prima Love",
    "ČT.sport.cz": "ČT Sport",
    "Senzi.sk": "Senzi",
    "Óčko.cz": "Óčko (540p)",
    "Prima.ZOOM.cz": "Prima ZOOM",
    "Disney.Channel.cz": "Disney Channel",
# Trik: Obe oddelené ČT stanice zlúčime pod jeden názov
    "ČT.:D.cz": "ČT :D / ČT art",
    "ČT.art.cz": "ČT :D / ČT art",
    "Barrandov.Krimi.HD.sk": "Barrandov Krimi",
    "AXN.White.cz": "AXN White"
}

def stiahni_filmbox_stars():
    """Špeciálna funkcia, ktorá vytiahne program pre FilmBox Stars priamo z webu.

    POZNÁMKA (aktualizované): Stránka tvprogram.centrum.cz medzičasom zmenila markup -
    názvy programov už nie sú obalené v <a> tagu, takže pôvodný regex na <a>...</a>
    nikdy nič nenašiel a funkcia vracala prázdny zoznam. Táto verzia nezávisí na
    konkrétnych HTML tagoch: odstráni všetky tagy a parsuje čistý text podľa vzoru
    "ČAS -> [voliteľný label film/seriál] -> NÁZOV". Navyše správne rozlišuje
    sekcie "Dnes"/"Zítra" na stránke a páruje s nimi správny dátum (predtým sa
    aj zajtrajším časom priraďoval dnešný dátum).
    """
    print("-> Sťahujem a analyzujem alternatívny zdroj: FilmBox Stars (tvprogram.centrum.cz)")
    url = "https://tvprogram.centrum.cz/stanice/filmbox-stars"
    program_data = []

    now = datetime.now()
    current_year = now.year
    aktualny_den = now.strftime("%Y%m%d")  # fallback, ak by sa header dňa nenašiel

    day_header_re = re.compile(r'^(Dnes|Zítra|Včera)\s*(\d{1,2})\.\s*(\d{1,2})\.$')
    time_re = re.compile(r'^\d{2}:\d{2}$')
    skip_labels = {'film', 'seriál', 'serial', 'dokument', 'sport'}

    try:
        # Tvarujeme sa ako prehliadač Chrome, aby nás stránka nezablokovala
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8')

        # Odstránime <script>/<style> blok, aby sa do textu nezamiešal JS/CSS kód
        html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.S | re.I)

        # Odstránime všetky HTML tagy a nahradíme ich novým riadkom (zachová poradie textu)
        text = re.sub(r'<[^>]+>', '\n', html)
        lines = [l.strip() for l in text.split('\n')]
        lines = [l for l in lines if l]

        i = 0
        while i < len(lines):
            line = lines[i]

            # Sekcia "Dnes21. 6." / "Zítra22. 6." -> nastaví aktuálny dátum pre ďalšie záznamy
            day_match = day_header_re.match(line)
            if day_match:
                day = int(day_match.group(2))
                month = int(day_match.group(3))
                aktualny_den = f"{current_year}{month:02d}{day:02d}"
                i += 1
                continue

            if time_re.match(line):
                cas = line
                j = i + 1
                # Preskočíme prípadný label "film"/"seriál" medzi časom a názvom
                while j < len(lines) and lines[j].lower() in skip_labels:
                    j += 1

                if j < len(lines) and not time_re.match(lines[j]) and not day_header_re.match(lines[j]):
                    nazov = lines[j]
                    if nazov and len(nazov) > 1 and "Zobrazit" not in nazov:
                        cas_xml = f"{aktualny_den}{cas.replace(':', '')}00 +0200"
                        program_data.append({
                            "start": cas_xml,
                            "stop": "",  # Stop čas doplníme v ďalšom kroku
                            "title": nazov,
                            "desc": ""
                        })
                    i = j + 1
                    continue

            i += 1

        # Keďže z webu nevieme, kedy film presne končí, stop čas nastavíme na začiatok ďalšieho programu
        for i in range(len(program_data)):
            if i < len(program_data) - 1:
                program_data[i]["stop"] = program_data[i + 1]["start"]
            else:
                # Poslednému nočnému programu pridáme orientačne 2 hodiny
                st = program_data[i]["start"]
                hodina = (int(st[8:10]) + 2) % 24
                program_data[i]["stop"] = f"{st[:8]}{hodina:02d}{st[10:]}"

    except Exception as e:
        print(f"[!] Chyba pri ťahaní FilmBox Stars z webu: {e}")

    return program_data


def vygeneruj_epg():
    print("[*] Spúšťam generovanie kompletného EPG...")
    
    # Príprava prázdnych zoznamov
    vysledne_epg = {display_name: [] for display_name in TARGET_CHANNELS.values()}
    
    # 1. Stiahneme FilmBox Stars z webu
    vysledne_epg["FilmBox Stars Czech"] = stiahni_filmbox_stars()
    
    dnesny_datum = datetime.now().strftime("%Y%m%d")

    # 2. Vytiahneme ostatné stanice z XML balíkov
    for url in SOURCES:
        print(f"-> Sťahujem a analyzujem XML zdroj: {url.split('/')[-1]}")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                with gzip.GzipFile(fileobj=response) as unzipped:
                    
                    context = ET.iterparse(unzipped, events=('end',))
                    
                    for event, elem in context:
                        if elem.tag == 'programme':
                            channel_id = elem.get('channel')
                            
                            # Kontrola s našimi presnými IDčkami
                            if channel_id in TARGET_CHANNELS:
                                display_name = TARGET_CHANNELS[channel_id]
                                start_time = elem.get('start')
                                stop_time = elem.get('stop')
                                
                                # Berieme len od dnešného dňa
                                if start_time and start_time[:8] >= dnesny_datum:
                                    title = elem.find('title').text if elem.find('title') is not None else "Neznámy program"
                                    desc = elem.find('desc').text if elem.find('desc') is not None else ""
                                    
                                    vysledne_epg[display_name].append({
                                        "start": start_time,
                                        "stop": stop_time,
                                        "title": title,
                                        "desc": desc
                                    })
                            
                            elem.clear()
                            
        except Exception as e:
            print(f"[!] Chyba pri spracovaní zdroja {url}: {e}")

    # 3. Zoradíme všetky stanice chronologicky podľa času začiatku.
    #    Dôležité najmä pre zlúčené kanály ako "ČT :D / ČT art" (dve rôzne EPG ID
    #    v rámci jedného display name), ale robíme to pre istotu pre všetky stanice.
    for nazov_stanice in vysledne_epg:
        vysledne_epg[nazov_stanice].sort(key=lambda p: p["start"][:14])

    # 4. Uložíme všetko do mini JSON súboru
    output_filename = "epg.json"
    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(vysledne_epg, f, ensure_ascii=False, indent=2)
        print(f"[✓] Hotovo! Všetky stanice (vrátane Óčka a FilmBox Stars) sú uložené v: {output_filename}")
    except Exception as e:
        print(f"[!] Nepodarilo sa zapísať súbor: {e}")

if __name__ == "__main__":
    vygeneruj_epg()
