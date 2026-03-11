from app.models import EventType, SectorImpact, StructuredEvent


EVENT_IMPACT_RULES: dict[EventType, list[SectorImpact]] = {
    EventType.OIL_SUPPLY_SHOCK: [
        SectorImpact(
            sector="energy",
            direction="bullish",
            rationale="Lower supply typically supports upstream energy pricing and revenues.",
        ),
        SectorImpact(
            sector="airlines",
            direction="bearish",
            rationale="Higher fuel costs pressure airline margins.",
        ),
        SectorImpact(
            sector="chemicals",
            direction="bearish",
            rationale="Petrochemical feedstock inflation can pressure chemical producers' margins.",
        ),
        SectorImpact(
            sector="renewables",
            direction="bullish",
            rationale="Higher fossil fuel prices can improve relative demand for clean-energy alternatives.",
        ),
    ],
    EventType.GOVERNMENT_STIMULUS: [
        SectorImpact(
            sector="materials",
            direction="bullish",
            rationale="Infrastructure demand tends to support metals and construction inputs.",
        ),
        SectorImpact(
            sector="industrials",
            direction="bullish",
            rationale="Capital spending cycles usually benefit machinery and engineering names.",
        ),
        SectorImpact(
            sector="construction",
            direction="bullish",
            rationale="Public works and housing activity can support construction suppliers and equipment rental.",
        ),
        SectorImpact(
            sector="mining",
            direction="bullish",
            rationale="Stimulus-led demand can raise expectations for bulk metals and miners.",
        ),
    ],
    EventType.RATE_HIKE: [
        SectorImpact(
            sector="financials",
            direction="bullish",
            rationale="Higher rates can expand net interest margins for banks.",
        ),
        SectorImpact(
            sector="technology",
            direction="bearish",
            rationale="Higher discount rates can compress long-duration growth valuations.",
        ),
        SectorImpact(
            sector="real_estate",
            direction="bearish",
            rationale="Higher financing costs often weigh on REITs and property-sensitive names.",
        ),
        SectorImpact(
            sector="utilities",
            direction="bearish",
            rationale="Bond-like utilities can underperform when yields rise.",
        ),
    ],
    EventType.SHIPPING_DISRUPTION: [
        SectorImpact(
            sector="shipping",
            direction="bullish",
            rationale="Freight tightness can lift rates and operator pricing power.",
        ),
        SectorImpact(
            sector="logistics",
            direction="bullish",
            rationale="Capacity constraints can support pricing for alternative logistics providers.",
        ),
        SectorImpact(
            sector="airlines",
            direction="bearish",
            rationale="Fuel and route uncertainty can hurt profitability.",
        ),
        SectorImpact(
            sector="energy",
            direction="bullish",
            rationale="Route risk may increase crude and refined product risk premiums.",
        ),
        SectorImpact(
            sector="retail",
            direction="bearish",
            rationale="Import delays and higher freight costs can weigh on inventory-heavy retailers.",
        ),
    ],
    EventType.SANCTIONS: [
        SectorImpact(
            sector="energy",
            direction="bullish",
            rationale="Restrictions can reduce effective energy supply and raise prices.",
        ),
        SectorImpact(
            sector="industrials",
            direction="bearish",
            rationale="Supply chain friction can increase input costs and delays.",
        ),
        SectorImpact(
            sector="defense",
            direction="bullish",
            rationale="Geopolitical escalations and export controls can increase defense spending expectations.",
        ),
        SectorImpact(
            sector="semiconductors",
            direction="bearish",
            rationale="Trade restrictions can disrupt advanced chip supply chains and end-market demand.",
        ),
        SectorImpact(
            sector="mining",
            direction="bullish",
            rationale="Restricted access to strategic metals can improve pricing for alternative miners.",
        ),
    ],
    EventType.NATURAL_DISASTER: [
        SectorImpact(
            sector="insurance",
            direction="bearish",
            rationale="Catastrophic events can increase claims and loss uncertainty.",
        ),
        SectorImpact(
            sector="construction",
            direction="bullish",
            rationale="Rebuilding demand can support construction activity.",
        ),
        SectorImpact(
            sector="utilities",
            direction="bearish",
            rationale="Grid disruptions and repair costs can pressure utilities in the near term.",
        ),
        SectorImpact(
            sector="agriculture",
            direction="bearish",
            rationale="Crop damage and weather volatility can hurt farm output and input planning.",
        ),
    ],
    EventType.OTHER: [
        SectorImpact(
            sector="financials",
            direction="bullish",
            rationale="Macro events often drive volatility; financials can benefit from trading activity.",
        ),
        SectorImpact(
            sector="utilities",
            direction="bullish",
            rationale="Broad macro stress can rotate capital toward defensive utilities.",
        ),
        SectorImpact(
            sector="materials",
            direction="bullish",
            rationale="General macro supply themes often spill into commodity-linked sectors.",
        ),
        SectorImpact(
            sector="technology",
            direction="bearish",
            rationale="Uncertain macro can compress growth valuations and risk appetite.",
        ),
        SectorImpact(
            sector="airlines",
            direction="bearish",
            rationale="Travel and fuel-sensitive sectors often underperform in macro stress.",
        ),
        SectorImpact(
            sector="real_estate",
            direction="bearish",
            rationale="Higher rates and uncertainty often weigh on property-sensitive names.",
        ),
        SectorImpact(
            sector="retail",
            direction="bearish",
            rationale="Consumer discretionary can lag when macro outlook weakens.",
        ),
    ],
}

# Sectors that default to bearish when dynamically added from OTHER events
_BEARISH_DEFAULT_SECTORS = frozenset({"airlines", "technology", "real_estate", "retail"})


def infer_impacts(event: StructuredEvent) -> list[SectorImpact]:
    impacts = list(EVENT_IMPACT_RULES.get(event.event_type, []))
    # For OTHER events, add sectors from dynamic detection so they get trade ideas
    if event.event_type == EventType.OTHER and event.sectors_affected:
        seen = {i.sector for i in impacts}
        for sector in event.sectors_affected:
            if sector not in seen:
                seen.add(sector)
                direction = "bearish" if sector in _BEARISH_DEFAULT_SECTORS else "bullish"
                impacts.append(
                    SectorImpact(
                        sector=sector,
                        direction=direction,
                        rationale="Sector-relevant catalyst detected in article.",
                    )
                )
    return impacts
