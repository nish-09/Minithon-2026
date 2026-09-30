"""Seed first-aid protocols (version 1).

IMPORTANT: These are drafted from widely published public first-aid guidance (Red Cross / St John /
NHS-style basics) and are deliberately conservative: they always favour calling emergency services
and never give dosing, medication, or invasive instructions. They MUST be reviewed and approved by
a qualified clinician before any real-world deployment. Admins manage versions via /api/admin/protocols.
The LLM may only *select* one of these and *rephrase* steps; it never authors medical content.
"""

SOURCE = "NEXA seed v1 - general first-aid principles; pending clinical review"

# slug, title, keywords, requires_emergency, steps: (instruction, fallback, is_critical)
PROTOCOLS = [
    (
        "BLEEDING_ASSISTANCE", "Bleeding control",
        ["bleed", "bleeding", "blood", "cut", "wound", "gash", "scrape", "laceration"],
        False,
        [
            ("First, make sure you are away from traffic or other danger. If the bleeding is heavy, spurting, or will not slow down, call your local emergency number now.",
             "If you cannot move, stay where you are and keep the injured area as still as you can.", True),
            ("Press firmly on the wound with a clean cloth, a clean piece of clothing, or your hand if nothing else is available. Keep pressing without lifting to check.",
             "If you can't press with your hand, lean or rest your body weight on the cloth over the wound.", True),
            ("If the cloth soaks through, do not remove it. Put another cloth on top and keep pressing.",
             "Keep pressure on whatever is already in place.", False),
            ("Sit or lie down somewhere safe. If you can, raise the injured arm or leg above the level of your heart, unless you think a bone may be broken.",
             "Stay in the position that hurts least and keep the injury still.", False),
            ("Keep holding pressure. Help is on the way. Tell me if you feel faint, dizzy, cold, or confused, or if the bleeding is getting worse.",
             "Keep pressure on and tell me how you feel.", False),
        ],
    ),
    (
        "DIZZY_FAINTNESS", "Dizziness or feeling faint",
        ["dizzy", "dizziness", "faint", "lightheaded", "light-headed", "woozy", "black out", "blacking out"],
        False,
        [
            ("Stop what you are doing and sit or lie down right away so you do not fall. Move away from stairs, traffic, or anything hard.",
             "If you cannot lie down, crouch low or lean against a wall to lower your head.", True),
            ("If you can, lie flat and raise your legs a little. If you are sitting, lean forward and put your head toward your knees.",
             "Stay in the position that feels safest.", False),
            ("Breathe slowly and steadily. Do not stand up quickly. If you can, loosen any tight clothing around your neck.",
             "Just keep breathing slowly and stay put.", False),
            ("If you pass out, have trouble speaking, have chest pain, or feel worse, call your local emergency number. Tell me how you feel now.",
             "Tell me how you feel now.", True),
        ],
    ),
    (
        "BURN_CARE", "Minor burns and scalds",
        ["burn", "burned", "burnt", "scald", "scalded", "hot oil", "boiling"],
        False,
        [
            ("Move away from the heat source. If clothing is on fire, stop, drop, and roll. Do not pull off clothes stuck to the skin.",
             "Get away from the heat in whatever way you can.", True),
            ("Hold the burn under cool (not ice-cold) running water for at least 20 minutes.",
             "If there is no running water, use a cool, clean, wet cloth and keep it cool.", True),
            ("Take off rings, watches, or tight items near the burn before it swells, unless they are stuck to the skin.",
             "Leave anything that is stuck in place.", False),
            ("Do not put ice, butter, creams, or toothpaste on it. Cover loosely with a clean non-fluffy cover like cling film or a clean cloth.",
             "Keep the burn clean and uncovered if you have nothing suitable.", False),
            ("If the burn is larger than your hand, on your face, hands, feet, or genitals, deep, white or charred, or caused by chemicals or electricity, call your local emergency number now.",
             "Tell me where the burn is and how big it is.", True),
        ],
    ),
    (
        "SUSPECTED_FRACTURE", "Suspected broken bone or sprain",
        ["broke", "broken", "fracture", "fractured", "sprain", "sprained", "twisted", "can't move my", "cannot move my", "dislocated"],
        False,
        [
            ("Stay still and do not try to move or straighten the injured area. Do not try to put a bone back in place.",
             "Move as little as possible.", True),
            ("Support the injured part in the position you found it, using cushions, folded clothing, or your other hand.",
             "Just keep it as still as you can.", False),
            ("If there is bleeding, press gently around the wound with a clean cloth without pushing on any exposed bone.",
             "Skip this step if there is no bleeding.", False),
            ("If you have a cold pack or a cloth-wrapped bag of ice, hold it near the injury for short periods. Do not put ice directly on skin.",
             "Skip this if you don't have anything cold nearby.", False),
            ("If the limb looks bent the wrong way, is numb, pale, or very swollen, or you cannot bear weight, call your local emergency number.",
             "Tell me what you can see and feel.", True),
        ],
    ),
    (
        "CHEST_PAIN_ALERT", "Chest pain or pressure",
        ["chest pain", "chest pressure", "heart attack", "tight chest", "chest tightness"],
        True,
        [
            ("Call your local emergency number now. Chest pain can be serious and needs professional help immediately.",
             "If you can't dial, ask anyone near you to call, or use voice dialing on your phone.", True),
            ("Stop everything. Sit down in a comfortable position, such as leaning back against a wall, and stay calm.",
             "Stay where you are and keep still.", True),
            ("Unlock your front door if it is safe to do so, so that help can reach you.",
             "Skip this if you can't get up safely.", False),
            ("Do not take any medicine unless the emergency operator tells you to. I'll stay with you. Tell me if you feel worse.",
             "Keep still and tell me how you feel.", False),
        ],
    ),
    (
        "SEVERE_ALLERGIC_REACTION", "Severe allergic reaction",
        ["allergic", "allergy", "anaphyl", "swelling throat", "throat closing", "hives", "bee sting", "can't breathe after"],
        True,
        [
            ("Call your local emergency number now. A severe allergic reaction is an emergency.",
             "If you can't dial, ask someone nearby to call.", True),
            ("If you have been prescribed an adrenaline or epinephrine auto-injector, use it as your prescriber taught you.",
             "If you do not have one, skip this step.", True),
            ("Sit up if breathing is hard, or lie down with your legs raised if you feel faint. Do not stand or walk around.",
             "Stay in the position that makes breathing easiest.", False),
            ("Stay with someone if you can. Tell me if breathing or your swelling gets worse.",
             "Tell me how you are breathing right now.", False),
        ],
    ),
    (
        "GENERAL_DISTRESS", "General safety check",
        [],
        False,
        [
            ("Let's make sure you are safe. Move away from any danger like traffic or fire if you can, and stay as still as possible if you are hurt.",
             "Stay where you are and tell me what is happening.", True),
            ("Tell me what happened and what hurts, in your own words. I will match it to approved guidance.",
             "Tell me the main thing that is wrong right now.", False),
            ("If you feel seriously unwell, cannot breathe properly, or cannot stay conscious, call your local emergency number now.",
             "Tell me if you need me to advise emergency services.", True),
        ],
    ),
]

# Keyword triggers that mean "advise emergency services immediately" regardless of protocol.
RED_FLAG_PHRASES = [
    "not breathing", "can't breathe", "cannot breathe", "trouble breathing", "unconscious", "unresponsive",
    "passed out", "seizure", "choking", "chest pain", "heart attack", "stroke", "spurting", "won't stop bleeding",
    "wont stop bleeding", "severe bleeding", "heavy bleeding", "bleeding a lot", "lot of blood", "head injury",
    "bone sticking", "suicid", "overdose", "poison",
]
