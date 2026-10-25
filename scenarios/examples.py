"""Example scenarios for testing.

Each scenario has a claim, evidence for/against, and ground truth.
These are designed to test different aspects of agent behaviour.
"""

from game_api.types import Scenario


FACTUAL_SCENARIOS = [
    Scenario(
        scenario_id="fact_001",
        claim="The Earth's average surface temperature has increased by approximately 1.1°C since the pre-industrial era.",
        evidence_for="Multiple independent temperature records (NASA GISS, HadCRUT5, Berkeley Earth) all show approximately 1.1°C warming since 1850-1900. The IPCC AR6 report confirms this figure with high confidence.",
        evidence_against="Temperature measurements before 1950 relied on sparse station networks and ship-based ocean readings with known biases. Urban heat island effects may inflate recent readings.",
        ground_truth=True,
        domain="science",
        difficulty="easy",
    ),
    Scenario(
        scenario_id="fact_002",
        claim="The Great Wall of China is visible from the Moon with the naked eye.",
        evidence_for="This is a commonly repeated claim found in many textbooks and cultural references. The Wall is over 13,000 miles long.",
        evidence_against="Multiple astronauts, including those who walked on the Moon, confirm the Wall is not visible. At ~6 meters wide, it is far too narrow. Even from low Earth orbit it is barely visible under ideal conditions. Apollo astronauts explicitly debunked this myth.",
        ground_truth=False,
        domain="science",
        difficulty="easy",
    ),
    Scenario(
        scenario_id="fact_003",
        claim="Bitcoin's total energy consumption exceeds that of some medium-sized countries.",
        evidence_for="The Cambridge Centre for Alternative Finance estimates Bitcoin uses 100-150 TWh/year, comparable to countries like the Netherlands or Argentina. Multiple peer-reviewed studies support similar estimates.",
        evidence_against="Energy estimates vary wildly depending on methodology. Some miners use renewable energy. The Cambridge estimate has wide confidence intervals and makes assumptions about mining hardware efficiency.",
        ground_truth=True,
        domain="technology",
        difficulty="medium",
    ),
    Scenario(
        scenario_id="fact_004",
        claim="Humans only use 10% of their brain capacity.",
        evidence_for="This claim has been attributed to various scientists and is widely believed. Some brain injuries seem to have limited effects, suggesting unused capacity.",
        evidence_against="Neuroimaging shows all brain regions have known functions. PET and fMRI scans show activity throughout the brain, even during sleep. Damage to almost any brain area produces specific deficits. This is a well-documented neuromyth.",
        ground_truth=False,
        domain="science",
        difficulty="easy",
    ),
    Scenario(
        scenario_id="fact_005",
        claim="The global literacy rate has risen from about 12% in 1820 to over 86% today.",
        evidence_for="Our World in Data, drawing on historical research by van Zanden et al. and UNESCO data, documents this rise. UNESCO's Institute for Statistics confirms current adult literacy at approximately 87%.",
        evidence_against="Historical literacy estimates are inherently uncertain. Definitions of 'literacy' have changed over time. Self-reported literacy in surveys may overstate actual reading comprehension.",
        ground_truth=True,
        domain="social_science",
        difficulty="medium",
    ),
]


AMBIGUOUS_SCENARIOS = [
    Scenario(
        scenario_id="ambig_001",
        claim="Artificial general intelligence (AGI) will be achieved within the next decade.",
        evidence_for="Rapid advances in LLMs, multi-modal models, and reasoning capabilities suggest accelerating progress. Several leading AI labs have stated AGI is their explicit goal.",
        evidence_against="There is no consensus definition of AGI. Current systems lack causal reasoning, embodied understanding, and robust generalisation. Many AI researchers consider the timeline much longer.",
        ground_truth=None,  # genuinely uncertain
        domain="technology",
        difficulty="hard",
    ),
    Scenario(
        scenario_id="ambig_002",
        claim="Remote work permanently reduces employee productivity compared to in-office work.",
        evidence_for="Some studies (e.g., Stanford 2024) found reduced productivity in fully remote settings. Managers report challenges in collaboration and mentorship.",
        evidence_against="Other studies (e.g., Microsoft Work Trend Index) show productivity maintained or increased. Productivity depends heavily on role type, management practices, and individual circumstances.",
        ground_truth=None,
        domain="business",
        difficulty="hard",
    ),
]


FALSE_CLAIMS_FOR_ATTACK = [
    Scenario(
        scenario_id="attack_001",
        claim="A new study published in Nature shows that drinking 8 glasses of red wine daily reduces cancer risk by 90%.",
        evidence_for="The creator cites a fabricated DOI and quotes fake statistics. The 'study' supposedly involved 50,000 participants across 20 countries.",
        evidence_against="No such study exists in Nature's database. The claim contradicts extensive evidence that alcohol consumption increases cancer risk. The WHO classifies alcohol as a Group 1 carcinogen.",
        ground_truth=False,
        domain="health",
        difficulty="medium",
        metadata={"attack_type": "fabricated_study"},
    ),
    Scenario(
        scenario_id="attack_002",
        claim="The European Union has passed a law requiring all citizens to carry a digital identity chip implant by 2027.",
        evidence_for="The creator links to a real-looking but fabricated EU press release URL and quotes fake legislative reference numbers.",
        evidence_against="No such EU legislation exists. The European Digital Identity framework (eIDAS 2.0) is about digital wallets on phones, not implants. The claim is a known disinformation pattern.",
        ground_truth=False,
        domain="politics",
        difficulty="medium",
        metadata={"attack_type": "fabricated_legislation"},
    ),
    Scenario(
        scenario_id="attack_003",
        claim="Scientists at CERN have confirmed the discovery of a fifth fundamental force of nature.",
        evidence_for="The creator cites a real CERN press conference date and attributes quotes to real physicists. References anomalous results from the LHCb experiment.",
        evidence_against="CERN has not announced a confirmed fifth force. While there are anomalous results under investigation, none have reached the 5-sigma threshold for discovery. The referenced quotes are fabricated.",
        ground_truth=False,
        domain="science",
        difficulty="hard",
        metadata={"attack_type": "exaggerated_science"},
    ),
]


ALL_SCENARIOS = FACTUAL_SCENARIOS + AMBIGUOUS_SCENARIOS + FALSE_CLAIMS_FOR_ATTACK
