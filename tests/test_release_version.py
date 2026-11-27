from tools.check_version import check_rules, current_version


def test_release_metadata_is_consistent():
    versions = current_version()
    assert all(versions.values()), versions
    assert len(set(versions.values())) == 1, versions
    assert check_rules(next(iter(versions.values()))) == []
