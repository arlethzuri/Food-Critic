"""The 25 comparison questions from app/tentative_questions.md, as data —
kept separate from that file (which is the human-readable rationale doc)
so run_comparison.py has a stable, parseable source instead of scraping
markdown. Keep the two in sync if a question's wording changes.
"""

QUESTIONS = [
    # --- A: V1 predicted to win — pure lookups, RAG/ontology add nothing ---
    {"id": "A1", "category": "A", "predicted_winner": "v1",
     "question": "How many total establishments are in the database, and how many have a Salt Lake County health inspection on record?"},
    {"id": "A2", "category": "A", "predicted_winner": "v1",
     "question": "What's Wingstop's price range and street address?"},
    {"id": "A3", "category": "A", "predicted_winner": "v1",
     "question": "Just give me the name of the single restaurant with the most reviews in the database — one line, no explanation."},
    {"id": "A4", "category": "A", "predicted_winner": "v1",
     "question": "List 5 pizza places in Salt Lake County. I just want names and addresses, nothing else."},
    {"id": "A5", "category": "A", "predicted_winner": "v1",
     "question": "What cuisine categories does Cafe Zupas fall under?"},
    {"id": "A6", "category": "A", "predicted_winner": "v1",
     "question": "What are In-N-Out Burger's hours on Sunday?"},

    # --- B: V2 predicted to win — regulatory content V1 can't reach, no establishment named ---
    {"id": "B1", "category": "B", "predicted_winner": "v2",
     "question": "A restaurant got cited for Cold Holding. Why does that matter, and what does the food safety rule require?"},
    {"id": "B2", "category": "B", "predicted_winner": "v2",
     "question": "What's the difference between a critical and a non-critical violation, and how does each affect an inspection score?"},
    {"id": "B3", "category": "B", "predicted_winner": "v2",
     "question": "How often does a restaurant get reinspected after a critical violation, according to the county's own stated policy?"},
    {"id": "B4", "category": "B", "predicted_winner": "v2",
     "question": "If a violation is corrected on-site, does it still count against the inspection score?"},
    {"id": "B5", "category": "B", "predicted_winner": "v2",
     "question": "What food safety training or certification requirements exist for food handlers in Salt Lake County?"},
    {"id": "B6", "category": "B", "predicted_winner": "v2",
     "question": "Does Utah's food code treat cross-contamination and temperature-control violations differently in terms of severity?"},

    # --- C: V3 predicted to win — judgment calls the ontology's hypothesis/evidence pipeline targets ---
    {"id": "C1", "category": "C", "predicted_winner": "v3",
     "question": "Is the In-N-Out Burger at 7206 Union Park Ave, Midvale a safe bet to eat at right now?"},
    {"id": "C2", "category": "C", "predicted_winner": "v3",
     "question": "STELLA GRILL's inspection scores have swung a lot over time (10 to 185) — should I be concerned, and would you warn someone away from it?"},
    {"id": "C3", "category": "C", "predicted_winner": "v3",
     "question": "Compare Sagato Bakery & Cafe and Texas Roadhouse — which has the worse track record, and why?"},
    {"id": "C4", "category": "C", "predicted_winner": "v3",
     "question": "I only care about restaurants with zero critical violations on their most recent inspection. Give me your top pick near downtown Salt Lake City and explain why you trust it."},
    {"id": "C5", "category": "C", "predicted_winner": "v3",
     "question": "Maddox Ranch House has a 4.7 rating with almost 6,000 reviews but I can't find any health inspection for it — should that worry me?"},
    {"id": "C6", "category": "C", "predicted_winner": "v3",
     "question": "Has Stella Grill's compliance been getting better or worse over its inspection history, and how confident are you?"},
    {"id": "C7", "category": "C", "predicted_winner": "v3",
     "question": "I'm looking at opening a restaurant near Sagato Bakery & Cafe — does that area have a lot of repeat health-code offenders nearby?"},
    {"id": "C8", "category": "C", "predicted_winner": "v3",
     "question": "Which is riskier to eat at: a restaurant with a high rating but a recent critical violation, or one with no reviews but a clean inspection history?"},

    # --- D: control — all three should land close to equal ---
    {"id": "D1", "category": "D", "predicted_winner": "control",
     "question": "Which 10 restaurants have the most critical violations? Show me a chart."},
    {"id": "D2", "category": "D", "predicted_winner": "control",
     "question": "Has the number of critical violations in Salt Lake County restaurants gone up or down over the last 5 years? Show me a chart."},
    {"id": "D3", "category": "D", "predicted_winner": "control",
     "question": "How many establishments in the database have never had a Salt Lake County health inspection, and what fraction is that?"},
    {"id": "D4", "category": "D", "predicted_winner": "control",
     "question": "Show me the geographic spread of restaurants with at least one critical violation, on a map."},
    {"id": "D5", "category": "D", "predicted_winner": "control",
     "question": "What's the average inspection score across all restaurants with SLCHD records, and how does that compare to the median?"},
]

assert len(QUESTIONS) == 25
assert len({q["id"] for q in QUESTIONS}) == 25  # no duplicate ids
