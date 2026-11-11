"""Gap-triggered dynamic sandbox updates for ShortTrip.

Pipeline (see 报告/06):

    checker says "missing_key_data"
        -> GapDetector builds a DataRequest
        -> Sources fetch external evidence (OSM / Wikipedia / Wikidata / LLM)
        -> Extractor turns evidence into sandbox-schema fields, each anchored
           to a verbatim quote
        -> QualityGate decides accept / quarantine / reject
        -> OverlayStore versions the record
        -> SandboxBus patches every live tool instance so the *existing*
           skills (attractions_select / goto / Is_attractions_correct) see it
        -> the query is re-planned under the new sandbox version
"""
