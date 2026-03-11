"""Sector definitions, synonyms, company/ETF mapping, and resolution logic."""

from __future__ import annotations

from dataclasses import dataclass

from app.models import EventType


@dataclass(frozen=True)
class SectorDefinition:
    key: str
    display_name: str
    category: str
    seed_keywords: list[str]
    representative_symbols: list[str]


def _sector(
    key: str,
    display_name: str,
    category: str,
    seed_keywords: list[str],
    representative_symbols: list[str],
) -> tuple[str, SectorDefinition]:
    return (key, SectorDefinition(key=key, display_name=display_name, category=category, seed_keywords=seed_keywords, representative_symbols=representative_symbols))


# ─── 200 Sectors ───────────────────────────────────────────────────────────────

SECTOR_ENTRIES: list[tuple[str, SectorDefinition]] = [
    # Tech
    _sector("technology", "Technology", "major", ["technology", "tech", "software", "hardware", "Apple", "Microsoft"], ["AAPL", "MSFT", "GOOGL"]),
    _sector("ai", "AI", "major", ["AI", "artificial intelligence", "machine learning", "generative AI", "large language model", "LLM"], ["NVDA", "MSFT", "GOOGL"]),
    _sector("cybersecurity", "Cybersecurity", "major", ["cyber attack", "cybersecurity", "data breach", "ransomware", "zero day", "cyber defense"], ["CRWD", "PANW", "ZS"]),
    _sector("robotics", "Robotics", "niche", ["robotics", "industrial robot", "automation", "cobots", "robot arm"], ["IR", "TER", "ROK"]),
    _sector("quantum_computing", "Quantum Computing", "niche", ["quantum computing", "quantum computer", "qubit", "quantum advantage"], ["IONQ", "RGTI", "IBM"]),
    _sector("cloud_computing", "Cloud Computing", "major", ["cloud computing", "cloud infrastructure", "AWS", "Azure", "GCP", "cloud migration"], ["AMZN", "MSFT", "GOOGL"]),
    _sector("saas", "SaaS", "niche", ["SaaS", "software as a service", "subscription software", "ARR", "cloud software"], ["CRM", "SNOW", "NOW"]),
    _sector("big_data", "Big Data", "niche", ["big data", "data analytics", "data warehouse", "ETL", "data platform"], ["SNOW", "MDB", "DDOG"]),
    _sector("internet_infrastructure", "Internet Infrastructure", "niche", ["CDN", "edge computing", "internet backbone", "fiber", "network infrastructure"], ["AKAM", "EQIX", "NET"]),
    _sector("semiconductors", "Semiconductors", "major", ["semiconductor", "chip", "foundry", "TSMC", "AI chip", "chip export"], ["NVDA", "AMD", "TSM"]),
    _sector("semiconductor_equipment", "Semiconductor Equipment", "niche", ["semiconductor equipment", "lithography", "ASML", "wafer", "chip fab"], ["ASML", "LRCX", "AMAT"]),
    _sector("data_centers", "Data Centers", "major", ["data center", "cloud capacity", "AI infrastructure", "server demand", "hyperscaler"], ["EQIX", "DLR", "VRT"]),
    # Consumer
    _sector("ecommerce", "E-commerce", "major", ["e-commerce", "online retail", "Amazon", "ecommerce", "digital commerce"], ["AMZN", "SHOP", "ETSY"]),
    _sector("streaming", "Streaming", "niche", ["streaming", "Netflix", "Disney+", "subscription video", "OTT"], ["NFLX", "DIS", "WBD"]),
    _sector("social_media", "Social Media", "niche", ["social media", "Meta", "TikTok", "Instagram", "social network"], ["META", "SNAP", "PINS"]),
    _sector("advertising", "Advertising", "niche", ["digital advertising", "ad spend", "programmatic", "ad tech"], ["GOOGL", "META", "TTD"]),
    _sector("luxury_goods", "Luxury Goods", "niche", ["luxury", "LVMH", "Hermès", "luxury brand", "high-end retail"], ["LVMUY", "KERING", "TIF"]),
    _sector("travel", "Travel", "niche", ["travel", "tourism", "hotel", "booking", "vacation"], ["BKNG", "ABNB", "MAR"]),
    _sector("restaurants", "Restaurants", "niche", ["restaurant", "fast food", "QSR", "dining", "food service"], ["MCD", "CMG", "DPZ"]),
    _sector("apparel", "Apparel", "niche", ["apparel", "clothing", "retail fashion", "Nike", "athleisure"], ["NKE", "LULU", "VFC"]),
    _sector("gaming", "Gaming", "niche", ["video game", "gaming", "esports", "console", "Nintendo", "PlayStation", "Xbox"], ["EA", "TTWO", "RBLX"]),
    # Industrial
    _sector("construction", "Construction", "niche", ["construction", "building", "infrastructure", "construction materials"], ["CAT", "DE", "VMC"]),
    _sector("mining", "Mining", "major", ["mining", "minerals", "commodity mining", "ore", "extraction"], ["FCX", "BHP", "RIO"]),
    _sector("steel", "Steel", "niche", ["steel", "steel production", "iron ore", "blast furnace"], ["NUE", "STLD", "X"]),
    _sector("copper", "Copper", "niche", ["copper", "copper mining", "red metal", "copper demand"], ["FCX", "SCCO", "TECK"]),
    _sector("cement", "Cement", "niche", ["cement", "concrete", "construction materials"], ["VMC", "MLM", "EXP"]),
    _sector("machinery", "Machinery", "niche", ["industrial machinery", "heavy equipment", "manufacturing equipment"], ["CAT", "DE", "CMI"]),
    _sector("rail", "Rail", "niche", ["railroad", "rail", "freight rail", "Class I railroad"], ["UNP", "CSX", "NSC"]),
    # Energy
    _sector("energy", "Energy", "major", ["oil", "OPEC", "natural gas", "refinery", "LNG", "pipeline"], ["XOM", "CVX", "SHEL"]),
    _sector("hydrogen", "Hydrogen", "niche", ["hydrogen", "green hydrogen", "hydrogen fuel", "electrolyzer"], ["PLUG", "BE", "BLDP"]),
    _sector("solar", "Solar", "niche", ["solar", "solar panel", "photovoltaic", "solar energy"], ["ENPH", "SOL", "FSLR"]),
    _sector("wind", "Wind", "niche", ["wind power", "wind turbine", "offshore wind", "renewable energy"], ["NEE", "VWDRY", "ORSTED"]),
    _sector("grid_storage", "Grid Storage", "niche", ["grid storage", "battery storage", "BESS", "energy storage"], ["NEE", "AES", "FLNC"]),
    _sector("smr_nuclear", "SMR Nuclear", "niche", ["small modular reactor", "SMR", "nuclear reactor", "nuclear power"], ["Nuscale", "SMR", "VST"]),
    _sector("carbon_capture", "Carbon Capture", "niche", ["carbon capture", "CCUS", "direct air capture", "carbon removal"], ["CLNE", "OXY", "CC"]),
    _sector("uranium", "Uranium", "niche", ["uranium", "nuclear fuel", "small modular reactor", "yellowcake", "Kazatomprom"], ["CCJ", "URA", "UUUU"]),
    _sector("carbon_markets", "Carbon Markets", "niche", ["carbon credits", "emissions trading", "cap and trade", "carbon market"], ["KRBN", "XOM", "NEE"]),
    # Transportation
    _sector("shipping", "Shipping", "major", ["shipping", "freight", "container", "maritime", "Red Sea", "port congestion"], ["ZIM", "MATX", "SBLK"]),
    _sector("airlines", "Airlines", "niche", ["airline", "aviation", "air travel", "jet fuel", "passenger demand"], ["DAL", "UAL", "LUV"]),
    _sector("trucking", "Trucking", "niche", ["trucking", "freight", "logistics", "LTL", "trucking rates"], ["JBHT", "XPO", "SAIA"]),
    _sector("autonomous_vehicles", "Autonomous Vehicles", "niche", ["autonomous vehicle", "self-driving", "autopilot", "AV", "robotaxi"], ["TSLA", "GOOGL", "GM"]),
    _sector("ride_sharing", "Ride Sharing", "niche", ["ride sharing", "Uber", "Lyft", "rideshare"], ["UBER", "LYFT"]),
    _sector("logistics", "Logistics", "niche", ["logistics", "supply chain", "warehouse", "last mile", "fulfillment"], ["UPS", "FDX", "CHRW"]),
    _sector("aerospace", "Aerospace", "niche", ["aerospace", "Boeing", "aviation", "commercial aircraft", "jet", "aircraft order"], ["BA", "LMT", "RTX", "GE"]),
    _sector("space", "Space", "niche", ["satellite", "SpaceX", "NASA", "orbital", "spacecraft", "Starlink", "launch"], ["RKLB", "IRDM", "ASTS"]),
    # Agriculture
    _sector("agriculture", "Agriculture", "niche", ["agriculture", "farming", "crop", "agribusiness"], ["DE", "ADM", "BG"]),
    _sector("agriculture_equipment", "Agriculture Equipment", "niche", ["farm equipment", "tractor", "combine", "John Deere"], ["DE", "AGCO", "CNHI"]),
    _sector("grain", "Grain", "niche", ["grain", "wheat", "corn", "soybean", "commodity grain"], ["ADM", "BG", "WEAT"]),
    _sector("livestock", "Livestock", "niche", ["livestock", "cattle", "beef", "pork", "animal protein"], ["TSN", "HRL", "PIC"]),
    _sector("precision_agriculture", "Precision Agriculture", "niche", ["precision agriculture", "ag tech", "farm tech", "crop monitoring"], ["DE", "CNHI", "AGCO"]),
    _sector("food_processing", "Food Processing", "niche", ["food processing", "packaged food", "food manufacturing"], ["GIS", "K", "CPB"]),
    _sector("fertilizers", "Fertilizers", "niche", ["fertilizer", "potash", "nitrogen", "ammonia", "crop nutrients"], ["MOS", "NTR", "CF"]),
    # Geopolitics
    _sector("china_tech", "China Tech", "niche", ["China tech", "Chinese semiconductor", "chip export China", "Huawei", "SMIC"], ["BABA", "PDD", "TCEHY"]),
    _sector("sanctions", "Sanctions", "niche", ["sanctions", "export controls", "embargo", "Russia sanctions"], ["XOM", "CVX", "BP"]),
    _sector("trade_war", "Trade War", "niche", ["trade war", "tariffs", "US China trade", "trade dispute"], ["BABA", "AAPL", "NVDA"]),
    _sector("supply_chain", "Supply Chain", "niche", ["supply chain", "reshoring", "nearshoring", "supply disruption"], ["AAPL", "NVDA", "TSM"]),
    _sector("defense", "Defense", "major", ["defense", "military", "missile", "drone", "Pentagon", "arms deal"], ["LMT", "NOC", "RTX"]),
    _sector("drones", "Drones", "niche", ["drone", "UAV", "counter-drone", "loitering munition"], ["AVAV", "KTOS", "RTX"]),
    # Finance
    _sector("financials", "Financials", "major", ["Federal Reserve", "banks", "interest rates", "credit", "yield curve"], ["JPM", "BAC", "GS"]),
    _sector("private_equity", "Private Equity", "niche", ["private equity", "PE", "LBO", "buyout", "alternative assets"], ["BX", "KKR", "APO"]),
    _sector("fintech", "Fintech", "niche", ["fintech", "digital payments", "financial technology", "neobank"], ["PYPL", "SQ", "COIN"]),
    _sector("payments", "Payments", "niche", ["payments", "payment processing", "Visa", "Mastercard", "card network"], ["V", "MA", "PYPL"]),
    _sector("mortgage_reits", "Mortgage REITs", "niche", ["mortgage REIT", "mREIT", "agency MBS", "residential mortgage"], ["AGNC", "NLY", "RITM"]),
    _sector("commercial_real_estate", "Commercial Real Estate", "niche", ["commercial real estate", "CRE", "office", "retail property", "CRE lending"], ["SPG", "SLG", "BXP"]),
    _sector("reinsurance", "Reinsurance", "niche", ["reinsurance", "cat losses", "property catastrophe", "renewal pricing"], ["RNR", "EG", "AIG"]),
    _sector("insurance", "Insurance", "niche", ["insurance", "P&C", "life insurance", "underwriting"], ["PGR", "TRV", "ALL"]),
    # Healthcare
    _sector("healthcare", "Healthcare", "major", ["healthcare", "pharma", "drug approval", "FDA", "hospital", "vaccine"], ["LLY", "JNJ", "UNH"]),
    _sector("biotech", "Biotech", "niche", ["biotech", "biotechnology", "clinical trial", "drug development"], ["MRNA", "BIIB", "REGN"]),
    _sector("pharma", "Pharma", "niche", ["pharma", "pharmaceutical", "drug approval", "FDA", "patent"], ["LLY", "JNJ", "PFE"]),
    _sector("medical_devices", "Medical Devices", "niche", ["medical device", "FDA device", "surgical", "implants"], ["ABT", "MDT", "BSX"]),
    _sector("diagnostics", "Diagnostics", "niche", ["diagnostics", "lab testing", "diagnostic", "pathology"], ["DHR", "TMO", "LAB"]),
    _sector("managed_care", "Managed Care", "niche", ["managed care", "health insurer", "Medicare", "Medicaid"], ["UNH", "ELV", "HUM"]),
    # Utilities & Infrastructure
    _sector("utilities", "Utilities", "major", ["utilities", "power grid", "electricity", "power demand", "load growth"], ["NEE", "DUK", "SO"]),
    _sector("water", "Water", "niche", ["water utility", "water scarcity", "desalination", "water infrastructure"], ["AWK", "WTRG", "XYL"]),
    # Materials
    _sector("rare_earths", "Rare Earths", "niche", ["rare earth", "critical minerals", "neodymium", "magnet materials"], ["MP", "LYC", "TECK"]),
    _sector("battery_materials", "Battery Materials", "niche", ["lithium", "nickel", "cathode", "battery materials", "EV battery"], ["ALB", "SQM", "LAC"]),
    _sector("lithium", "Lithium", "niche", ["lithium", "lithium mining", "EV battery", "lithium carbonate"], ["ALB", "SQM", "LAC"]),
    _sector("nickel", "Nickel", "niche", ["nickel", "nickel mining", "battery nickel", "stainless steel"], ["VALE", "NICK", "TECK"]),
    # Other
    _sector("crypto", "Crypto", "niche", ["bitcoin", "crypto", "cryptocurrency", "ethereum", "blockchain", "BTC", "ETH", "spot ETF"], ["COIN", "MSTR", "IBIT"]),
    _sector("ev", "Electric Vehicles", "major", ["electric vehicle", "EV", "Tesla", "electric car", "EV charging"], ["TSLA", "RIVN", "LCID"]),
    _sector("broadcasting", "Broadcasting", "niche", ["broadcasting", "TV", "cable", "media"], ["DIS", "CMCSA", "FOXA"]),
    _sector("home_improvement", "Home Improvement", "niche", ["home improvement", "home depot", "Lowe's", "housing"], ["HD", "LOW", "SHW"]),
    _sector("apparel_retail", "Apparel Retail", "niche", ["apparel retail", "clothing store", "fashion retail"], ["ANF", "AEO", "GPS"]),
    # Tech (continued)
    _sector("5g", "5G", "niche", ["5G", "5G network", "wireless infrastructure", "mmWave"], ["QCOM", "AVGO", "TMUS"]),
    _sector("iot", "IoT", "niche", ["IoT", "internet of things", "connected devices", "sensors"], ["ARM", "AMZN", "GOOGL"]),
    _sector("edge_computing", "Edge Computing", "niche", ["edge computing", "edge AI", "edge deployment", "edge server"], ["AMZN", "MSFT", "CDN"]),
    _sector("memory_chips", "Memory Chips", "niche", ["memory chip", "DRAM", "NAND", "flash memory", "Micron", "SK Hynix"], ["MU", "WDC", "Samsung"]),
    _sector("ai_infrastructure", "AI Infrastructure", "niche", ["AI infrastructure", "GPU cluster", "AI training", "compute"], ["NVDA", "AMZN", "GOOGL"]),
    _sector("enterprise_software", "Enterprise Software", "niche", ["enterprise software", "ERP", "CRM", "enterprise SaaS"], ["ORCL", "CRM", "SAP"]),
    _sector("dev_tools", "Developer Tools", "niche", ["developer tools", "DevOps", "CI/CD", "GitHub"], ["MSFT", "DDOG", "NET"]),
    _sector("semiconductor_design", "Semiconductor Design", "niche", ["chip design", "EDA", "Synopsys", "Cadence"], ["SNPS", "CDNS", "ARM"]),
    _sector("optical_networking", "Optical Networking", "niche", ["optical", "fiber optic", "datacom", "coherent"], ["LITE", "IIVI", "ACIA"]),
    _sector("software_defined_networking", "SDN", "niche", ["SDN", "software defined", "network virtualization"], ["VMW", "CSCO", "JNPR"]),
    # Energy (continued)
    _sector("natural_gas", "Natural Gas", "niche", ["natural gas", "LNG", "gas pipeline", "Henry Hub"], ["XOM", "CVX", "EQT"]),
    _sector("oil_services", "Oil Services", "niche", ["oil services", "drilling", "oilfield", "Schlumberger", "Halliburton"], ["SLB", "HAL", "BKR"]),
    _sector("refining", "Refining", "niche", ["refining", "refinery", "crack spread", "downstream"], ["VLO", "MPC", "PSX"]),
    _sector("geothermal", "Geothermal", "niche", ["geothermal", "geothermal energy", "enhanced geothermal"], ["ORA", "CLNE", "NEE"]),
    _sector("biofuels", "Biofuels", "niche", ["biofuel", "ethanol", "renewable diesel", "biodiesel"], ["CLNE", "REGI", "Gevo"]),
    _sector("nuclear_utilities", "Nuclear Utilities", "niche", ["nuclear utility", "nuclear plant", "Vogtle"], ["VST", "NEE", "XEL"]),
    _sector("power_distribution", "Power Distribution", "niche", ["power distribution", "grid", "transmission", "T&D"], ["NEE", "SRE", "AEP"]),
    _sector("renewables", "Renewables", "niche", ["renewable energy", "clean energy", "renewables"], ["NEE", "ENPH", "FSLR"]),
    _sector("energy_storage", "Energy Storage", "niche", ["energy storage", "BESS", "grid battery"], ["FLNC", "NEE", "AES"]),
    _sector("ev_charging", "EV Charging", "niche", ["EV charging", "charging station", "EV infrastructure"], ["CHPT", "EVGO", "BLNK"]),
    # Materials (continued)
    _sector("aluminum", "Aluminum", "niche", ["aluminum", "aluminum smelting", "bauxite"], ["AA", "AL", "CENX"]),
    _sector("zinc", "Zinc", "niche", ["zinc", "zinc mining", "zinc price"], ["TECK", "HBM", "SCCO"]),
    _sector("cobalt", "Cobalt", "niche", ["cobalt", "cobalt mining", "battery cobalt"], ["GLNCY", "CMCL", "LAC"]),
    _sector("graphite", "Graphite", "niche", ["graphite", "graphite anode", "natural graphite"], ["SYRA", "NMG", "NOVONIX"]),
    _sector("manganese", "Manganese", "niche", ["manganese", "manganese mining", "battery manganese"], ["VALE", "South32", "Eramet"]),
    _sector("platinum", "Platinum", "niche", ["platinum", "PGM", "platinum group"], ["SBSW", "NEM", "PLG"]),
    _sector("palladium", "Palladium", "niche", ["palladium", "PGM", "catalytic converter"], ["SBSW", "NEM", "PLG"]),
    _sector("silver", "Silver", "niche", ["silver", "silver mining", "silver price"], ["NEM", "PAAS", "AG"]),
    _sector("gold", "Gold", "niche", ["gold", "gold mining", "gold price"], ["NEM", "GOLD", "AEM"]),
    _sector("potash", "Potash", "niche", ["potash", "potassium", "K2O"], ["NTR", "MOS", "ICL"]),
    _sector("phosphates", "Phosphates", "niche", ["phosphate", "phosphorus", "fertilizer phosphate"], ["MOS", "ICL", "CF"]),
    _sector("chemicals", "Chemicals", "niche", ["chemicals", "petrochemical", "specialty chemical"], ["LIN", "APD", "DD"]),
    _sector("industrial_gases", "Industrial Gases", "niche", ["industrial gas", "oxygen", "nitrogen", "Linde", "Air Products"], ["LIN", "APD", "N2"]),
    _sector("packaging", "Packaging", "niche", ["packaging", "corrugated", "containerboard"], ["IP", "PKG", "WRK"]),
    _sector("paper", "Paper", "niche", ["paper", "pulp", "paperboard"], ["IP", "PKG", "WRK"]),
    _sector("plastics", "Plastics", "niche", ["plastics", "polymer", "resin"], ["LIN", "DD", "EMN"]),
    # Transportation (continued)
    _sector("marine", "Marine", "niche", ["marine", "shipbuilding", "offshore vessels"], ["HII", "GD", "NOC"]),
    _sector("rail_equipment", "Rail Equipment", "niche", ["rail equipment", "locomotive", "freight car"], ["WAB", "TRN", "GBX"]),
    _sector("auto_parts", "Auto Parts", "niche", ["auto parts", "OEM", "automotive supplier"], ["APTV", "BWA", "LEG"]),
    _sector("tires", "Tires", "niche", ["tire", "tires", "rubber"], ["GT", "BFS", "ML"]),
    _sector("ev_batteries", "EV Batteries", "niche", ["EV battery", "battery pack", "cell manufacturing"], ["PANasonic", "LG", "CATL"]),
    _sector("micromobility", "Micromobility", "niche", ["micromobility", "e-scooter", "e-bike"], ["LYFT", "UBER", "Bird"]),
    _sector("autonomous_trucks", "Autonomous Trucks", "niche", ["autonomous truck", "self-driving truck", "robotruck"], ["PACCAR", "NVDA", "AUR"]),
    _sector("airports", "Airports", "niche", ["airport", "airport operator", "aviation infrastructure"], ["ASR", "VINP", "GAP"]),
    _sector("ports", "Ports", "niche", ["port", "seaport", "port operator"], ["DPW", "PSA", "Hutchison"]),
    # Consumer (continued)
    _sector("sports", "Sports", "niche", ["sports", "sports league", "sports media"], ["DIS", "FOXA", "DKNG"]),
    _sector("fitness", "Fitness", "niche", ["fitness", "gym", "Peloton", "exercise"], ["PTON", "NKE", "LULU"]),
    _sector("outdoor", "Outdoor", "niche", ["outdoor", "camping", "recreational"], ["DECK", "VFC", "JWN"]),
    _sector("pets", "Pets", "niche", ["pet", "pet food", "pet care"], ["CHWY", "PET", "WOOF"]),
    _sector("toys", "Toys", "niche", ["toy", "toys", "Hasbro", "Mattel"], ["HAS", "MAT", "DIS"]),
    _sector("cosmetics", "Cosmetics", "niche", ["cosmetics", "beauty", "makeup", "skincare"], ["EL", "PG", "UL"]),
    _sector("beverages", "Beverages", "niche", ["beverage", "soft drink", "alcohol", "beer"], ["KO", "PEP", "BUD"]),
    _sector("tobacco", "Tobacco", "niche", ["tobacco", "cigarette", "smoking"], ["PM", "MO", "BTI"]),
    _sector("consumer_electronics", "Consumer Electronics", "niche", ["consumer electronics", "smartphone", "wearable"], ["AAPL", "SONY", "Samsung"]),
    _sector("home_appliances", "Home Appliances", "niche", ["home appliance", "white goods", "Whirlpool"], ["WHR", "GE", "LG"]),
    _sector("furniture", "Furniture", "niche", ["furniture", "home furnishings", "Wayfair"], ["W", "RH", "WSM"]),
    _sector("discount_retail", "Discount Retail", "niche", ["discount retail", "dollar store", "off-price"], ["DG", "DLTR", "ROST"]),
    _sector("convenience_stores", "Convenience Stores", "niche", ["convenience store", "c-store", "Circle K"], ["WBA", "CVS", "KR"]),
    # Finance (continued)
    _sector("asset_management", "Asset Management", "niche", ["asset management", "AUM", "BlackRock", "Vanguard"], ["BLK", "SCHW", "IVZ"]),
    _sector("exchanges", "Exchanges", "niche", ["exchange", "stock exchange", "CME", "Nasdaq"], ["CME", "NDAQ", "ICE"]),
    _sector("wealth_management", "Wealth Management", "niche", ["wealth management", "RIA", "broker-dealer"], ["SCHW", "GS", "MS"]),
    _sector("investment_banking", "Investment Banking", "niche", ["investment banking", "M&A", "IPO", "underwriting"], ["GS", "MS", "JPM"]),
    _sector("consumer_finance", "Consumer Finance", "niche", ["consumer finance", "personal loan", "credit card"], ["COF", "SYF", "DFS"]),
    _sector("mortgage", "Mortgage", "niche", ["mortgage", "mortgage lending", "origination"], ["RKT", "UWMC", "LDI"]),
    _sector("title_insurance", "Title Insurance", "niche", ["title insurance", "title search", "FNF"], ["FNF", "FIS", "STC"]),
    _sector("reinsurance_broker", "Reinsurance Broker", "niche", ["reinsurance broker", "Guy Carpenter", "Aon"], ["AON", "WTW", "MMC"]),
    _sector("specialty_finance", "Specialty Finance", "niche", ["specialty finance", "factoring", "asset-based lending"], ["OCSL", "ARCC", "FSK"]),
    _sector("cannabis", "Cannabis", "niche", ["cannabis", "marijuana", "weed", "CBD"], ["TLRY", "CGC", "CRON"]),
    # Healthcare (continued)
    _sector("cro", "CRO", "niche", ["CRO", "clinical research", "contract research"], ["IQV", "ICLR", "LAB"]),
    _sector("healthcare_it", "Healthcare IT", "niche", ["healthcare IT", "health IT", "EHR", "Epic"], ["EPAM", "CERN", "MDRX"]),
    _sector("telehealth", "Telehealth", "niche", ["telehealth", "telemedicine", "virtual care"], ["TDOC", "CVS", "AMWL"]),
    _sector("pharma_services", "Pharma Services", "niche", ["pharma services", "CDMO", "pharma outsourcing"], ["CDMO", "LONZA", "CPhI"]),
    _sector("generics", "Generics", "niche", ["generic drug", "generic pharma", "biosimilar"], ["TEVA", "VTRS", "AMGN"]),
    _sector("life_sciences_tools", "Life Sciences Tools", "niche", ["life sciences tools", "lab equipment", "reagents"], ["TMO", "DHR", "ABT"]),
    _sector("dental", "Dental", "niche", ["dental", "dental equipment", "dental implants"], ["ALGN", "XRAY", "HSIC"]),
    _sector("veterinary", "Veterinary", "niche", ["veterinary", "animal health", "pet pharma"], ["ZTS", "ELAN", "IDXX"]),
    _sector("hospitals", "Hospitals", "niche", ["hospital", "hospital operator", "HCA"], ["HCA", "CYH", "THC"]),
    _sector("reits", "REITs", "niche", ["REIT", "real estate investment trust"], ["PLD", "AMT", "EQIX"]),
    _sector("residential_reits", "Residential REITs", "niche", ["residential REIT", "apartment REIT", "multifamily"], ["EQR", "AVB", "MAA"]),
    _sector("industrial_reits", "Industrial REITs", "niche", ["industrial REIT", "warehouse REIT", "logistics real estate"], ["PLD", "STAG", "REXR"]),
    _sector("data_center_reits", "Data Center REITs", "niche", ["data center REIT", "colocation"], ["EQIX", "DLR", "AMT"]),
    # Industrial (continued)
    _sector("aerospace_components", "Aerospace Components", "niche", ["aerospace component", "aerostructures", "titanium"], ["TDG", "TXT", "HII"]),
    _sector("defense_electronics", "Defense Electronics", "niche", ["defense electronics", "radar", "avionics"], ["L3H", "LHX", "RTX"]),
    _sector("munitions", "Munitions", "niche", ["munitions", "ammunition", "ordnance"], ["LMT", "NOC", "GD"]),
    _sector("satellite_communications", "Satellite Communications", "niche", ["satellite communications", "satcom", "VSAT"], ["SATS", "VSAT", "IRDM"]),
    _sector("earth_observation", "Earth Observation", "niche", ["earth observation", "remote sensing", "imagery"], ["PL", "MAXR", "BLDE"]),
    _sector("launch_vehicles", "Launch Vehicles", "niche", ["launch vehicle", "rocket", "launch provider"], ["RKLB", "LMT", "NOC"]),
    _sector("pumps", "Pumps", "niche", ["pump", "pumps", "flow control"], ["ITW", "FLR", "XYL"]),
    _sector("valves", "Valves", "niche", ["valve", "valves", "flow control"], ["ITW", "EMR", "SWK"]),
    _sector("bearings", "Bearings", "niche", ["bearing", "bearings", "SKF", "Timken"], ["SKF", "TKR", "RBC"]),
    _sector("fasteners", "Fasteners", "niche", ["fastener", "fasteners", "bolts", "nuts"], ["FAST", "ITW", "SWK"]),
    _sector("electrical_equipment", "Electrical Equipment", "niche", ["electrical equipment", "switchgear", "transformers"], ["EMR", "ETN", "ROK"]),
    _sector("industrial_distribution", "Industrial Distribution", "niche", ["industrial distribution", "MRO", "Grainger"], ["GWW", "FAST", "MSM"]),
    _sector("waste_management", "Waste Management", "niche", ["waste management", "recycling", "landfill"], ["WM", "RSG", "WCN"]),
    _sector("environmental_services", "Environmental Services", "niche", ["environmental services", "remediation", "hazardous waste"], ["WM", "RSG", "CLH"]),
    # Agriculture (continued)
    _sector("seeds", "Seeds", "niche", ["seeds", "seed company", "Bayer", "Corteva"], ["BAYRY", "CTVA", "SYT"]),
    _sector("agrochemicals", "Agrochemicals", "niche", ["agrochemical", "crop protection", "pesticide"], ["CTVA", "FMC", "NTR"]),
    _sector("dairy", "Dairy", "niche", ["dairy", "milk", "cheese"], ["DF", "SAP", "Dean"]),
    _sector("sugar", "Sugar", "niche", ["sugar", "sugar cane", "sugar beet"], ["INGR", "ADM", "BG"]),
    _sector("agriculture_land", "Agriculture Land", "niche", ["farmland", "agriculture real estate", "FARM"], ["FARM", "LAND", "GLAD"]),
    _sector("vertical_farming", "Vertical Farming", "niche", ["vertical farming", "indoor farming", "controlled environment"], ["APPH", "HYFM", "CULTF"]),
    _sector("aquaculture", "Aquaculture", "niche", ["aquaculture", "fish farming", "salmon"], ["MOWI", "SalMar", "Grieg"]),
    _sector("timber", "Timber", "niche", ["timber", "lumber", "forest products"], ["WY", "RYN", "PCH"]),
    # Geopolitics (continued)
    _sector("nato", "NATO", "niche", ["NATO", "alliance", "collective defense"], ["LMT", "NOC", "RTX"]),
    _sector("military_spending", "Military Spending", "niche", ["military spending", "defense budget", "Pentagon budget"], ["LMT", "NOC", "GD"]),
    _sector("export_controls", "Export Controls", "niche", ["export control", "export ban", "entity list"], ["NVDA", "AMD", "INTC"]),
    _sector("critical_minerals", "Critical Minerals", "niche", ["critical minerals", "strategic minerals", "supply chain security"], ["MP", "LAC", "ALB"]),
    _sector("reshoring", "Reshoring", "niche", ["reshoring", "onshoring", "manufacturing return"], ["CAT", "DE", "NUE"]),
    _sector("semiconductor_subsidies", "Semiconductor Subsidies", "niche", ["CHIPS Act", "semiconductor subsidy", "fab incentive"], ["INTC", "TSM", "NVDA"]),
    _sector("ev_subsidies", "EV Subsidies", "niche", ["EV subsidy", "IRA", "EV tax credit"], ["TSLA", "GM", "F"]),
    _sector("infrastructure_bill", "Infrastructure Bill", "niche", ["infrastructure bill", "IIJA", "Bipartisan Infrastructure"], ["CAT", "VMC", "NUE"]),
    # Utilities (continued)
    _sector("regulated_utilities", "Regulated Utilities", "niche", ["regulated utility", "rate base", "utility regulation"], ["NEE", "DUK", "SO"]),
    _sector("independent_power", "Independent Power", "niche", ["independent power", "IPP", "merchant power"], ["VST", "CWEN", "ORA"]),
    _sector("gas_utilities", "Gas Utilities", "niche", ["gas utility", "natural gas distribution"], ["NJR", "OGS", "SWX"]),
    _sector("renewable_utilities", "Renewable Utilities", "niche", ["renewable utility", "clean energy utility"], ["NEE", "AES", "CWEN"]),
    _sector("smart_grid", "Smart Grid", "niche", ["smart grid", "AMI", "smart meter"], ["ITRI", "XYL", "Sensus"]),
    _sector("demand_response", "Demand Response", "niche", ["demand response", "load management", "peak shaving"], ["NEE", "VST", "CWEN"]),
    # Consumer discretionary (continued)
    _sector("auto_dealers", "Auto Dealers", "niche", ["auto dealer", "car dealer", "dealership"], ["AN", "LAD", "PAG"]),
    _sector("auto_manufacturing", "Auto Manufacturing", "niche", ["auto manufacturing", "OEM", "car maker"], ["F", "GM", "STLA"]),
    _sector("motorcycles", "Motorcycles", "niche", ["motorcycle", "Harley", "Honda"], ["HOG", "PII", "HMC"]),
    _sector("rv", "RV", "niche", ["RV", "recreational vehicle", "motorhome"], ["THO", "WGO", "LCII"]),
    _sector("boats", "Boats", "niche", ["boat", "marine", "yacht"], ["MBUU", "MCFT", "BC"]),
    _sector("casinos", "Casinos", "niche", ["casino", "gaming", "Las Vegas"], ["LVS", "MGM", "WYNN"]),
    _sector("cruise", "Cruise", "niche", ["cruise", "cruise line", "Carnival"], ["CCL", "RCL", "NCLH"]),
    _sector("lodging", "Lodging", "niche", ["lodging", "hotel", "hospitality"], ["MAR", "HLT", "H"]),
    _sector("timeshare", "Timeshare", "niche", ["timeshare", "vacation ownership"], ["WYN", "HGV", "VAC"]),
    _sector("education_services", "Education Services", "niche", ["education services", "for-profit education", "online education"], ["LRN", "COCO", "GHC"]),
    _sector("staffing", "Staffing", "niche", ["staffing", "temp agency", "workforce"], ["RHI", "MAN", "KFY"]),
    _sector("professional_services", "Professional Services", "niche", ["professional services", "consulting", "advisory"], ["ACN", "Deloitte", "EY"]),
    _sector("security_services", "Security Services", "niche", ["security services", "guarding", "G4S"], ["ALL", "Securitas", "G4S"]),
    _sector("facilities_management", "Facilities Management", "niche", ["facilities management", "FM", "building services"], ["CBRE", "Cushman", "JLL"]),
    _sector("media", "Media", "niche", ["media", "publishing", "content"], ["DIS", "WBD", "PARA"]),
    _sector("music", "Music", "niche", ["music", "streaming music", "Spotify"], ["SPOT", "WMG", "UMG"]),
    _sector("podcasts", "Podcasts", "niche", ["podcast", "podcasting", "audio"], ["SPOT", "GOOGL", "AAPL"]),
]

SECTOR_UNIVERSE: dict[str, SectorDefinition] = dict(SECTOR_ENTRIES)

# ─── Synonym Expansion (3–5x recall boost) ────────────────────────────────────

SECTOR_SYNONYMS: dict[str, list[str]] = {
    "semiconductors": ["chips", "chipmaking", "fab", "foundry", "integrated circuits", "wafer"],
    "semiconductor_equipment": ["lithography", "ASML", "wafer", "chip fab", "equipment"],
    "defense": ["military spending", "weapons", "arms production", "defense contractor", "Pentagon"],
    "aerospace": ["aviation", "Boeing", "aircraft", "jet order", "commercial aircraft"],
    "space": ["SpaceX", "satellite", "orbital", "launch", "Starlink", "NASA"],
    "ai": ["artificial intelligence", "machine learning", "LLM", "generative AI", "AI chip"],
    "cybersecurity": ["ransomware", "data breach", "cyber attack", "zero day"],
    "shipping": ["container", "freight", "maritime", "Red Sea", "port", "Suez"],
    "energy": ["oil", "OPEC", "natural gas", "crude", "LNG", "pipeline"],
    "uranium": ["nuclear", "yellowcake", "SMR", "nuclear fuel"],
    "ev": ["electric vehicle", "Tesla", "EV", "EV charging", "battery"],
    "financials": ["banks", "Fed", "interest rates", "credit", "yield curve"],
    "healthcare": ["pharma", "FDA", "hospital", "drug", "vaccine"],
    "data_centers": ["hyperscaler", "AI infrastructure", "server", "cloud capacity"],
    "mining": ["ore", "extraction", "commodity", "minerals"],
    "rail": ["railroad", "freight rail", "Class I"],
    "airlines": ["aviation", "air travel", "jet fuel", "passenger"],
    "logistics": ["supply chain", "warehouse", "fulfillment", "last mile"],
    "supply_chain": ["reshoring", "nearshoring", "supply disruption"],
    "trade_war": ["tariffs", "US China", "trade dispute"],
    "china_tech": ["Huawei", "SMIC", "Chinese chip", "export controls"],
    "natural_gas": ["LNG", "Henry Hub", "gas pipeline", "methane"],
    "oil_services": ["drilling", "oilfield", "Schlumberger", "Halliburton"],
    "renewables": ["clean energy", "solar", "wind", "renewable"],
    "gold": ["gold mining", "gold price", "precious metals"],
    "asset_management": ["AUM", "BlackRock", "Vanguard", "fund manager"],
    "exchanges": ["CME", "Nasdaq", "stock exchange", "trading venue"],
    "telehealth": ["telemedicine", "virtual care", "remote health"],
    "waste_management": ["recycling", "landfill", "WM", "waste"],
    "military_spending": ["defense budget", "Pentagon", "NATO spending"],
}


def get_expanded_keywords(sector_key: str) -> list[str]:
    """Return seed_keywords + synonyms for a sector. Used for search and filtering."""
    sector = SECTOR_UNIVERSE.get(sector_key)
    if not sector:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for kw in sector.seed_keywords:
        k = kw.lower()
        if k not in seen:
            seen.add(k)
            out.append(kw)
    for syn in SECTOR_SYNONYMS.get(sector_key, []):
        k = syn.lower()
        if k not in seen:
            seen.add(k)
            out.append(syn)
    return out


# ─── Company → Sector Mapping ────────────────────────────────────────────────

COMPANY_SECTOR_MAP: dict[str, str] = {
    "tesla": "ev",
    "nvidia": "semiconductors",
    "nvda": "semiconductors",
    "amd": "semiconductors",
    "intel": "semiconductors",
    "tsmc": "semiconductors",
    "boeing": "aerospace",
    "ba": "aerospace",
    "lockheed": "defense",
    "lockheed martin": "defense",
    "lmt": "defense",
    "northrop": "defense",
    "rtx": "defense",
    "raytheon": "defense",
    "spacex": "space",
    "amazon": "ecommerce",
    "amzn": "ecommerce",
    "apple": "technology",
    "aapl": "technology",
    "microsoft": "cloud_computing",
    "msft": "cloud_computing",
    "google": "cloud_computing",
    "alphabet": "cloud_computing",
    "googl": "cloud_computing",
    "meta": "social_media",
    "netflix": "streaming",
    "nflx": "streaming",
    "exxon": "energy",
    "xom": "energy",
    "chevron": "energy",
    "cvx": "energy",
    "jpmorgan": "financials",
    "jpm": "financials",
    "bank of america": "financials",
    "bac": "financials",
    "goldman": "financials",
    "gs": "financials",
    "crowdstrike": "cybersecurity",
    "crwd": "cybersecurity",
    "palo alto": "cybersecurity",
    "panw": "cybersecurity",
    "zscaler": "cybersecurity",
    "zs": "cybersecurity",
    "coinbase": "crypto",
    "coin": "crypto",
    "microstrategy": "crypto",
    "mstr": "crypto",
    "caterpillar": "construction",
    "cat": "construction",
    "john deere": "agriculture_equipment",
    "de": "agriculture_equipment",
    "ups": "logistics",
    "fedex": "logistics",
    "fdx": "logistics",
    "union pacific": "rail",
    "unp": "rail",
    "csx": "rail",
    "delta": "airlines",
    "dal": "airlines",
    "united": "airlines",
    "ual": "airlines",
    "southwest": "airlines",
    "luv": "airlines",
    "uber": "ride_sharing",
    "lyft": "ride_sharing",
    "airbnb": "travel",
    "abnb": "travel",
    "booking": "travel",
    "bkng": "travel",
    "mcdonald": "restaurants",
    "mcd": "restaurants",
    "chipotle": "restaurants",
    "cmg": "restaurants",
    "nike": "apparel",
    "nke": "apparel",
    "lululemon": "apparel",
    "lulu": "apparel",
    "eli lilly": "pharma",
    "lly": "pharma",
    "johnson": "pharma",
    "jnj": "pharma",
    "pfizer": "pharma",
    "pfe": "pharma",
    "united health": "managed_care",
    "unh": "managed_care",
    "blackstone": "private_equity",
    "bx": "private_equity",
    "kkr": "private_equity",
    "apollo": "private_equity",
    "apo": "private_equity",
    "visa": "payments",
    "v": "payments",
    "mastercard": "payments",
    "ma": "payments",
    "paypal": "payments",
    "pypl": "payments",
    "square": "fintech",
    "sq": "fintech",
    "block": "fintech",
    "crowdstrike": "cybersecurity",
    "crwd": "cybersecurity",
    "palo alto": "cybersecurity",
    "panw": "cybersecurity",
    "zscaler": "cybersecurity",
    "rivian": "ev",
    "rivn": "ev",
    "lucid": "ev",
    "lcid": "ev",
    "equinix": "data_centers",
    "eqix": "data_centers",
    "digital realty": "data_centers",
    "dlr": "data_centers",
    "plug power": "hydrogen",
    "plug": "hydrogen",
    "enphase": "solar",
    "enph": "solar",
    "first solar": "solar",
    "fslr": "solar",
}


# ─── Sector → Event Type (for cluster labels and impact inference) ─────────────

SECTOR_TO_EVENT_TYPE: dict[str, EventType] = {
    "energy": EventType.OIL_SUPPLY_SHOCK,
    "shipping": EventType.SHIPPING_DISRUPTION,
    "financials": EventType.RATE_HIKE,
    "construction": EventType.GOVERNMENT_STIMULUS,
    "mining": EventType.GOVERNMENT_STIMULUS,
    "steel": EventType.GOVERNMENT_STIMULUS,
    "sanctions": EventType.SANCTIONS,
    "trade_war": EventType.SANCTIONS,
    "china_tech": EventType.SANCTIONS,
    "agriculture": EventType.NATURAL_DISASTER,
    "fertilizers": EventType.NATURAL_DISASTER,
    "grain": EventType.NATURAL_DISASTER,
    "insurance": EventType.NATURAL_DISASTER,
    "reinsurance": EventType.NATURAL_DISASTER,
    # More sectors → event types that have bearish impacts
    "aerospace": EventType.SHIPPING_DISRUPTION,
    "airlines": EventType.OIL_SUPPLY_SHOCK,
    "technology": EventType.RATE_HIKE,
    "semiconductors": EventType.SANCTIONS,
    "real_estate": EventType.RATE_HIKE,
    "utilities": EventType.RATE_HIKE,
    "retail": EventType.SHIPPING_DISRUPTION,
}
# All other sectors default to EventType.OTHER


# ─── ETF → Sector Mapping ────────────────────────────────────────────────────

ETF_SECTORS: dict[str, str] = {
    "XLK": "cloud_computing",
    "XLE": "energy",
    "XLF": "financials",
    "XLV": "healthcare",
    "XLI": "machinery",
    "XLP": "food_processing",
    "XLY": "ecommerce",
    "XLB": "mining",
    "XLU": "utilities",
    "SMH": "semiconductors",
    "SOXX": "semiconductors",
    "ITA": "defense",
    "URA": "uranium",
    "KRBN": "carbon_markets",
    "TAN": "solar",
    "ICLN": "hydrogen",
    "QCLN": "ev",
    "DRIV": "autonomous_vehicles",
    "BOTZ": "robotics",
    "HACK": "cybersecurity",
    "IBUY": "ecommerce",
    "JETS": "airlines",
    "IYT": "logistics",
    "XHB": "construction",
    "MOO": "agriculture",
    "DBA": "grain",
    "VNQ": "commercial_real_estate",
    "REM": "mortgage_reits",
    "BIB": "biotech",
    "XBI": "biotech",
    "GAMR": "gaming",
    "BLOK": "crypto",
    "LIT": "battery_materials",
    "REMX": "rare_earths",
    "SRVR": "data_centers",
    "PHO": "water",
    "KIE": "reinsurance",
    "IBIT": "crypto",
    "ARKX": "space",
    "OIH": "oil_services",
    "IPAY": "fintech",
    "CPER": "copper",
    "SLX": "steel",
}

# Sector → primary ETF (for market signals). Built from ETF_SECTORS + overrides.
SECTOR_TO_ETF: dict[str, str] = {sector: etf for etf, sector in ETF_SECTORS.items()}
# Override duplicates (prefer more liquid/common ETF)
SECTOR_TO_ETF.update({
    "semiconductors": "SMH",
    "biotech": "XBI",
    "hydrogen": "ICLN",
    "ev": "QCLN",
})
# Add sectors not in ETF_SECTORS
SECTOR_TO_ETF.update({
    "shipping": "IYT",
    "defense": "ITA",
    "utilities": "XLU",
    "drones": "ITA",
    "ai": "XLK",
    "cybersecurity": "HACK",
    "cloud_computing": "XLK",
    "ev": "QCLN",
    "solar": "TAN",
    "hydrogen": "ICLN",
    "ecommerce": "IBUY",
    "airlines": "JETS",
    "biotech": "XBI",
    "mining": "XLB",
    "copper": "CPER",
    "steel": "SLX",
    "fintech": "IPAY",
    "payments": "IPAY",
    "oil_services": "OIH",
    "robotics": "BOTZ",
    "saas": "IGV",
})


# ─── Default scan order ──────────────────────────────────────────────────────

DEFAULT_SCAN_ORDER: list[str] = [
    "energy",
    "financials",
    "semiconductors",
    "ai",
    "shipping",
    "defense",
    "healthcare",
    "utilities",
    "ev",
    "space",
    "aerospace",
    "fertilizers",
    "uranium",
    "carbon_markets",
    "data_centers",
    "cybersecurity",
    "cloud_computing",
    "water",
    "rare_earths",
    "drones",
    "battery_materials",
    "reinsurance",
    "fintech",
    "solar",
    "hydrogen",
]

# Broader sector list for daily precomputed scan (homepage)
DAILY_SCAN_ORDER: list[str] = [
    "energy",
    "financials",
    "semiconductors",
    "ai",
    "cybersecurity",
    "data_centers",
    "cloud_computing",
    "ev",
    "shipping",
    "defense",
    "aerospace",
    "space",
    "healthcare",
    "biotech",
    "pharma",
    "utilities",
    "uranium",
    "solar",
    "hydrogen",
    "carbon_markets",
    "mining",
    "copper",
    "lithium",
    "rare_earths",
    "battery_materials",
    "steel",
    "rail",
    "airlines",
    "logistics",
    "trucking",
    "agriculture",
    "fertilizers",
    "grain",
    "ecommerce",
    "streaming",
    "gaming",
    "social_media",
    "advertising",
    "crypto",
    "payments",
    "fintech",
    "private_equity",
    "insurance",
    "reinsurance",
    "china_tech",
    "trade_war",
    "supply_chain",
    "water",
    "construction",
    "robotics",
    "drones",
]


def normalize_sector_key(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


# Runtime registry for user-defined sectors
_DYNAMIC_SECTORS: dict[str, SectorDefinition] = {}

# Common user phrases → sector (avoids creating redundant custom sectors)
PHRASE_TO_SECTOR: dict[str, str] = {
    "video games": "gaming",
    "electric cars": "ev",
    "electric vehicles": "ev",
    "oil and gas": "energy",
    "oil gas": "energy",
    "social media": "social_media",
    "artificial intelligence": "ai",
    "machine learning": "ai",
    "nuclear power": "uranium",
    "solar power": "solar",
    "wind power": "wind",
    "cloud computing": "cloud_computing",
    "data centers": "data_centers",
    "semiconductor": "semiconductors",
    "semiconductors": "semiconductors",
    "chips": "semiconductors",
    "ai chips": "semiconductors",
    "defense contractors": "defense",
    "military": "defense",
    "shipping industry": "shipping",
    "airlines": "airlines",
    "aviation": "aerospace",
    "space industry": "space",
    "cryptocurrency": "crypto",
    "bitcoin": "crypto",
    "banks": "financials",
    "insurance": "insurance",
    "real estate": "commercial_real_estate",
    "pharmaceuticals": "pharma",
    "biotech": "biotech",
    "health": "healthcare",
    "health care": "healthcare",
    "healthcare": "healthcare",
    "e-commerce": "ecommerce",
    "ecommerce": "ecommerce",
    "streaming": "streaming",
    "advertising": "advertising",
    "retail": "ecommerce",
    "mining": "mining",
    "copper": "copper",
    "lithium": "lithium",
    "steel": "steel",
    "agriculture": "agriculture",
    "farming": "agriculture",
    "logistics": "logistics",
    "supply chain": "supply_chain",
    "trade war": "trade_war",
    "tariffs": "trade_war",
    "china": "china_tech",
    "sanctions": "sanctions",
    "oil services": "oil_services",
    "renewable": "renewables",
    "clean energy": "renewables",
    "gold mining": "gold",
    "silver mining": "silver",
    "asset managers": "asset_management",
    "stock exchange": "exchanges",
    "telemedicine": "telehealth",
    "waste": "waste_management",
    "recycling": "waste_management",
    "farmland": "agriculture_land",
    "hotels": "lodging",
    "car dealers": "auto_dealers",
    "defense budget": "military_spending",
    "chips act": "semiconductor_subsidies",
    "cyber": "cybersecurity",
    "cyber security": "cybersecurity",
    "cloud": "cloud_computing",
    "data center": "data_centers",
    "electric cars": "ev",
    "tesla": "ev",
    "solar panels": "solar",
    "hydrogen fuel": "hydrogen",
    "green hydrogen": "hydrogen",
    "fintech": "fintech",
    "digital payments": "payments",
    "oil services": "oil_services",
    "drilling": "oil_services",
    "copper mining": "copper",
    "steel production": "steel",
    "railroads": "rail",
    "streaming services": "streaming",
    "social networks": "social_media",
    "asset managers": "asset_management",
    "stock exchanges": "exchanges",
}

# Expansions for short/ambiguous terms
TOPIC_EXPANSIONS: dict[str, list[str]] = {
    "ai": ["AI", "artificial intelligence", "machine learning", "generative AI"],
    "ev": ["electric vehicle", "EV", "Tesla", "electric car"],
    "ml": ["machine learning", "ML", "AI"],
    "pe": ["private equity", "PE", "buyout"],
    "saas": ["SaaS", "software as a service", "cloud software"],
    "cre": ["commercial real estate", "CRE", "office property"],
    "lng": ["LNG", "liquefied natural gas", "natural gas"],
    "smr": ["small modular reactor", "SMR", "nuclear"],
    "evs": ["electric vehicle", "EV", "Tesla"],
}


def create_dynamic_sector(user_input: str) -> SectorDefinition | None:
    """Create a sector from user input. Used when the topic isn't predefined."""
    phrase = user_input.strip()
    if not phrase:
        return None
    key = normalize_sector_key(phrase)
    if not key:
        return None
    if key in TOPIC_EXPANSIONS:
        seed_keywords = TOPIC_EXPANSIONS[key]
    else:
        seed_keywords = [phrase]
        if phrase.endswith("s") and len(phrase) > 2:
            seed_keywords.append(phrase[:-1])
        # Add common variations for compound terms
        if " " in phrase:
            seed_keywords.append(phrase.replace(" ", "-"))
    display_name = phrase.title()
    sector = SectorDefinition(
        key=key,
        display_name=display_name,
        category="custom",
        seed_keywords=seed_keywords,
        representative_symbols=[],
    )
    _DYNAMIC_SECTORS[key] = sector
    return sector


def get_sector(key: str) -> SectorDefinition | None:
    """Get sector by key from predefined or dynamic registry."""
    return SECTOR_UNIVERSE.get(key) or _DYNAMIC_SECTORS.get(key)


def resolve_sector_keys(watchlist: list[str] | None = None) -> list[str]:
    """Resolve watchlist to sector keys. Accepts any user input; creates dynamic sectors for unknowns.
    Resolution order: Company → ETF → Sector → Dynamic.
    """
    if not watchlist:
        return DEFAULT_SCAN_ORDER

    resolved: list[str] = []
    seen: set[str] = set()

    for item in watchlist:
        raw = item.strip()
        if not raw:
            continue

        key = normalize_sector_key(raw)
        phrase_lower = raw.lower()

        # 1. Phrase → sector (e.g. "video games" → gaming)
        if phrase_lower in PHRASE_TO_SECTOR:
            sector = PHRASE_TO_SECTOR[phrase_lower]
            if sector not in seen:
                seen.add(sector)
                resolved.append(sector)
            continue

        # 2. Direct sector match
        if key in SECTOR_UNIVERSE:
            if key not in seen:
                seen.add(key)
                resolved.append(key)
            continue

        # 3. Company → sector
        company_key = key.replace("_", " ")
        if company_key in COMPANY_SECTOR_MAP:
            sector = COMPANY_SECTOR_MAP[company_key]
            if sector not in seen:
                seen.add(sector)
                resolved.append(sector)
            continue

        # 4. ETF symbol → sector (uppercase for tickers)
        ticker = raw.upper()
        if ticker in ETF_SECTORS:
            sector = ETF_SECTORS[ticker]
            if sector not in seen:
                seen.add(sector)
                resolved.append(sector)
            continue

        # 5. Dynamic sector for unknown topics
        if create_dynamic_sector(raw):
            if key not in seen:
                seen.add(key)
                resolved.append(key)

    return resolved or DEFAULT_SCAN_ORDER
