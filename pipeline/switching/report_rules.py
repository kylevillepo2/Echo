"""Shared report eligibility and market naming. Health is calculated in stats only."""
import json
from pathlib import Path

SHUTDOWNS = json.loads(Path(__file__).with_name("categories.json").read_text()).get("shutdowns", {})

UBER_RIDES = "Uber (Rides)"
UBER_EATS = "Uber Eats"
RIDES = {"Lyft", "Bolt", "inDrive", "DiDi", "Waymo", "Careem", "Grab", "Ola", "Curb", "Via", "Taxi", "Taxis"}
DELIVERY = {"DoorDash", "Grubhub", "Instacart", "Spark Driver", "Just Eat", "Deliveroo", "Amazon Flex",
            "Shipt", "Rappi", "Gopuff", "Roadie", "Postmates", "Wolt", "Seamless", "Foodpanda"}
TRUE = {"true", "1", "yes", "y"}


def uber_market(other):
    if other in RIDES or other == UBER_RIDES:
        return UBER_RIDES
    if other in DELIVERY or other == UBER_EATS:
        return UBER_EATS
    return None


def normalize_edge(row, allow_unassigned=False):
    row = dict(row)
    source, target = row["source"].strip(), row["target"].strip()
    original_reviewed = row.get("reviewed_app_original", row.get("reviewed_app", ""))
    if source == "Uber":
        market = uber_market(target)
        if market is None and not allow_unassigned:
            raise ValueError(f"Cannot assign Uber market from counterpart {target!r}")
        source = market or source
    if target == "Uber":
        market = uber_market(source)
        if market is None and not allow_unassigned:
            raise ValueError(f"Cannot assign Uber market from counterpart {source!r}")
        target = market or target
    reviewed = row.get("reviewed_app", "")
    if reviewed == "Uber":
        reviewed = next((app for app in (source, target) if app in {UBER_RIDES, UBER_EATS}), reviewed)
    row.update(source=source, target=target, reviewed_app=reviewed, reviewed_app_original=original_reviewed)
    return row


def is_customer(row):
    # n/a is the pipeline's label for categories where occupational roles do not
    # apply. A labeled rides/delivery report must explicitly be a customer.
    return "reviewer_role" not in row or row["reviewer_role"].strip().lower() in {"customer", "n/a", "not applicable"}


def is_forced(row, shutdowns=None):
    if row["source"] == "Skype":
        # Override the old blanket True flag, including on already-corrected CSVs.
        month = row.get("month", "")[:7]
        return len(month) == 7 and month >= "2025-02"
    shutdowns = SHUTDOWNS if shutdowns is None else shutdowns
    return row["source"] in shutdowns or str(row.get("forced_move", "")).strip().lower() in TRUE


def switch_reports(rows, shutdowns=None):
    """One actual switch/return report per review, pair, month and kind."""
    seen = set()
    for original in rows:
        if original["kind"] not in {"switch", "return"} or not is_customer(original):
            continue
        row = normalize_edge(original)
        if not row["source"] or not row["target"] or row["source"] == row["target"] or is_forced(row, shutdowns):
            continue
        key = (row.get("feedback_id"), row["source"], row["target"], row.get("month", ""), row["kind"])
        if key[0] and key in seen:
            continue
        seen.add(key)
        yield row


def dataset_categories(categories):
    result = dict(categories)
    if "Uber" in result:
        category = result.pop("Uber")
        result[UBER_RIDES] = result[UBER_EATS] = category
    return result


def uber_review_markets(mentions):
    """Assign a pooled Uber review only when all identified markets agree."""
    markets = {}
    for row in mentions:
        reviewed = row.get("reviewed_app_original", row.get("reviewed_app"))
        if reviewed != "Uber":
            continue
        market = uber_market(row["mentioned_app"])
        if market:
            markets.setdefault(row["feedback_id"], set()).add(market)
    return {review_id: next(iter(values)) for review_id, values in markets.items() if len(values) == 1}
