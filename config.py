"""
OneCode AI - Configuration.
CPSE list and material-category ontology live here, separate from matching logic,
so they can be edited without touching pipeline code (spec requirement: "configurable
rather than hard-coded").
"""

# ---------------- CPSEs (configurable) ----------------
CPSE_LIST = ["ONGC", "CPCL", "GAIL", "IOCL", "BPCL", "HPCL", "NTPC", "SAIL", "BHEL"]

# ---------------- Material category ontology (configurable) ----------------
# Each category defines: critical attributes (hard-block if they differ),
# structural attributes (used for attribute-agreement scoring), and family
# hints (real variant differences that should be "Similar", not "Duplicate").
CATEGORY_ONTOLOGY = {
    "Bearing": {
        "critical_attrs": [],
        "structural_attrs": ["material", "norm_dimension", "standard"],
        "family_hints": ["OPEN", "SEALED", "SHIELDED", "2RS", "ZZ"],
        "spec_template": ["category", "norm_dimension", "material", "standard"],
    },
    "Fastener": {
        "critical_attrs": ["grade"],
        "structural_attrs": ["material", "norm_dimension", "standard", "grade"],
        "family_hints": [],
        "spec_template": ["category", "norm_dimension", "material", "standard", "grade"],
    },
    "Pipe": {
        "critical_attrs": ["grade", "pressure_rating"],
        "structural_attrs": ["material", "norm_dimension", "standard", "grade", "pressure_rating"],
        "family_hints": ["THREADED", "WELDED", "FLANGED"],
        "spec_template": ["category", "norm_dimension", "material", "standard", "grade", "pressure_rating"],
    },
    "Valve": {
        "critical_attrs": ["pressure_rating"],
        "structural_attrs": ["material", "norm_dimension", "standard", "pressure_rating"],
        "family_hints": [],
        "spec_template": ["category", "norm_dimension", "material", "standard", "pressure_rating"],
    },
    "Cable": {
        "critical_attrs": ["voltage_rating"],
        "structural_attrs": ["material", "norm_dimension", "standard", "voltage_rating"],
        "family_hints": [],
        "spec_template": ["category", "norm_dimension", "material", "standard", "voltage_rating"],
    },
    # New categories can be added here without touching pipeline.py, e.g.:
    # "Pump": {"critical_attrs": [...], "structural_attrs": [...], "family_hints": [...], "spec_template": [...]},
}

DEFAULT_ONTOLOGY = {
    "critical_attrs": [],
    "structural_attrs": ["material", "norm_dimension"],
    "family_hints": [],
    "spec_template": ["category", "norm_dimension", "material", "standard"],
}

def get_ontology(category):
    return CATEGORY_ONTOLOGY.get(category, DEFAULT_ONTOLOGY)

BRAND_KEYWORDS = ["SKF", "FAG", "NSK", "TIMKEN", "NTN"]

CNMC_PREFIX = {  # OneCode category prefixes
    "Bearing": "BRG", "Fastener": "FST", "Pipe": "PIP",
    "Valve": "VLV", "Cable": "CBL",
}

ABBREVIATIONS = {
    r"\bBRG\b": "BEARING", r"\bDGBB\b": "DEEP GROOVE BALL BEARING",
    r"\bBLT\b": "BOLT", r"\bGR\b": "GRADE", r"\bGR\.": "GRADE",
    r"\bSS\b": "STAINLESS STEEL", r"\bCS\b": "CARBON STEEL",
    r"\bHEX\b": "HEXAGONAL", r"\bSQMM\b": "SQ MM",
    r"\bCLASS(\d)": r"CLASS \1",
}

UNIT_TO_BASE = {"mm": 1.0, "inch": 25.4, "model": None, "sqmm": 1.0}

# ---------------- Column auto-mapping synonyms (for Data Onboarding) ----------------
# Maps our internal schema field -> list of column-name variants seen in real
# exports (SAP field codes, common CSV headers, etc.)
FIELD_SYNONYMS = {
    "material_code": ["material_code", "matnr", "code", "item code", "part number", "sku", "material no", "item_code"],
    "raw_description": ["raw_description", "description", "maktx", "desc", "item description", "material description"],
    "category": ["category", "matkl", "material group", "type", "item type", "material_type"],
    "unit": ["unit", "meins", "uom", "unit of measure"],
    "material": ["material", "werkstoff", "material grade", "base material"],
    "dimension_1": ["dimension_1", "dimension", "size", "dim"],
    "standard": ["standard", "spec", "specification", "norm"],
    "grade": ["grade", "bolt grade", "material grade class"],
    "pressure_rating": ["pressure_rating", "pressure class", "pressure rating", "class"],
    "voltage_rating": ["voltage_rating", "voltage", "voltage class", "kv rating"],
    "manufacturer": ["manufacturer", "make", "brand", "oem"],
    "manufacturer_part_number": ["manufacturer_part_number", "mfrpn", "mpn", "manufacturer part no", "oem part number"],
    "cpse_id": ["cpse_id", "cpse", "organization", "plant", "org", "company code"],
    "unit_price": ["unit_price", "price", "rate", "unit cost"],
    "quantity_procured": ["quantity_procured", "quantity", "qty", "procured quantity"],
}

REQUIRED_FIELDS = ["material_code", "raw_description"]
RECOMMENDED_FIELDS = ["category", "unit", "material", "dimension_1", "grade", "standard",
                      "manufacturer", "manufacturer_part_number"]
