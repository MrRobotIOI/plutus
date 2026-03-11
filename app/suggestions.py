import json
import os

from app.models import SectorImpact, Signal, StructuredEvent, TradeIdea
from app.sectors import get_sector


# Max symbols per sector impact (increase for more options)
MAX_SYMBOLS_PER_IMPACT = 6


def _load_extra_symbols() -> dict[str, list[str]]:
    """Load extra symbols from PLUTUS_EXTRA_SYMBOLS env var (JSON: {"oil": ["BP"], "ai": ["GOOGL"]})."""
    raw = os.getenv("PLUTUS_EXTRA_SYMBOLS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: v if isinstance(v, list) else [] for k, v in data.items() if isinstance(k, str)}
    except json.JSONDecodeError:
        return {}

SECTOR_COMPANY_MAP: dict[str, list[str]] = {
    "energy": ["XOM", "CVX", "SHEL", "COP", "EOG", "SLB"],
    "airlines": ["DAL", "UAL", "AAL", "LUV", "ALK", "JBLU"],
    "chemicals": ["DD", "LIN", "APD", "DOW", "EMN", "CE"],
    "renewables": ["FSLR", "ENPH", "SEDG", "RUN", "NOVA", "ARRY"],
    "materials": ["FCX", "BHP", "RIO", "NEM", "VALE", "SCCO"],
    "industrials": ["CAT", "DE", "ETN", "EMR", "ITW", "ROK"],
    "construction": ["VMC", "MLM", "URI", "CEM", "EXP", "SUM"],
    "mining": ["NEM", "SCCO", "TECK", "FCX", "VALE", "RGLD"],
    "financials": ["JPM", "BAC", "GS", "MS", "C", "WFC"],
    "technology": ["NVDA", "AMD", "INTC", "MSFT", "GOOGL", "META"],
    "ai": ["NVDA", "AMD", "MSFT", "GOOGL", "META", "AVGO"],
    "cybersecurity": ["CRWD", "PANW", "ZS", "FTNT", "CHKP", "OKTA"],
    "cloud_computing": ["AMZN", "MSFT", "GOOGL", "ORCL", "CRM", "SNOW"],
    "data_centers": ["EQIX", "DLR", "VRT", "AMT", "CCI", "COR"],
    "real_estate": ["PLD", "O", "SPG", "AMT", "EQIX", "PSA"],
    "utilities": ["NEE", "DUK", "SO", "D", "AEP", "XEL"],
    "shipping": ["ZIM", "MATX", "SBLK", "GOGL", "DAC", "EGLE"],
    "logistics": ["UPS", "FDX", "EXPD", "XPO", "CHRW", "JBHT"],
    "retail": ["WMT", "TGT", "COST", "HD", "LOW", "DG"],
    "ecommerce": ["AMZN", "SHOP", "ETSY", "MELI", "SE", "BABA"],
    "defense": ["LMT", "NOC", "RTX", "GD", "LHX", "HII"],
    "semiconductors": ["NVDA", "AMD", "TSM", "INTC", "AVGO", "QCOM"],
    "insurance": ["ALL", "TRV", "CB", "PGR", "AIG", "CNA"],
    "agriculture": ["MOS", "DE", "ADM", "NTR", "CF", "BG"],
    "fertilizers": ["MOS", "NTR", "CF", "ICL", "SMG", "FMC"],
    "consumer_staples": ["PG", "KO", "PEP", "CL", "KMB", "GIS"],
    "healthcare": ["LLY", "JNJ", "UNH", "PFE", "ABBV", "MRK"],
    "biotech": ["VRTX", "REGN", "GILD", "BIIB", "AMGN", "MRNA"],
    "pharma": ["LLY", "JNJ", "PFE", "MRK", "ABBV", "BMY"],
    "aerospace": ["BA", "GE", "TDG", "LMT", "RTX", "HII"],
    "space": ["RKLB", "IRDM", "ASTS", "LMT", "NOC", "BA"],
    "uranium": ["CCJ", "UUUU", "NAC", "DNN", "EU", "NXE"],
    "carbon_markets": ["KRBN", "NEE", "XOM", "KEP", "CWEN", "ORA"],
    "water": ["AWK", "WTRG", "XYL", "SJW", "MSEX", "CWT"],
    "rare_earths": ["MP", "LYC", "TECK", "LAC", "NEO", "REEMF"],
    "drones": ["AVAV", "KTOS", "RTX", "LMT", "NOC", "HII"],
    "battery_materials": ["ALB", "SQM", "LAC", "LTHM", "LITM", "PLL"],
    "lithium": ["ALB", "SQM", "LAC", "LTHM", "LITM", "PLL"],
    "reinsurance": ["RNR", "EG", "AIG", "RE", "WRB", "AXS"],
    "gaming": ["EA", "TTWO", "RBLX", "U", "ZNGA", "DKNG"],
    "crypto": ["COIN", "MSTR", "IBIT", "MARA", "RIOT", "BITF"],
    "ev": ["TSLA", "RIVN", "LCID", "GM", "F", "NIO"],
    "solar": ["ENPH", "FSLR", "SEDG", "RUN", "NOVA", "ARRY"],
    "hydrogen": ["PLUG", "BE", "BLDP", "NEL", "ITM", "FCEL"],
    "fintech": ["PYPL", "SQ", "COIN", "AFRM", "SOFI", "UPST"],
    "payments": ["V", "MA", "PYPL", "GPN", "FIS", "ADYEN"],
    "private_equity": ["BX", "KKR", "APO", "CG", "ARES", "STEP"],
    "oil_services": ["SLB", "HAL", "BKR", "NOV", "CHRD", "HP"],
    "natural_gas": ["XOM", "CVX", "EQT", "CHK", "SWN", "AR"],
    "copper": ["FCX", "SCCO", "TECK", "FQVLF", "IVPAF", "LUN"],
    "steel": ["NUE", "STLD", "X", "CLF", "RS", "CMC"],
    "rail": ["UNP", "CSX", "NSC", "BNI", "CP", "KSU"],
    "streaming": ["NFLX", "DIS", "WBD", "PARA", "ROKU", "SPOT"],
    "social_media": ["META", "SNAP", "PINS", "BMBL", "MTCH", "YELP"],
    "travel": ["BKNG", "ABNB", "MAR", "HLT", "EXPE", "TRIP"],
    "restaurants": ["MCD", "CMG", "DPZ", "YUM", "DRI", "WING"],
    "apparel": ["NKE", "LULU", "VFC", "UA", "DECK", "CROX"],
    "asset_management": ["BLK", "SCHW", "IVZ", "BEN", "TROW", "AMG"],
    "exchanges": ["CME", "NDAQ", "ICE", "CBOE", "MKTX", "FIS"],
    "medical_devices": ["ABT", "MDT", "BSX", "SYK", "ZBH", "BAX"],
    "waste_management": ["WM", "RSG", "WCN", "CLH", "GFL", "CWST"],
    "robotics": ["IR", "TER", "ROK", "FANUY", "ABB", "EMR"],
    "saas": ["CRM", "SNOW", "NOW", "WDAY", "HUBS", "ZS"],
    "china_tech": ["BABA", "PDD", "TCEHY", "JD", "BIDU", "NIO"],
    "trade_war": ["BABA", "AAPL", "NVDA", "TSM", "INTC", "QCOM"],
    "supply_chain": ["AAPL", "NVDA", "TSM", "AMZN", "WMT", "HD"],
}

# Symbols for common custom topics (oil, crypto, AI, etc.) — expanded for more options
CUSTOM_TOPIC_SYMBOLS: dict[str, list[str]] = {
    "oil": ["XOM", "CVX", "SHEL", "COP", "EOG", "SLB"],
    "crypto": ["COIN", "MSTR", "IBIT", "MARA", "RIOT", "BITF"],
    "cryptocurrency": ["COIN", "MSTR", "IBIT", "MARA", "RIOT"],
    "bitcoin": ["COIN", "MSTR", "IBIT", "MARA", "RIOT"],
    "ethereum": ["COIN", "MSTR", "IBIT"],
    "energy": ["XOM", "CVX", "SHEL", "COP", "EOG"],
    "ai": ["NVDA", "AMD", "MSFT", "GOOGL", "META", "AVGO"],
    "chips": ["NVDA", "AMD", "TSM", "INTC", "AVGO", "QCOM"],
    "defense": ["LMT", "NOC", "RTX", "GD", "LHX", "HII"],
    "banks": ["JPM", "BAC", "GS", "MS", "C", "WFC"],
    "pharma": ["LLY", "JNJ", "PFE", "MRK", "ABBV", "BMY"],
    "solar": ["ENPH", "FSLR", "SEDG", "RUN", "NOVA", "ARRY"],
    "ev": ["TSLA", "RIVN", "LCID", "GM", "F", "NIO"],
    "cyber": ["CRWD", "PANW", "ZS", "FTNT", "CHKP", "OKTA"],
}


def risk_level_from_confidence(confidence: float) -> str:
    if confidence >= 0.75:
        return "low"
    if confidence >= 0.55:
        return "medium"
    return "high"


def build_trade_ideas(impacts: list[SectorImpact]) -> list[TradeIdea]:
    ideas: list[TradeIdea] = []
    extra = _load_extra_symbols()
    for impact in impacts:
        sector_def = get_sector(impact.sector)
        base = (
            SECTOR_COMPANY_MAP.get(impact.sector)
            or CUSTOM_TOPIC_SYMBOLS.get(impact.sector)
            or (sector_def.representative_symbols if sector_def else [])
        )
        symbols = list(dict.fromkeys([*base, *extra.get(impact.sector, [])]))
        for symbol in symbols[:MAX_SYMBOLS_PER_IMPACT]:
            ideas.append(
                TradeIdea(
                    side="LONG" if impact.direction == "bullish" else "SHORT",
                    symbol=symbol,
                    sector=impact.sector,
                    rationale=impact.rationale,
                )
            )
    return ideas


def build_signal(event: StructuredEvent, impacts: list[SectorImpact]) -> Signal:
    return Signal(
        event=event,
        impacts=impacts,
        trade_ideas=build_trade_ideas(impacts),
        risk_level=risk_level_from_confidence(event.confidence),
    )
