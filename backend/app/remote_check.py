"""JSON-only entry point executed against detached evidence in a remote sandbox."""
import json
import sys

from .integrity import inspect
from .ledger import Ledger
from .models import JournalEntry, PaymentInstruction, Proposal, SandboxReport, SettlementEvent, utcnow


def validate(payload: dict) -> dict:
    ledger = Ledger(payload["accounts"])
    for item in payload["entries"]:
        ledger.append(JournalEntry.model_validate(item))
    instructions = {item["id"]: PaymentInstruction.model_validate(item)
                    for item in payload["instructions"]}
    events = [SettlementEvent.model_validate(item) for item in payload["events"]]
    before = inspect(ledger, instructions, events)
    balances_before = ledger.balances()
    valid = True
    try:
        proposal = Proposal.model_validate(payload["proposal"])
        expected = Proposal.model_validate(payload["expected_proposal"])

        def signature(entry):
            return entry.model_dump(exclude={"ts", "actor"})

        if not proposal.entries or [signature(e) for e in proposal.entries] != [
            signature(e) for e in expected.entries
        ]:
            raise ValueError("Proposal must exactly restore the affected instruction effects")
        for entry in proposal.entries:
            if entry.kind != "compensation":
                raise ValueError("Proposal can only append compensation")
            ledger.append(entry)
    except (ValueError, TypeError, KeyError):
        valid = False
    after = inspect(ledger, instructions, events)
    return SandboxReport(
        passed=valid and all(check.passed for check in after.checks),
        checks_before=before.checks, checks_after=after.checks,
        balances_before=balances_before, balances_after=ledger.balances(), ts=utcnow(),
    ).model_dump(mode="json", by_alias=True)


if __name__ == "__main__":
    with open(sys.argv[1]) as source:
        print(json.dumps(validate(json.load(source))))
