"""Draw every slide of the Ontos business deck into the presentation in pid.txt. Re-runnable: clears and redraws.

  python3 step1.py   # once: create the deck from the Databricks template
  python3 build.py   # draw all slides (or: python3 build.py 4 12  to redraw only slides 4 and 12)
  python3 notes.py   # speaker notes
"""
import sys
from pathlib import Path
from lib import g, Slide, reset
import slides_a as a
import slides_b as b

PID = (Path(__file__).parent / "pid.txt").read_text().strip()
FNS = [a.s01, a.s02, a.s03, a.s04, a.s05, a.s06, a.s07, a.s08, a.s09, a.s10, a.s11, a.s12, a.s13,
       b.s14, b.s15, b.s16, b.s17, b.s18, b.s19, b.s20, b.s21, b.s22, b.s23, b.s24, b.s25, b.s26, None]  # last = closing layout, untouched

if __name__ == "__main__":
    only = {int(x) for x in sys.argv[1:]}
    g._invalidate_presentation_cache(PID)
    slides = reset(PID, only)
    assert len(slides) == len(FNS), (len(slides), len(FNS))
    for n, ((sid, ph), fn) in enumerate(zip(slides, FNS), 1):
        if fn is None or (only and n not in only):
            continue
        S = Slide(sid, ph)
        fn(S)
        r = g.batch_update(PID, S.reqs)
        if "error" in r:
            print(n, r["error"]); sys.exit(1)
        print(n, "ok", len(S.reqs))
    print(f"https://docs.google.com/presentation/d/{PID}/edit")
