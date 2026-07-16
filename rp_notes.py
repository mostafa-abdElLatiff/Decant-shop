#!/usr/bin/env python3
"""Arabic note-name translations and dupe-reference brand splitting for
roseperfume.online product descriptions. Used by sync_roseperfume.py."""

NOTE_TRANSLATIONS = {
"أخشاب البتولا": "Birch", "أخشاب الغاياك": "Guaiac Wood", "أخشاب الكشمير": "Cashmere Wood",
"أشجار السرو": "Cypress", "أشجار السرور": "Cypress", "أكوازون": "Aquazone", "أمبروفيكس": "Ambrofix",
"أمبروكسان": "Ambroxan", "أوراق الأرز": "Cedar Leaves", "أوراق البنفسج": "Violet Leaf",
"أوراق القرفة": "Cinnamon Leaf", "إبرة الراعي": "Geranium", "إبره الراعي": "Geranium",
"إكليل الجبل": "Rosemary", "الآمبرغريس": "Ambergris", "الأترج": "Citron", "الأخشاب": "Woods",
"الأخشاب الطافية": "Driftwood", "الأرز": "Cedar", "الأزهار": "Flowers", "الأفسنتين نبات": "Wormwood",
"الألدهيدات": "Aldehydes", "الأمبروكسان": "Ambroxan", "الأمبريت": "Ambrette", "الأناناس": "Pineapple",
"الأوسمانثوس": "Osmanthus", "الإليمي": "Elemi", "الإيليمي": "Elemi", "الباتشولي": "Patchouli",
"الباتشولي الهندي": "Patchouli", "البتولا": "Birch", "البخور": "Incense", "البرتقال": "Orange",
"البرتقال الصقلي": "Sicilian Orange", "البرغموت": "Bergamot", "البرقوق": "Plum", "البطيخ": "Watermelon",
"البنزونين": "Benzoin", "البنزوين": "Benzoin", "البنزوين - الجاوي": "Benzoin", "البنفسج": "Violet",
"البيتي غران": "Petitgrain", "البيتيتغرين": "Petitgrain", "البيتيغرين": "Petitgrain", "التبغ": "Tobacco",
"التفاح": "Apple", "التفاح الأخضر": "Green Apple", "التوابل": "Spices", "التوفي": "Toffee",
"الجاوشير": "Galbanum", "الجريب فروت": "Grapefruit", "الجلبانوم": "Galbanum", "الجلد": "Leather",
"الجلد المدبوغ": "Leather", "الجلود": "Leather", "الحمضيات": "Citrus", "الخزامى": "Lavender",
"الخزامى البري": "Lavender", "الخزامي": "Lavender", "الخشب الأبيض": "White Wood", "الخوخ": "Peach",
"الخوخ الأبيض": "White Peach", "الدافانا": "Davana", "الدخان": "Smoke", "الروائح الشرقيه": "Oriental",
"الزعرور البري": "Hawthorn", "الزعفران": "Saffron", "الزنبق نجيل الهند": "Lily",
"الزنجبيل": "Ginger", "الزنجبيل النيجيري": "Ginger", "الزهر": "Orange Blossom", "السرو": "Cypress",
"السكر": "Sugar", "السوسن": "Iris", "الشاي الأخضر": "Green Tea", "الشيح": "Wormwood",
"الشيكولاته الداكنة": "Dark Chocolate", "الطحالب": "Moss", "الطحلب": "Moss", "العرعر": "Juniper",
"العرقسوس": "Licorice", "العشب": "Grass", "العطر الهيل": "Cardamom", "العنبر": "Amber",
"العنبر الخفيف": "Amber", "العنبر الرمادي": "Ambergris", "العنبر خشب الصندل": "Amber",
"العود": "Oud", "الغالابانوم": "Galbanum", "الفانيليا": "Vanilla", "الفانيليا الدافئة": "Vanilla",
"الفلفل": "Pepper", "الفلفل الأسود": "Black Pepper", "الفلفل الحار": "Pepper",
"الفلفل الحلو الاسباني": "Pepper", "الفلفل الوردي": "Pink Pepper", "الفيتيفر": "Vetiver",
"القرفة": "Cinnamon", "القرفه": "Cinnamon", "القرنفل": "Clove", "الكاموميل": "Chamomile",
"الكراميل": "Caramel", "الكزبرة": "Coriander", "الكستناء": "Chestnut", "الكشمش الأسود": "Blackcurrant",
"الكمثرى": "Pear", "الكمثري": "Pear", "الكمون": "Cumin", "اللابدانوم": "Labdanum",
"اللافندر": "Lavender", "اللبان": "Frankincense", "اللبلاب": "Ivy", "الليم": "Lime",
"الليمون": "Lemon", "المالتول": "Maltol", "الماندرين (اليوسفي)": "Mandarin", "المريمية": "Sage",
"المستكة": "Mastic", "المسك": "Musk", "المسك الأبيض": "White Musk", "الملح": "Salt",
"النعناع": "Mint", "النفحات الخشبية": "Woody Notes", "النوتات الترابية": "Earthy",
"النوتات الخضراء": "Green Notes", "النوتات المعدنية": "Metallic", "النيرولي": "Neroli",
"الهيل": "Cardamom", "الورد": "Rose", "الورد الصخري": "Rockrose", "الياسمين": "Jasmine",
"الياسمين المغربي": "Jasmine", "اليانسون النجمي": "Star Anise", "الينسون": "Anise",
"اليوزو الياباني": "Yuzu", "اليوسفي": "Tangerine", "اليوسفي الأحمر": "Tangerine",
"اليوسفي الأخضر": "Tangerine", "باتشولي": "Patchouli", "بذور اليانسون": "Anise",
"برغموت كالابريا": "Bergamot", "برقوق": "Plum", "بشر الليمون": "Lemon Zest", "بلسم تولو": "Tolu Balsam",
"تانجرين (اليوسفي)": "Tangerine", "تتكون من أخشاب الغاياك": "Guaiac Wood",
"تتكون من أخشاب الكشمير": "Cashmere Wood", "تتكون من إكليل الجبل": "Rosemary",
"تتكون من الأمبروكسان": "Ambroxan", "تتكون من الأمبريت": "Ambrette", "تتكون من الباتشولي": "Patchouli",
"تتكون من البخور": "Incense", "تتكون من الجلود": "Leather", "تتكون من الشاي الصيني الأسود": "Black Tea",
"تتكون من العنبر": "Amber", "تتكون من العنبر المسك": "Amber", "تتكون من الفانيليا": "Vanilla",
"تتكون من اللبان": "Frankincense", "تتكون من المسك": "Musk", "تتكون من جزئ الكالون": "Calone",
"تتكون من حبوب التونكا": "Tonka Bean", "تتكون من خشب الأرز": "Cedarwood", "تتكون من نجيل الهند": "Lemongrass",
"ثمار التين": "Fig", "ثمار الغابات": "Forest Fruits", "جريب فروت": "Grapefruit",
"جوز الهند": "Coconut", "جوزة الطيب": "Nutmeg", "جوزه الطيب": "Nutmeg", "حبوب التونكا": "Tonka Bean",
"حبوب التونكا و المسك": "Tonka Bean", "حلوى الكراميل": "Caramel", "حلوي اللوز": "Almond",
"خشب أكيجالا": "Akigalawood", "خشب الأرز": "Cedarwood", "خشب الصندل": "Sandalwood",
"خشب الطفو": "Driftwood", "خشب العنبر": "Amberwood", "خشب الكشمير": "Cashmere Wood",
"خشب الورد": "Rosewood", "خشبية": "Woody", "رائحه التوابل": "Spices", "رائحه الماء": "Aquatic Notes",
"راتنج الإليمي": "Elemi", "روائح البحر": "Marine Notes", "روائح خشبية": "Woody",
"روائح معدنية": "Metallic", "زنابق الوادي": "Lily of the Valley", "زنبق الوادي": "Lily of the Valley",
"زهر البرتقال": "Orange Blossom", "زهر البرتقال التونسي": "Orange Blossom",
"زهر الجريب فروت": "Grapefruit Blossom", "زهر العسل - صريمة الجدي": "Honeysuckle",
"زهر جوزه الطيب": "Nutmeg", "زهرة البرتقال": "Orange Blossom", "زهرة اللوتس الزرقاء": "Blue Lotus",
"زهرة الليمون": "Lemon Blossom", "زهور السوسن (آيريس)": "Iris", "شجرة أجار": "Agarwood",
"شمام": "Melon", "طحلب البلوط": "Oakmoss", "طحلب البلوط (طحلب السنديان)": "Oakmoss",
"طحلب السنديان": "Oakmoss", "عشب الليمون": "Lemongrass", "عنبر": "Amber",
"فانيليا بوربون": "Vanilla", "فلفل تايمور": "Timur Pepper", "فلفل سيشوان": "Sichuan Pepper",
"فول التونكا": "Tonka Bean", "قرفة سيلان": "Cinnamon", "لافندر": "Lavender", "لبان": "Frankincense",
"ماء": "Aquatic Notes", "ماء جوز الهند": "Coconut Water", "مسك": "Musk", "مسك الروم": "Musk",
"ملاحظات مائية": "Aquatic Notes", "من الفانيليا": "Vanilla", "نجيل الهند": "Lemongrass",
"نفحات بحرية": "Marine Notes", "نفحات خشبية": "Woody Notes", "نفحات شرقية": "Oriental",
"نفحات مائية": "Aquatic Notes", "نوتات خشبية": "Woody Notes", "نوتات شمسية": "Solar Notes",
"هيل": "Cardamom",
}

KNOWN_BRANDS = [
    "Yves Saint Laurent", "Giorgio Armani", "Parfums de Marly", "Maison Francis Kurkdjian",
    "Louis Vuitton", "Jean Paul Gaultier", "Tom Ford", "Hugo Boss", "Dolce Gabbana",
    "Dolce & Gabbana", "Roja Dove", "Xerjoff", "Nishane", "Amouage", "Creed", "Dior",
    "Chanel", "Guerlain", "Versace", "Gucci", "Prada", "Valentino", "Burberry", "Montblanc",
    "Rabanne", "Paco Rabanne", "Azzaro", "Bvlgari", "Cartier", "Armani", "Calvin Klein",
    "Issey Miyake", "Kenzo", "Lacoste", "Ferrari", "Montale", "Mancera", "By Kilian",
    "Initio", "Memo Paris",
]


def translate_note(raw: str):
    return NOTE_TRANSLATIONS.get(raw.strip())


def split_dupe(raw: str):
    """Best-effort split of 'Name Brand' into 'Name — Brand'."""
    if not raw:
        return None
    raw = raw.strip()
    for brand in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if raw.endswith(brand):
            name = raw[: -len(brand)].strip()
            if name:
                return f"{name} — {brand}"
    return raw
