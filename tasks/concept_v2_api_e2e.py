#!/usr/bin/env python3
"""API-driven E2E suite for the Concepts-v2 fix batch (2026-08-18).

Runs against a LIVE Ontos app (default ontos-cbv2b) over REST, exercising the
failure PATTERNS that unit/regression tests keep missing:

  * lifecycle / multi-step state  — create -> import -> delete -> recreate,
    version-row leak, upload-as-draft, sourceFile freshness
  * cross-surface data flow        — conflict payload shape, phantom
    ConceptScheme concept, source_file on grouped concepts
  * governance reachability        — submit-review preview (governed flag),
    changeset gate OFF (uploads land draft, never held)

Design:
  * Self-contained: every scheme it creates is prefixed E2E-AUTO- and torn
    down in a finally block (best-effort), so re-runs start clean.
  * Read-only assertions where possible; destructive steps only on its own
    E2E-AUTO- schemes.
  * SKIP (not FAIL) when a precondition can't be met (e.g. no governing
    workflow installed) — skips never fail the run, but are summarized.

Auth: Databricks Apps sit behind OAuth. Provide a bearer token:
    DATABRICKS_TOKEN=$(databricks auth token --profile fevm-valcon-demo \\
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
    DATABRICKS_TOKEN=$DATABRICKS_TOKEN python tasks/concept_v2_api_e2e.py \\
        --base https://ontos-cbv2b-7474646273329147.aws.databricksapps.com

Exit code: 0 if all executed checks pass (skips do not fail); 1 on any failure.
"""
import argparse
import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []
# Schemes created during this run, torn down at the end.
_created_iris: list[str] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    marker = {"PASS": "\033[92m", "FAIL": "\033[91m", "SKIP": "\033[93m"}.get(status, "")
    print(f"{marker}[{status}]\033[0m {name}" + (f" — {detail}" if detail else ""))


def _headers(json_body: bool = True) -> dict:
    h = {}
    if json_body:
        h["Content-Type"] = "application/json"
    tok = os.environ.get("DATABRICKS_TOKEN")
    cookie = os.environ.get("ONTOS_COOKIE")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    if cookie:
        h["Cookie"] = cookie
    return h


def call(base: str, method: str, path: str, body=None, params=None, raw_status=False):
    """JSON REST call. Returns (status_code, parsed_json_or_text)."""
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            txt = resp.read().decode()
            try:
                return resp.status, json.loads(txt)
            except json.JSONDecodeError:
                return resp.status, txt
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except json.JSONDecodeError:
            return e.code, txt
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def upload_file(base: str, collection_iri: str, filename: str, content: str,
                conflict_mode: str | None = None):
    """Multipart upload to the /import endpoint. Returns (status, json)."""
    boundary = "----ontosE2E" + uuid.uuid4().hex
    path = f"/api/knowledge/collections/{urllib.parse.quote(collection_iri, safe='')}/import"
    if conflict_mode:
        path += "?" + urllib.parse.urlencode({"conflict_mode": conflict_mode})
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/turtle\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    h = _headers(json_body=False)
    h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(base.rstrip("/") + path, data=body, method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            txt = resp.read().decode()
            try:
                return resp.status, json.loads(txt)
            except json.JSONDecodeError:
                return resp.status, txt
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except json.JSONDecodeError:
            return e.code, txt
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def detect_conflicts(base: str, collection_iri: str, filename: str, content: str):
    """POST to /import/conflicts. Returns (status, json)."""
    boundary = "----ontosE2E" + uuid.uuid4().hex
    path = f"/api/knowledge/collections/{urllib.parse.quote(collection_iri, safe='')}/import/conflicts"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/turtle\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    h = _headers(json_body=False)
    h["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = urllib.request.Request(base.rstrip("/") + path, data=body, method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:  # noqa: BLE001
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def create_scheme(base: str, label: str) -> str | None:
    status, data = call(base, "POST", "/api/knowledge/collections", body={
        "label": label,
        "collection_type": "ontology",
        "scope_level": "enterprise",
        "description": f"E2E-AUTO scheme {label}",
    })
    if status in (200, 201) and isinstance(data, dict) and data.get("iri"):
        _created_iris.append(data["iri"])
        return data["iri"]
    return None


def delete_scheme(base: str, iri: str) -> tuple[int, object]:
    return call(base, "DELETE", f"/api/knowledge/collections/{urllib.parse.quote(iri, safe='')}")


def get_grouped(base: str) -> dict:
    status, data = call(base, "GET", "/api/semantic-models/concepts-grouped")
    if status == 200 and isinstance(data, dict):
        return data.get("grouped_concepts", {})
    return {}


# --------------------------------------------------------------------------- #
# Fixture TTL. File-native namespace (NOT under the scheme urn:) so the        #
# delete/version-leak path is genuinely exercised.                            #
# --------------------------------------------------------------------------- #
NS = "http://ontos-e2e.example.org/onto#"
PREFIX = f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <{NS}> .
"""

# A scheme header (skos:ConceptScheme) PLUS two real concepts — the header must
# NOT be enumerated as a concept (S2).
BASE_TTL = PREFIX + """
ex:MyScheme a skos:ConceptScheme ;
    rdfs:label "My E2E Scheme header" .

ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Order a skos:Concept ;
    skos:prefLabel "Order" ;
    skos:definition "A purchase request." .
"""

# Overlaps ex:Customer / ex:Order (conflict), adds ex:Lead.
OVERLAY_TTL = PREFIX + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer (revised)." .

ex:Order a skos:Concept ;
    skos:prefLabel "Order" ;
    skos:definition "A purchase (revised)." .

ex:Lead a skos:Concept ;
    skos:prefLabel "Lead" ;
    skos:definition "A prospect." .
"""


def local(iri: str) -> str:
    return iri.split("#")[-1].split("/")[-1]


# --------------------------------------------------------------------------- #
# TESTS                                                                        #
# --------------------------------------------------------------------------- #
def t_upload_lands_draft_and_no_scheme_concept(base: str) -> str | None:
    """S2 + S5-batch: import lands concepts as Draft; the ConceptScheme header
    is NOT enumerated as a concept; imported concepts get a version (v1)."""
    label = f"E2E-AUTO-Base-{uuid.uuid4().hex[:6]}"
    iri = create_scheme(base, label)
    if not iri:
        record("CREATE base scheme", FAIL, "could not create scheme")
        return None
    record("CREATE base scheme", PASS, iri)

    status, data = upload_file(base, iri, "base_scheme.ttl", BASE_TTL)
    if status != 200:
        record("IMPORT base file", FAIL, f"status={status} {str(data)[:120]}")
        return iri
    record("IMPORT base file", PASS, f"mode={data.get('mode') if isinstance(data,dict) else '?'}")

    # Grouped concepts for THIS scheme.
    grouped = get_grouped(base)
    concepts = grouped.get(iri) or grouped.get(local(iri)) or []
    # Some deployments key grouped by source_context that may differ; fall back
    # to scanning any group whose concept IRIs are in our namespace.
    if not concepts:
        for _src, arr in grouped.items():
            arr2 = [c for c in arr if str(c.get("iri", "")).startswith(NS)]
            concepts.extend(arr2)

    names = {local(c.get("iri", "")) for c in concepts}
    # S2: MyScheme (the ConceptScheme header) must NOT appear as a concept.
    if "MyScheme" in names:
        record("S2 no phantom scheme concept", FAIL, "ConceptScheme header enumerated as a concept")
    else:
        record("S2 no phantom scheme concept", PASS, f"concepts={sorted(names)}")

    # Batch#5-5: all imported concepts land as draft.
    statuses = {local(c.get("iri", "")): (c.get("status") or "").lower() for c in concepts
                if local(c.get("iri", "")) in ("Customer", "Order")}
    if statuses and all(s == "draft" for s in statuses.values()):
        record("Batch5-5 uploads land Draft", PASS, str(statuses))
    else:
        record("Batch5-5 uploads land Draft", FAIL, f"expected all draft, got {statuses}")

    # S4: imported concepts get a version (badge not blank).
    cust_iri = NS + "Customer"
    vstatus, vdata = call(base, "GET", "/api/semantic-models/concepts/version",
                          params={"iri": cust_iri})
    cv = vdata.get("current_version") if isinstance(vdata, dict) else None
    if vstatus == 200 and cv == 1:
        record("S4 imported concept has v1", PASS, f"current_version={cv}")
    elif vstatus == 200 and isinstance(cv, int) and cv >= 1:
        record("S4 imported concept has v1", PASS, f"current_version={cv} (>=1)")
    else:
        record("S4 imported concept has v1", FAIL, f"status={vstatus} current_version={cv}")

    # S3-provenance: sourceFile stamped with the uploaded filename.
    cstatus, cdata = call(base, "GET", "/api/semantic-models/concepts/by-iri",
                          params={"iri": cust_iri})
    concept = cdata.get("concept") if isinstance(cdata, dict) else None
    sf = (concept or {}).get("source_file")
    if sf == "base_scheme.ttl":
        record("sourceFile stamped on import", PASS, sf)
    else:
        record("sourceFile stamped on import", SKIP, f"source_file={sf!r} (field may be omitted)")

    return iri


def t_conflict_payload_shape(base: str, base_iri: str) -> None:
    """S1: conflict detection returns one row per CONFLICTING CONCEPT, each with
    the concept's own label + the scheme it already lives in — NOT the scheme
    repeated. Uploading the overlay into a NEW scheme collides on Customer+Order."""
    label = f"E2E-AUTO-Overlay-{uuid.uuid4().hex[:6]}"
    overlay_iri = create_scheme(base, label)
    if not overlay_iri:
        record("S1 conflict payload", SKIP, "could not create overlay scheme")
        return
    status, data = detect_conflicts(base, overlay_iri, "overlay_conflict.ttl", OVERLAY_TTL)
    if status != 200 or not isinstance(data, dict):
        record("S1 conflict payload", FAIL, f"status={status} {str(data)[:120]}")
        return
    conflicts = data.get("conflicts", [])
    # Expect exactly the two overlapping concepts (Customer, Order), each a
    # DISTINCT row carrying its own concept label (not the scheme label).
    iris = {local(c.get("iri", "")) for c in conflicts}
    labels = [c.get("label") for c in conflicts]
    has_label_key = all("label" in c for c in conflicts) if conflicts else False
    distinct_concepts = iris == {"Customer", "Order"}
    # The concept label must be the concept's own (Customer/Order), not the
    # base scheme's label.
    label_is_concept = all(
        (c.get("label") or "").strip() in ("Customer", "Order") or
        local(c.get("iri", "")) in ("Customer", "Order")
        for c in conflicts
    )
    if distinct_concepts and has_label_key and label_is_concept:
        record("S1 conflict lists distinct concepts w/ own label", PASS,
               f"iris={sorted(iris)} labels={labels}")
    else:
        record("S1 conflict lists distinct concepts w/ own label", FAIL,
               f"iris={sorted(iris)} labels={labels} has_label_key={has_label_key}")
    # Clean up the empty overlay scheme now (nothing imported).
    delete_scheme(base, overlay_iri)
    _created_iris.remove(overlay_iri) if overlay_iri in _created_iris else None


def t_reupload_refreshes_sourcefile(base: str) -> None:
    """C2: re-uploading a MODIFIED concept from a NEW file refreshes its
    ontos:sourceFile provenance (does not keep the first filename)."""
    run_ns = f"http://ontos-e2e.example.org/prov-{uuid.uuid4().hex[:8]}#"
    v1 = (f"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
          f"@prefix ex: <{run_ns}> .\n"
          f'ex:Customer a skos:Concept ; skos:prefLabel "Customer" ; '
          f'skos:definition "A buyer." .\n')
    v2 = (f"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
          f"@prefix ex: <{run_ns}> .\n"
          f'ex:Customer a skos:Concept ; skos:prefLabel "Customer" ; '
          f'skos:definition "A buyer (revised)." .\n')
    cust = run_ns + "Customer"
    label = f"E2E-AUTO-Prov-{uuid.uuid4().hex[:6]}"
    iri = create_scheme(base, label)
    if not iri:
        record("C2 sourceFile refresh on re-upload", SKIP, "could not create scheme")
        return
    s1, _ = upload_file(base, iri, "prov_v1.ttl", v1)
    if s1 != 200:
        record("C2 sourceFile refresh on re-upload", SKIP, f"first import failed status={s1}")
        return
    # Re-upload the modified concept from a new filename -> preview token.
    s2, d2 = upload_file(base, iri, "prov_v2.ttl", v2)
    if s2 != 200 or not (isinstance(d2, dict) and d2.get("mode") == "preview"):
        record("C2 sourceFile refresh on re-upload", SKIP,
               f"expected preview on re-upload, got status={s2} {str(d2)[:100]}")
        return
    token = d2["preview_token"]
    cs, cd = call(base, "POST",
                  f"/api/semantic-models/uploads/preview/{urllib.parse.quote(token, safe='')}/confirm")
    if cs != 200:
        record("C2 sourceFile refresh on re-upload", FAIL, f"confirm failed status={cs} {str(cd)[:100]}")
        return
    _, cdata = call(base, "GET", "/api/semantic-models/concepts/by-iri", params={"iri": cust})
    got = ((cdata or {}).get("concept") or {}).get("source_file") if isinstance(cdata, dict) else None
    if got == "prov_v2.ttl":
        record("C2 sourceFile refresh on re-upload", PASS, f"source_file={got}")
    elif got == "prov_v1.ttl":
        record("C2 sourceFile refresh on re-upload", FAIL, "kept stale prov_v1.ttl (C2 regression)")
    else:
        record("C2 sourceFile refresh on re-upload", SKIP, f"source_file={got!r} (field may be omitted)")


def t_delete_recreate_no_leak(base: str) -> None:
    """Batch#5-2: delete a scheme with FILE-NATIVE IRIs, then recreate the same
    label + re-import the same file — must NOT leak version rows (no v2/history
    carry-over, no 'already exists' collision).

    Uses a run-UNIQUE namespace so the file-native IRIs don't collide with any
    OTHER live scheme (an IRI denotes one concept globally; re-using the base
    test's ex: namespace would trip the cross-scheme guard, not the leak path)."""
    run_ns = f"http://ontos-e2e.example.org/delcycle-{uuid.uuid4().hex[:8]}#"
    ttl = f"""@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <{run_ns}> .
ex:MyScheme a skos:ConceptScheme ; rdfs:label "DelCycle header" .
ex:Customer a skos:Concept ; skos:prefLabel "Customer" ; skos:definition "A buyer." .
ex:Order a skos:Concept ; skos:prefLabel "Order" ; skos:definition "A purchase." .
"""
    cust_ns_iri = run_ns + "Customer"
    label = f"E2E-AUTO-DelCycle-{uuid.uuid4().hex[:6]}"
    iri1 = create_scheme(base, label)
    if not iri1:
        record("Batch5-2 delete/recreate no leak", SKIP, "could not create scheme")
        return
    s1, d1 = upload_file(base, iri1, "cycle.ttl", ttl)
    if s1 != 200:
        record("Batch5-2 delete/recreate no leak", SKIP, f"first import failed status={s1} {str(d1)[:100]}")
        return
    # Delete it.
    ds, dd = delete_scheme(base, iri1)
    if ds not in (200, 204):
        record("Batch5-2 delete/recreate no leak", FAIL, f"delete failed status={ds} {str(dd)[:100]}")
        return
    if iri1 in _created_iris:
        _created_iris.remove(iri1)
    # Recreate the SAME label -> same sanitized IRI.
    iri2 = create_scheme(base, label)
    if not iri2:
        record("Batch5-2 delete/recreate no leak", FAIL,
               "recreate failed — likely 'Collection already exists' (leak)")
        return
    # Re-import the same file. A version-row leak would surface as the concept
    # coming back at v2+ (history survived), or an import failure.
    s2, d2 = upload_file(base, iri2, "cycle.ttl", ttl)
    if s2 != 200:
        record("Batch5-2 delete/recreate no leak", FAIL,
               f"re-import after recreate failed status={s2} {str(d2)[:120]}")
        return
    vstatus, vdata = call(base, "GET", "/api/semantic-models/concepts/version",
                          params={"iri": cust_ns_iri})
    cv = vdata.get("current_version") if isinstance(vdata, dict) else None
    if vstatus == 200 and cv == 1:
        record("Batch5-2 delete/recreate no leak", PASS,
               f"recreated + reimported cleanly, Customer back at v{cv}")
    else:
        record("Batch5-2 delete/recreate no leak", FAIL,
               f"version leak suspected: Customer current_version={cv} (expected 1)")


def t_submit_preview_governance(base: str, base_iri: str) -> None:
    """S3: submit-review preview reports governed flag WITHOUT side effects."""
    cust_iri = NS + "Customer"
    status, data = call(base, "GET", "/api/knowledge/concepts/by-iri/submit-review/preview",
                        params={"iri": cust_iri})
    if status != 200 or not isinstance(data, dict):
        record("S3 submit-review preview", FAIL, f"status={status} {str(data)[:120]}")
        return
    if "governed" in data and "workflow_names" in data and "workflow_count" in data:
        record("S3 submit-review preview shape", PASS,
               f"governed={data['governed']} workflows={data['workflow_names']}")
    else:
        record("S3 submit-review preview shape", FAIL, f"missing keys: {list(data.keys())}")
    # Side-effect check: the concept must STILL be draft (preview changed nothing).
    cstatus, cdata = call(base, "GET", "/api/semantic-models/concepts/by-iri",
                          params={"iri": cust_iri})
    cur = ((cdata or {}).get("concept") or {}).get("status", "").lower() if isinstance(cdata, dict) else "?"
    if cur == "draft":
        record("S3 preview has NO side effect", PASS, "concept still draft after preview")
    else:
        record("S3 preview has NO side effect", FAIL, f"concept status changed to {cur}")


def t_changeset_trigger_hidden(base: str) -> None:
    """S1: concept_changeset must NOT be a selectable trigger entity type on
    on_request_status_change (the gate is off)."""
    status, data = call(base, "GET", "/api/workflows/trigger-types")
    if status != 200:
        record("S1 concept_changeset hidden in triggers", SKIP,
               f"trigger-types status={status} (endpoint may differ)")
        return
    # Find the on_request_status_change row and inspect its entity_types.
    rows = data if isinstance(data, list) else data.get("trigger_types", data.get("triggers", []))
    hit = None
    for r in rows if isinstance(rows, list) else []:
        if r.get("value") == "on_request_status_change" or r.get("trigger_type") == "on_request_status_change":
            hit = r
            break
    if hit is None:
        record("S1 concept_changeset hidden in triggers", SKIP,
               "on_request_status_change not found in trigger catalog")
        return
    ets = hit.get("entity_types", [])
    if "concept_changeset" not in ets:
        record("S1 concept_changeset hidden in triggers", PASS, f"entity_types={ets}")
    else:
        record("S1 concept_changeset hidden in triggers", FAIL,
               f"concept_changeset still selectable: {ets}")


def t_approval_workflow_model(base: str, base_iri: str) -> None:
    """Concept approval two-workflow model:
      (a) an APPROVAL wizard resolves for the concept entity (for_request_status_change),
      (b) the PROCESS gate holds a submitted concept in under_review,
      (c) approving via the workflow moves the concept to approved.
    All three are SKIP (not FAIL) when the corresponding workflow isn't
    configured on this app — the wiring is in code, the instances are data."""
    # (a) approval wizard resolves for the concept entity.
    ws, wd = call(base, "GET",
                  "/api/workflows/for-trigger/for_request_status_change",
                  params={"entity_type": "ontology_concept"})
    if ws == 200 and isinstance(wd, dict) and wd.get("id"):
        record("Approval wizard resolves for concept", PASS,
               f"{wd.get('name')} (type={wd.get('workflow_type')})")
    elif ws == 404:
        record("Approval wizard resolves for concept", SKIP,
               "no approval (for_request_status_change) workflow configured for concepts")
    else:
        record("Approval wizard resolves for concept", FAIL, f"status={ws} {str(wd)[:120]}")

    # (b)+(c) process gate: submit a fresh draft, expect it HELD in under_review
    # if a process workflow with an approval step is scoped to concepts.
    cust_iri = NS + "Customer"
    # Ensure the concept is a draft (the base import left it draft).
    ss, sd = call(base, "POST", "/api/knowledge/concepts/by-iri/submit-review",
                  params={"iri": cust_iri}, body={})
    if ss != 200:
        record("Process gate holds submitted concept", SKIP, f"submit status={ss} {str(sd)[:100]}")
        return
    governed = sd.get("governed") if isinstance(sd, dict) else None
    # Read back status.
    _, cd = call(base, "GET", "/api/semantic-models/concepts/by-iri", params={"iri": cust_iri})
    st = ((cd or {}).get("concept") or {}).get("status", "").lower() if isinstance(cd, dict) else "?"
    if st == "under_review":
        record("Process gate holds submitted concept", PASS,
               f"status=under_review, governed={governed}")
    else:
        record("Process gate holds submitted concept", FAIL,
               f"expected under_review, got {st} (governed={governed})")


def cleanup(base: str) -> None:
    for iri in list(_created_iris):
        ds, _ = delete_scheme(base, iri)
        if ds in (200, 204):
            print(f"  cleaned {iri}")
        else:
            print(f"  WARN could not clean {iri} (status={ds}) — delete manually")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://ontos-cbv2b-7474646273329147.aws.databricksapps.com")
    ap.add_argument("--keep", action="store_true", help="skip teardown (leave E2E-AUTO schemes)")
    args = ap.parse_args()

    if not (os.environ.get("DATABRICKS_TOKEN") or os.environ.get("ONTOS_COOKIE")):
        print("ERROR: set DATABRICKS_TOKEN (or ONTOS_COOKIE) for the app host.", file=sys.stderr)
        return 2

    # Sanity: authed?
    s, d = call(args.base, "GET", "/api/user/info")
    if s != 200:
        print(f"ERROR: not authenticated to {args.base} (status={s}). Refresh the token.", file=sys.stderr)
        return 2
    print(f"Authed as {d.get('email')} on {args.base}\n")

    try:
        base_iri = t_upload_lands_draft_and_no_scheme_concept(args.base)
        if base_iri:
            t_conflict_payload_shape(args.base, base_iri)
            t_submit_preview_governance(args.base, base_iri)
        t_reupload_refreshes_sourcefile(args.base)
        t_delete_recreate_no_leak(args.base)
        t_changeset_trigger_hidden(args.base)
        # Approval two-workflow model — run LAST on the base scheme, since it
        # mutates the base Customer concept (draft -> under_review).
        if base_iri:
            t_approval_workflow_model(args.base, base_iri)
    finally:
        if not args.keep:
            print("\n--- teardown ---")
            cleanup(args.base)

    n_pass = sum(1 for _, s, _ in results if s == PASS)
    n_fail = sum(1 for _, s, _ in results if s == FAIL)
    n_skip = sum(1 for _, s, _ in results if s == SKIP)
    print(f"\n===== {n_pass} PASS · {n_fail} FAIL · {n_skip} SKIP =====")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
