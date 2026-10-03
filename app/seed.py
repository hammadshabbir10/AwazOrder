"""Demo data: one distributor account, a product catalogue and a few shops.

Prices are illustrative demo values in PKR, not real trade prices.
"""

DEMO_USER = {
    "email": "demo@awazorder.pk",
    "password": "Demo@1234",
    "name": "Awaz Demo Distributors",
}

# sku, name, unit, price (PKR per unit), aliases (Roman Urdu / Urdu / English)
PRODUCTS = [
    ("SHAN-BIRYANI", "Shan Biryani Masala 50g", "carton", 9500, ["shan biryani", "biryani masala", "biryani", "بریانی", "شان بریانی"]),
    ("SHAN-PULAO", "Shan Pulao Biryani Masala 50g", "carton", 9200, ["shan pulao", "pulao masala", "pulao", "پلاؤ"]),
    ("SHAN-KARAHI", "Shan Chicken Karahi Masala 50g", "carton", 8800, ["karahi masala", "shan karahi", "karahi", "کڑاہی"]),
    ("SHAN-NIHARI", "Shan Nihari Masala 60g", "carton", 9800, ["nihari masala", "nihari", "نہاری"]),
    ("NATIONAL-BIRYANI", "National Biryani Masala 39g", "carton", 7800, ["national biryani", "national masala"]),
    ("DALDA-TIN", "Dalda Banaspati Ghee 5kg Tin", "tin", 2950, ["dalda", "dalda tin", "dalda ghee", "ڈالڈا", "ghee tin"]),
    ("DALDA-OIL", "Dalda Cooking Oil 1L Pouch", "carton", 6600, ["dalda oil", "dalda cooking oil", "cooking oil"]),
    ("SUFI-OIL", "Sufi Cooking Oil 1L", "carton", 6500, ["sufi", "sufi oil", "صوفی"]),
    ("MEZAN-GHEE", "Mezan Banaspati Ghee 1kg", "carton", 5200, ["mezan", "mezan ghee", "میزان"]),
    ("TAPAL-DANEDAR", "Tapal Danedar Tea 950g", "pack", 1650, ["tapal", "tapal danedar", "danedar", "ٹپال", "chai patti"]),
    ("LIPTON-YL", "Lipton Yellow Label Tea 950g", "pack", 1700, ["lipton", "yellow label", "لپٹن"]),
    ("VITAL-TEA", "Vital Tea 950g", "pack", 1500, ["vital", "vital chai", "وائٹل"]),
    ("MILKPAK-1L", "Nestle Milkpak 1L", "carton", 3900, ["milkpak", "milk pak", "nestle milk", "doodh", "دودھ", "ملک پیک"]),
    ("OLPERS-1L", "Olper's Milk 1L", "carton", 3850, ["olpers", "olper", "اولپرز"]),
    ("TARANG-1L", "Tarang Tea Whitener 1L", "carton", 3300, ["tarang", "ترنگ"]),
    ("BASMATI-5KG", "Super Kernel Basmati Rice 5kg", "bag", 2400, ["basmati", "super kernel", "chawal", "چاول", "rice"]),
    ("SELLA-25KG", "Sella Rice 25kg", "bori", 9500, ["sella", "sella chawal", "سیلا"]),
    ("SUGAR-50KG", "Sugar 50kg", "bori", 7800, ["cheeni", "chini", "sugar", "چینی"]),
    ("ATTA-20KG", "Sunridge Chakki Atta 20kg", "bag", 2900, ["atta", "aata", "sunridge", "آٹا"]),
    ("DAAL-CHANA", "Daal Chana", "kg", 290, ["daal chana", "dal chana", "chana daal", "دال چنا"]),
    ("DAAL-MASOOR", "Daal Masoor", "kg", 330, ["daal masoor", "dal masoor", "masoor", "مسور"]),
    ("SALT-800G", "National Iodized Salt 800g", "carton", 1250, ["namak", "salt", "نمک"]),
    ("RED-CHILLI", "National Red Chilli Powder 200g", "carton", 6000, ["lal mirch", "red chilli", "mirch", "مرچ"]),
    ("HALDI", "National Haldi Powder 200g", "carton", 4200, ["haldi", "turmeric", "ہلدی"]),
    ("PEPSI-1.5L", "Pepsi 1.5L", "carton", 1100, ["pepsi", "پیپسی"]),
    ("COKE-1.5L", "Coca-Cola 1.5L", "carton", 1100, ["coke", "coca cola", "کوک"]),
    ("SPRITE-1.5L", "Sprite 1.5L", "carton", 1100, ["sprite", "سپرائٹ"]),
    ("WATER-1.5L", "Nestle Pure Life 1.5L", "carton", 600, ["pani", "water", "nestle water", "پانی"]),
    ("SURF-EXCEL", "Surf Excel 1kg", "carton", 6600, ["surf", "surf excel", "سرف"]),
    ("ARIEL", "Ariel 1kg", "carton", 6900, ["ariel", "ایریل"]),
    ("LIFEBUOY", "Lifebuoy Soap 110g", "carton", 8200, ["lifebuoy", "sabun", "صابن", "لائف بوائے"]),
    ("LUX", "Lux Soap 110g", "carton", 9000, ["lux", "لکس"]),
    ("SAFEGUARD", "Safeguard Soap 115g", "carton", 9300, ["safeguard", "سیف گارڈ"]),
    ("SUNSILK", "Sunsilk Shampoo 160ml", "carton", 8400, ["sunsilk", "shampoo", "شیمپو"]),
    ("COLGATE", "Colgate Toothpaste 100g", "carton", 9600, ["colgate", "toothpaste", "manjan", "کولگیٹ"]),
    ("LU-PRINCE", "LU Prince Biscuit", "carton", 1100, ["prince", "prince biscuit", "پرنس"]),
    ("LU-CANDI", "LU Candi Biscuit", "carton", 1100, ["candi", "کینڈی"]),
    ("LU-TUC", "LU TUC Biscuit", "carton", 1150, ["tuc", "ٹک"]),
    ("KOLSON-SLANTY", "Kolson Slanty", "carton", 1300, ["slanty", "kolson", "سلانٹی"]),
    ("KNORR-NOODLES", "Knorr Chicken Noodles", "carton", 4500, ["noodles", "knorr", "نوڈلز"]),
]

# name, area, phone, opening balance (PKR owed to distributor)
SHOPS = [
    ("Bismillah General Store", "Satellite Town, Rawalpindi", "0300-0000001", 18500),
    ("Madina Karyana", "G-9 Markaz, Islamabad", "0300-0000002", 7200),
    ("Al-Rehman Traders", "Saddar, Rawalpindi", "0300-0000003", 0),
    ("Faisal Super Store", "I-8 Markaz, Islamabad", "0300-0000004", 32400),
    ("Usman Karyana", "Committee Chowk, Rawalpindi", "0300-0000005", 4100),
    ("Chaudhry Mart", "Bahria Phase 7, Rawalpindi", "0300-0000006", 0),
]
