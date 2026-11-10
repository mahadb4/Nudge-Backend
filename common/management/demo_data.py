"""The made-up workspace seed_demo builds. Fictional people and companies; no real data and no
credentials (the Owner's email and password are generated at run time)."""

DEMO_ORGANIZATION = "Nudge Demo Workspace"
DEMO_OWNER_NAME = "Demo Owner"
DEMO_TIMEZONE = "Asia/Karachi"
DEMO_EMAIL_DOMAIN = "example.com"

# name, domain, industry, size_range
DEMO_COMPANIES: tuple[tuple[str, str, str, str], ...] = (
    ("Indus Software House", "indus-software.example.com", "Software", "51-200"),
    ("Lahore Logistics", "lahore-logistics.example.com", "Transport", "201-500"),
    ("Bluewave Marketing", "bluewave.example.com", "Marketing", "11-50"),
    ("Orbit Fintech", "orbitfintech.example.com", "Financial services", "51-200"),
    ("Karakoram Agro Traders", "karakoram-agro.example.com", "Agriculture", "11-50"),
    ("Sapphire Health Clinics", "sapphire-health.example.com", "Healthcare", "201-500"),
    ("Metro Retail Group", "metroretail.example.com", "Retail", "500+"),
    ("Zenith Solar", "zenith-solar.example.com", "Energy", "1-10"),
)

# first name, last name, job title, phone (or None), index of the company (or None)
DEMO_CONTACTS: tuple[tuple[str, str, str, str | None, int | None], ...] = (
    ("Ayesha", "Khan", "Head of Engineering", "+923001234567", 0),
    ("Bilal", "Ahmed", "Product Manager", "+923211234567", 0),
    ("Sana", "Malik", "Finance Director", None, 0),
    ("Usman", "Tariq", "Operations Manager", "+923331234567", 1),
    ("Hira", "Siddiqui", "Procurement Lead", "+923451234567", 1),
    ("Omar", "Farooq", "Fleet Coordinator", None, 1),
    ("Zainab", "Raza", "Marketing Director", "+923021234567", 2),
    ("Hamza", "Qureshi", "Account Executive", None, 2),
    ("Mariam", "Javed", "Brand Strategist", "+923101234567", 2),
    ("Fahad", "Mirza", "Chief Financial Officer", "+923111234567", 3),
    ("Noor", "Hussain", "Risk Analyst", None, 3),
    ("Danish", "Iqbal", "Head of Partnerships", "+923121234567", 3),
    ("Rabia", "Anwar", "Purchasing Manager", "+923131234567", 4),
    ("Salman", "Butt", "Founder", "+923141234567", 4),
    ("Iman", "Zafar", "Medical Director", None, 5),
    ("Kamran", "Yousaf", "Facilities Manager", "+923151234567", 5),
    ("Layla", "Chaudhry", "Administrator", "+923161234567", 5),
    ("Talha", "Saeed", "Regional Manager", "+923171234567", 6),
    ("Areeba", "Nadeem", "Category Buyer", None, 6),
    ("Waqar", "Hashmi", "IT Manager", "+923181234567", 6),
    ("Sidra", "Aslam", "Co-founder", "+923191234567", 7),
    ("Junaid", "Abbasi", "Sales Lead", None, 7),
    ("Eman", "Rehman", "Freelance Consultant", "+923201234567", None),
    ("Rafay", "Lodhi", "Startup Advisor", None, None),
    ("Hania", "Gill", "Event Organiser", "+923221234567", None),
)
