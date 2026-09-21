# Hand-authored feature — not compiled from adcp-req.
#
# LOCALLY-ADDED (survives BR-*.feature regeneration).
#
# SUBJECT. The buyer's opaque `context` object comes back unchanged on EVERY
# outcome the seller can produce: a success, a refusal by the seller's own
# rules, a schema rejection, a version rejection and an auth rejection. One
# seam reads it off the request and writes it onto whatever leaves, so the
# outcome cannot decide whether the buyer gets its correlation data back.
#
# PINNED AUTHORITY (adcp==6.6.0 -> _schemas/3.1, AdCP 3.1.1 — docs/adcp-spec-version.md).
#   core/protocol-envelope.json .properties.context -> $ref core/context.json,
#   described there as "Per-request opaque caller-supplied correlation object
#   echoed unchanged in the response ... that the agent MUST preserve
#   byte-for-byte without parsing", and "The envelope declaration is
#   authoritative for the schema definition". The envelope is the shape EVERY
#   response uses, success and error alike, so the obligation is not
#   per-outcome.
#   core/context.json is `{"type": "object", "additionalProperties": true}` — a
#   free-form bag with zero declared properties. That is why every scenario
#   below sends a bag with extra keys AND a nested object, and why the Then
#   asserts the WHOLE object came back rather than one field of it: "preserve
#   byte-for-byte" is not graded by checking that correlation_id survived.
#   compliance/universal/error-compliance.yaml: "Context echo is required on
#   error responses - the correlation ID is even more important for error
#   diagnosis than for success cases. Every error response must include the
#   caller's context object unchanged."
#
# UPSTREAM GAP this file fills. The generated features grade the echo on three
# scenarios, all of them BUSINESS errors on update_media_buy
# (BR-UC-003-update-media-buy.feature:2179, :2195, :2212 — "the response should
# echo the context.correlation_id unchanged"). No generated scenario grades it
# on a SCHEMA rejection, a VERSION rejection, an AUTH rejection, or a SUCCESS,
# and those are exactly the outcomes where the seller drops it today. Reconcile
# upstream in adcp-req, then retire this file for the regenerated scenarios.
#
# WHY THE MALFORMED FIELD IS (ALMOST) NEVER `context` ITSELF. A non-object
# context is refused by the request model, and the seller then has no object
# left to echo. The echo scenarios therefore malform some OTHER declared field.
# The one scenario that malforms the context grades the complement: the
# rejection goes out with NO context key, never one the seller invented, and
# the buyer's real fault is not shadowed by the seller's inability to echo.
Feature: The buyer's context object is echoed unchanged on every outcome (local)

  # ── get_products: an auth-optional read, reachable with a tenant alone ──
  # Routed to ProductEnv by the @ctxecho-products tag (tests/bdd/conftest.py).

  @T-CTXECHO-success @context-echo @ctxecho-products
  Scenario: A successful response echoes the buyer's context object unchanged
    Given the buyer's request carries an opaque context object
    And the request names a brief the seller can answer
    When the Buyer Agent sends the get_products request
    Then the response arrives
    And the successful response echoes the buyer's context object unchanged

  @T-CTXECHO-business-error @context-echo @error @ctxecho-products
  Scenario: A refusal by the seller's own rules echoes the buyer's context object unchanged
    # get_products requires at least one search criterion (brief, brand or
    # filters). Sending none is a well-formed document the SELLER's rules
    # refuse — VALIDATION_ERROR, not INVALID_REQUEST — so this grades the
    # outcome that reaches the seam from inside the implementation.
    Given the buyer's request carries an opaque context object
    And the request names no search criterion at all
    When the Buyer Agent sends the get_products request
    Then the response arrives
    And the response contains error code VALIDATION_ERROR
    And the error recovery should be "correctable"
    And the error response echoes the buyer's context object unchanged

  @T-CTXECHO-schema-rejection @context-echo @error @ctxecho-products
  Scenario: A schema rejection echoes the buyer's context object unchanged
    # pin: get-products-request.json .properties.brief.type = "string".
    # An integer there is refused on the bytes' own merits, which the repo's
    # error table (src/core/errors/codes.py, quoting the pinned
    # enums/error-code.json) classifies as INVALID_REQUEST — "malformed".
    Given the buyer's request carries an opaque context object
    And the request carries a brief of the wrong JSON type
    When the Buyer Agent sends the get_products request
    Then the response arrives
    And the response contains error code INVALID_REQUEST
    And the error recovery should be "correctable"
    And the error response echoes the buyer's context object unchanged

  @T-CTXECHO-unmodellable-context @context-echo @error @ctxecho-products
  Scenario: A context that is not an object is dropped from the rejection, not raised over
    # pin: core/context.json is `{"type": "object", ...}`. A string there is
    # refused as INVALID_REQUEST like any other schema violation, and there is
    # nothing to echo: the response carries no context key at all.
    Given the request names a brief the seller can answer
    And the request carries a context that is not an object
    When the Buyer Agent sends the get_products request
    Then the response arrives
    And the response contains error code INVALID_REQUEST
    And the error recovery should be "correctable"
    And the error response carries no context object

  @T-CTXECHO-version-rejection @context-echo @error @ctxecho-products
  Scenario: A version rejection echoes the buyer's context object unchanged
    # The seller speaks a fixed set of releases; a pin outside it is refused
    # with VERSION_UNSUPPORTED. The buyer whose pin was refused still needs its
    # correlation data back to match the refusal to the call it made.
    Given the buyer's request carries an opaque context object
    And the request names a brief the seller can answer
    And the request pins AdCP version "99.0"
    When the Buyer Agent sends the get_products request
    Then the response arrives
    And the response contains error code VERSION_UNSUPPORTED
    And the error recovery should be "correctable"
    And the error response echoes the buyer's context object unchanged

  # ── get_media_buys: a read that REQUIRES a credential ──────────────────
  # Routed to MediaBuyListEnv by the @ctxecho-media-buys tag. The tool is
  # chosen for its auth declaration: get_products is auth-optional, so a
  # token-less caller reaches the implementation and is refused there, which
  # grades a different seam than the one these two scenarios are about.

  @T-CTXECHO-auth-rejection @context-echo @error @auth @ctxecho-media-buys
  Scenario: An auth rejection echoes the buyer's context object unchanged
    Given the buyer's request carries an opaque context object
    And the Buyer has no authentication credentials
    When the Buyer Agent sends the get_media_buys request
    Then the response arrives
    And the response contains error code AUTH_MISSING
    And the error recovery should be "correctable"
    And the error response echoes the buyer's context object unchanged

  @T-CTXECHO-malformed-before-auth @context-echo @error @auth @ctxecho-media-buys
  Scenario: A malformed request from an unauthenticated caller is answered as malformed, and still echoes the context
    # ORDERING. The document is refused for what it IS before the seller asks
    # who sent it, so an unauthenticated caller sending nonsense is told the
    # request is malformed rather than that its credential is missing. The
    # echo obligation holds for that outcome too.
    # pin: get-media-buys-request.json .properties.media_buy_ids.type = "array".
    Given the buyer's request carries an opaque context object
    And the Buyer has no authentication credentials
    And the request carries media_buy_ids of the wrong JSON type
    When the Buyer Agent sends the get_media_buys request
    Then the response arrives
    And the response contains error code INVALID_REQUEST
    And the error recovery should be "correctable"
    And the error response echoes the buyer's context object unchanged
