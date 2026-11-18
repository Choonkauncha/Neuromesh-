"""Typed evidence packet: the only artifact allowed to cross from Explorer to Verifier.

Unknown keys are rejected, so a free-form reasoning narrative cannot ride along.
Every excerpt must appear verbatim in the cited source file (fabricated quotes fail).
"""
import hashlib, json, re, subprocess
from pathlib import Path

SOURCE_TYPES = {"primary_document", "official_documentation", "executed_code_or_test",
                "direct_tool_observation", "peer_reviewed_publication", "reputable_secondary_source",
                "community_or_forum", "model_generated", "user_provided", "unknown"}
GRADES = {"a", "b", "c", "d", "unassessed"}
GROUPS = {"independent_origin", "same_publisher", "same_underlying_dataset", "same_quoted_source",
          "derived_from_other_evidence", "unknown"}
STATUSES = {"proposed", "provisional", "supported", "disputed", "rejected"}

EVIDENCE_REQUIRED = {"evidence_id", "source_file", "source_type", "grade", "independence_group", "excerpt"}
EVIDENCE_ALLOWED = EVIDENCE_REQUIRED | {"publisher", "derived_from", "supports", "contradicts", "applicability_checked", "superseded_by"}
CLAIM_REQUIRED = {"claim_id", "statement", "status"}
CLAIM_ALLOWED = CLAIM_REQUIRED | {"supersedes"}


def extract_json(text):
    """Return the first balanced top-level JSON object in text (fences/prose ignored)."""
    if not isinstance(text, str):
        raise ValueError("no text")
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object found in output")


def _norm(s):
    return re.sub(r"\s+", " ", s).strip()


def validate_claims(claims):
    errs, ids = [], set()
    if not isinstance(claims, list):
        return ["claims must be a list"]
    for i, c in enumerate(claims):
        if not isinstance(c, dict):
            errs.append(f"claims[{i}] must be an object"); continue
        missing, extra = CLAIM_REQUIRED - set(c), set(c) - CLAIM_ALLOWED
        if missing: errs.append(f"claims[{i}] missing {sorted(missing)}")
        if extra: errs.append(f"claims[{i}] unknown keys {sorted(extra)}")
        cid = c.get("claim_id")
        if cid in ids: errs.append(f"duplicate claim_id {cid}")
        ids.add(cid)
        if c.get("status") not in STATUSES: errs.append(f"claims[{i}] bad status {c.get('status')!r}")
        if not isinstance(c.get("statement"), str) or not (3 <= len(c["statement"]) <= 400):
            errs.append(f"claims[{i}] statement must be a 3-400 char string")
        sup = c.get("supersedes", [])
        if not isinstance(sup, list): errs.append(f"claims[{i}] supersedes must be a list")
    return errs


def validate_evidence(evidence, claim_ids, inputs_dir, visible_files, extra_texts=None):
    errs, ids = [], set()
    if not isinstance(evidence, list):
        return ["evidence must be a list"]
    all_ids = {e.get("evidence_id") for e in evidence if isinstance(e, dict)}
    for i, e in enumerate(evidence):
        if not isinstance(e, dict):
            errs.append(f"evidence[{i}] must be an object"); continue
        missing, extra = EVIDENCE_REQUIRED - set(e), set(e) - EVIDENCE_ALLOWED
        if missing: errs.append(f"evidence[{i}] missing {sorted(missing)}")
        if extra: errs.append(f"evidence[{i}] unknown keys {sorted(extra)} (no free-form narrative allowed)")
        eid = e.get("evidence_id")
        if eid in ids: errs.append(f"duplicate evidence_id {eid}")
        ids.add(eid)
        if e.get("source_type") not in SOURCE_TYPES: errs.append(f"evidence[{i}] bad source_type {e.get('source_type')!r}")
        if e.get("grade") not in GRADES: errs.append(f"evidence[{i}] bad grade {e.get('grade')!r} (use a|b|c|d|unassessed)")
        if e.get("independence_group") not in GROUPS: errs.append(f"evidence[{i}] bad independence_group {e.get('independence_group')!r}")
        sb = e.get("superseded_by")
        if sb is not None and (sb not in all_ids or sb == eid): errs.append(f"evidence[{i}] superseded_by must name a different evidence_id in this packet")
        for key in ("supports", "contradicts", "derived_from"):
            vals = e.get(key, [])
            if not isinstance(vals, list): errs.append(f"evidence[{i}].{key} must be a list"); continue
            for v in vals:
                if key == "derived_from" and v not in all_ids: errs.append(f"evidence[{i}] derived_from unknown evidence_id {v!r}")
                if key != "derived_from" and v not in claim_ids: errs.append(f"evidence[{i}].{key} unknown claim_id {v!r}")
        sf, ex = e.get("source_file"), e.get("excerpt")
        extra = extra_texts or {}
        if sf not in visible_files and sf not in extra:
            errs.append(f"evidence[{i}] source_file {sf!r} is not an available input file or recorded tool output")
        elif isinstance(ex, str):
            body = extra[sf] if sf in extra else (Path(inputs_dir) / sf).read_text()
            if not (8 <= len(ex) <= 400): errs.append(f"evidence[{i}] excerpt must be 8-400 chars")
            elif _norm(ex) not in _norm(body):
                errs.append(f"evidence[{i}] excerpt is not a verbatim quote from {sf}")
        else:
            errs.append(f"evidence[{i}] excerpt must be a string")
    return errs


def validate_packet(obj, inputs_dir, visible_files, extra_texts=None):
    if not isinstance(obj, dict): return ["packet must be a JSON object"]
    extra = set(obj) - {"claims", "evidence"}
    errs = [f"unknown top-level keys {sorted(extra)}"] if extra else []
    errs += validate_claims(obj.get("claims"))
    claim_ids = {c.get("claim_id") for c in obj.get("claims", []) if isinstance(c, dict)}
    errs += validate_evidence(obj.get("evidence"), claim_ids, inputs_dir, visible_files, extra_texts)
    return errs


def canonical(packet):
    """Re-serialise only schema fields; this is what the Verifier is shown."""
    claims = [{k: c[k] for k in CLAIM_ALLOWED if k in c} for c in packet["claims"]]
    ev = [{k: e[k] for k in sorted(EVIDENCE_ALLOWED) if k in e} for e in packet["evidence"]]
    return {"claims": claims, "evidence": ev}


def to_crystal(packet):
    ev = []
    for e in packet["evidence"]:
        ev.append({"evidence_id": e["evidence_id"], "source_type": e["source_type"], "grade": e["grade"],
                   "independence_group": e["independence_group"], "provenance_uri": e["source_file"],
                   "publisher": e.get("publisher"), "retrieved_at": "",
                   "derived_from": e.get("derived_from", []), "supports_claim_ids": e.get("supports", []),
                   "contradicts_claim_ids": e.get("contradicts", []),
                   "excerpt_hash": hashlib.sha256(_norm(e["excerpt"]).encode()).hexdigest(),
                   "applicability_checked": bool(e.get("applicability_checked", False)),
                   "superseded_by": e.get("superseded_by")})
    return {"claims": [{"claim_id": c["claim_id"]} for c in packet["claims"]], "evidence": ev}


def arbitrate(packet, binary, workdir):
    """Deterministic claim statuses from the Crystal runtime; None if binary unavailable."""
    if not binary or not Path(binary).exists():
        return None
    path = Path(workdir) / "arbitrate_input.json"
    path.write_text(json.dumps(to_crystal(packet)))
    r = subprocess.run([str(binary), "--arbitrate", str(path)], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"arbitration failed: {r.stderr[-500:]}")
    return json.loads(r.stdout)
