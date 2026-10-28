"""
Normalization constants and lookup tables.

Canonical values for states, crops, categories, and their aliases.
Used by the normalizer to convert variant spellings to canonical forms.
"""

# ============================================================
# CANONICAL INDIAN STATES
# ============================================================

CANONICAL_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab",
    "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    # Union Territories
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh",
    "Lakshadweep", "Puducherry",
]

STATE_ALIASES = {
    "ap": "Andhra Pradesh",
    "andhra": "Andhra Pradesh",
    "ar": "Arunachal Pradesh",
    "as": "Assam",
    "br": "Bihar",
    "cg": "Chhattisgarh",
    "chattisgarh": "Chhattisgarh",
    "chhatisgarh": "Chhattisgarh",
    "ga": "Goa",
    "gj": "Gujarat",
    "hr": "Haryana",
    "hp": "Himachal Pradesh",
    "jh": "Jharkhand",
    "ka": "Karnataka",
    "karnatak": "Karnataka",
    "karnataka state": "Karnataka",
    "kl": "Kerala",
    "mp": "Madhya Pradesh",
    "mh": "Maharashtra",
    "mn": "Manipur",
    "ml": "Meghalaya",
    "mz": "Mizoram",
    "nl": "Nagaland",
    "or": "Odisha",
    "orissa": "Odisha",
    "pb": "Punjab",
    "rj": "Rajasthan",
    "sk": "Sikkim",
    "tn": "Tamil Nadu",
    "tamilnadu": "Tamil Nadu",
    "ts": "Telangana",
    "tr": "Tripura",
    "up": "Uttar Pradesh",
    "uk": "Uttarakhand",
    "uttaranchal": "Uttarakhand",
    "wb": "West Bengal",
    "dl": "Delhi",
    "jk": "Jammu and Kashmir",
    "j&k": "Jammu and Kashmir",
    "la": "Ladakh",
    "ch": "Chandigarh",
    "py": "Puducherry",
    "pondicherry": "Puducherry",
}

# ============================================================
# CANONICAL CROPS
# ============================================================

CANONICAL_CROPS = [
    "rice", "wheat", "maize", "ragi", "jowar", "bajra",
    "cotton", "sugarcane", "groundnut", "soybean",
    "mustard", "sunflower", "sesame", "linseed",
    "pulses", "tur", "moong", "urad", "chana", "masur",
    "potato", "onion", "tomato", "chilli",
    "banana", "mango", "coconut", "arecanut",
    "tea", "coffee", "rubber", "cardamom", "pepper",
    "jute", "tobacco", "oilseeds", "millets",
    "vegetables", "fruits", "spices", "horticulture",
]

CROP_ALIASES = {
    "finger millet": "ragi",
    "nachni": "ragi",
    "mandua": "ragi",
    "sorghum": "jowar",
    "great millet": "jowar",
    "pearl millet": "bajra",
    "corn": "maize",
    "makka": "maize",
    "paddy": "rice",
    "dhan": "rice",
    "chawal": "rice",
    "gehu": "wheat",
    "gehun": "wheat",
    "kapas": "cotton",
    "ganna": "sugarcane",
    "moongphali": "groundnut",
    "peanut": "groundnut",
    "sarson": "mustard",
    "til": "sesame",
    "alsi": "linseed",
    "arhar": "tur",
    "pigeon pea": "tur",
    "green gram": "moong",
    "mung": "moong",
    "black gram": "urad",
    "chickpea": "chana",
    "gram": "chana",
    "bengal gram": "chana",
    "red lentil": "masur",
    "lentil": "masur",
    "aloo": "potato",
    "pyaaz": "onion",
    "tamatar": "tomato",
    "mirch": "chilli",
    "kela": "banana",
    "aam": "mango",
    "nariyal": "coconut",
    "supari": "arecanut",
    "chai": "tea",
}

# ============================================================
# CANONICAL SOCIAL CATEGORIES
# ============================================================

CANONICAL_CATEGORIES = ["General", "OBC", "SC", "ST", "Minority", "EWS"]

CATEGORY_ALIASES = {
    "general": "General",
    "gen": "General",
    "obc": "OBC",
    "other backward class": "OBC",
    "other backward classes": "OBC",
    "sc": "SC",
    "scheduled caste": "SC",
    "scheduled castes": "SC",
    "st": "ST",
    "scheduled tribe": "ST",
    "scheduled tribes": "ST",
    "minority": "Minority",
    "minorities": "Minority",
    "ews": "EWS",
    "economically weaker section": "EWS",
    "economically weaker sections": "EWS",
}

# ============================================================
# GENDER VALUES
# ============================================================

CANONICAL_GENDERS = ["male", "female", "any", "unknown"]

GENDER_ALIASES = {
    "m": "male",
    "f": "female",
    "all": "any",
    "both": "any",
    "men": "male",
    "women": "female",
    "woman": "female",
    "man": "male",
}

# ============================================================
# KNOWN OFFICIAL DOMAINS
# ============================================================

OFFICIAL_DOMAINS = {
    "myscheme.gov.in": "OFFICIAL_SCHEME_PORTAL",
    "pmkisan.gov.in": "OFFICIAL_CENTRAL",
    "pmfby.gov.in": "OFFICIAL_CENTRAL",
    "agricoop.nic.in": "OFFICIAL_CENTRAL",
    "agriculture.gov.in": "OFFICIAL_CENTRAL",
    "dahd.nic.in": "OFFICIAL_CENTRAL",
    "rural.nic.in": "OFFICIAL_CENTRAL",
    "nrega.nic.in": "OFFICIAL_CENTRAL",
    "india.gov.in": "OFFICIAL_CENTRAL",
    "pib.gov.in": "OFFICIAL_CENTRAL",
    "dbt.gov.in": "OFFICIAL_CENTRAL",
    "vikaspedia.in": "SECONDARY",
}
