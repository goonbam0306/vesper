from vesper.fallbacks import FallbackFingerprint, FallbackRecord, CandidateBuilder


def test_fallback_fingerprint_matches_structure_not_label():
    a = FallbackRecord("a", "English label", ("analyze",), ("text",), ("text",), ("read",), ("accuracy",), ("read",))
    b = FallbackRecord("b", "다른 이름", ("analyze",), ("text",), ("text",), ("read",), ("accuracy",), ("read",))
    c = FallbackRecord("c", "unrelated", ("generate",), ("image",), ("image",), (), ("style",), ())
    assert FallbackFingerprint.from_record(a).similarity(FallbackFingerprint.from_record(b)) == 1.0
    assert FallbackFingerprint.from_record(a).similarity(FallbackFingerprint.from_record(c)) < 1.0


def test_candidate_requires_stable_cluster_and_remains_unactivated():
    records = [FallbackRecord(str(i), "label", ("analyze",), ("text",), ("text",), ("read",), ("accuracy",), ("read",)) for i in range(3)]
    candidate = CandidateBuilder().build(records)
    assert candidate.recommended_abstraction == "SKILL"
    assert candidate.activation_status == "PENDING_DIRECTOR_APPROVAL"
    assert len(candidate.supporting_fallback_ids) == 3
