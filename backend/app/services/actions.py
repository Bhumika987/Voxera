"""Auto-generates the Manager Action Center's task list from the call data.

Each rule is a pure function of a DB session that returns zero or more *findings*.
A finding carries a stable ``source_key`` so that regenerating the list upserts
onto existing rows (via :func:`generate`) and never clobbers a manager's status,
assignee, or note. ``generate`` also auto-resolves rows whose rule stopped firing.

The thresholds below are tuned against the current dataset and are safe to adjust
— they only change which findings cross the bar, not the persistence behaviour.
"""

import json
from datetime import datetime

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.database.schema import ActionItem, Call, Customer, MoodEvent

VALID_STATUSES = ("open", "investigating", "resolved", "dismissed")
_ACTIVE_STATUSES = ("open", "investigating")

# --- tuning knobs --------------------------------------------------------------
MIN_UNRESOLVED_PER_CATEGORY = 10
MIN_UNRESOLVED_CALLS_PER_CUSTOMER = 2
NEGATIVE_FROM = ("neutral", "happy", "calm")
NEGATIVE_TO = ("frustrated", "angry")

# Human-readable phrasing for the closed intent-category vocabulary (analyze.py).
_CATEGORY_LABELS = {
    "BILL_PAYMENT": "bill payment",
    "TRANSFER_MONEY": "money transfer",
    "APPOINTMENT_SCHEDULING": "appointment scheduling",
    "LOST_CARD": "lost card",
    "DUPLICATE_CHARGE": "duplicate charge",
    "PASSWORD_RESET": "password reset",
    "BALANCE_CHECK": "balance check",
    "ACCOUNT_CLOSURE": "account closure",
    "BRANCH_INQUIRY": "branch inquiry",
    "OTHER": "uncategorised",
}


def _category_label(category: str | None) -> str:
    if not category:
        return "uncategorised"
    return _CATEGORY_LABELS.get(category, category.replace("_", " ").lower())


def _priority(count: int, medium_at: int, high_at: int) -> str:
    if count >= high_at:
        return "high"
    if count >= medium_at:
        return "medium"
    return "low"


def _plural(count: int, word: str) -> str:
    return word if count == 1 else word + "s"


def _finding(source_key, rule_id, title, description, priority, group_label, entity_type, entity_ids):
    return {
        "source_key": source_key,
        "rule_id": rule_id,
        "title": title,
        "description": description,
        "priority": priority,
        "group_label": group_label,
        "entity_type": entity_type,
        "entity_ids": [str(e) for e in entity_ids],
    }


# --- rules -------------------------------------------------------------------


def rule_unresolved_by_category(db: Session) -> list[dict]:
    """One task per intent category carrying a meaningful backlog of unresolved calls."""
    rows = (
        db.query(Call.intent_category, func.count(Call.id))
        .filter(Call.processed.is_(True), Call.resolution == "unresolved")
        .group_by(Call.intent_category)
        .all()
    )
    findings = []
    for category, count in rows:
        if not category or count < MIN_UNRESOLVED_PER_CATEGORY:
            continue
        label = _category_label(category)
        call_ids = [
            cid
            for (cid,) in db.query(Call.id)
            .filter(
                Call.processed.is_(True),
                Call.resolution == "unresolved",
                Call.intent_category == category,
            )
            .order_by(Call.attention_score.desc(), Call.id.asc())
        ]
        findings.append(
            _finding(
                f"unresolved_category:{category}",
                "unresolved_by_category",
                f"Investigate {count} unresolved {label} {_plural(count, 'call')}",
                f"{count} {label} calls ended without resolution. Review them for a common "
                f"root cause before these customers call back.",
                _priority(count, 10, 20),
                "Unresolved issues",
                "call",
                call_ids,
            )
        )
    return findings


def rule_negative_mood_shifts(db: Session) -> list[dict]:
    """Calls where the customer started calm and the mood turned frustrated/angry."""
    call_ids = sorted(
        {
            cid
            for (cid,) in db.query(MoodEvent.call_id)
            .join(Call, Call.id == MoodEvent.call_id)
            .filter(
                Call.processed.is_(True),
                func.lower(MoodEvent.mood_before).in_(NEGATIVE_FROM),
                func.lower(MoodEvent.mood_after).in_(NEGATIVE_TO),
            )
        }
    )
    count = len(call_ids)
    if count == 0:
        return []
    return [
        _finding(
            "negative_mood_shift",
            "negative_mood_shift",
            f"Review {count} {_plural(count, 'call')} with a severe negative mood swing",
            f"On {count} calls the customer started neutral or happy and ended frustrated "
            f"or angry. Listen for what triggered the turn.",
            _priority(count, 1, 20),
            "Mood",
            "call",
            call_ids,
        )
    ]


def rule_repeat_unresolved_contact(db: Session) -> list[dict]:
    """Customers carrying more than one unresolved call — candidates for proactive outreach."""
    unresolved = func.sum(case((Call.resolution == "unresolved", 1), else_=0))
    rows = (
        db.query(Call.customer_id)
        .filter(Call.processed.is_(True))
        .group_by(Call.customer_id)
        .having(unresolved >= MIN_UNRESOLVED_CALLS_PER_CUSTOMER)
        .all()
    )
    customer_ids = sorted(r[0] for r in rows)
    count = len(customer_ids)
    if count == 0:
        return []
    return [
        _finding(
            "repeat_unresolved_contact",
            "repeat_unresolved_contact",
            f"Follow up with {count} {_plural(count, 'customer')} stuck in repeat unresolved calls",
            f"{count} customers have {MIN_UNRESOLVED_CALLS_PER_CUSTOMER} or more unresolved calls "
            f"on record. A proactive call can stop another inbound.",
            _priority(count, 1, 40),
            "Repeat contact",
            "customer",
            customer_ids,
        )
    ]


def rule_ended_upset(db: Session) -> list[dict]:
    """Calls that finished with the customer frustrated or angry."""
    call_ids = [
        cid
        for (cid,) in db.query(Call.id)
        .filter(Call.processed.is_(True), func.lower(Call.final_mood).in_(NEGATIVE_TO))
        .order_by(Call.attention_score.desc(), Call.id.asc())
    ]
    count = len(call_ids)
    if count == 0:
        return []
    return [
        _finding(
            "ended_upset",
            "ended_upset",
            f"Follow up on {count} {_plural(count, 'call')} that ended with an upset customer",
            f"{count} calls finished with the customer frustrated or angry. A quick recovery "
            f"call can save the relationship.",
            _priority(count, 1, 15),
            "Mood",
            "call",
            call_ids,
        )
    ]


RULES = (
    rule_unresolved_by_category,
    rule_negative_mood_shifts,
    rule_repeat_unresolved_contact,
    rule_ended_upset,
)


# --- generation ------------------------------------------------------------


def collect_findings(db: Session) -> list[dict]:
    findings: list[dict] = []
    for rule in RULES:
        findings.extend(rule(db))
    return findings


def generate(db: Session) -> dict:
    """Upsert the current findings into ``action_items`` and auto-resolve stale rows.

    Idempotent: running it repeatedly with unchanged data is a no-op beyond
    touching ``last_generated_at``. Manager-set status / assignee / note are
    preserved across runs; only ``open`` / ``investigating`` rows whose rule
    stopped firing are auto-resolved.
    """
    now = datetime.utcnow()
    findings = collect_findings(db)

    seen_keys: set[str] = set()
    created = updated = 0

    for f in findings:
        seen_keys.add(f["source_key"])
        item = db.query(ActionItem).filter(ActionItem.source_key == f["source_key"]).one_or_none()
        if item is None:
            item = ActionItem(source_key=f["source_key"], status="open", created_at=now)
            db.add(item)
            created += 1
        else:
            updated += 1
            # a rule that fired again undoes a previous auto-resolve
            if item.auto_resolved and item.status == "resolved":
                item.status = "open"
            item.auto_resolved = False

        item.rule_id = f["rule_id"]
        item.title = f["title"]
        item.description = f["description"]
        item.priority = f["priority"]
        item.group_label = f["group_label"]
        item.metric_count = len(f["entity_ids"])
        item.entity_type = f["entity_type"]
        item.entity_ids = json.dumps(f["entity_ids"])
        item.last_generated_at = now
        item.updated_at = now

    auto_resolved = 0
    if seen_keys:  # never mass-resolve on an empty run (data glitch guard)
        stale = (
            db.query(ActionItem)
            .filter(
                ActionItem.status.in_(_ACTIVE_STATUSES),
                ~ActionItem.source_key.in_(seen_keys),
            )
            .all()
        )
        for item in stale:
            item.status = "resolved"
            item.auto_resolved = True
            suffix = "(auto-resolved: condition no longer met)"
            item.note = f"{item.note} {suffix}".strip() if item.note else suffix
            item.updated_at = now
            auto_resolved += 1

    db.commit()
    return {
        "created": created,
        "updated": updated,
        "auto_resolved": auto_resolved,
        "rules_run": len(RULES),
        "generated_at": now.isoformat(),
    }
