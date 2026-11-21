"""Slides 14-23: access policies, authority, get started."""
from lib import C, D, T, M, R, W
from slides_a import section, outcomes

# Access-policy verdicts: computed by the Ontos evaluator on its retail demo example
# (docs/decks/access-policies-odrl, VIZ-DATA "matrix"); A=allow, P=allowed once duties are met, X=deny, -=no rule.
PEOPLE = [("Alice", "Sales analyst"), ("Bob", "Sales analytics team"), ("Farah", "Finance"),
          ("Hugo", "HR partner"), ("Iris", "Data steward"), ("Dan", "Data science")]
ASKS = [("Sales orders", "read"), ("Sales summary", "read"), ("Invoices", "read"), ("Invoices", "change"),
        ("HR records", "read"), ("Finance area", "browse"), ("Model features", "read")]
GRID = ["AA--X--", "AA--X--", "P-AA---", "P---P--", "P----A-", "P------"]
# Grant release for the demo's Unity Catalog target: 23 tracked grants; reconcile finds 1 missing + 1 unmanaged.
GRANTS, MISSING, UNMANAGED = 23, 1, 1
# ARF demo pack (docs/decks/arf/data/arf_scenarios.json, dna_rows "stored")
DNA_TP = dict(people=0.08, policy=0.07, structural=0.0, total=0.15, ceiling=0.30)
DNA_DECOM = 0.42
DNA_PA = 0.08  # production access grant, documented-exceeds-actual


# ---------------------------------------------------------------- 14 section: access
def s14(S):
    section(S, "PART 3  ·  ACCESS", "Access policies: who may do what, on which data",
            "Written once in business terms, checked on every request, and delivered to the platform as tracked grants.")


# ---------------------------------------------------------------- 15 policy anatomy
def s15(S):
    S.title("An access policy is written once in business terms: who may, or must not, do what on which data")
    S.lead("Policies follow the W3C open standard for digital rights. Each rule points to a reusable audience (the who) and a "
           "reusable asset collection (the what), so a change to a group is made once and every policy follows.")
    # audiences
    ax, aw = 0.5, 3.0
    S.heading(ax, 2.25, aw, "AUDIENCES  ·  THE WHO", T)
    auds = [("Sales Analysts", "a team plus a named analyst"), ("Finance Team", "a team"), ("HR Partners", "a team"),
            ("Data Science", "a team"), ("Data Stewards", "anyone holding the Data Steward role")]
    for i, (a, b) in enumerate(auds):
        S.box(ax, 2.6+i*0.62, aw, 0.54, [(a, 13, D, True), (b, 10, M, False)], fill=C["tealtint"], spacing=0, valign="MIDDLE")
    # collections
    cx, cw = 9.8, 3.0
    S.heading(cx, 2.25, cw, "ASSET COLLECTIONS  ·  THE WHAT", T)
    cols = [("Sales data", "sales area plus the sales summary"), ("Finance ledger", "the finance area"), ("HR records", "the HR area")]
    for i, (a, b) in enumerate(cols):
        S.box(cx, 2.6+i*0.66, cw, 0.58, [(a, 13, D, True), (b, 10, M, False)], fill=C["tealtint"], spacing=0, valign="MIDDLE")
    S.box(cx, 4.62, cw, 0.9, [("Collections bundle tables, views and whole areas; a rule can also name one asset directly.", 11, M, False)])
    # policy card
    px, pw = 3.85, 5.6
    S.box(px, 2.25, pw, 3.3, fill=W, outline=R, weight=1.5)
    S.box(px+0.2, 2.33, pw-0.4, 0.5, [("POLICY  ·  Sales analytics read", 13, R, True)], valign="MIDDLE")
    rules = [("PERMISSION", C["green"], C["greentint"], ["Sales Analysts", "may", "read", "Sales data"]),
             ("PROHIBITION", R, C["redtint"], ["Sales Analysts", "must not", "read", "HR records"])]
    for i, (k, col, tint, (who, verb, act, what)) in enumerate(rules):
        y = 2.9+i*1.05
        S.box(px+0.2, y, pw-0.4, 0.92, fill=tint)
        S.box(px+0.2, y, 0.08, 0.92, fill=col, shape="RECTANGLE")
        S.box(px+0.4, y+0.05, 2.0, 0.28, [(k, 10, col, True)])
        S.box(px+0.4, y+0.38, 1.5, 0.42, [(who, 12, D, True)], fill=C["tealtint"], align="CENTER", valign="MIDDLE")
        S.box(px+1.95, y+0.38, 0.85, 0.42, [(verb, 12, D, True, "i")], align="CENTER", valign="MIDDLE")
        S.box(px+2.85, y+0.38, 0.85, 0.42, [(act, 12, W, True)], fill=D, align="CENTER", valign="MIDDLE")
        S.box(px+3.8, y+0.38, 1.4, 0.42, [(what, 12, D, True)], fill=C["tealtint"], align="CENTER", valign="MIDDLE")
    S.box(px+0.2, 5.0, pw-0.4, 0.45, [("When both apply to the same person, the prohibition wins.", 12, D, True)],
          align="CENTER", valign="MIDDLE")
    # links
    S.line(ax+aw, 2.89, px+0.6, 3.28+0.0, color=T, weight=1.25, head=False, dash="DOT")
    S.line(cx, 2.89, px+3.8+1.4, 3.28, color=T, weight=1.25, head=False, dash="DOT")
    S.line(cx, 4.21, px+3.8+1.4, 4.33, color=T, weight=1.25, head=False, dash="DOT")
    # duties strip
    S.box(0.5, 5.75, 12.3, 0.95, fill=C["yellowtint"])
    S.box(0.5, 5.75, 0.08, 0.95, fill=C["yellow"], shape="RECTANGLE")
    S.box(0.75, 5.8, 11.9, 0.85, [("DUTIES: PERMISSIONS WITH CONDITIONS", 10, "#9A6700", True),
                                  ("HR Partners may read HR records once they acknowledge the terms. Anyone outside Sales may read "
                                   "the sales orders once they accept the terms of use and get approval.", 13, D, False)])
    S.tag("Ontos demo example", y=5.45, x=9.8, w=3.0)


# ---------------------------------------------------------------- 16 verdict grid
def s16(S):
    S.title("Every access request gets a clear answer, and a prohibition beats a permission for the same person")
    S.lead("Six people ask for seven things. Each cell is the answer Ontos returns from the active policies, together with "
           "the rules that matched. Anything no rule covers is denied by default.")
    lx, lw, cx0, cw, gap = 0.5, 2.1, 2.7, 0.95, 0.07
    y0, rh, rgap = 2.25, 0.52, 0.08
    for j, (a, b) in enumerate(ASKS):
        S.box(cx0+j*(cw+gap), y0, cw, 0.62, [(a, 10, D, True), (b, 10, M, False)], align="CENTER", valign="BOTTOM", spacing=0)
    style = {"A": ("Allow", C["green"], W), "P": ("Terms first", C["yellow"], D), "X": ("Deny", R, W), "-": ("No rule", C["gray"], C["light"])}
    for i, ((n, role), row) in enumerate(zip(PEOPLE, GRID)):
        y = y0+0.72+i*(rh+rgap)
        S.box(lx, y, lw, rh, [(n, 13, D, True), (role, 10, M, False)], spacing=0, valign="MIDDLE")
        for j, v in enumerate(row):
            t, f, tc = style[v]
            sel = i == 0 and j == 4
            S.box(cx0+j*(cw+gap), y, cw, rh, [(t, 11, tc, True)], fill=f, align="CENTER", valign="MIDDLE",
                  outline=D if sel else None, weight=2.5 if sel else 1)
    n_all = sum(len(r) for r in GRID)
    n_rule = sum(1 for r in GRID for v in r if v != "-")
    # right panel
    rx, rw = 10.15, 2.65
    S.box(rx, 2.25, rw, 1.05, [(f"{n_rule} of {n_all}", 26, R, True), ("requests meet a rule; the rest are denied by default", 11, M, False)])
    legend = [("Allow", C["green"], "a permission applies"), ("Terms first", C["yellow"], "allowed once its duties are met"),
              ("Deny", R, "a prohibition applies"), ("No rule", C["gray"], "nothing covers it, so no access")]
    for k, (a, col, b) in enumerate(legend):
        y = 3.42+k*0.5
        S.box(rx, y+0.06, 0.3, 0.3, fill=col, shape="RECTANGLE")
        S.box(rx+0.4, y, rw-0.4, 0.48, [(a, 11, D, True), (b, 10, M, False)], spacing=0)
    S.box(rx, 5.5, rw, 1.2, [("Alice reads sales data, but not HR records", 12, D, True),
                             ("Her team is prohibited from HR records, and the prohibition wins.", 11, M, False)],
          fill=C["gray"], outline=D, weight=1.5)
    S.tag("Ontos demo example, computed by Ontos", x=2.7, y=6.4, w=7.1)


# ---------------------------------------------------------------- 17 compile & deliver
def s17(S):
    S.title("Approved policies become reviewed, delivered and tracked grants, and drift shows up as a difference")
    S.lead("Governance writes the rules; Ontos carries them out on the platform and keeps checking them. One release for the "
           "demo's Unity Catalog target, stage by stage.")
    st = [("Compile", f"Active policies become {GRANTS} grants, including the parent access people need. Rules still waiting on duties are held back."),
          ("Review", "The release is reviewed with separation of duties: whoever prepared it cannot approve it."),
          ("Deliver", "Delivered the way the platform allows: here a ready-to-apply change set an administrator confirms."),
          ("Track", "Every grant becomes a ledger entry: who, what, why and until when. Time-bound grants are revoked on expiry."),
          ("Reconcile", f"On a schedule, the ledger is compared with the live platform: {GRANTS} tracked, {MISSING} missing, {UNMANAGED} added by hand.")]
    sw = (12.3 - 0.1*4)/5
    for i, (n, b) in enumerate(st):
        x = 0.5 + i*(sw+0.1)
        S.box(x, 2.3, sw, 0.62, [(f"{i+1}  {n}", 15, W, True)], fill=D if i >= 3 else R,
              shape="HOME_PLATE" if i < 4 else "ROUND_RECTANGLE", valign="MIDDLE")
        S.box(x, 3.05, sw, 1.95, [(b, 13, D, False)], fill=C["gray"] if i >= 3 else C["redtint"])
    # branch brackets
    S.box(0.5, 5.12, 3*sw+0.2, 0.05, fill=R, shape="RECTANGLE")
    S.box(0.5+3*(sw+0.1), 5.12, 2*sw+0.1, 0.05, fill=D, shape="RECTANGLE")
    S.box(0.5, 5.2, 3*sw+0.2, 0.32, [("Executive: Data Management carries the rules out", 12, R, True)], align="CENTER")
    S.box(0.5+3*(sw+0.1), 5.2, 2*sw+0.1, 0.32, [("Judicial: audit checks that they hold", 12, D, True)], align="CENTER")
    S.box(0.5, 5.75, 6.05, 0.95, [("Drift is reported, never silently reverted", 13, D, True),
                                  ("Someone removed a read grant and added a change grant by hand. Reconcile shows both; administrators decide.", 11, M, False)],
          fill=W, outline=C["line"], dash="DASH")
    S.box(6.75, 5.75, 6.05, 0.95, [("Every grant has a reason", 13, D, True),
                                   ("Each entry names the policy that produced it, so “why does this person have access?” has an answer.", 11, M, False)],
          fill=W, outline=C["line"], dash="DASH")
    S.tag("Ontos demo example", x=10.3, y=1.95)


# ---------------------------------------------------------------- 18 section: authority
def s18(S):
    section(S, "PART 4  ·  AUTHORITY", "Authority: who may decide what",
            "One trusted answer for people, workflows and AI agents, backed by policy and kept current by evidence.")


# ---------------------------------------------------------------- 19 the problem
def s19(S):
    S.title("Authority is written in one place and exercised in another, and people and agents fill the gap")
    S.lead("Delegations of authority live in policy documents. Real decisions happen in workflows, in email and, more and more, "
           "in AI agents. Each one interprets the rules on its own, so answers differ and nobody can show afterwards why.")
    S.box(3.4, 2.25, 6.5, 0.7, [("“Can I approve a USD 620,000 trade promotion?”", 18, D, True)], fill=C["gray"],
          align="CENTER", valign="MIDDLE")
    S.line(5.0, 2.95, 3.4, 3.35, weight=2)
    S.line(8.3, 2.95, 9.9, 3.35, weight=2)
    S.heading(0.5, 3.15, 5.6, "ON PAPER", T)
    S.box(0.5, 3.5, 5.6, 1.9, [("Trade Promotion Policy  ·  version 2", 14, D, True),
                               ("Clause 4.3", 12, T, True),
                               ("Budgets above USD 500,000 need VP sign-off. Expected margin must stay at or above 15%.", 13, D, False)],
          fill=C["tealtint"], outline=T)
    S.box(6.3, 3.9, 0.7, 0.7, [("≠", 30, R, True)], align="CENTER", valign="MIDDLE")
    S.heading(7.2, 3.15, 5.6, "IN PRACTICE", R)
    said = [("Agent A", "“Yes, you own the budget.”"), ("Agent B", "“Probably, but check with Finance.”"),
            ("Approver, by email", "“Approved.” No VP sign-off on record.")]
    for i, (who, t) in enumerate(said):
        S.box(7.2, 3.5+i*0.65, 5.6, 0.57, [(f"{who}:  {t}", 13, D, False)], fill=C["redtint"], valign="MIDDLE")
    outcomes(S, [("Inconsistent", "The same question gets different answers from different agents"),
                 ("Unaccountable", "Nothing records which rule decided, or whether it was followed"),
                 ("Unsafe to scale", "Automating decisions multiplies the gap instead of closing it")], y=5.75, h=0.95, size=(15, 12))
    S.tag("Illustrative")


# ---------------------------------------------------------------- 20 one service
def s20(S):
    S.title("One authority service gives every person, workflow and agent the same answer, with the clause behind it")
    S.lead("Approved delegations of authority live in Ontos, tied to the business objects they govern. Everyone asks the same "
           "service and gets one of three answers, each recorded for audit.")
    callers = ["Approval workflow", "Procurement agent", "Finance assistant", "Genie"]
    ax, aw, ah, ay0, agap = 0.5, 2.45, 0.55, 2.62, 0.17
    S.heading(ax, 2.25, aw, "WHO ASKS")
    for i, a in enumerate(callers):
        S.box(ax, ay0+i*(ah+agap), aw, ah, [(a, 14, D, True)], fill=C["gray"], outline=C["line"], align="CENTER", valign="MIDDLE")
    hx, hy, hw, hh = 3.65, 2.62, 4.6, 2.71
    for i in range(4):
        cy = ay0+i*(ah+agap)+ah/2
        S.arrow(ax+aw+0.06, cy, hx-0.08, cy, weight=2)
    S.box(hx, hy, hw, hh, [("ONTOS  ·  AUTHORITY SERVICE", 11, R, True)], fill=C["redtint"], outline=R, weight=1.5)
    inner = [("Approved policies", "Who may decide what, up to which limit"),
             ("Ontology", "Links each rule to the business objects it governs"),
             ("Decision record", "Every answer kept with the policy that decided it")]
    for i, (h, b) in enumerate(inner):
        S.box(hx+0.18, hy+0.42+i*0.75, hw-0.36, 0.66, [(h, 14, D, True), (b, 12, M, False)], fill=W, outline=C["redline"], spacing=0)
    vx, vw = 8.95, 3.85
    S.heading(vx, 2.25, vw, "ONE SHARED ANSWER")
    verdicts = [("Permit", C["green"], "Within delegated authority"),
                ("Conditional", C["yellow"], "Permitted once a named sign-off is in"),
                ("Deny", R, "Outside policy, citing the clause that says so")]
    for i, (v, col, b) in enumerate(verdicts):
        vy = ay0 + i*0.95
        S.box(vx, vy, 0.1, 0.81, fill=col, shape="RECTANGLE")
        S.box(vx+0.1, vy, vw-0.1, 0.81, [(v, 15, D, True), (b, 12, M, False)], fill=C["gray"], valign="MIDDLE", spacing=0)
        S.arrow(hx+hw+0.08, vy+0.405, vx-0.08, vy+0.405, weight=2)
    S.box(0.5, 5.5, 12.3, 0.52,
          [("Example:  “Can I approve a USD 620,000 trade promotion?”   →   Conditional: VP sign-off needed above "
            "USD 500,000 (Policy v2, clause 4.3). Recorded for audit.", 12, D, False)],
          fill=W, outline=C["line"], valign="MIDDLE", dash="DASH")
    outs = [("Consistent", "Same question, same answer, from every caller"),
            ("Accountable", "Every decision cites the policy behind it"),
            ("Safe to scale", "Automate within limits your leaders approved")]
    ow = (12.3 - 0.3*2) / 3
    for i, (hd, b) in enumerate(outs):
        ox = 0.5 + i*(ow+0.3)
        S.box(ox, 6.14, 0.06, 0.56, fill=R, shape="RECTANGLE")
        S.box(ox+0.15, 6.08, ow-0.15, 0.7, [(hd, 14, D, True), (b, 12, M, False)], spacing=0)


# ---------------------------------------------------------------- 21 six parts
def s21(S):
    S.title("An authority relation has six parts, and only one of them is measured rather than declared")
    S.lead("Each relation states who may do what, on which business object, in which context and on what grounds. The sixth "
           "part measures how far real practice has drifted from what is written. Example: trade promotion budget approval.")
    parts = [("Actor", "Who holds the authority", "Trade Marketing Director"),
             ("Action", "What they may do", "Approve"),
             ("Object", "The business object it covers", "Trade promotion budget"),
             ("Context", "Where, and within which limits", "Germany, modern trade; alone up to USD 500k"),
             ("Justification", "The policy it rests on", "Trade Promotion Policy v2, clause 4.3"),
             ("Divergence", "How far practice drifts from the rule", f"{DNA_TP['total']:.2f}, under its ceiling of {DNA_TP['ceiling']:.2f}")]
    cw, gap, y, h = 1.9, 0.18, 2.6, 2.75
    for i, (n, d, ex) in enumerate(parts):
        x = 0.5 + i*(cw+gap)
        hl = i == 5
        S.box(x, y, cw, h, fill=C["redtint"] if hl else C["gray"], outline=R if hl else None, weight=1.5)
        S.box(x+0.15, y+0.15, 0.48, 0.48, [(str(i+1), 14, W, True)], fill=R if hl else T, shape="ELLIPSE",
              align="CENTER", valign="MIDDLE")
        S.box(x+0.12, y+0.72, cw-0.24, h-0.8, [(n, 16, D, True), (d, 11, M, False), ("", 4, M, False), (ex, 12, R if hl else T, True)])
    S.box(0.5, 2.25, 5*cw+4*gap, 0.05, fill=T, shape="RECTANGLE")
    S.box(0.5, 2.3, 5*cw+4*gap, 0.28, [("DECLARED: taken from policy documents and data", 10, T, True)], align="CENTER")
    S.box(0.5+5*(cw+gap), 2.25, cw, 0.05, fill=R, shape="RECTANGLE")
    S.box(0.5+5*(cw+gap), 2.3, cw, 0.28, [("MEASURED", 10, R, True)], align="CENTER")
    S.box(0.5, 5.6, 12.3, 1.05, fill=W, outline=C["line"])
    S.box(0.7, 5.68, 11.9, 0.9, [("Tied to the ontology", 14, D, True),
                                 ("The relation is linked to the business concept Trade promotion, so any question about that object "
                                  "finds the authority that governs it, and its prerequisites, such as market compliance, are checked first.", 12, M, False)])
    S.tag("Demo example")


# ---------------------------------------------------------------- 22 earned & current
def s22(S):
    S.title("Authority is earned and kept current: three-way sign-off, a measured coefficient and automatic review")
    S.lead("A rule is only as good as its fit with reality. Ontos activates authority only when it rests on a valid policy, its "
           "DNA-Coefficient is under the ceiling, and business, technology and governance have each signed off.")
    # gate panel
    gx, gy, gw, gh = 0.5, 2.25, 4.0, 2.95
    S.box(gx, gy, gw, gh, [("1 · THE ACTIVATION GATE", 10, M, True)], fill=C["gray"])
    checks = [("Valid policy", "Approved, in force, not withdrawn"), ("Coefficient under the ceiling", "Measured, not assumed"),
              ("Signed off by all three", "Business · Technology · Governance")]
    for i, (h, b) in enumerate(checks):
        y = gy+0.45+i*0.8
        S.box(gx+0.15, y+0.1, 0.42, 0.42, [("✓", 14, W, True)], fill=C["green"], shape="ELLIPSE", align="CENTER", valign="MIDDLE")
        S.box(gx+0.7, y, gw-0.85, 0.7, [(h, 14, D, True), (b, 11, M, False)], spacing=0, valign="MIDDLE")
    # coefficient panel
    qx, qw = 4.75, 8.05
    S.box(qx, gy, qw, gh, [("2 · ONE COEFFICIENT, TWO DIRECTIONS, ONE CEILING", 10, M, True)], fill=C["gray"])
    dw = 3.6
    S.box(qx+0.25, gy+0.42, dw, 0.56, [("Practice runs ahead of the document", 12, D, True),
                                       ("People decide beyond their written authority", 10, M, False)],
          fill=W, outline=C["line"], spacing=0, valign="MIDDLE")
    S.box(qx+qw-0.25-dw, gy+0.42, dw, 0.56, [("The document runs ahead of practice", 12, D, True),
                                             ("Written authority is bypassed or escalated", 10, M, False)],
          fill=W, outline=C["line"], spacing=0, valign="MIDDLE", align="END")
    S.box(qx+0.25, gy+1.02, qw-0.5, 0.3, [("Either direction raises the one coefficient; the direction tells governance which way to fix it.",
                                           10, R, True)], align="CENTER")
    scale = 0.5
    sx, sw, sy = qx+0.4, qw-0.8, gy+1.85
    cxl = sx + sw*DNA_TP["ceiling"]/scale
    S.box(sx, sy, cxl-sx, 0.22, fill=C["green"], shape="RECTANGLE")
    S.box(cxl, sy, sx+sw-cxl, 0.22, fill=R, shape="RECTANGLE")
    S.box(cxl-0.02, sy-0.45, 0.04, 0.9, fill=D, shape="RECTANGLE")
    S.box(cxl+0.08, sy+0.25, 1.4, 0.28, [(f"Ceiling {DNA_TP['ceiling']:.2f}", 11, D, True)])
    S.box(sx+sw-0.8, sy+0.25, 0.85, 0.28, [(f"{scale:.2f}", 10, M, False)], align="END")
    for v in (DNA_PA, DNA_TP["total"], DNA_DECOM):
        m = sx + sw*v/scale
        S.box(m-0.11, sy, 0.22, 0.22, fill=W, outline=D, weight=2, shape="ELLIPSE")
    S.box(sx+1.4, sy-0.5, 2.6, 0.48, [(f"Trade promotion  {DNA_TP['total']:.2f}", 12, D, True),
                                       ("practice ahead · stays in force", 10, C["green"], True)], spacing=0, valign="BOTTOM")
    S.box(sx-0.05, sy+0.25, 2.8, 0.48, [(f"Production access  {DNA_PA:.2f}", 12, D, True),
                                         ("document ahead · stays in force", 10, C["green"], True)], spacing=0)
    S.box(cxl+0.15, sy-0.5, sx+sw-cxl-0.2, 0.48, [(f"Decommissioning  {DNA_DECOM:.2f}", 12, D, True),
                                                   ("practice ahead · back to review", 10, R, True)], spacing=0, valign="BOTTOM")
    S.box(qx+3.1, gy+2.6, qw-3.35, 0.3, [("Combined from decision logs, network analysis or interviews",
                                          10, M, False, "i")], align="END")
    # loop
    by = 5.4
    S.box(0.5, by, 9.0, 0.28, [("3 · RE-MEASURED ON A SCHEDULE YOU SET", 10, M, True)])
    steps = [("Collect evidence", "Decisions and approvals"), ("Recompute", "One value + direction"),
             ("Compare to ceiling", "Keep, or send to review"), ("Re-affirm", "All three sign off")]
    sw4 = (9.0 - 0.1*3) / 4
    for i, (h, b) in enumerate(steps):
        S.box(0.5+i*(sw4+0.1), by+0.32, sw4, 0.98, [(h, 13, W if i == 2 else D, True), (b, 11, W if i == 2 else M, False)],
              fill=T if i == 2 else C["tealtint"], shape="HOME_PLATE" if i < 3 else "ROUND_RECTANGLE", valign="MIDDLE", spacing=0)
    S.box(9.7, by, 3.1, 1.3, [("Policy withdrawn?", 13, R, True),
                              ("Its authority ends at once, and every relation that cites it goes to review.", 11, D, False)],
          fill=C["redtint"], outline=R)
    S.tag("Demo values", y=1.95)


# ---------------------------------------------------------------- 23 section: get started
def s23(S):
    section(S, "PART 5  ·  GETTING STARTED", "How to get started",
            "Start small, start from the questions people actually ask, and let the mesh grow one domain at a time.")


# ---------------------------------------------------------------- 24 pilot
def s24(S):
    S.title("Start with one domain: publish its first products, and let the mesh grow from there")
    S.lead("Ontos proves itself in one domain before anyone changes how the rest of the company works.")
    S.heading(0.5, 2.25, 5.6, "WHAT ONTOS GIVES YOU")
    items = [("Products, not tables", "Data arrives with an owner, a contract and a lifecycle."),
             ("Meaning built in", "One ontology links products, contracts and columns for people and AI."),
             ("Rules that are enforced and checked", "Access and authority written once, delivered, recorded and audited."),
             ("Complements Databricks", "Runs in your workspace, on Unity Catalog, with open standards.")]
    for i, (h, b) in enumerate(items):
        y = 2.65+i*1.02
        S.box(0.5, y, 0.07, 0.86, fill=R, shape="RECTANGLE")
        S.box(0.7, y-0.04, 5.4, 0.98, [(h, 16, D, True), (b, 12, M, False)], spacing=0)
    px, pw = 6.75, 6.05
    S.box(px, 2.25, pw, 4.45, fill=C["redtint"], outline=R, weight=1.5)
    S.box(px+0.25, 2.35, pw-0.5, 0.35, [("A FIRST PILOT", 11, R, True)])
    steps = ["Deploy Ontos in one Databricks workspace.",
             "Pick one domain, its owners and a steward.",
             "Pick a spike: its top questions, a small ontology, and the products that answer them.",
             "Write its access policies, and one authority relation for a key decision.",
             "Open the marketplace to one consumer team; count the requests answered without a meeting."]
    for i, t in enumerate(steps):
        y = 2.82+i*0.75
        S.box(px+0.25, y, 0.44, 0.44, [(str(i+1), 13, W, True)], fill=R, shape="ELLIPSE", align="CENTER", valign="MIDDLE")
        S.box(px+0.85, y-0.06, pw-1.1, 0.7, [(t, 13, D, False)], valign="MIDDLE")


# ---------------------------------------------------------------- 25 questions -> ontology -> products
def s25(S):
    S.title("Pick a spike inside the domain: start from the questions, map them to a small ontology, then to products")
    S.lead("Don't start from the tables. Start from what people in the domain need to know, capture only the business concepts "
           "those questions use, and build the few products that answer them.")
    cw, gap, y, h = 3.85, 0.375, 2.25, 3.3
    xs = [0.5 + i*(cw+gap) for i in range(3)]
    heads = [("1  ·  START FROM THE QUESTIONS", "5 to 10 real questions from people in the domain", M, C["gray"], None),
             ("2  ·  MAP THEM TO A SMALL ONTOLOGY", "Only the concepts the questions use", R, C["redtint"], C["redline"]),
             ("3  ·  MAP THE ONTOLOGY TO PRODUCTS", "2 or 3 products with contracts and semantic links", T, C["tealtint"], None)]
    for i, (hd, sub_, col, fill, ol) in enumerate(heads):
        S.heading(xs[i], y, cw, hd, col)
        S.box(xs[i], y+0.35, cw, h-0.35, fill=fill, outline=ol)
        S.box(xs[i]+0.15, y+h-0.45, cw-0.3, 0.38, [(sub_, 11, col, True, "i")])
        if i < 2:
            S.arrow(xs[i]+cw+0.05, y+0.35+(h-0.35)/2, xs[i+1]-0.05, y+0.35+(h-0.35)/2, color=R, weight=2.25)
    qs = ["Which key accounts are at risk of churning?", "Which promotions paid back last quarter?",
          "Which regions hold our best customers?", "How much do repeat orders earn us?"]
    for j, q in enumerate(qs):
        S.box(xs[0]+0.15, y+0.5+j*0.6, cw-0.3, 0.52, [(f"“{q}”", 12, D, False, "i")], fill=W, outline=C["line"], valign="MIDDLE")
    cpts = ["Customer", "Key account", "Churn risk", "Order", "Promotion", "Revenue", "Region"]
    for j, c_ in enumerate(cpts):
        S.box(xs[1]+0.15+(j % 2)*1.8, y+0.5+(j // 2)*0.47, 1.7, 0.38, [(c_, 12, R, True)], fill=W, outline=R,
              align="CENTER", valign="MIDDLE")
    S.box(xs[1]+0.15, y+2.42, cw-0.3, 0.42, [("Key account is a Customer · Customer places Order · Promotion drives Revenue", 10, D, False, "i")])
    prods = [("Customer 360", "Customer · Key account · Churn risk"), ("Promotion performance", "Promotion · Revenue"),
             ("Sales transactions", "Order · Revenue · Region")]
    for j, (a, b) in enumerate(prods):
        S.box(xs[2]+0.15, y+0.5+j*0.78, cw-0.3, 0.68, [(a, 13, W, True), (b, 11, C["light"], False)], fill=T, spacing=0, valign="MIDDLE")
    S.box(0.5, 5.75, 6.05, 0.95, [("Why questions first", 13, D, True),
                                  ("Every product exists because someone asked a question it answers, and every concept because a question uses it.", 11, M, False)],
          fill=W, outline=C["line"])
    S.box(6.75, 5.75, 6.05, 0.95, [("What to avoid", 13, R, True),
                                   ("Modelling the whole estate up front. You end up with a large catalog and an ontology nobody asked for.", 11, M, False)],
          fill=W, outline=C["redline"])
    S.tag("Illustrative sales domain", y=1.95)


# ---------------------------------------------------------------- 26 choosing the spike & growing
def s26(S):
    S.title("Choose a spike that is wanted, owned and small, then let the mesh grow domain by domain")
    S.lead("The first spike sets the pattern every later domain reuses: the same lifecycle, the same reviews and a shared "
           "ontology that grows with each domain.")
    S.heading(0.5, 2.25, 5.9, "A GOOD SPIKE IS")
    crit = [("Wanted", "People ask these questions today, and the answers take meetings"),
            ("Owned", "A committed data owner and steward in the domain"),
            ("Available", "The data that answers the questions is already in Unity Catalog"),
            ("Small", "5 to 10 questions, up to 20 concepts, 2 or 3 products"),
            ("Measurable", "For example: requests answered without a meeting, time to find data")]
    for i, (h, b) in enumerate(crit):
        y = 2.62 + i*0.82
        S.box(0.5, y+0.08, 0.42, 0.42, [("✓", 13, W, True)], fill=C["green"], shape="ELLIPSE", align="CENTER", valign="MIDDLE")
        S.box(1.05, y, 5.35, 0.74, [(h, 14, D, True), (b, 11, M, False)], spacing=0, valign="MIDDLE")
    px, pw = 6.75, 6.05
    S.heading(px, 2.25, pw, "THEN GROW")
    st = [("Spike", "One domain, a few questions"), ("Domain", "All its key products, policies and authority"),
          ("Mesh", "The next domain reuses the shared ontology")]
    sw3 = (pw - 0.1*2) / 3
    for i, (h, b) in enumerate(st):
        S.box(px+i*(sw3+0.1), 2.62, sw3, 1.15, [(h, 14, W, True), (b, 11, W, False)], fill=[T, R, D][i],
              shape="HOME_PLATE" if i < 2 else "ROUND_RECTANGLE", valign="MIDDLE", spacing=0)
    S.box(px, 4.05, pw, 2.65, fill=C["redtint"], outline=R, weight=1.5)
    S.box(px+0.25, 4.15, pw-0.5, 0.35, [("PLANNED FOR ONTOS 1.4  ·  HELP WITH THE FIRST STEPS", 10, R, True)])
    help_ = [("Estate Import", "Suggests assets, contracts and products from your existing data estate, in phases you review before anything is applied."),
             ("Workload Migration", "Assesses legacy workloads and plans their move to Databricks, with the data product as the unit of migration.")]
    for i, (h, b) in enumerate(help_):
        S.box(px+0.25, 4.55+i*1.03, pw-0.5, 0.95, [(h, 14, D, True), (b, 11, M, False)], fill=W, outline=C["redline"], spacing=0, valign="MIDDLE")
