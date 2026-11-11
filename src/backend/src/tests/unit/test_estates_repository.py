"""EstatesRepository: estates with export/import policies stored in the database (#146)."""
from src.db_models.estates import EstateDb, SharingPolicyDb, SharingRuleDb
from src.models.estate import Estate, SharingPolicy, SharingRule
from src.repositories.estates_repository import estates_repo


def _estate(name="US Production", **overrides):
    data = dict(
        name=name,
        description="Primary workspace",
        workspace_url="https://us.cloud.databricks.com",
        cloud_type="aws",
        metastore_name="us_prod",
        export_policies=[
            SharingPolicy(
                name="Active products",
                resource_type="data_product",
                rules=[
                    SharingRule(filter_type="status", operator="equals", filter_value="active"),
                    SharingRule(filter_type="domain", operator="equals", filter_value="Finance"),
                ],
            )
        ],
        import_policies=[
            SharingPolicy(name="All contracts", resource_type="data_contract", rules=[]),
        ],
    )
    data.update(overrides)
    return Estate(**data)


def _save(db, estate):
    row = estates_repo.apply(db, EstateDb(), estate)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_apply_stores_the_estate_its_policies_and_rules(db_session):
    row = _save(db_session, _estate())

    stored = estates_repo.get(db_session, row.id)
    assert stored.name == "US Production"
    assert stored.cloud_type == "aws"
    assert [(p.direction, p.name, p.resource_type) for p in stored.policies] == [
        ("export", "Active products", "data_product"),
        ("import", "All contracts", "data_contract"),
    ]
    assert [(r.filter_type, r.operator, r.filter_value) for r in stored.policies[0].rules] == [
        ("status", "equals", "active"),
        ("domain", "equals", "Finance"),
    ]


def test_apply_keeps_the_id_of_a_policy_that_stays(db_session):
    row = _save(db_session, _estate())
    export_id = next(p.id for p in row.policies if p.direction == "export")

    edited = _estate(
        export_policies=[
            SharingPolicy(id=export_id, name="Renamed", resource_type="data_product", rules=[]),
            SharingPolicy(name="Terms", resource_type="business_term", rules=[]),
        ],
        import_policies=[],
    )
    estates_repo.apply(db_session, row, edited)
    db_session.commit()
    db_session.refresh(row)

    assert [(p.id == export_id, p.name, p.position) for p in row.policies] == [
        (True, "Renamed", 0),
        (False, "Terms", 1),
    ]
    # The removed import policy and the replaced rules are gone from the tables.
    assert db_session.query(SharingPolicyDb).count() == 2
    assert db_session.query(SharingRuleDb).count() == 0


def test_an_unknown_policy_id_gets_a_new_row(db_session):
    row = _save(db_session, _estate(
        export_policies=[SharingPolicy(id="client-made-id", name="X", resource_type="concept")],
        import_policies=[],
    ))
    assert row.policies[0].id != "client-made-id"


def test_list_all_is_sorted_by_name_and_get_by_name_finds_one(db_session):
    _save(db_session, _estate(name="b-estate"))
    _save(db_session, _estate(name="a-estate"))

    assert [e.name for e in estates_repo.list_all(db_session)] == ["a-estate", "b-estate"]
    assert estates_repo.get_by_name(db_session, "b-estate").name == "b-estate"
    assert estates_repo.get_by_name(db_session, "missing") is None


def test_deleting_an_estate_deletes_its_policies_and_rules(db_session):
    row = _save(db_session, _estate())
    db_session.delete(row)
    db_session.commit()

    assert db_session.query(EstateDb).count() == 0
    assert db_session.query(SharingPolicyDb).count() == 0
    assert db_session.query(SharingRuleDb).count() == 0
