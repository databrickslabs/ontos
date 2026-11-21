"""Five-part speaker notes for every slide of the Ontos business deck. Re-runnable."""
from lib import g
from build import PID


def n(purpose, talk, evidence, transition, question):
    return dict(purpose=purpose, talk_track=talk, evidence=evidence, transition=transition, likely_question=question)


NOTES = [
 n("Open: position Ontos as the business catalog that sits on top of Databricks, for governance practitioners.",
   "Most organisations already have plenty of metadata. What they lack is data that arrives the way a product does: with an "
   "owner, a promise about what it contains, a record of who approved it, and a place to find it. Ontos is the business catalog "
   "for Databricks. It manages data as business products using data mesh principles, governs it with the rules you set, and "
   "grounds it in one shared business language, an ontology. Over the next minutes: why, where it fits, and the four parts: "
   "products, meaning, access and authority.",
   ["Open source, runs as a Databricks App inside the customer's own workspace", "Built on open standards for products, contracts, policies and ontologies"],
   "Let's start with the question every catalog leaves open.",
   "Is this another catalog to run next to Unity Catalog? No. Unity Catalog stays the system of record; Ontos adds the business layer on top of it."),
 n("Name the gap: a technical inventory doesn't answer business questions.",
   "Here is what a catalog gives you: tables, views and models. Every one raises the same three questions. Who owns this? What "
   "does it mean? Am I allowed to use it? Today the answer is a meeting, a spreadsheet or a ticket. In Ontos the objects become "
   "one data product, Customer 360. It has business owners in named roles: a data owner, a technical owner and a business sponsor. "
   "It is linked to the concepts it carries. And it has been approved, certified and published, so consumers request access in "
   "one step instead of asking around.",
   ["Illustrative example; Customer 360 and Sales Ops are sample names", "Unity Catalog records one owner principal; Ontos adds named business roles"],
   "So where exactly does Ontos sit relative to Databricks?",
   "Do we have to convert every table into a product? No. Start with the datasets people ask about most; the rest stays in the catalog."),
 n("Show the architecture in business terms: Ontos complements, never replaces, Unity Catalog.",
   "Unity Catalog governs the platform: data, permissions, lineage and audit. Ontos sits on top and serves the people who need "
   "the business view: business users, producers, stewards, security and AI assistants. It manages five kinds of business object: "
   "data products and contracts, the ontology, the marketplace, access policies and authority. It runs inside your Databricks "
   "workspace and uses the permissions you already have, so no data leaves and nothing new has to be secured. It can also cover "
   "assets on other platforms, and even business assets that don't exist physically yet.",
   ["Runs as a Databricks App; enforces Unity Catalog permissions", "Exchanges products, contracts, policies and ontologies in open formats"],
   "Now a way to think about what Ontos covers: the three branches of government.",
   "How does this relate to Databricks' own discovery features? They help you find tables. Ontos adds ownership, contracts, meaning, rules and decisions on top."),
 n("Frame Ontos with the separation-of-powers analogy: it covers legislative, executive and judicial work.",
   "A useful way to think about data governance is a constitution. Data Governance is the legislative branch: it decides the "
   "rules, meaning the vocabulary, the ownership roles, who may access what, who may decide what, and what a product must meet before "
   "it is published. Data Management is the executive branch: it carries those rules out, building and publishing products, "
   "writing contracts, reviewing and approving, granting access and delivering it to Unity Catalog. And there is a third branch "
   "people often forget, the judicial: checking that the rules actually hold. Every decision is recorded, drift in grants shows "
   "up as a difference, and authority is measured against how decisions are really made. Most tools serve one branch. Ontos "
   "connects all three around the same business objects.",
   ["Analogy for the operating model; every item listed maps to an Ontos capability shown later in the deck"],
   "Let's start with the executive branch's main object: the data product.",
   "Doesn't this blur responsibilities? The opposite: Ontos keeps reviewers and approvers apart, and records who did what in each branch."),
 n("Section break: data mesh and the managed lifecycle of business objects.",
   "Part one is data mesh. Domains own their data, publish it as products with a contract, and every product follows the same "
   "managed lifecycle.",
   ["Data mesh principles: domain ownership, data as a product, self-service, federated governance"],
   "Data mesh starts with people, so let's look at who uses Ontos.",
   "Do we need a full data mesh reorganisation to use this? No. Ontos supports a gradual move, one domain at a time."),
 n("Show self-service for every role: the foundation of a working data mesh.",
   "Data mesh only works if every role can act without waiting on another team. Ontos ships with six personas, each with its "
   "own view and permissions. These are pre-seeded starting points: you can adjust any of them, add your own roles, or remove the ones you don't need. Consumers search, browse or simply ask, then request access through a guided usage agreement. "
   "Producers create products from existing assets or by uploading standard files. Stewards work one review queue, with reviewers "
   "and approvers kept apart. The governance officer sets the rules and certifies. The security officer sees who can access what. "
   "And the administrator runs Ontos as a platform, including the AI assistants that work with it.",
   ["Pre-seeded roles: fully adjustable, and roles can be added or removed", "Separation of duties: review and approval are distinct permissions"],
   "What do producers actually create? Contracts and products.",
   "Can we map these to our existing roles? Yes. Roles map to your identity groups, and teams can carry role overrides."),
 n("Explain contracts and products in plain terms: the promise and the unit of ownership.",
   "Each dot is one table, view or model in one company's three domains. On their own, none of them says what it is for. "
   "Producers describe the assets that matter with a contract: what each column holds, the quality rules, the service levels, "
   "the terms of use. Contracts are packaged into data products, each owned by a team. Consumers then subscribe to products, "
   "not tables, and the owner knows exactly who depends on them.",
   ["Illustrative company", "Contracts and products follow the open ODCS and ODPS standards"],
   "Products rarely stand alone; they form chains.",
   "Who writes contracts, IT or the business? Both. The business states the promise; producers fill in the technical detail."),
 n("Show the value chain: products feed products, and contracts make each hand-off explicit.",
   "A data product is a set of assets sold together, like a car with its manual and its keys. Here Customer 360 contains tables, "
   "a view, a dashboard and a user guide. Products sit along a value chain, from source-aligned products close to the systems, "
   "through aggregates, to consumer-aligned products built for a use. On every hand-off there is a contract, so a producer "
   "knows who depends on them, and a consumer knows what they can rely on.",
   ["Illustrative value chain", "Source-aligned, aggregate and consumer-aligned are standard data mesh product types"],
   "Every one of those products goes through the same managed lifecycle.",
   "What happens when an upstream product changes? Its subscribers are told, and the contract shows what they relied on."),
 n("Make lifecycle governance tangible: stages are gates with people, actions and notifications.",
   "Every kind of business object has its own lifecycle; this is the default one for data products. The producer builds in a private draft and can try it in a sandbox, while "
   "readiness checks fill in. Requesting a review opens a task, so nobody chases reviewers by email. An approving steward signs "
   "off; many people can review, few can approve. Ontos then activates the product and can push tags and grants to Unity "
   "Catalog. Publication and certification are their own steps, so the marketplace only shows what was reviewed. Retirement "
   "warns every subscriber before anything disappears. Contracts, concepts, policies and authority relations have lifecycles "
   "of their own, with the same reviews and history. And in Ontos 1.2, lifecycle stages and transitions become fully customizable "
   "per type of object.",
   ["Default data product lifecycle shown; each entity type has its own", "Ontos 1.2: fully customizable lifecycle stages and transitions", "Every transition is recorded in the object's history"],
   "Once a product is published, this is what a consumer sees.",
   "Can we add our own approval steps? Yes. Workflows are configurable per object type."),
 n("Show the consumer experience: one listing replaces a meeting.",
   "Think of a familiar online store, for data. Before anyone opens a table, the listing answers six questions. Who owns it: "
   "a named team and steward. Can I trust it: certification, freshness and data quality. Quality checks either run in Ontos with the integrated DQX, or results come in from the tools you already use, such as dbt tests. What does it mean: the "
   "business concepts it carries. What's inside: output ports, each backed by a contract. What do others say: ratings, comments "
   "and quality checks consumers suggest to the owner. And how do I get it: a guided usage agreement, approved by workflow, "
   "delivered as a Unity Catalog grant, and time-bound with a reminder before it expires.",
   ["Illustrative listing", "Data quality: integrated DQX checks, or metrics received from external tools such as dbt",
    "Access is delivered through Unity Catalog; agreements carry the disclaimers the owner set"],
   "The third question, what does it mean, is where Ontos goes further. That's part two.",
   "Does access need a human every time? No. Owners decide which requests auto-approve and which go to a reviewer."),
 n("Section break: ontologies and semantics.",
   "Part two is meaning. Business concepts are defined once, linked to the data that carries them, and used by people and AI "
   "assistants alike.",
   ["Ontologies and glossaries in open semantic web standards"],
   "Here's what that looks like as a graph.",
   "Is an ontology just a glossary? A glossary lists terms; an ontology also captures how they relate, which is what makes discovery and reasoning possible."),
 n("Make semantic discovery concrete: search a concept, reach the data.",
   "Concepts come from your ontology and glossary, with real relationships: a key account is a customer, a customer places "
   "orders, orders earn revenue, churn risk is a property of a customer. Semantic links attach those concepts to products and "
   "columns. So when someone searches for churn risk, they find the churn_score column and the Customer 360 product, even "
   "though no table is named after it. The same graph serves people in search and AI assistants answering questions.",
   ["Illustrative knowledge graph", "Concepts link to data products, contracts and individual columns"],
   "Meaning is more than a search aid. It does governance work too.",
   "Do we have to build an ontology from scratch? No. Start from industry ontologies or your existing glossary, and grow one domain at a time."),
 n("Show the governance uses of the ontology beyond discovery.",
   "Once meaning is part of the catalog, it becomes a tool for stewards. Ontos shows the columns that carry no concept yet "
   "and suggests one; a steward decides. Grouping the graph by its links reveals your business areas, a strong starting point "
   "for mesh domains. Definitions are agreed once, so reports stop disagreeing. Policies and authority attach to concepts such as "
   "Customer or Trade promotion, not to single tables. Ask Ontos and Genie answer with the same governed meaning. And concepts "
   "have a lifecycle too: proposed, reviewed and approved like products.",
   ["Meaning-gap suggestions are reviewed by a steward before they are applied", "Concepts carry status, owners and review history"],
   "Meaning tells us what data is. The next question is who may use it. Part three: access.",
   "Who owns the ontology? Governance owns the shared core; domains propose extensions through review."),
 n("Section break: access policies.",
   "Part three is access. Policies are written once in business terms, checked on every request, and delivered to the "
   "platform as tracked grants.",
   ["Policies follow the W3C ODRL rights standard"],
   "Let's look at one policy.",
   "Does this replace Unity Catalog permissions? No. Unity Catalog keeps enforcing; Ontos decides what to grant and keeps track of it."),
 n("Explain a policy without jargon: who, may or must not, do what, on which data, with which duties.",
   "A policy is written once, in business terms, following the W3C open standard for digital rights. This one, Sales analytics "
   "read, says Sales Analysts may read the sales data, and must not read HR records. When both apply to the same person, the "
   "prohibition wins. The who and the what are not lists of names: they are reusable audiences and asset collections. Change "
   "who is in Sales Analysts once, and every policy that uses it follows. Audiences can be teams, named people, or anyone "
   "holding a business role such as Data Steward. And permissions can carry duties, such as accepting terms of use first.",
   ["Ontos demo example: 5 audiences and 3 asset collections reused across the policies", "Conflict strategy in the demo: prohibition overrides permission"],
   "What does that mean for actual requests?",
   "Can policies have an end date? Yes. Rules can be time-bound, and the resulting grants are revoked on expiry."),
 n("Show that every request gets a clear, explainable answer.",
   "Six people ask for seven things. Each cell is the answer Ontos returns from the active policies, with the rules that "
   "matched. Only 14 of the 42 requests meet a rule; everything else is denied by default. The highlighted cell is the point of "
   "the prohibition: Alice is a sales analyst, so she reads sales data, but her audience is prohibited from HR records, and "
   "the prohibition wins. Terms first means allowed once duties are met: anyone outside Sales can read the sales orders after "
   "accepting the terms and getting approval.",
   ["Ontos demo example; verdicts computed by Ontos, not typed by hand", "Draft policies are not evaluated; only active ones count"],
   "Answers are one thing. Delivering them on the platform, and keeping them true, is the next.",
   "Can a steward see why someone was denied? Yes. Each answer lists the policies and reasons that matched."),
 n("Show the path from policy to platform, and the audit loop that keeps it true.",
   "One release, stage by stage. Compile turns the active policies into 23 grants, including the parent access people need, "
   "and holds back what is still waiting on duties. The release is reviewed with separation of duties. Delivery follows what "
   "the platform allows; here an administrator applies and confirms a ready-made change set. Every grant then becomes a ledger "
   "entry with its reason and end date. And on a schedule, reconcile compares the ledger with the live platform. In the demo, "
   "someone removed one grant and added another by hand; reconcile reports both and changes nothing. Administrators decide.",
   ["Ontos demo example: 23 tracked grants; reconcile finds 1 missing and 1 unmanaged", "Releases need a different approver than their author"],
   "Access answers who may use data. The last part answers who may decide. Part four: authority.",
   "Why not revert drift automatically? Some hand-made changes are emergencies; Ontos reports, and the decision stays with people."),
 n("Section break: authority.",
   "Part four is authority: one trusted answer for people, workflows and AI agents, backed by policy and kept current by evidence.",
   ["Authority Resolution: who may decide what, up to which limit, on which business object"],
   "First, the problem.",
   "How is this different from access policies? Access is about using data; authority is about making business decisions, like approving a budget."),
 n("Name the authority gap: policy on paper differs from practice, and AI agents widen it.",
   "Delegations of authority live in policy documents. Clause 4.3 of the trade promotion policy says budgets above 500,000 dollars "
   "need VP sign-off. In practice, the question arrives in a workflow, an email or an AI agent. Agent A says yes, you own the "
   "budget. Agent B says probably. An approver says approved, with no VP sign-off on record. Nobody can show afterwards which "
   "rule decided. As more decisions are automated, the gap multiplies.",
   ["Illustrative scenario based on the trade promotion demo pack"],
   "Ontos closes the gap by putting authority in one service.",
   "Isn't this just a workflow problem? Workflows route; they don't know the rules. Ontos gives every workflow and agent the same rule."),
 n("Show the authority service: one shared, recorded answer.",
   "Approved delegations of authority live in Ontos, linked through the ontology to the business objects they govern: a "
   "promotion, a vendor contract, production access. Every caller, whether an approval workflow, an agent or Genie, asks the "
   "same service and gets one of three answers. Permit. Conditional, with the sign-off that is still needed. Or deny, with "
   "the clause that says so. Each answer is recorded with the policy version that decided it. A 620,000-dollar promotion "
   "comes back conditional: VP sign-off needed above 500,000.",
   ["Example verdict is engine output on the demo pack: budget 620,000 USD, threshold 500,000 USD, no VP sign-off, so conditional",
    "Same request from two different agents returns the same verdict and the same record fingerprint"],
   "What exactly is stored behind that answer? Six parts.",
   "Does this replace our approval workflows? No. Workflows and agents ask for the verdict; people still sign where the policy demands it, and Ontos records that they did."),
 n("Explain the authority relation in plain terms; highlight the measured part.",
   "Each authority relation has six parts. Five are declared from documents and data: the actor, here the Trade Marketing "
   "Director; the action, approve; the object, a trade promotion budget; the context, Germany and modern trade, alone up to "
   "500,000 dollars; and the justification, the policy version and clause it rests on. The sixth is measured: divergence, how far "
   "real practice has drifted from the rule. And because the relation is tied to the concept Trade promotion in the ontology, "
   "any question about that object finds the right authority, with prerequisites such as market compliance checked first.",
   ["Demo example: Trade Promotion Budget Approval; justification cites Trade Promotion Policy v2, clause 4.3",
    "Also in the context: expected margin must stay at or above 15%"],
   "That measured part is what keeps authority honest.",
   "Who writes these relations? Governance drafts them from policy documents; they are reviewed and approved like any other object."),
 n("Show that authority is earned and kept current: one measured coefficient with a direction, gated by a ceiling.",
   "A rule is only as good as its fit with reality. Ontos activates authority only when three things are true: it rests on a "
   "valid policy, its DNA-Coefficient is under the ceiling, and business, technology and governance have each signed off. The "
   "coefficient is one value per relation: zero means documented and lived authority match. Divergence can run in two opposite "
   "directions. Practice can run ahead of the document, when people decide beyond their written authority. Or the document can run "
   "ahead of practice, when written authority is bypassed or escalated. Either direction raises the coefficient; the direction tells "
   "governance which way to fix it. Trade promotion scores 0.15 with practice ahead, production access 0.08 with the document "
   "ahead, and both stay in force under the 0.30 ceiling. Decommissioning scores 0.42, so it goes back to review and agents stop "
   "relying on it. The value is recomputed on a schedule you set, and if a policy is withdrawn, its authority ends at once.",
   ["Per the ARF paper: one normalized composite divergence value (0 = documented and lived authority match) plus a direction flag",
    "The paper proposes combining instruments (decision-log analysis, organisational network analysis, structured elicitation) but leaves the formula open",
    "Demo values: trade promotion 0.15 (actual exceeds documented), production access 0.08 (documented exceeds actual), decommissioning 0.42; ceiling 0.30",
    "Evidence comes from decision and approval records in governed Unity Catalog tables"],
   "That completes the four parts. How do you start?",
   "Is measuring how people decide privacy-sensitive? Decision logs are already governed in Unity Catalog; network analysis and interviews need privacy and works-council review first."),
 n("Section break: getting started.",
   "Part five: how to get started. Start small, start from the questions people actually ask, and let the mesh grow one domain at a time.",
   [], "First, the shape of a pilot.", "Do we need everything in place before we start? No. One domain and a handful of questions is enough."),
 n("Close with a low-risk pilot: one domain, measurable outcome.",
   "Ontos gives each team what it needs: products instead of tables, meaning built in, rules that are enforced and checked, and "
   "all of it on the Databricks platform you already have. The best way to see it is small. Deploy Ontos in one workspace, pick "
   "one domain with its owners and a steward, pick a spike in it, from its top questions to a small ontology to the products that answer them, write "
   "its access policies and one authority relation for a key decision. Then open the marketplace to one consumer team and count "
   "how many requests get answered without a meeting.",
   ["Ontos is open source and deploys as a Databricks App"],
   "How do you pick that spike? Start from the questions.",
   "How long does a pilot take? Typically weeks, not months: one domain, a few products, one consumer team."),
 n("Teach the spike method: questions, then a small ontology, then products.",
   "Inside the domain, don't start from the tables. Start from what people need to know: collect five to ten real questions, such as "
   "which key accounts are at risk of churning, or which promotions paid back last quarter. Then capture only the business concepts "
   "those questions use: customer, key account, churn risk, order, promotion, revenue, region, and how they relate. That is your "
   "first, small ontology, and you can borrow from an industry ontology where one fits. Finally, map the ontology to the data that "
   "answers the questions: two or three products, each with a contract and semantic links. Every product exists because someone "
   "asked a question it answers. The trap to avoid is modelling the whole estate up front.",
   ["Illustrative sales domain", "Concepts and products shown match the knowledge-graph and marketplace examples earlier in the deck"],
   "Which spike should you pick, and how does it grow from there?",
   "Who collects the questions? The domain's data owner and steward, with the business people who ask them; a short workshop is usually enough."),
 n("Give selection criteria for the spike and show the growth path plus upcoming tooling support.",
   "A good spike is wanted: people ask these questions today and the answers take meetings. It is owned: there is a committed data "
   "owner and steward. The data is available, already in Unity Catalog. It is small: five to ten questions, up to twenty concepts, "
   "two or three products. And it is measurable, for example requests answered without a meeting, or time to find data. From the "
   "spike, complete the domain, then move to the next one, which reuses the shared ontology. Planned for around Ontos 1.4, two "
   "capabilities help with these first steps: Estate Import suggests assets, contracts and products from your existing estate, in "
   "phases you review before anything is applied; and Workload Migration assesses legacy workloads and plans their move to "
   "Databricks, with the data product as the unit of migration.",
   ["Estate Import and Workload Migration are planned (around v1.4), not shipping today", "Suggestions are always reviewed before they are applied"],
   "Thank you. Let's pick the domain and its first questions.",
   "Can we start before 1.4? Yes. The spike method works today; Estate Import and Workload Migration speed up the later, larger domains."),
 n("Closing slide.", "Thank you. Questions.", [], "", ""),
]

if __name__ == "__main__":
    ids = g.get_slide_ids(PID)
    assert len(ids) == len(NOTES), (len(ids), len(NOTES))
    for i, (sid, note) in enumerate(zip(ids, NOTES), 1):
        r = g.set_speaker_notes(PID, sid, note)
        print(i, "error" if "error" in r else "ok")
