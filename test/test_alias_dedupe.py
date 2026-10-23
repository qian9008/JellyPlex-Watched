"""重复别名的处理。

同一个 canonical 下出现两次相同的 (server, 名称) 是冗余信息，不构成冲突：
legacy USER_MAPPING / LIBRARY_MAPPING 在左右两个名字相同时（比如
{"alice": "alice"}）必然生成这种重复，迁移出来的 config.yaml 若被拒绝就
完全不可用。所以重复项应当被丢弃并给出警告。

真正需要拒绝的是另一个 canonical 抢同一个 (server, 名称)，那才是身份冲突。
"""

from __future__ import annotations

import pytest

from src.legacy_settings import _build_legacy_mappings
from src.settings import AppSettings

from conftest import settings_override


def test_duplicate_user_alias_is_dropped() -> None:
    settings = settings_override(
        user_mappings=[
            {
                "canonical": "xxx",
                "aliases": [
                    {"server": "jellyfin-main", "username": "xxx"},
                    {"server": "jellyfin-main", "username": "xxx"},
                    {"server": "plex-main", "username": "xxx"},
                ],
            }
        ]
    )

    aliases = [
        (alias.server, alias.username)
        for alias in settings.user_mappings[0].aliases
    ]
    assert aliases == [("jellyfin-main", "xxx"), ("plex-main", "xxx")]


def test_duplicate_alias_ignoring_case_is_dropped() -> None:
    """大小写不同也算重复：匹配用的是 casefold 后的名字。"""

    settings = settings_override(
        user_mappings=[
            {
                "canonical": "xxx",
                "aliases": [
                    {"server": "jellyfin-main", "username": "xxx"},
                    {"server": "jellyfin-main", "username": "XXX"},
                ],
            }
        ]
    )

    assert len(settings.user_mappings[0].aliases) == 1


def test_duplicate_library_alias_is_dropped() -> None:
    settings = settings_override(
        library_mappings=[
            {
                "canonical": "movies",
                "aliases": [
                    {"server": "jellyfin-main", "library": "电影"},
                    {"server": "jellyfin-main", "library": "电影"},
                ],
            }
        ]
    )

    assert len(settings.library_mappings[0].aliases) == 1


def test_same_alias_on_two_canonicals_still_rejected() -> None:
    """两个 canonical 抢同一个身份仍然报错，这是真冲突。"""

    with pytest.raises(ValueError, match="claimed by both"):
        settings_override(
            user_mappings=[
                {
                    "canonical": "alice",
                    "aliases": [
                        {"server": "jellyfin-main", "username": "shared"},
                    ],
                },
                {
                    "canonical": "bob",
                    "aliases": [
                        {"server": "jellyfin-main", "username": "shared"},
                    ],
                },
            ]
        )


def test_legacy_mapping_with_equal_names_has_no_duplicates() -> None:
    """legacy USER_MAPPING={"xxx": "xxx"} 迁移后不应产生重复别名。"""

    mappings = _build_legacy_mappings(
        {"xxx": "xxx"}, ["jellyfin-main", "plex-main"], "username"
    )

    assert mappings[0]["aliases"] == [
        {"server": "jellyfin-main", "username": "xxx"},
        {"server": "plex-main", "username": "xxx"},
    ]


def test_legacy_mapping_with_equal_names_loads() -> None:
    """端到端：迁移生成的等价配置必须能通过校验。"""

    mappings = _build_legacy_mappings(
        {"xxx": "xxx"}, ["jellyfin-main", "plex-main"], "username"
    )

    settings = AppSettings(
        plex=[
            {
                "name": "plex-main",
                "baseurl": "http://plex",
                "token": "x",
                "sync_to": ["jellyfin-main"],
            }
        ],
        jellyfin=[
            {
                "name": "jellyfin-main",
                "baseurl": "http://jellyfin",
                "token": "x",
                "sync_to": ["plex-main"],
            }
        ],
        user_mappings=mappings,
    )

    assert len(settings.user_mappings[0].aliases) == 2
