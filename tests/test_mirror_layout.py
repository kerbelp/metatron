from pathlib import Path
from metatron.models import Decision, Origin, Status
from metatron.mirror.layout import slug_for, path_for, status_for_path


def _d(status, pattern="Use zod at API boundaries"):
    return Decision(repo="r", pattern=pattern, scope="web/api", rationale="x",
                    origin=Origin.HUMAN, status=status)


def test_slug_is_stable_and_id_based():
    d = _d(Status.CANDIDATE)
    assert slug_for(d) == slug_for(d.model_copy(update={"pattern": "totally different"}))


def test_path_reflects_status_directory():
    assert path_for(_d(Status.CANDIDATE)).parent.name == "candidate"
    assert path_for(_d(Status.CANONICAL)).parent.name == "decisions"


def test_status_for_path_maps_directory():
    assert status_for_path(Path("metatron/candidate/x.md")) == Status.CANDIDATE
    assert status_for_path(Path("metatron/decisions/x.md")) == Status.CANONICAL
