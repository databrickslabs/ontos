"""Slides 1-13: cover, why, fit, three branches, data mesh, meaning."""
from lib import C, D, T, M, R, W


def section(S, part, title, sub):
    S.box(0.5, 2.45, 11.9, 0.45, [(part, 14, R, True)])
    S.placeholder_text("TITLE", title)
    S.box(0.5, 4.6, 8.4, 1.2, [(sub, 18, C["light"], False)])


def outcomes(S, items, y=5.6, h=1.1, size=(16, 12)):
    ow = (12.3 - 0.3*(len(items)-1)) / len(items)
    for i, (hd, b) in enumerate(items):
        ox = 0.5 + i*(ow+0.3)
        S.box(ox, y, ow, 0.06, fill=R, shape="RECTANGLE")
        S.box(ox, y+0.12, ow, h, [(hd, size[0], D, True), (b, size[1], M, False)])


# ---------------------------------------------------------------- 1 cover
def s01(S):
    S.placeholder_text("CENTERED_TITLE", "Ontos: the business catalog for Databricks")
    S.placeholder_text("SUBTITLE", "Data people can find, trust and use: managed as business products, governed by your rules, "
                                   "grounded in one shared business language.")


# ---------------------------------------------------------------- 2 why
def s02(S):
    S.title("A catalog lists what exists; the business needs to know who owns it, what it means and who may use it")
    S.lead("Unity Catalog governs the platform: tables, permissions, lineage and audit. Business users, stewards and AI agents "
           "ask different questions, and today they answer them in meetings, spreadsheets and email.")
    # left: the inventory
    S.heading(0.5, 2.25, 3.0, "THE INVENTORY")
    objs = ["orders  ·  table", "customers  ·  table", "web_events  ·  table", "v_sales_summary  ·  view", "churn_model  ·  model"]
    for i, o in enumerate(objs):
        S.box(0.5, 2.62+i*0.62, 3.0, 0.5, [(o, 12, D, False)], fill=C["gray"], outline=C["line"], valign="MIDDLE")
    # middle: questions
    S.heading(4.25, 2.25, 4.0, "EVERY OBJECT RAISES THREE QUESTIONS")
    qs = [("Who owns it?", "One technical owner, or a group nobody can explain"),
          ("What does it mean?", "Column names, not business terms"),
          ("May I use it?", "Ask around, open a ticket, wait")]
    for i, (q, b) in enumerate(qs):
        S.box(4.25, 2.62+i*1.04, 4.0, 0.9, [(q, 16, D, True), (b, 12, M, False)], fill=W, outline=C["line"], valign="MIDDLE")
    S.arrow(3.6, 4.0, 4.15, 4.0, weight=2.25)
    S.arrow(8.35, 4.0, 8.9, 4.0, color=R, weight=2.25)
    # right: the product
    S.heading(9.0, 2.25, 3.8, "ONTOS: ONE PRODUCT ANSWERS ALL THREE", R)
    S.box(9.0, 2.62, 3.8, 3.02, fill=C["redtint"], outline=R, weight=1.5)
    S.box(9.15, 2.72, 3.5, 0.45, [("Customer 360  ·  data product", 15, D, True)])
    ans = [("Owned", "Data owner, technical owner, business sponsor"),
           ("Meaningful", "Linked to Customer and Churn risk"),
           ("Usable", "Certified; request access in one step")]
    for i, (h, b) in enumerate(ans):
        S.box(9.15, 3.22+i*0.8, 3.5, 0.72, [(h, 13, R, True), (b, 11, D, False)], fill=W, outline=C["redline"])
    outcomes(S, [("Owned", "Named business roles, not just a technical principal"),
                 ("Understood", "Business meaning attached to every product and column"),
                 ("Usable", "Consumers subscribe instead of asking around")], y=5.85, h=0.85, size=(15, 12))
    S.tag("Illustrative example")


# ---------------------------------------------------------------- 3 fit
def s03(S):
    S.title("Ontos is the business catalog on top of Unity Catalog and the rest of your data estate")
    S.lead("Unity Catalog stays the system of record for data and access. Ontos adds what the business needs on top: products, "
           "meaning, rules and decisions. It runs inside your Databricks workspace and also covers assets on other platforms.")
    x0, w = 0.5, 8.3
    S.box(x0, 2.25, w, 0.92, [("WHO IT SERVES", 10, M, True)], fill=C["gray"])
    chips = ["Business users", "Data producers", "Stewards & governance", "Security", "AI assistants"]
    cw = (w - 0.3 - 0.12*4) / 5
    for i, c in enumerate(chips):
        S.box(x0+0.15+i*(cw+0.12), 2.57, cw, 0.48, [(c, 12, D, True)], fill=W, outline=C["line"], align="CENTER", valign="MIDDLE")
    S.box(x0, 3.3, w, 1.95, [("ONTOS  ·  BUSINESS CATALOG", 11, R, True)], fill=C["redtint"], outline=R, weight=1.5)
    tiles = [("Data products & contracts", "Owned, versioned, promised"),
             ("Ontology", "Business meaning, defined once"),
             ("Marketplace", "Find, trust, subscribe"),
             ("Access policies", "Who may do what"),
             ("Authority", "Who may decide what")]
    tw = (w - 0.3 - 0.12*4) / 5
    for i, (h, b) in enumerate(tiles):
        S.box(x0+0.15+i*(tw+0.12), 3.68, tw, 1.42, [(h, 13, D, True), (b, 11, M, False)], fill=W, outline=C["redline"])
    S.box(x0, 5.38, 5.45, 1.32, [("DATABRICKS DATA INTELLIGENCE PLATFORM", 10, C["light"], True),
                                 ("Unity Catalog", 15, W, True),
                                 ("Data, permissions, lineage and audit", 12, C["light"], False),
                                 ("Lakehouse  ·  Genie  ·  Databricks Apps", 12, C["light"], False)], fill=D)
    S.box(x0+5.6, 5.38, w-5.6, 1.32, [("OTHER PLATFORMS", 10, T, True),
                                      ("Warehouses, BI tools, event streams", 13, D, True),
                                      ("and business assets with no physical form yet", 11, M, False)], fill=C["tealtint"])
    rx, rw = 9.15, 3.65
    S.heading(rx, 2.25, rw, "WHY IT COMPLEMENTS DATABRICKS")
    items = [("The business view", "Unity Catalog answers what exists and who can read it. Ontos answers what it means and who stands behind it."),
             ("No new silo", "Runs as an app in your workspace, uses your Unity Catalog permissions. Data never leaves."),
             ("Open standards", "Products, contracts, policies and ontologies are exchanged in open, industry formats.")]
    y = 2.62
    for h, b in items:
        S.box(rx, y, 0.07, 1.12, fill=R, shape="RECTANGLE")
        S.box(rx+0.18, y-0.05, rw-0.18, 1.3, [(h, 15, D, True), (b, 12, M, False)])
        y += 1.38


# ---------------------------------------------------------------- 4 three branches
def s04(S):
    S.title("Ontos covers the whole operating model: make the rules, carry them out, check that they hold")
    S.lead("Think of data governance like a constitution. Data Governance is the legislative branch, Data Management the executive, "
           "and audit the judicial. Most tools serve one branch; Ontos connects all three around the same business objects.")
    cols = [("LEGISLATIVE", "Data Governance", "Decides the rules", T, C["tealtint"],
             ["Business vocabulary and ontology", "Domains and ownership roles", "Access policies: who may do what",
              "Authority: who may decide what", "Rules a product must meet before publication",
              "Lifecycles and approval gates"]),
            ("EXECUTIVE", "Data Management", "Carries them out", R, C["redtint"],
             ["Build and publish data products", "Contracts: schema, quality, service levels", "Review, approve and certify",
              "Grant access via requests and agreements", "Deliver grants and tags to Unity Catalog",
              "Tell subscribers about every change"]),
            ("JUDICIAL", "Audit & Conformance", "Checks that they hold", D, C["gray"],
             ["Every decision recorded with its rule", "Products checked against the rules",
              "Grant drift reported as a difference", "Authority measured against real practice",
              "Outdated authority sent back to review", "Full history of who approved what"])]
    cw, gap = 3.95, 0.225
    for i, (k, name, verb, col, tint, items) in enumerate(cols):
        x = 0.5 + i*(cw+gap)
        S.box(x, 2.25, cw, 0.95, [(k, 11, W, True), (name, 18, W, True)], fill=col, valign="MIDDLE",
              shape="ROUND_RECTANGLE")
        S.box(x, 3.28, cw, 2.72, fill=tint)
        S.box(x+0.15, 3.36, cw-0.3, 0.36, [(verb, 13, col, True)])
        for j, it in enumerate(items):
            S.box(x+0.18, 3.8+j*0.36, 0.09, 0.09, fill=col, shape="RECTANGLE")
            S.box(x+0.32, 3.7+j*0.36, cw-0.45, 0.34, [(it, 12, D, False)])
    S.box(0.5, 6.12, 12.3, 0.58, [("One set of business objects connects all three branches: products, contracts, concepts, "
                                   "access policies and authority relations", 14, W, True)],
          fill=D, align="CENTER", valign="MIDDLE")


# ---------------------------------------------------------------- 5 section: data mesh
def s05(S):
    section(S, "PART 1  ·  DATA MESH", "Business objects, managed as products",
            "Domains own their data, publish it as products with a contract, and every product follows the same managed lifecycle.")


# ---------------------------------------------------------------- 6 personas
def s06(S):
    S.title("Six pre-seeded personas each get a self-service path, from first search to final approval")
    S.lead("Data mesh only works when every role can act without waiting in someone else's ticket queue. Each persona opens "
           "Ontos to its own view, its own actions and its own permissions.")
    ps = [("Data Consumer", "Uses data", "Finds data by search, by browsing or by simply asking. Requests access through a guided usage agreement.", R),
          ("Data Producer", "Builds products", "Creates products and contracts from existing assets or standard files, and publishes them to the marketplace.", R),
          ("Data Steward", "Reviews and approves", "Works one review queue. Many people can review, few can approve, and the two are kept apart.", T),
          ("Governance Officer", "Sets the rules", "Defines the rules, vocabularies and lifecycles, and certifies what the company can trust.", T),
          ("Security Officer", "Controls access", "Owns the access policies and sees who can reach what data, and why.", D),
          ("Administrator", "Runs the platform", "Manages roles, connections and the AI assistants that work with Ontos.", D)]
    cw, ch, gx, gy = 3.95, 1.8, 0.225, 0.15
    for i, (n, role, b, col) in enumerate(ps):
        x = 0.5 + (i % 3)*(cw+gx)
        y = 2.3 + (i // 3)*(ch+gy)
        S.box(x, y, cw, ch, fill=W, outline=C["line"])
        S.box(x, y, 0.09, ch, fill=col, shape="RECTANGLE")
        S.box(x+0.25, y+0.12, cw-0.4, ch-0.2, [(role.upper(), 10, col, True), (n, 18, D, True), ("", 4, M, False), (b, 12, M, False)])
    S.box(0.5, 6.18, 12.3, 0.52, [("These are starting points, not a fixed model: adjust any persona's views and permissions, "
                                   "add your own roles, or remove the ones you don't need.", 13, D, True)],
          fill=C["redtint"], outline=R, align="CENTER", valign="MIDDLE")


# ---------------------------------------------------------------- 7 products & contracts
def s07(S):
    S.title("Raw assets become governed products: described by contracts, packaged as products, consumed by subscription")
    S.lead("Producers describe the assets that matter with a data contract, package contracts into data products and publish "
           "them. Consumers subscribe to products, not to tables, and hear about every change from the owner.")
    cw, gap, y, h = 2.75, 0.43, 2.25, 3.25
    heads = ["1  ·  ASSETS BY DOMAIN", "2  ·  UNDER CONTRACT", "3  ·  PACKAGED AS PRODUCTS", "4  ·  SUBSCRIBED"]
    xs = [0.5 + i*(cw+gap) for i in range(4)]
    for i, hd in enumerate(heads):
        S.heading(xs[i], y, cw, hd, R if i else M)
        S.box(xs[i], y+0.35, cw, h-0.35, fill=C["gray"] if i == 0 else C["redtint"], outline=None if i == 0 else C["redline"])
        if i < 3:
            S.arrow(xs[i]+cw+0.06, y+0.35+(h-0.35)/2, xs[i+1]-0.06, y+0.35+(h-0.35)/2, weight=2.25)
    # 1: dots by domain
    doms = [("Sales", R), ("Finance", T), ("Supply chain", C["yellow"])]
    for r, (dn, col) in enumerate(doms):
        yy = y+0.55+r*0.92
        S.box(xs[0]+0.15, yy, 2.4, 0.28, [(dn, 11, D, True)])
        for k in range(8):
            S.box(xs[0]+0.17+k*0.3, yy+0.33, 0.2, 0.2, fill=col, shape="ELLIPSE")
    # 2: contract
    S.box(xs[1]+0.15, y+0.5, cw-0.3, 0.42, [("Customer profile contract", 13, D, True)])
    parts = [("Schema", "what each column holds"), ("Quality rules", "complete, valid, unique"),
             ("Service levels", "fresh daily by 7:00"), ("Terms of use", "who may use it, for what")]
    for j, (a, b) in enumerate(parts):
        S.box(xs[1]+0.15, y+0.95+j*0.56, cw-0.3, 0.5, [(a, 12, D, True), (b, 10, M, False)], fill=W, outline=C["redline"], spacing=0)
    # 3: products
    prods = [("Customer 360", "Sales Ops", R), ("Revenue ledger", "Finance", T), ("Supplier scorecard", "Supply chain", C["yellow"])]
    for j, (a, o, col) in enumerate(prods):
        yy = y+0.55+j*0.88
        S.box(xs[2]+0.15, yy, cw-0.3, 0.76, fill=W, outline=C["redline"])
        S.box(xs[2]+0.15, yy, 0.08, 0.76, fill=col, shape="RECTANGLE")
        S.box(xs[2]+0.3, yy+0.04, cw-0.5, 0.7, [(a, 13, D, True), (f"Owned by {o}", 11, M, False)], spacing=0)
    # 4: subscribers
    subs = ["Marketing analytics", "Finance planning", "Churn prediction", "Sales Genie space", "Executive dashboard"]
    for j, s_ in enumerate(subs):
        S.box(xs[3]+0.15, y+0.55+j*0.52, cw-0.3, 0.42, [(s_, 12, D, False)], fill=W, outline=C["redline"], valign="MIDDLE")
    outcomes(S, [("Contracts are the promise", "Schema, quality and service levels, agreed before anyone depends on them"),
                 ("Products are the unit of ownership", "Each one has named owners, a lifecycle and a place in the marketplace"),
                 ("Subscriptions are the relationship", "Owners know who depends on them; consumers hear about changes first")],
             y=5.7, h=1.0, size=(14, 12))
    S.tag("Illustrative company")


# ---------------------------------------------------------------- 8 value chain
def s08(S):
    S.title("Products chain like parts in a supply chain: one product's output is the next one's input")
    S.lead("A data product is a set of assets sold together, like a car with its manual and its keys. Products sit along a value "
           "chain, and a contract on every hand-off states exactly what flows between them.")
    chain = [("SOURCE-ALIGNED", "Point-of-sale feed", "Store systems team"),
             ("AGGREGATE", "Sales transactions", "Sales data team"),
             ("CONSUMER-ALIGNED", "Customer 360", "Sales Ops"),
             ("CONSUMER-ALIGNED", "Churn insights", "Customer success")]
    pw, gap, y = 2.45, 0.83, 2.4
    for i, (k, n, o) in enumerate(chain):
        x = 0.5 + i*(pw+gap)
        hl = i == 2
        S.box(x, y, pw, 1.25, [(k, 10, R if hl else M, True), (n, 15, D, True), (f"Owner: {o}", 11, M, False)],
              fill=C["redtint"] if hl else W, outline=R if hl else C["line"], weight=1.5 if hl else 1)
        if i < 3:
            cx = x+pw+0.05
            S.arrow(cx, y+0.62, cx+gap-0.1, y+0.62, color=R, weight=2.25)
            S.box(cx-0.05, y+0.72, gap, 0.42, [("contract", 10, R, True)], align="CENTER")
    # what's inside Customer 360
    x2 = 0.5 + 2*(pw+gap)
    S.line(x2+pw/2, y+1.3, x2+pw/2, y+1.6, color=R, weight=1.5, head=False)
    S.box(3.3, y+1.6, 6.72, 1.45, fill=C["gray"])
    S.box(3.45, y+1.68, 6.4, 0.3, [("SOLD TOGETHER: WHAT CUSTOMER 360 CONTAINS", 10, M, True)])
    inside = ["Customer profile table", "Customer events table", "Segment view", "Churn dashboard", "User guide"]
    iw = (6.4 - 0.1*4)/5
    for j, it in enumerate(inside):
        S.box(3.45+j*(iw+0.1), y+2.05, iw, 0.85, [(it, 11, D, True)], fill=W, outline=C["line"], align="CENTER", valign="MIDDLE")
    S.box(0.5, y+1.6, 2.6, 1.45, [("Input ports", 13, D, True), ("What a product consumes, each under the upstream contract", 11, M, False)])
    S.box(10.22, y+1.6, 2.6, 1.45, [("Output ports", 13, D, True), ("What it delivers, each backed by its own contract", 11, M, False)])
    outcomes(S, [("Change with confidence", "Every hand-off has a contract, so producers know exactly who depends on them"),
                 ("Trace impact", "Follow the chain from the source system to the decision it informs"),
                 ("Clear accountability", "Every link in the chain has an owner on both sides")],
             y=5.75, h=0.95, size=(14, 12))
    S.tag("Illustrative value chain")


# ---------------------------------------------------------------- 9 lifecycle
def s09(S):
    S.title("Every business object moves through a managed lifecycle, with an owner and a reviewer at every gate")
    S.lead("Lifecycle stages are not labels; they are gates. Each kind of object has its own lifecycle; shown here is the default "
           "for data products. Ontos routes each step to the right people, records the decision and tells everyone affected.")
    stages = [("Build", "Producer drafts in private and tries it out in a sandbox", "Tracks readiness and maturity checks", "The owning team"),
              ("Review", "Reviewers check the product and its contracts", "Opens a review task, so nobody chases by email", "Requester and reviewers"),
              ("Approve", "An approving steward signs off", "Activates it and pushes tags and grants to Unity Catalog", "Owners and stewards"),
              ("Publish & certify", "Governance certifies it as trusted", "Lists only reviewed products in the marketplace", "Interested consumers"),
              ("Retire", "The owner deprecates it with a sunset date", "Warns every subscriber before anything disappears", "Every subscriber")]
    lw, x0 = 1.55, 0.5
    sw = (12.3 - lw - 0.1*4) / 5
    y0 = 2.3
    for i, (n, who, does, hears) in enumerate(stages):
        x = x0 + lw + i*(sw+0.1)
        S.box(x, y0, sw, 0.62, [(f"{i+1}  {n}", 14, W, True)], fill=R if i == 3 else T,
              shape="HOME_PLATE" if i < 4 else "ROUND_RECTANGLE", valign="MIDDLE")
        for r, t in enumerate([who, does, hears]):
            S.box(x, y0+0.75+r*0.95, sw, 0.85, [(t, 12, D, False)], fill=C["redtint"] if r == 1 else C["gray"], valign="MIDDLE")
    for r, lab in enumerate(["WHO ACTS", "WHAT ONTOS DOES", "WHO HEARS"]):
        S.box(x0, y0+0.75+r*0.95, lw-0.1, 0.85, [(lab, 10, R if r == 1 else M, True)], valign="MIDDLE")
    S.box(0.5, 5.95, 12.3, 0.72, [("Contracts, concepts, access policies and authority relations each have a lifecycle of their own, with the same "
                                   "reviews and history.", 13, D, True),
                                  ("Coming in Ontos 1.2: fully customizable lifecycle stages and transitions, per type of object.", 13, R, True)],
          fill=C["redtint"], outline=R, valign="MIDDLE", align="CENTER")


# ---------------------------------------------------------------- 10 marketplace
def s10(S):
    S.title("One marketplace listing answers the six questions a consumer would otherwise email about")
    S.lead("Think of a familiar online store, for data. Before anyone opens a table, the listing answers the questions that "
           "usually take a meeting.")
    # listing mock
    lx, ly, lw, lh = 0.5, 2.25, 6.3, 4.45
    S.box(lx, ly, lw, lh, fill=W, outline=C["line"], weight=1.25)
    S.box(lx+0.25, ly+0.15, 3.6, 0.5, [("Customer 360", 20, D, True)])
    S.box(lx+3.95, ly+0.22, 1.0, 0.34, [("Certified", 10, W, True)], fill=C["green"], align="CENTER", valign="MIDDLE")
    S.box(lx+5.05, ly+0.22, 0.95, 0.34, [("Active", 10, T, True)], fill=C["tealtint"], align="CENTER", valign="MIDDLE")
    S.box(lx+0.25, ly+0.68, lw-0.9, 0.35, [("Owned by Sales Ops  ·  Steward: M. Rivera", 12, M, False)])
    S.box(lx+0.25, ly+1.08, lw-0.9, 0.6, [("Fresh daily by 7:00  ·  99.8% complete", 12, D, False),
                                          ("12 of 12 quality checks passing  ·  DQX and dbt", 12, C["green"], True)],
          fill=C["gray"], valign="MIDDLE")
    S.box(lx+0.25, ly+1.8, 1.0, 0.3, [("Concepts", 11, M, True)])
    for j, cpt in enumerate(["Customer", "Key account", "Churn risk"]):
        S.box(lx+1.25+j*1.45, ly+1.78, 1.35, 0.34, [(cpt, 11, R, True)], fill=C["redtint"], outline=C["redline"],
              align="CENTER", valign="MIDDLE", shape="ROUND_RECTANGLE")
    S.box(lx+0.25, ly+2.3, 2.0, 0.3, [("Output ports", 11, M, True)])
    for j, port in enumerate(["Customer profile", "Customer events", "Segments"]):
        S.box(lx+0.25+j*1.83, ly+2.62, 1.73, 0.42, [(port, 11, D, True)], fill=C["tealtint"], align="CENTER", valign="MIDDLE")
    S.box(lx+0.25, ly+3.22, 3.4, 0.4, [("★★★★☆  4.6  ·  12 reviews", 12, D, False)])
    S.box(lx+0.25, ly+3.6, 3.6, 0.6, [("“Could we get a check on duplicate emails?”", 11, M, False, "i")])
    S.box(lx+4.15, ly+3.45, 1.9, 0.55, [("Request access", 13, W, True)], fill=R, align="CENTER", valign="MIDDLE")
    marks = [(lx+5.85, ly+0.62), (lx+5.85, ly+1.15), (lx+5.85, ly+1.78), (lx+5.85, ly+2.62), (lx+2.95, ly+3.24), (lx+3.65, ly+3.55)]
    for k, (mx, my) in enumerate(marks):
        S.box(mx, my, 0.36, 0.36, [(str(k+1), 11, W, True)], fill=D, shape="ELLIPSE", align="CENTER", valign="MIDDLE")
    # questions
    qs = [("Who owns it?", "A named team, data owner and steward"),
          ("Can I trust it?", "Certification, freshness and data quality: checks run with the built-in DQX, or results sent in from tools like dbt"),
          ("What does it mean?", "The business concepts it carries"),
          ("What's inside?", "Output ports, each backed by a contract"),
          ("What do others say?", "Ratings, comments and suggested quality checks"),
          ("How do I get it?", "A guided usage agreement, approved by workflow, delivered as a time-bound grant")]
    qx = 7.15
    for k, (q, a) in enumerate(qs):
        yy = 2.25 + k*0.75
        S.box(qx, yy+0.05, 0.36, 0.36, [(str(k+1), 11, W, True)], fill=D, shape="ELLIPSE", align="CENTER", valign="MIDDLE")
        S.box(qx+0.5, yy-0.02, 12.8-qx-0.5, 0.72, [(q, 14, D, True), (a, 12, M, False)], spacing=0)
    S.tag("Illustrative listing", x=4.3)


# ---------------------------------------------------------------- 11 section: meaning
def s11(S):
    section(S, "PART 2  ·  MEANING", "Ontologies: the shared language of the business",
            "Business concepts, defined once, linked to the data that carries them, and used by people and AI assistants alike.")


# ---------------------------------------------------------------- 12 knowledge graph
def s12(S):
    S.title("Semantic links tie business concepts to products and columns, so people search by meaning")
    S.lead("Concepts come from your ontology and glossary, with real relationships between them. Semantic links attach them to the "
           "data, so a search for a concept finds the data that carries it, even when no table is named after it.")
    # bands
    S.box(0.5, 2.25, 8.0, 2.0, fill=C["gray"])
    S.box(0.5, 4.4, 8.0, 2.12, fill=C["tealtint"])
    S.box(6.4, 3.85, 2.0, 0.3, [("ONTOLOGY", 10, M, True)], align="END")
    S.box(0.6, 4.45, 1.2, 0.3, [("DATA", 10, T, True)])
    cw, chh = 1.5, 0.5
    cpt = {"Key account": (0.65, 2.45), "Customer": (2.65, 2.45), "Order": (4.65, 2.45), "Revenue": (6.65, 2.45),
           "Churn risk": (3.65, 3.4)}
    for n, (x, y) in cpt.items():
        S.box(x, y, cw, chh, [(n, 13, R, True)], fill=C["redtint"], outline=R, shape="ROUND_RECTANGLE", align="CENTER", valign="MIDDLE")
    rels = [((2.15, 2.7), (2.65, 2.7), "is a"), ((4.15, 2.7), (4.65, 2.7), "places"), ((6.15, 2.7), (6.65, 2.7), "earns")]
    for (a, b, lab) in rels:
        S.arrow(a[0], a[1], b[0], b[1], color=D, weight=1.5)
        S.box(a[0]-0.25, a[1]-0.42, 1.0, 0.3, [(lab, 9, D, False, "i")], align="CENTER")
    S.arrow(4.2, 3.4, 3.9, 2.95, color=D, weight=1.5)
    S.box(4.15, 3.02, 0.6, 0.3, [("of", 9, D, False, "i")])
    # data nodes
    prod = {"Customer 360": (1.65, 4.8), "Sales transactions": (5.45, 4.8)}
    for n, (x, y) in prod.items():
        S.box(x, y, 1.75, 0.55, [(n, 12, W, True)], fill=T, align="CENTER", valign="MIDDLE")
    cols = {"acct_tier": (0.6, 5.85), "churn_score": (3.7, 5.85), "order_amount": (6.95, 5.85)}
    for n, (x, y) in cols.items():
        S.box(x, y, 1.35, 0.42, [(n, 11, T, True)], fill=W, outline=T, align="CENTER", valign="MIDDLE", shape="RECTANGLE")
    # contains
    for a, b in [((2.3, 5.35), (1.3, 5.85)), ((2.75, 5.35), (4.37, 5.85)), ((6.6, 5.35), (7.62, 5.85))]:
        S.line(a[0], a[1], b[0], b[1], color=C["light"], weight=1.25, head=False)
    # semantic links
    for a, b in [((3.4, 2.95), (2.6, 4.8)), ((1.3, 2.95), (1.25, 5.85)), ((4.45, 3.9), (4.42, 5.85)),
                 ((5.4, 2.95), (6.3, 4.8)), ((7.4, 2.95), (7.62, 5.85))]:
        S.line(a[0], a[1], b[0], b[1], color=R, weight=1.75, dash="DASH", head=False)
    # legend
    lg = [("Concept", C["redtint"], R), ("Data product", T, None), ("Column", W, T)]
    lx = 0.5
    for n, f, o in lg:
        S.box(lx, 6.62, 0.26, 0.2, fill=f, outline=o, shape="RECTANGLE")
        S.box(lx+0.32, 6.56, 1.3, 0.3, [(n, 10, M, False)])
        lx += 1.55
    S.line(lx, 6.72, lx+0.45, 6.72, color=D, weight=1.5, head=False)
    S.box(lx+0.5, 6.56, 1.4, 0.3, [("Ontology relation", 10, M, False)])
    lx += 2.0
    S.line(lx, 6.72, lx+0.45, 6.72, color=R, weight=1.75, dash="DASH", head=False)
    S.box(lx+0.5, 6.56, 1.4, 0.3, [("Semantic link", 10, M, False)])
    # search panel
    rx, rw = 8.8, 4.0
    S.heading(rx, 2.25, rw, "SEARCH BY MEANING")
    S.box(rx, 2.6, rw, 0.5, [("Search:  churn risk", 13, D, False)], fill=W, outline=D, valign="MIDDLE")
    res = [("Customer 360", "Data product  ·  carries Customer"),
           ("churn_score", "Column  ·  means Churn risk"),
           ("Churn insights", "Data product  ·  downstream of Customer 360")]
    for j, (a, b) in enumerate(res):
        S.box(rx, 3.2+j*0.72, rw, 0.64, [(a, 13, D, True), (b, 11, M, False)], fill=C["gray"], spacing=0, valign="MIDDLE")
    S.box(rx, 5.4, rw, 1.1, [("Found by meaning", 14, R, True),
                             ("No table is called “churn risk”: the ontology and its links lead there, for people and AI assistants alike.", 12, M, False)])
    S.tag("Illustrative knowledge graph")


# ---------------------------------------------------------------- 13 ontology governance work
def s13(S):
    S.title("The ontology also does governance work: it finds gaps, reveals domains and keeps AI grounded")
    S.lead("Once meaning is part of the catalog, it becomes a working tool for stewards and governance, not only a search aid.")
    tiles = [("Close meaning gaps", "Ontos shows the columns that carry no concept yet, suggests one, and a steward decides."),
             ("Discover domains of meaning", "Grouping the graph by its links reveals your business areas: a strong starting point for data mesh domains."),
             ("One vocabulary for every team", "Definitions are agreed once and reused, so reports stop disagreeing. Start from industry ontologies and grow."),
             ("Govern by business object", "Access policies and authority attach to concepts such as Customer or Trade promotion, not to single tables."),
             ("Ground AI in governed meaning", "Ask Ontos and Genie answer with the same concepts, products and rules your people use."),
             ("Concepts have a lifecycle too", "New and changed terms are proposed, reviewed and approved, just like products.")]
    cw, ch, gx, gy = 3.95, 2.0, 0.225, 0.2
    for i, (h, b) in enumerate(tiles):
        x = 0.5 + (i % 3)*(cw+gx)
        y = 2.3 + (i // 3)*(ch+gy)
        S.box(x, y, cw, ch, fill=C["redtint"] if i in (0, 3) else C["gray"], outline=C["redline"] if i in (0, 3) else None)
        S.box(x+0.2, y+0.18, 0.5, 0.5, [(str(i+1), 14, W, True)], fill=R if i in (0, 3) else T, shape="ELLIPSE",
              align="CENTER", valign="MIDDLE")
        S.box(x+0.2, y+0.78, cw-0.4, ch-0.85, [(h, 16, D, True), (b, 12, M, False)])
