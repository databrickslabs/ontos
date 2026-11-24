"""UUID columns keep their value on the SQLite test database.

The models use the Postgres UUID type. On SQLite a column declared ``UUID``
has NUMERIC affinity, so a uuid4 whose hex is all digits, or digits with one
``e``, was stored as a number and failed to read back. It happened about once
per million ids, often enough to fail an integration run now and then.
"""
import uuid

import pytest
from sqlalchemy import text

from src.db_models.rdf_triples import RdfTripleDb

# Both are valid uuid4 values; the second hex reads as a float exponent
NUMERIC_LOOKING = [
    uuid.UUID("05461699073647498402143133845537"),
    uuid.UUID("872587e7965249158168734135567462"),
]


@pytest.mark.parametrize("triple_id", NUMERIC_LOOKING)
def test_a_numeric_looking_uuid_reads_back(db_session, triple_id):
    db_session.add(RdfTripleDb(
        id=triple_id, subject_uri="urn:s", predicate_uri="urn:p", object_value="o",
    ))
    db_session.flush()
    db_session.expire_all()

    stored = db_session.execute(
        text("SELECT typeof(id) FROM rdf_triples WHERE subject_uri = 'urn:s'")
    ).scalar()
    assert stored == "text"
    assert db_session.query(RdfTripleDb.id).filter_by(subject_uri="urn:s").scalar() == triple_id
