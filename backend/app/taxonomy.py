"""Reference data: categories, skills, certifications, relationship types. Seeded idempotently at startup."""

# slug, label, default skills, icon
CATEGORIES = [
    ("medical_assistance", "Medical / First Aid", ["first_aid"], "🩹"),
    ("household_assistance", "Household Assistance", ["physical_assistance"], "🏠"),
    ("repair", "Repairs & Maintenance", ["plumbing", "electrical", "carpentry"], "🔧"),
    ("tutoring", "Tutoring & Teaching", ["teaching"], "📚"),
    ("pet_care", "Pet Care", ["pet_care"], "🐾"),
    ("errands", "Errands & Delivery", ["errands"], "🛍️"),
    ("transport", "Rides & Transport", ["driving"], "🚗"),
    ("tech_help", "Tech Help", ["tech_support"], "💻"),
    ("elder_care", "Elder Care & Companionship", ["elder_care"], "🧓"),
    ("other", "Other", [], "🤝"),
]

# slug, label, trust_category
SKILLS = [
    ("first_aid", "First Aid", "medical_assistance"),
    ("cpr", "CPR", "medical_assistance"),
    ("physical_assistance", "Physical Assistance / Lifting", "household_assistance"),
    ("plumbing", "Plumbing", "repair"),
    ("electrical", "Electrical", "repair"),
    ("carpentry", "Carpentry", "repair"),
    ("teaching", "Teaching", "tutoring"),
    ("pet_care", "Pet Care", "pet_care"),
    ("errands", "Errands", "errands"),
    ("driving", "Driving", "transport"),
    ("tech_support", "Tech Support", "tech_help"),
    ("elder_care", "Elder Care", "elder_care"),
]

# slug, label, grants_skill
CERTIFICATIONS = [
    ("first_aid_cert", "First Aid Certificate", "first_aid"),
    ("cpr_cert", "CPR / BLS Certificate", "cpr"),
    ("electrician_license", "Licensed Electrician", "electrical"),
    ("plumber_license", "Licensed Plumber", "plumbing"),
    ("teaching_cert", "Teaching Qualification", "teaching"),
    ("vet_assistant_cert", "Veterinary Assistant", "pet_care"),
]

# slug, label, group, inverse
RELATIONSHIP_TYPES = [
    ("mother", "Mother", "family", "child"),
    ("father", "Father", "family", "child"),
    ("parent", "Parent", "family", "child"),
    ("child", "Child", "family", "parent"),
    ("brother", "Brother", "family", "sibling"),
    ("sister", "Sister", "family", "sibling"),
    ("sibling", "Sibling", "family", "sibling"),
    ("cousin", "Cousin", "family", "cousin"),
    ("uncle", "Uncle", "family", "nephew_niece"),
    ("aunt", "Aunt", "family", "nephew_niece"),
    ("nephew_niece", "Nephew / Niece", "family", "uncle"),
    ("grandparent", "Grandparent", "family", "grandchild"),
    ("grandchild", "Grandchild", "family", "grandparent"),
    ("spouse", "Spouse / Partner", "family", "spouse"),
    ("friend", "Friend", "friends", "friend"),
    ("neighbor", "Neighbor", "other", "neighbor"),
    ("other", "Other trusted person", "other", "other"),
]

URGENCIES = ("normal", "urgent", "critical")
