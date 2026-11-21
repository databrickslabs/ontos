"""Drawing helpers for the Ontos business deck (native Google Slides shapes, Databricks template)."""
import sys
sys.path.insert(0, "/Users/lars.george/.vibe/marketplace/plugins/fe-google-tools/skills/google-slides/resources")
import gslides_builder as g  # noqa: E402

E = 914400
C = dict(dark="#1B3037", teal="#1B5161", muted="#618793", light="#9EB7BE", red="#FF3620",
         gray="#F1F1F1", white="#FFFFFF", green="#00B378", yellow="#FFAB00", line="#D5DEE1",
         redtint="#FFF1EE", redline="#F5C2B8", tealtint="#E8EFF1", greentint="#E3F6EF", yellowtint="#FFF4DB",
         darkred="#98102A")
FONT = "Barlow"
D, T, M, R, W = C["dark"], C["teal"], C["muted"], C["red"], C["white"]


def rgb(h):
    h = h.lstrip("#")
    return {"red": int(h[0:2], 16)/255, "green": int(h[2:4], 16)/255, "blue": int(h[4:6], 16)/255}


class Slide:
    def __init__(self, sid, ph):
        self.sid, self.ph, self.reqs, self.n = sid, ph, [], 0

    def _id(self):
        self.n += 1
        return f"{self.sid[-10:]}_e{self.n}"

    def _el(self, w, h, x, y, sx=1, sy=1):
        return {"pageObjectId": self.sid,
                "size": {"width": {"magnitude": max(int(w*E), 1), "unit": "EMU"},
                         "height": {"magnitude": max(int(h*E), 1), "unit": "EMU"}},
                "transform": {"scaleX": sx, "scaleY": sy, "translateX": int(x*E), "translateY": int(y*E), "unit": "EMU"}}

    def box(self, x, y, w, h, paras=None, fill=None, outline=None, weight=1, shape="ROUND_RECTANGLE",
            align="START", valign="TOP", inset=None, dash=None, spacing=3):
        oid = self._id()
        self.reqs.append({"createShape": {"objectId": oid, "shapeType": shape, "elementProperties": self._el(w, h, x, y)}})
        props = {"shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": rgb(fill)}}} if fill
                 else {"propertyState": "NOT_RENDERED"}}
        if outline:
            ol = {"outlineFill": {"solidFill": {"color": {"rgbColor": rgb(outline)}}},
                  "weight": {"magnitude": weight, "unit": "PT"}}
            if dash:
                ol["dashStyle"] = dash
            props["outline"] = ol
        else:
            props["outline"] = {"propertyState": "NOT_RENDERED"}
        props["contentAlignment"] = valign
        self.reqs.append({"updateShapeProperties": {"objectId": oid, "shapeProperties": props,
                                                    "fields": "shapeBackgroundFill,outline,contentAlignment"}})
        if paras:
            self.text(oid, paras, align, spacing)
        return oid

    def text(self, oid, paras, align="START", spacing=3):
        # paras: list of (text, size, color, bold[, "i"]) — one paragraph each
        full = "\n".join(p[0] for p in paras)
        self.reqs.append({"insertText": {"objectId": oid, "text": full, "insertionIndex": 0}})
        i = 0
        for t, size, color, bold, *rest in paras:
            if t:
                self.reqs.append({"updateTextStyle": {
                    "objectId": oid, "textRange": {"type": "FIXED_RANGE", "startIndex": i, "endIndex": i+len(t)},
                    "style": {"fontFamily": FONT, "fontSize": {"magnitude": size, "unit": "PT"},
                              "foregroundColor": {"opaqueColor": {"rgbColor": rgb(color)}}, "bold": bold,
                              "italic": bool(rest and rest[0] == "i")},
                    "fields": "fontFamily,fontSize,foregroundColor,bold,italic"}})
            i += len(t) + 1
        self.reqs.append({"updateParagraphStyle": {
            "objectId": oid, "textRange": {"type": "ALL"},
            "style": {"alignment": align, "spaceAbove": {"magnitude": 0, "unit": "PT"},
                      "spaceBelow": {"magnitude": spacing, "unit": "PT"}, "lineSpacing": 100},
            "fields": "alignment,spaceAbove,spaceBelow,lineSpacing"}})

    def line(self, x1, y1, x2, y2, color=None, weight=2, dash=None, head=True):
        # A signed scale maps the line's (0,0) to (x1,y1) and its far corner to (x2,y2), so endArrow sits at (x2,y2).
        oid = self._id()
        w, h = x2-x1, y2-y1
        self.reqs.append({"createLine": {"objectId": oid, "lineCategory": "STRAIGHT", "elementProperties":
                                         self._el(abs(w), abs(h), x1, y1, 1 if w >= 0 else -1, 1 if h >= 0 else -1)}})
        lp = {"lineFill": {"solidFill": {"color": {"rgbColor": rgb(color or M)}}}, "weight": {"magnitude": weight, "unit": "PT"}}
        f = "lineFill,weight"
        if head:
            lp["endArrow"] = "FILL_ARROW"
            f += ",endArrow"
        if dash:
            lp["dashStyle"] = dash
            f += ",dashStyle"
        self.reqs.append({"updateLineProperties": {"objectId": oid, "lineProperties": lp, "fields": f}})

    def arrow(self, *a, **k):
        self.line(*a, **k)

    # ---------- page furniture ----------
    def title(self, t, size=26):
        tid = self.ph["TITLE"]
        self.reqs.append({"insertText": {"objectId": tid, "text": t, "insertionIndex": 0}})
        self.reqs.append({"updateTextStyle": {
            "objectId": tid, "textRange": {"type": "ALL"},
            "style": {"fontFamily": FONT, "fontSize": {"magnitude": size, "unit": "PT"}, "bold": True,
                      "foregroundColor": {"opaqueColor": {"rgbColor": rgb(D)}}},
            "fields": "fontFamily,fontSize,bold,foregroundColor"}})

    def lead(self, t, size=14):
        self.box(0.5, 1.45, 12.3, 0.66, [(t, size, M, False)], inset=0)

    def tag(self, t, x=10.33, y=6.82, w=2.5):
        self.box(x, y, w, 0.28, [(t, 9, C["light"], False, "i")], align="END")

    def heading(self, x, y, w, t, color=M):
        self.box(x, y, w, 0.3, [(t, 10, color, True)])

    def placeholder_text(self, ph_type, t):
        self.reqs.append({"insertText": {"objectId": self.ph[ph_type], "text": t, "insertionIndex": 0}})


def reset(pid, only=None):
    """Clear slides (all, or the 1-based numbers in `only`) back to their layout placeholders;
    return [(slide_id, {placeholder_type: id})] for every slide."""
    p = g.get_presentation(pid)
    reqs, out = [], []
    for n, s in enumerate(p["slides"], 1):
        ph = {}
        for el in s.get("pageElements", []):
            pl = el.get("shape", {}).get("placeholder")
            if pl:
                ph[pl["type"]] = el["objectId"]
                if only and n not in only:
                    continue
                if el["shape"].get("text"):
                    reqs.append({"deleteText": {"objectId": el["objectId"], "textRange": {"type": "ALL"}}})
            elif not only or n in only:
                reqs.append({"deleteObject": {"objectId": el["objectId"]}})
        out.append((s["objectId"], ph))
    if reqs:
        r = g.batch_update(pid, reqs)
        if "error" in r:
            raise SystemExit(r["error"])
    return out
