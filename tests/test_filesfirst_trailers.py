from metatron.filesfirst.trailers import parse_trailers


def test_parses_all_three_kinds():
    body = (
        "Implement server-side refresh.\n\n"
        "Decisions-Applied: token-refresh-strategy, auth-session-ttl\n"
        "Decisions-Considered: rate-limit-policy\n"
        "Decisions-Violated: legacy-retry-policy\n"
    )
    t = parse_trailers(body)
    assert t.applied == ["token-refresh-strategy", "auth-session-ttl"]
    assert t.considered == ["rate-limit-policy"]
    assert t.violated == ["legacy-retry-policy"]


def test_no_trailers_is_empty():
    t = parse_trailers("just a normal commit message\n")
    assert t.applied == [] and t.considered == [] and t.violated == []


def test_key_match_is_case_insensitive_and_trims():
    t = parse_trailers("decisions-applied:   a ,b,  c \n")
    assert t.applied == ["a", "b", "c"]


def test_blank_values_ignored():
    t = parse_trailers("Decisions-Applied: , ,\n")
    assert t.applied == []
