"""The 8 application states and the offer statuses tracked inside APPROVED."""

from enum import StrEnum


class AppState(StrEnum):
    DRAFT = "DRAFT"
    KYC_PENDING = "KYC_PENDING"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    APPROVED = "APPROVED"
    REFERRED = "REFERRED"
    DECLINED = "DECLINED"
    DISBURSED = "DISBURSED"
    EXPIRED = "EXPIRED"


TERMINAL_STATES: frozenset[AppState] = frozenset(
    {AppState.DECLINED, AppState.DISBURSED, AppState.EXPIRED}
)
ACTIVE_STATES: frozenset[AppState] = frozenset(AppState) - TERMINAL_STATES

# Exactly the transitions in docs/STATE_MACHINE.md §3. Anything else is illegal.
ALLOWED_TRANSITIONS: dict[AppState, frozenset[AppState]] = {
    AppState.DRAFT: frozenset({AppState.KYC_PENDING, AppState.EXPIRED}),
    AppState.KYC_PENDING: frozenset({AppState.UNDER_ASSESSMENT, AppState.EXPIRED}),
    AppState.UNDER_ASSESSMENT: frozenset(
        {AppState.APPROVED, AppState.REFERRED, AppState.DECLINED}
    ),
    AppState.REFERRED: frozenset({AppState.APPROVED, AppState.DECLINED}),
    AppState.APPROVED: frozenset({AppState.DISBURSED, AppState.EXPIRED}),
    AppState.DECLINED: frozenset(),
    AppState.DISBURSED: frozenset(),
    AppState.EXPIRED: frozenset(),
}


class OfferStatus(StrEnum):
    GENERATED = "GENERATED"
    ACCEPTED = "ACCEPTED"
    ESIGNED = "ESIGNED"
    EXPIRED = "EXPIRED"


OFFER_TRANSITIONS: dict[OfferStatus, frozenset[OfferStatus]] = {
    OfferStatus.GENERATED: frozenset({OfferStatus.ACCEPTED, OfferStatus.EXPIRED}),
    OfferStatus.ACCEPTED: frozenset({OfferStatus.ESIGNED, OfferStatus.EXPIRED}),
    OfferStatus.ESIGNED: frozenset(),
    OfferStatus.EXPIRED: frozenset(),
}


class EventType(StrEnum):
    STATE_CHANGE = "STATE_CHANGE"
    OFFER_STATUS = "OFFER_STATUS"
    FRAUD_CHECK = "FRAUD_CHECK"
    NOTE = "NOTE"
