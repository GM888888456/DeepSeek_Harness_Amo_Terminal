from memory_scope import is_group_umo, private_rows


def test_group_session_is_detected():
    assert is_group_umo("aiocqhttp:GroupMessage:123456")
    assert not is_group_umo("aiocqhttp:FriendMessage:123456")


def test_private_rows_excludes_group_messages_but_keeps_legacy_rows():
    rows = [
        {"umo": "aiocqhttp:FriendMessage:100", "content": "private"},
        {"umo": "aiocqhttp:GroupMessage:200", "content": "group"},
        {"content": "legacy-without-umo"},
    ]
    result = private_rows(rows)
    assert [row["content"] for row in result] == ["private", "legacy-without-umo"]
