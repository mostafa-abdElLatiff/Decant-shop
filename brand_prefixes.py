#!/usr/bin/env python3
"""Shared brand-name recognition for stores whose product titles are plain
text like "Brand Fragrance Name" with no separate structured brand field
(MO Shawky, Sniffz). Extend BRAND_PREFIXES/ABBREVIATIONS if a sync script
keeps landing products with brand="" — check with find_duplicates.py or a
quick spot-check of the run's output rather than assuming this is exhaustive.
"""

BRAND_PREFIXES = [
    "Essential Parfums", "Alfred Dunhill", "Dunhill", "Paco Rabanne", "Parfums de Marly",
    "Maison Francis Kurkdjian", "Maison Alhambra", "Dolce & Gabbana", "Dolce&Gabbana", "D&G",
    "Giorgio Armani", "Emporio Armani", "Yves Saint Laurent", "Jean Paul Gaultier", "Tom Ford",
    "Hugo Boss", "Roja Dove", "Xerjoff", "Nishane", "Amouage", "Creed",
    "Dior", "Chanel", "Guerlain", "Versace", "Gucci", "Prada", "Valentino",
    "Burberry", "Mont Blanc", "Montblanc", "Rabanne", "Azzaro", "Bvlgari", "Cartier",
    "Armani", "Calvin Klein", "Issey Miyake", "Kenzo", "Lacoste", "Ferrari",
    "Montale", "Mancera", "By Kilian", "Initio", "Memo Paris",
    "Elizabeth Arden", "Davidoff", "Givenchy", "CH", "Rayhaan", "Assaf",
    "Le Bonheur", "Lattafa", "Armaf", "Rasasi", "Khadlaj", "Afnan",
    "French Avenue", "Zimaya", "Ard Al Zaafaran", "Arabiyat Prestige",
    "Fragrance World", "Ghalati", "Al Rehab", "AL-REHAB", "Emper",
    "Smart Collection", "La Sera", "Milestone", "Pendora Scents", "Camara",
    "Mirada", "Wadi Al Khaleej", "Laverne", "Omanluxury", "Sospiro",
    "Roberto Cavalli", "Lancôme", "Lancome", "Narciso Rodriguez", "Mugler",
    "Nautica", "Missoni", "Hermès", "Hermes", "Nina Ricci", "Rochas",
    "Guy Laroche", "Mercedes-Benz", "Mercedes Benz", "John Varvatos",
    "Lalique", "Bentley", "Boucheron", "Guess",
    "Carolina Herrera", "Roger & Gallet", "Ahmed Al Maghribi", "Arabian Oud",
    "SF Uomo", "Chopard", "Viktor&Rolf", "Viktor & Rolf", "Zadig & Voltaire",
    "Jacques Bogart", "Coach", "Michael Kors", "Salvatore Ferragamo",
    "Bottega Veneta", "Chloé", "Chloe", "Diesel", "Moschino", "Trussardi",
    "JPG", "YSL", "Rosendo Mateu", "Louis Vuitton", "Kilian", "Killian",
    "By Killian", "Orto Parisi", "Nasomatto", "Penhaligon's", "Penhaligons",
    "Maison Martin Margiela", "Maison Margiela", "Stéphane Humbert Lucas 777",
    "Stephane Humbert Lucas 777", "Stéphane Humbert Lucas",
    "Stephane Humbert Lucas", "Room 1015", "Kayali", "Goldfield & Banks",
    "Nikos", "Ibraheem AlQurashi", "Ibraheem Al Qurashi", "Al-Ezz",
    "Al-Ezz for Oud", "Gissah", "Aromatix", "Giardini Di Toscana",
    "Bond No 9", "Bond No. 9", "Maison Asrar", "SpongeBob", "Spongebob",
    "Riffs", "Riiffs", "Iven", "Vitality", "Troove", "BORNTOSTANDOUT",
    "MPF", "Le Falconé", "Le Falcone", "Nina Ricci",
]

# Some titles use an abbreviation or alt spelling — normalize to the same
# brand name the rest of the catalog uses.
ABBREVIATIONS = {
    "JPG": "Jean Paul Gaultier", "YSL": "Yves Saint Laurent",
    "D&G": "Dolce & Gabbana", "Dolce&Gabbana": "Dolce & Gabbana",
    "Dunhill": "Alfred Dunhill", "Montblanc": "Mont Blanc",
    "Lancome": "Lancôme", "Hermes": "Hermès",
    "Mercedes-Benz": "Mercedes Benz",
    "Riiffs": "Riffs", "Le Falcone": "Le Falconé Perfumes",
    "Le Falconé": "Le Falconé Perfumes",
}


def split_brand_prefix(name: str):
    """If `name` starts with a known brand, return (rest, canonical_brand).
    Otherwise return (name, "")."""
    for brand in sorted(BRAND_PREFIXES, key=len, reverse=True):
        if name.lower().startswith(brand.lower() + " "):
            return name[len(brand):].strip(), ABBREVIATIONS.get(brand, brand)
    return name, ""


def split_brand_suffix(name: str):
    """If `name` ends with a known brand, return (rest, canonical_brand).
    Otherwise return (name, "")."""
    for brand in sorted(BRAND_PREFIXES, key=len, reverse=True):
        if name.lower().endswith(" " + brand.lower()):
            return name[: -len(brand)].strip(), ABBREVIATIONS.get(brand, brand)
    return name, ""
