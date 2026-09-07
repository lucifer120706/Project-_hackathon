"""
OneCode AI - Material Resolution Pipeline (v2).

Architecture: ingest -> normalize -> category classification -> blocking (retrieval)
-> hybrid scoring (fuzzy + semantic + structured attributes) -> critical-conflict
validation -> decision classification -> clustering (union-find) -> OneCode
assignment -> explainable evidence -> data quality -> procurement aggregation.

Decision classes (simple terminology, per spec):
  Duplicate            - same material identity
  Equivalent           - technically interchangeable, different manufacturer/code
  Similar              - close match, real variant difference, needs review
  No Match             - not the same material (includes critical-attribute conflicts)
  Insufficient Data    - not enough information for a safe decision

Semantic similarity uses sentence-transformers/MiniLM when available (needs
internet to download the model); falls back to TF-IDF automatically otherwise.
"""
import re
import itertools
import hashlib
from datetime import datetime, timezone
from collections import Counter, defaultdict

import pandas as pd
from rapidfuzz import fuzz, process as rf_process

import config

# ---------------- Semantic backend (auto-detect) ----------------
USE_REAL_EMBEDDINGS = True
_model = None
try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
    _model = SentenceTransformer("all-MiniLM-L6-v2")
except Exception as e:
    USE_REAL_EMBEDDINGS = False
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    print(f"[pipeline] sentence-transformers unavailable ({e}); using TF-IDF fallback.")

STANDARD_COLUMNS = [
    "cpse_id", "material_code", "raw_description", "category", "material",
    "dimension_1", "unit", "standard", "grade", "pressure_rating",
    "voltage_rating", "manufacturer", "manufacturer_part_number",
    "unit_price", "quantity_procured", "source",
]

# ==================================================================
# NORMALIZATION
# ==================================================================
def normalize_text(s):
    s = str(s).upper()
    s = re.sub(r"[^\w\s.]", " ", s)
    for pattern, repl in config.ABBREVIATIONS.items():
        s = re.sub(pattern, repl, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_dimension(dim, unit):
    unit = str(unit).lower()
    if unit in ("model", "", "nan"):
        return str(dim)
    try:
        parts = [float(p) for p in re.split(r"[xX]", str(dim))]
        factor = config.UNIT_TO_BASE.get(unit, 1.0) or 1.0
        return "x".join(f"{p*factor:.1f}" for p in parts)
    except (ValueError, TypeError):
        return str(dim)

def extract_brand(desc):
    return next((b for b in config.BRAND_KEYWORDS if b in desc), None)

# ==================================================================
# COLUMN AUTO-MAPPING (Data Onboarding)
# ==================================================================
def detect_column_mapping(source_columns):
    """For each uploaded column, find the best-matching internal field via
    fuzzy match against known synonyms (SAP field codes, common headers, etc.)."""
    suggestions = []
    used_targets = set()
    for col in source_columns:
        col_norm = str(col).strip().lower()
        best_field, best_score = None, 0
        for field, synonyms in config.FIELD_SYNONYMS.items():
            if field in used_targets:
                continue
            match = rf_process.extractOne(col_norm, synonyms, scorer=fuzz.token_sort_ratio)
            if match and match[1] > best_score:
                best_field, best_score = field, match[1]
        if best_field and best_score >= 60:
            suggestions.append({"source_column": col, "target_field": best_field, "confidence": best_score})
            used_targets.add(best_field)
        else:
            suggestions.append({"source_column": col, "target_field": None, "confidence": 0})
    return suggestions

def missing_required_fields(mapping):
    mapped_targets = {m["target_field"] for m in mapping if m["target_field"]}
    return [f for f in config.REQUIRED_FIELDS if f not in mapped_targets]

def apply_mapping_and_standardize(df, mapping, source_label="Uploaded file"):
    """Rename columns per mapping, ensure all standard columns exist, tag source."""
    rename = {m["source_column"]: m["target_field"] for m in mapping if m["target_field"]}
    df = df.rename(columns=rename)
    for col in STANDARD_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["source"] = source_label
    df = df.fillna("")
    # ensure material_code is unique/non-empty; synthesize if missing
    if (df["material_code"] == "").any():
        df.loc[df["material_code"] == "", "material_code"] = [
            f"REC-{i}" for i in range(int((df["material_code"] == "").sum()))
        ]
    return df[STANDARD_COLUMNS]

def read_any(file_path, filename):
    """Source-agnostic ingestion: CSV, Excel, or JSON."""
    lower = filename.lower()
    if lower.endswith(".csv"):
        return pd.read_csv(file_path)
    elif lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(file_path)
    elif lower.endswith(".json"):
        return pd.read_json(file_path)
    else:
        raise ValueError(f"Unsupported file type: {filename}. Use CSV, Excel (.xlsx/.xls), or JSON.")

# ==================================================================
# DECISION ENGINE
# ==================================================================
MERGE_DECISIONS = {"Duplicate", "Equivalent"}

def has_missing_data(row, ontology):
    if row["material"] == "" or row["standard"] == "":
        return True
    return any(row.get(a, "") == "" for a in ontology["critical_attrs"])

def critical_conflict(a, b, ontology):
    for attr in ontology["critical_attrs"]:
        va, vb = str(a.get(attr, "")).strip(), str(b.get(attr, "")).strip()
        if va and vb and va != vb:
            return attr, va, vb
    return None, None, None

def attribute_agreement(a, b, ontology):
    attrs = ontology["structural_attrs"]
    compared = matched = 0
    for attr in attrs:
        va, vb = str(a.get(attr, "")).strip(), str(b.get(attr, "")).strip()
        if va and vb:
            compared += 1
            matched += (va == vb)
    return (matched / compared) if compared else 0.0

def family_difference(a, b, ontology):
    hints = ontology["family_hints"]
    tags_a = {h for h in hints if h in a["norm_description"]}
    tags_b = {h for h in hints if h in b["norm_description"]}
    return tags_a != tags_b

def build_evidence(a, b, ontology, fuzzy_s, semantic_s, attr_score, dim_match):
    """Structured evidence table for Explainable AI -- never a single black-box score."""
    evidence = [{"feature": "Description similarity", "result": f"{round(semantic_s*100)}%"}]
    for attr in ["material", "standard"]:
        va, vb = str(a.get(attr, "")).strip(), str(b.get(attr, "")).strip()
        if va or vb:
            ok = va == vb and va != ""
            evidence.append({"feature": attr.capitalize(), "result": f"{va or '—'} {'✓' if ok else ('vs ' + (vb or chr(8212)) + ' ✗') if va and vb else ''}".strip()})
    evidence.append({"feature": "Dimension", "result": f"{a['norm_dimension']} {'✓' if dim_match else 'vs ' + b['norm_dimension'] + ' ✗'}"})

    conflict_attr, va, vb = critical_conflict(a, b, ontology)
    if conflict_attr:
        evidence.append({"feature": "Critical attributes", "result": f"{conflict_attr.capitalize()} conflict: {va} ≠ {vb} ✗"})
    else:
        evidence.append({"feature": "Critical attributes", "result": "No conflict ✓"})

    brand_a, brand_b = extract_brand(a["norm_description"]), extract_brand(b["norm_description"])
    if brand_a and brand_b:
        evidence.append({"feature": "Manufacturer", "result": f"{brand_a} vs {brand_b} → Different" if brand_a != brand_b else f"{brand_a} → Same"})
    else:
        evidence.append({"feature": "Manufacturer", "result": "Not specified"})
    return evidence

def decide(a, b, ontology, score, dim_match, attr_score):
    conflict_attr, va, vb = critical_conflict(a, b, ontology)
    if conflict_attr:
        return "No Match", f"Specification conflict: critical attribute '{conflict_attr}' differs ({va} ≠ {vb}) — do not merge, regardless of text similarity"
    if has_missing_data(a, ontology) or has_missing_data(b, ontology):
        return "Insufficient Data", "One or both records are missing a required attribute (material/standard/critical spec)"
    if not dim_match:
        return "No Match", "Dimension/model does not match after unit normalization"
    if family_difference(a, b, ontology):
        return "Similar", "Same core spec but a real variant difference detected (e.g. seal/end type) — needs human review, not an automatic identity match"

    perfect_attrs = attr_score >= 0.999
    if perfect_attrs or score >= 0.85:
        brand_a, brand_b = extract_brand(a["norm_description"]), extract_brand(b["norm_description"])
        if brand_a and brand_b and brand_a != brand_b:
            return "Equivalent", f"Matching spec (attribute agreement {attr_score:.0%}) but different manufacturer ('{brand_a}' vs '{brand_b}') — technically interchangeable, distinct identity"
        basis = "structured attributes match exactly" if perfect_attrs else f"high combined similarity ({score:.2f})"
        return "Duplicate", f"{basis.capitalize()}; attribute agreement {attr_score:.0%}, similarity {score:.2f}"
    elif score >= 0.55:
        return "Similar", f"Moderate similarity ({score:.2f}); needs human confirmation before treating as the same material"
    else:
        return "No Match", f"Low similarity ({score:.2f})"

def blocking_candidates(df):
    blocks = {}
    for idx, row in df.iterrows():
        blocks.setdefault(row["category"], []).append(idx)
    return [pair for idxs in blocks.values() for pair in itertools.combinations(idxs, 2)]

# ==================================================================
# UNION-FIND (clustering transitively-linked Duplicate/Equivalent pairs)
# ==================================================================
class DSU:
    def __init__(self, items):
        self.parent = {i: i for i in items}
    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

def generate_onecode(category, spec_key):
    h = hashlib.md5(spec_key.upper().encode()).hexdigest()[:6].upper()
    prefix = config.CNMC_PREFIX.get(category, "GEN")
    return f"OC-{prefix}-{h}"

def detect_family_tag(row, ontology):
    """Real variant markers (e.g. sealed vs open bearing) must be part of the
    OneCode identity -- otherwise two genuinely different clusters can hash to
    the same OneCode just because their core attributes match."""
    hints = ontology["family_hints"]
    found = sorted(h for h in hints if h in row["norm_description"])
    return "+".join(found)

def build_standard_spec(row, ontology):
    parts = []
    for field in ontology["spec_template"]:
        if field == "category":
            val = row["category"]
        else:
            val = row.get(field, "")
        if val and str(val) not in ("N/A", "nan"):
            parts.append(str(val))
    tag = detect_family_tag(row, ontology)
    if tag:
        parts.append(tag)
    return " | ".join(parts) if parts else "Unclassified"

# ==================================================================
# DATA QUALITY
# ==================================================================
QUALITY_CHECK_FIELDS = ["raw_description", "category", "unit", "material", "standard", "dimension_1"]

def compute_data_quality(df):
    per_cpse = {}
    for cpse, group in df.groupby("cpse_id"):
        n = len(group)
        penalties = 0
        issues = Counter()
        for field in QUALITY_CHECK_FIELDS:
            missing = (group[field].astype(str).str.strip() == "").sum()
            if missing:
                issues[f"missing_{field}"] = int(missing)
                penalties += missing
        dup_desc = group["raw_description"].str.upper().duplicated().sum()
        if dup_desc:
            issues["duplicate_descriptions"] = int(dup_desc)
            penalties += dup_desc
        max_penalty_points = n * len(QUALITY_CHECK_FIELDS)
        score = max(0, round(100 - (penalties / max_penalty_points * 100))) if max_penalty_points else 100
        per_cpse[cpse] = {"records": int(n), "score": int(score), "issues": dict(issues)}
    overall = round(sum(v["score"] * v["records"] for v in per_cpse.values()) / max(sum(v["records"] for v in per_cpse.values()), 1))
    return {"overall_score": int(overall), "by_cpse": per_cpse}

# ==================================================================
# MAIN PIPELINE RUN
# ==================================================================
def run_pipeline(df):
    df = df.copy().fillna("")
    df["norm_description"] = df["raw_description"].apply(normalize_text)
    df["norm_dimension"] = df.apply(lambda r: normalize_dimension(r.get("dimension_1", ""), r.get("unit", "")), axis=1)

    if USE_REAL_EMBEDDINGS:
        embeddings = _model.encode(df["norm_description"].tolist(), normalize_embeddings=True)
        def semantic(i, j):
            return float(np.dot(embeddings[i], embeddings[j]))
    else:
        vectorizer = TfidfVectorizer().fit(df["norm_description"].tolist()) if len(df) > 1 else None
        def semantic(i, j):
            if vectorizer is None:
                return 0.0
            tf = vectorizer.transform([df.loc[i, "norm_description"], df.loc[j, "norm_description"]])
            return float(cosine_similarity(tf[0], tf[1])[0][0])

    pairs = blocking_candidates(df)
    results = []
    dsu = DSU(df["material_code"].tolist())

    for i, j in pairs:
        a, b = df.loc[i], df.loc[j]
        category = a["category"]
        ontology = config.get_ontology(category)
        dim_match = a["norm_dimension"] == b["norm_dimension"]
        fuzzy_s = fuzz.token_sort_ratio(a["norm_description"], b["norm_description"]) / 100.0
        semantic_s = semantic(i, j)
        attr_score = attribute_agreement(a, b, ontology)
        combined = round(0.3 * fuzzy_s + 0.2 * semantic_s + 0.5 * attr_score, 4)
        decision, evidence_text = decide(a, b, ontology, combined, dim_match, attr_score)
        evidence_table = build_evidence(a, b, ontology, fuzzy_s, semantic_s, attr_score, dim_match)

        if decision in MERGE_DECISIONS:
            dsu.union(a["material_code"], b["material_code"])

        results.append({
            "pair": [a["material_code"], b["material_code"]],
            "cpse_pair": [a["cpse_id"], b["cpse_id"]],
            "descriptions": [a["raw_description"], b["raw_description"]],
            "category": category, "combined_score": combined,
            "fuzzy_score": round(fuzzy_s, 4), "semantic_score": round(semantic_s, 4),
            "attribute_agreement": round(attr_score, 4),
            "decision": decision, "evidence": evidence_text, "evidence_table": evidence_table,
            "review_status": "pending_human_review" if decision in MERGE_DECISIONS else "no_action_needed",
        })

    # ---- Build OneCode clusters from the union-find groups ----
    groups = defaultdict(list)
    for idx, row in df.iterrows():
        groups[dsu.find(row["material_code"])].append(idx)

    onecode_master = {}
    material_to_onecode = {}
    for root, idxs in groups.items():
        rep = df.loc[idxs[0]]
        category = rep["category"]
        ontology = config.get_ontology(category)
        family_tag = detect_family_tag(rep, ontology)
        # Spec key must include every structural attribute (which already covers
        # each category's critical attributes, e.g. grade/pressure/voltage) --
        # otherwise two DSU roots that were correctly kept separate by a
        # critical-attribute hard-block could still hash to the same OneCode.
        attr_values = "|".join(str(rep.get(a, "")).strip() for a in ontology["structural_attrs"])
        spec_key = f"{category}|{attr_values}|{family_tag}"
        onecode = generate_onecode(category, spec_key)
        spec = build_standard_spec(rep, ontology)
        members = []
        for idx in idxs:
            r = df.loc[idx]
            members.append({
                "cpse_id": r["cpse_id"], "material_code": r["material_code"],
                "raw_description": r["raw_description"], "source": r.get("source", "Demo CSV"),
            })
            material_to_onecode[r["material_code"]] = onecode
        onecode_master[onecode] = {
            "onecode": onecode, "category": category, "standard_specification": spec,
            "cpse_count": len(set(m["cpse_id"] for m in members)),
            "members": members,
        }

    audit_log = []
    for r in results:
        if r["decision"] in MERGE_DECISIONS:
            onecode = material_to_onecode.get(r["pair"][0])
            audit_log.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "candidate_cluster_proposed",
                "materials": r["pair"], "onecode": onecode,
                "decision": r["decision"], "status": "pending_human_review",
                "previous_value": None, "reason": r["evidence"],
            })

    n = len(df)
    full_pairs = n * (n - 1) // 2

    savings_rows = []
    for onecode, cluster in onecode_master.items():
        if cluster["cpse_count"] < 2:
            continue
        codes = [m["material_code"] for m in cluster["members"]]
        sub = df[df.material_code.isin(codes)]
        prices = sub["unit_price"].replace("", 0).astype(float)
        qtys = sub["quantity_procured"].replace("", 0).astype(float)
        if prices.max() <= 0:
            continue
        min_p, max_p, total_qty = float(prices.min()), float(prices.max()), float(qtys.sum())
        savings_rows.append({
            "onecode": onecode, "cpses_involved": sub["cpse_id"].tolist(),
            "combined_demand": total_qty, "price_range": [min_p, max_p],
            "estimated_savings_inr": round((max_p - min_p) * total_qty * 0.5, 2),
            "note": "Illustrative Demo Estimate — 50% of price gap x combined quantity, based on synthetic/demo data.",
        })

    quality = compute_data_quality(df)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantic_method": "sentence-transformers/MiniLM" if USE_REAL_EMBEDDINGS else "TF-IDF (fallback)",
        "total_records": n, "candidate_pairs_evaluated": len(pairs),
        "full_pairwise_would_be": full_pairs,
        "compute_saved_by_blocking_pct": round((1 - len(pairs) / full_pairs) * 100, 1) if full_pairs else 0,
        "decision_breakdown": dict(Counter(r["decision"] for r in results)),
        "results": results,
        "audit_log": audit_log,
        "onecode_master": onecode_master,
        "material_to_onecode": material_to_onecode,
        "onecodes_generated": len(onecode_master),
        "records_requiring_review": sum(1 for r in results if r["review_status"] == "pending_human_review"),
        "potential_procurement_opportunities": len(savings_rows),
        "savings": {
            "clusters": savings_rows,
            "total_estimated_savings_inr": round(sum(r["estimated_savings_inr"] for r in savings_rows), 2),
        },
        "data_quality": quality,
        "df_records": df.to_dict(orient="records"),  # for material explorer / lookup
    }
    return output
