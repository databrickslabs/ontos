"""Create the presentation skeleton (layouts only) and print placeholder geometry. Run once; writes pid.txt."""
import sys
sys.path.insert(0, "/Users/lars.george/.vibe/marketplace/plugins/fe-google-tools/skills/google-slides/resources")
import gslides_builder as g

LAYOUTS = (["title"] + ["title_only"] * 3 + ["section_break_1"] + ["title_only"] * 5 + ["section_break_1"]
           + ["title_only"] * 2 + ["section_break_1"] + ["title_only"] * 3 + ["section_break_1"]
           + ["title_only"] * 5 + ["closing"])
assert len(LAYOUTS) == 24
pid = g.create_from_template("Ontos — The Business Catalog for Databricks")
leftover = g.get_slide_ids(pid)
for name in LAYOUTS:
    r = g.add_template_slide_by_name(pid, name)
    if "error" in r: print(name, r); sys.exit(1)
if leftover:
    g.batch_update(pid, [{"deleteObject": {"objectId": i}} for i in leftover])
g._invalidate_presentation_cache(pid)
open("pid.txt", "w").write(pid)
p = g.get_presentation(pid)
print(pid, len(p["slides"]))
seen = set()
for n, s in zip(LAYOUTS, p["slides"]):
    if n in seen: continue
    seen.add(n)
    for el in s.get("pageElements", []):
        t = el["transform"]; sz = el["size"]
        print(n, el["objectId"], el.get("shape", {}).get("placeholder"), round(t.get("translateX", 0)/914400, 2),
              round(t.get("translateY", 0)/914400, 2), round(sz["width"]["magnitude"]*t.get("scaleX", 1)/914400, 2),
              round(sz["height"]["magnitude"]*t.get("scaleY", 1)/914400, 2))
