"""
OneCode AI - FastAPI backend (v2).

Run locally:  uvicorn main:app --reload --port 8000
Deploy:       uvicorn main:app --host 0.0.0.0 --port $PORT

See README.md for the full endpoint list and deployment instructions.
"""
import os
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Optional, Literal

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import pipeline
import config

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(APP_DIR, "data", "sample_materials.csv")

app = FastAPI(title="OneCode AI - Material Standardization & Harmonization Platform", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state for the demo. Swap for a real DB before production use.
STATE = {"last_output": None, "reviewed": {}, "current_source": "Demo CSV", "pending_upload": None}


def _load_default():
    df = pd.read_csv(DEFAULT_CSV).fillna("")
    df["source"] = "Demo CSV (synthetic)"
    STATE["last_output"] = pipeline.run_pipeline(df)
    STATE["current_source"] = "Demo CSV (synthetic)"

_load_default()  # run once at startup so GET endpoints work immediately


class ReviewRequest(BaseModel):
    pair: list[str]
    action: Literal["approve", "reject", "modify"]
    reviewer: str = "demo_user"
    note: Optional[str] = None


def _require_run():
    if STATE["last_output"] is None:
        raise HTTPException(400, "No data loaded yet.")
    return STATE["last_output"]


# ==================================================================
# ROOT / HEALTH
# ==================================================================
@app.get("/")
def root():
    return {
        "product": "OneCode AI", "subtitle": "AI-Driven Material Standardization & Harmonization Platform",
        "message": "Different CPSE Codes → One Standard Specification → OneCode",
        "docs": "/docs", "health": "/health",
    }

@app.get("/health")
def health():
    return {"status": "ok", "semantic_method": "MiniLM" if pipeline.USE_REAL_EMBEDDINGS else "TF-IDF"}


# ==================================================================
# CONFIG (spec #3, #15 -- configurable CPSE list & ontology)
# ==================================================================
@app.get("/config/cpses")
def get_cpses():
    return {"cpses": config.CPSE_LIST}

@app.get("/config/categories")
def get_categories():
    return {"categories": {cat: ont for cat, ont in config.CATEGORY_ONTOLOGY.items()}}


# ==================================================================
# OVERVIEW / NATIONAL MATERIAL VIEW (spec #16)
# ==================================================================
@app.get("/overview")
def overview():
    o = _require_run()
    db = o["decision_breakdown"]
    return {
        "total_material_records": o["total_records"],
        "potential_duplicates": db.get("Duplicate", 0),
        "equivalent_materials": db.get("Equivalent", 0),
        "similar_materials": db.get("Similar", 0),
        "unique_harmonized_materials": o["onecodes_generated"],
        "onecodes_generated": o["onecodes_generated"],
        "records_requiring_review": o["records_requiring_review"],
        "potential_procurement_opportunities": o["potential_procurement_opportunities"],
        "current_data_source": STATE["current_source"],
        "semantic_method": o["semantic_method"],
    }


# ==================================================================
# MATERIAL EXPLORER
# ==================================================================
@app.get("/materials")
def list_materials(cpse: Optional[str] = None, category: Optional[str] = None, q: Optional[str] = None):
    o = _require_run()
    records = o["df_records"]
    if cpse:
        records = [r for r in records if r["cpse_id"].lower() == cpse.lower()]
    if category:
        records = [r for r in records if r["category"].lower() == category.lower()]
    if q:
        ql = q.lower()
        records = [r for r in records if ql in r["raw_description"].lower() or ql in r["material_code"].lower()]
    for r in records:
        r["onecode"] = o["material_to_onecode"].get(r["material_code"])
    return {"count": len(records), "materials": records}


# ==================================================================
# AI MATCHING / DUPLICATE DETECTION
# ==================================================================
@app.get("/results")
def get_results(decision: Optional[str] = None, category: Optional[str] = None):
    o = _require_run()
    results = o["results"]
    if decision:
        results = [r for r in results if r["decision"].lower() == decision.lower()]
    if category:
        results = [r for r in results if r["category"].lower() == category.lower()]
    return {"count": len(results), "results": results}

@app.get("/duplicates")
def get_duplicates():
    o = _require_run()
    results = [r for r in o["results"] if r["decision"] in ("Duplicate", "Equivalent")]
    return {"count": len(results), "results": results}


# ==================================================================
# CODE LOOKUP (spec #3-6) -- forward and reverse lookup
# ==================================================================
@app.get("/lookup/material")
def lookup_material(cpse: str, code: str):
    """Forward lookup: given a CPSE + its existing material code, find the OneCode
    and every other CPSE code mapped to the same material."""
    o = _require_run()
    record = next((r for r in o["df_records"]
                    if r["cpse_id"].lower() == cpse.lower() and r["material_code"].lower() == code.lower()), None)
    if not record:
        raise HTTPException(404, f"No material found for CPSE '{cpse}' with code '{code}'.")

    onecode = o["material_to_onecode"].get(record["material_code"])
    cluster = o["onecode_master"].get(onecode, {"members": [record], "standard_specification": "Unclassified", "cpse_count": 1})

    # find the pairwise result (if any) between this record and another member, for match type/confidence
    match_type, confidence = "Duplicate", 100.0
    for r in o["results"]:
        if record["material_code"] in r["pair"] and r["decision"] in ("Duplicate", "Equivalent"):
            other = r["pair"][0] if r["pair"][1] == record["material_code"] else r["pair"][1]
            if other != record["material_code"]:
                match_type = r["decision"]
                confidence = round(r["combined_score"] * 100, 1)
                break

    return {
        "material_found": {
            "cpse": record["cpse_id"], "existing_material_code": record["material_code"],
            "description": record["raw_description"], "category": record["category"],
            "standard_specification": cluster["standard_specification"],
            "onecode": onecode, "match_type": match_type, "confidence": confidence,
            "source": record.get("source", "Demo CSV"),
        },
        "same_material_across_cpses": [
            {
                "cpse": m["cpse_id"], "existing_material_code": m["material_code"],
                "description": m["raw_description"], "onecode": onecode,
                "match": "Exact" if m["material_code"] == record["material_code"] else match_type,
            }
            for m in cluster["members"]
        ],
        "cpse_codes_mapped": cluster["cpse_count"],
    }

@app.get("/lookup/onecode")
def lookup_onecode(code: str):
    """Reverse lookup: given a OneCode, return the standard spec and every mapped CPSE material."""
    o = _require_run()
    cluster = o["onecode_master"].get(code.upper())
    if not cluster:
        raise HTTPException(404, f"OneCode '{code}' not found.")
    return {
        "onecode": code.upper(),
        "standard_specification": cluster["standard_specification"],
        "category": cluster["category"],
        "mapped_cpse_materials": len(cluster["members"]),
        "mappings": [{"cpse": m["cpse_id"], "material_code": m["material_code"]} for m in cluster["members"]],
    }


# ==================================================================
# MATERIAL 360 (spec #7)
# ==================================================================
@app.get("/material360/{onecode}")
def material_360(onecode: str):
    o = _require_run()
    cluster = o["onecode_master"].get(onecode.upper())
    if not cluster:
        raise HTTPException(404, f"OneCode '{onecode}' not found.")

    member_codes = {m["material_code"] for m in cluster["members"]}
    rep = next((r for r in o["df_records"] if r["material_code"] in member_codes), {})

    # gather AI decision evidence from any pairwise result within this cluster
    evidence_sample = next(
        (r for r in o["results"] if set(r["pair"]) <= member_codes and r["decision"] in ("Duplicate", "Equivalent")),
        None,
    )

    total_qty = sum(float(r.get("quantity_procured") or 0) for r in o["df_records"] if r["material_code"] in member_codes)
    prices = [float(r.get("unit_price") or 0) for r in o["df_records"] if r["material_code"] in member_codes and r.get("unit_price")]

    audit_entries = [a for a in o["audit_log"] if a.get("onecode") == onecode.upper()]
    audit_entries += [v for v in STATE["reviewed"].values() if onecode.upper() in str(v.get("materials", ""))]

    return {
        "identity": {
            "onecode": onecode.upper(), "category": cluster["category"],
            "standard_specification": cluster["standard_specification"],
        },
        "cpse_codes": [{"cpse": m["cpse_id"], "material_code": m["material_code"], "source": m.get("source", "")} for m in cluster["members"]],
        "technical_attributes": {
            "material": rep.get("material", ""), "dimension": rep.get("dimension_1", ""),
            "grade": rep.get("grade", ""), "standard": rep.get("standard", ""),
            "manufacturer": rep.get("manufacturer", ""), "manufacturer_part_number": rep.get("manufacturer_part_number", ""),
            "unit": rep.get("unit", ""), "pressure_rating": rep.get("pressure_rating", ""),
            "voltage_rating": rep.get("voltage_rating", ""),
        },
        "ai_decision": {
            "match_type": evidence_sample["decision"] if evidence_sample else "Single record — no comparison yet",
            "confidence": round(evidence_sample["combined_score"] * 100, 1) if evidence_sample else None,
            "evidence": evidence_sample["evidence"] if evidence_sample else None,
            "evidence_table": evidence_sample["evidence_table"] if evidence_sample else [],
        },
        "procurement_intelligence": {
            "total_aggregated_demand": total_qty,
            "number_of_cpses": cluster["cpse_count"],
            "price_range": [min(prices), max(prices)] if prices else None,
            "potential_procurement_opportunity": cluster["cpse_count"] > 1,
        },
        "audit": {
            "created": o["generated_at"], "reviewer": "demo_user" if audit_entries else None,
            "approval_status": audit_entries[-1]["action"] if audit_entries else "pending_human_review",
            "change_history": audit_entries,
        },
    }


# ==================================================================
# ONECODE MASTER (spec #21)
# ==================================================================
@app.get("/onecode-master")
def onecode_master():
    o = _require_run()
    rows = [
        {"onecode": oc, "category": c["category"], "standard_specification": c["standard_specification"], "cpse_count": c["cpse_count"]}
        for oc, c in o["onecode_master"].items()
    ]
    rows.sort(key=lambda r: -r["cpse_count"])
    return {"count": len(rows), "onecode_master": rows}


# ==================================================================
# CPSE MAPPING / LEGACY CODE MAPPING (spec #22)
# ==================================================================
@app.get("/mapping")
def code_mapping(cpse: Optional[str] = None, status: Optional[str] = None):
    o = _require_run()
    rows = []
    for oc, cluster in o["onecode_master"].items():
        for m in cluster["members"]:
            approved = tuple(sorted([m["material_code"]])) in {k for k in STATE["reviewed"]}
            row_status = "Approved" if cluster["cpse_count"] > 1 else "Pending"
            for key, entry in STATE["reviewed"].items():
                if m["material_code"] in entry.get("materials", []):
                    row_status = "Approved" if entry["action"] == "human_approve" else ("Rejected" if entry["action"] == "human_reject" else row_status)
            rows.append({"cpse": m["cpse_id"], "existing_code": m["material_code"], "onecode": oc, "status": row_status})
    if cpse:
        rows = [r for r in rows if r["cpse"].lower() == cpse.lower()]
    if status:
        rows = [r for r in rows if r["status"].lower() == status.lower()]
    return {"count": len(rows), "mapping": rows}


# ==================================================================
# CPSE ANALYTICS (spec #17)
# ==================================================================
@app.get("/cpse-analytics")
def cpse_analytics():
    o = _require_run()
    df_records = o["df_records"]
    quality = o["data_quality"]["by_cpse"]
    stats = {}
    for r in df_records:
        cpse = r["cpse_id"]
        stats.setdefault(cpse, {"cpse": cpse, "records": 0, "duplicates": 0, "equivalent": 0})
        stats[cpse]["records"] += 1
    for res in o["results"]:
        for cpse in res["cpse_pair"]:
            if res["decision"] == "Duplicate":
                stats.setdefault(cpse, {"cpse": cpse, "records": 0, "duplicates": 0, "equivalent": 0})["duplicates"] += 1
            elif res["decision"] == "Equivalent":
                stats.setdefault(cpse, {"cpse": cpse, "records": 0, "duplicates": 0, "equivalent": 0})["equivalent"] += 1
    for cpse, row in stats.items():
        row["data_quality"] = quality.get(cpse, {}).get("score", None)
    return {"cpse_analytics": list(stats.values())}


# ==================================================================
# DATA QUALITY (spec #18)
# ==================================================================
@app.get("/data-quality")
def data_quality():
    o = _require_run()
    return o["data_quality"]


# ==================================================================
# REVIEW & APPROVAL (spec #19)
# ==================================================================
@app.get("/review-queue")
def review_queue():
    o = _require_run()
    queue = [r for r in o["results"] if r["decision"] in ("Duplicate", "Equivalent", "Similar")]
    for r in queue:
        key = tuple(sorted(r["pair"]))
        r = r  # keep original; overlay status below
        r["current_status"] = STATE["reviewed"].get(key, {}).get("action", "pending_human_review")
    return {"count": len(queue), "queue": queue}

@app.post("/review")
def review_pair(req: ReviewRequest):
    o = _require_run()
    key = tuple(sorted(req.pair))
    valid_pairs = {tuple(sorted(r["pair"])) for r in o["results"]}
    if key not in valid_pairs:
        raise HTTPException(404, f"Pair {req.pair} not found in the current dataset.")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": f"human_{req.action}",
        "materials": list(req.pair), "reviewer": req.reviewer, "note": req.note,
        "previous_value": "pending_human_review", "new_value": req.action,
        "status": "reversible",
    }
    STATE["reviewed"][key] = entry
    return {"message": f"Recorded '{req.action}' for {req.pair}.", "entry": entry}


# ==================================================================
# AUDIT TRAIL (spec #20)
# ==================================================================
@app.get("/audit")
def get_audit():
    o = _require_run()
    log = list(o["audit_log"]) + list(STATE["reviewed"].values())
    log.sort(key=lambda x: x["timestamp"])
    return {"count": len(log), "audit_log": log}


# ==================================================================
# PROCUREMENT INSIGHTS (spec #23)
# ==================================================================
@app.get("/procurement-insights")
def procurement_insights():
    o = _require_run()
    return o["savings"]


# ==================================================================
# MODEL EVALUATION (spec #25) -- only meaningful on the demo dataset,
# which carries a hidden true_cluster ground-truth column.
# ==================================================================
@app.get("/evaluation")
def evaluation():
    o = _require_run()
    df = pd.read_csv(DEFAULT_CSV).fillna("")
    if "true_cluster" not in df.columns or STATE["current_source"] != "Demo CSV (synthetic)":
        return {
            "available": False,
            "message": "Evaluation requires labelled ground truth, which only exists for the bundled synthetic demo dataset. Load the demo dataset to see these metrics.",
        }
    code_to_cluster = dict(zip(df["material_code"], df["true_cluster"]))
    MERGE = {"Duplicate", "Equivalent"}
    y_true, y_pred, conflict_flags = [], [], []
    for r in o["results"]:
        ca, cb = code_to_cluster.get(r["pair"][0], ""), code_to_cluster.get(r["pair"][1], "")
        if not ca or not cb:
            continue
        should_merge = ca == cb and "conflict" not in ca and "insufficient" not in ca
        must_block = "conflict" in ca or "conflict" in cb
        predicted_merge = r["decision"] in MERGE
        if must_block:
            conflict_flags.append(not predicted_merge)
        y_true.append(1 if should_merge else 0)
        y_pred.append(1 if predicted_merge else 0)

    tp = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 1)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t == 1 and p == 0)
    tn = sum(1 for t, p in zip(y_true, y_pred) if t == 0 and p == 0)
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    false_merge_rate = 1 - (sum(conflict_flags) / len(conflict_flags)) if conflict_flags else 0.0

    return {
        "available": True,
        "note": "Evaluation performed on synthetic/demo ground-truth data. Does not represent real CPSE performance.",
        "precision": round(precision, 3), "recall": round(recall, 3), "f1_score": round(f1, 3),
        "confusion_matrix": {"true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": tn},
        "critical_conflict_cases": len(conflict_flags),
        "critical_conflicts_correctly_blocked": sum(conflict_flags),
        "false_merge_rate_on_critical_conflicts": round(false_merge_rate, 3),
    }


# ==================================================================
# DATA ONBOARDING (spec #11, #12) -- source-agnostic ingestion
# ==================================================================
@app.get("/onboarding/sources")
def onboarding_sources():
    return {
        "supported_sources": [
            {"type": "SAP/ERP export", "status": "SAP/ERP-compatible ingestion (via CSV/Excel export)", "live_integration": False},
            {"type": "CSV", "status": "supported", "live_integration": True},
            {"type": "Excel (.xlsx/.xls)", "status": "supported", "live_integration": True},
            {"type": "JSON", "status": "supported", "live_integration": True},
            {"type": "REST API", "status": "architecture ready (POST /onboarding/ingest)", "live_integration": True},
            {"type": "Database import", "status": "architecture ready, not yet implemented", "live_integration": False},
        ]
    }

@app.post("/onboarding/detect-columns")
async def detect_columns(file: UploadFile = File(...)):
    tmp_path = os.path.join(tempfile.gettempdir(), f"detect_{datetime.now().timestamp()}_{file.filename}")
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        df = pipeline.read_any(tmp_path, file.filename)
        mapping = pipeline.detect_column_mapping(list(df.columns))
        missing = pipeline.missing_required_fields(mapping)
        return {
            "filename": file.filename, "rows_detected": len(df), "columns_detected": list(df.columns),
            "suggested_mapping": mapping, "missing_required_fields": missing,
            "warning": "Matching confidence may be reduced without recommended fields (category, material, dimension, grade, standard)." if missing else None,
        }
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.post("/onboarding/ingest")
async def ingest(file: UploadFile = File(...), mapping_json: Optional[str] = Form(None), source_label: Optional[str] = Form(None)):
    import json as _json
    tmp_path = os.path.join(tempfile.gettempdir(), f"ingest_{datetime.now().timestamp()}_{file.filename}")
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        df = pipeline.read_any(tmp_path, file.filename)

        if mapping_json:
            mapping = _json.loads(mapping_json)
        else:
            mapping = pipeline.detect_column_mapping(list(df.columns))

        missing = pipeline.missing_required_fields(mapping)
        if missing:
            raise HTTPException(400, f"Cannot ingest: missing required field(s) {missing}. Provide a column mapping for these.")

        label = source_label or f"Uploaded: {file.filename}"
        std_df = pipeline.apply_mapping_and_standardize(df, mapping, source_label=label)

        output = pipeline.run_pipeline(std_df)
        STATE["last_output"] = output
        STATE["reviewed"] = {}
        STATE["current_source"] = label

        return {
            "message": "Dataset ingested and pipeline run complete.",
            "source": label, "total_records": output["total_records"],
            "decision_breakdown": output["decision_breakdown"],
            "onecodes_generated": output["onecodes_generated"],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

@app.post("/onboarding/reset-demo")
def reset_demo():
    """Reload the bundled synthetic demo dataset (useful after testing an upload)."""
    _load_default()
    return {"message": "Reloaded bundled demo dataset.", "source": STATE["current_source"]}


# ==================================================================
# SYSTEM INTEGRATION (spec #13, #11)
# ==================================================================
@app.get("/system-integration")
def system_integration():
    o = _require_run()
    sources_in_use = sorted(set(r.get("source", "Demo CSV") for r in o["df_records"]))
    return {
        "current_data_source": STATE["current_source"],
        "sources_seen_in_current_dataset": sources_in_use,
        "available_ingestion_methods": ["SAP/ERP export (CSV/Excel)", "CSV", "Excel", "JSON", "REST API"],
        "note": "This prototype demonstrates SAP/ERP-compatible ingestion via file export; a live, authenticated SAP connector is architecture-ready but not implemented in this build.",
    }


# ==================================================================
# DASHBOARD STATS (summary for the frontend)
# ==================================================================
@app.get("/dashboard-stats")
def dashboard_stats():
    o = _require_run()
    return {
        "total_records": o["total_records"], "candidate_pairs_evaluated": o["candidate_pairs_evaluated"],
        "full_pairwise_would_be": o["full_pairwise_would_be"],
        "compute_saved_by_blocking_pct": o["compute_saved_by_blocking_pct"],
        "decision_breakdown": o["decision_breakdown"],
        "onecodes_generated": o["onecodes_generated"],
        "records_requiring_review": o["records_requiring_review"],
        "potential_procurement_opportunities": o["potential_procurement_opportunities"],
        "total_estimated_savings_inr": o["savings"]["total_estimated_savings_inr"],
        "data_quality_overall": o["data_quality"]["overall_score"],
        "semantic_method": o["semantic_method"],
        "current_source": STATE["current_source"],
    }
