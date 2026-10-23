"""家庭视频库（Home Videos）支持的回归测试。

只覆盖 Jellyfin/Emby 侧：Plex 的“其他视频”库在 plexapi 里上报的 type 就是
movie，走的是原有电影库代码路径，无需额外分支。

三件事必须始终成立：
1. homevideos 库能被识别出来（声明了 CollectionType 或靠条目类型推断出来）；
2. 读取这类库时查询的是 Video 条目，而不是 Movie；
3. 照片库、音乐库这类依旧被排除，电影/剧集库行为不变。
"""

from __future__ import annotations

from typing import Any

from src.jellyfin_emby import JellyfinEmby

from conftest import settings_override


def _make_client() -> JellyfinEmby:
    """构造一个不联网的 JellyfinEmby。

    __init__ 会立即拉取用户列表和服务器版本，单测里用 __new__ 绕开它，
    只填后续方法真正用到的属性。
    """
    client = object.__new__(JellyfinEmby)
    client.app_settings = settings_override()
    client.server_type = "Jellyfin"
    client.server_name = "jellyfin-main"
    client.users = {"user": "user-id"}
    return client


def _views_response(
    name: str = "家庭视频", collection_type: str | None = "homevideos"
) -> dict[str, Any]:
    library: dict[str, Any] = {"Id": "lib-1", "Name": name}
    if collection_type is not None:
        library["CollectionType"] = collection_type
    return {"Items": [library]}


def test_declared_homevideos_library_is_discovered(monkeypatch) -> None:
    client = _make_client()
    monkeypatch.setattr(
        client, "query", lambda *args, **kwargs: _views_response()
    )

    assert client.get_user_libraries(("user", "user-id")) == {"家庭视频": "homevideos"}


def test_untyped_library_inferred_from_video_items(monkeypatch) -> None:
    """库没声明 CollectionType 时，靠抽样条目推断：Video -> homevideos。

    家庭视频库常混入照片，所以这里同时返回 Photo，确认不影响推断。
    """

    def fake_query(query: str, *args, **kwargs) -> dict[str, Any]:
        if "Views" in query:
            return _views_response(collection_type=None)
        return {"Items": [{"Type": "Video"}, {"Type": "Photo"}]}

    client = _make_client()
    monkeypatch.setattr(client, "query", fake_query)

    assert client.get_user_libraries(("user", "user-id")) == {"家庭视频": "homevideos"}


def test_photo_only_library_still_skipped(monkeypatch) -> None:
    """纯照片库不能因为放开家庭视频而被误纳入。"""

    def fake_query(query: str, *args, **kwargs) -> dict[str, Any]:
        if "Views" in query:
            return _views_response(name="照片", collection_type="photos")
        return {"Items": [{"Type": "Photo"}]}

    client = _make_client()
    monkeypatch.setattr(client, "query", fake_query)

    assert client.get_user_libraries(("user", "user-id")) == {}


def test_homevideos_watched_query_uses_video_item_type(monkeypatch) -> None:
    """读取家庭视频库时必须查 Video 条目，查 Movie 会一无所获。"""
    calls: list[str] = []

    def fake_query(query: str, *args, **kwargs) -> dict[str, Any]:
        calls.append(query)
        return {"Items": []}

    client = _make_client()
    monkeypatch.setattr(client, "query", fake_query)

    client.get_user_library_watched(
        "user", "user-id", "homevideos", "lib-1", "家庭视频"
    )

    video_queries = [call for call in calls if "IncludeItemTypes=Video" in call]
    assert video_queries, f"未发出 Video 查询，实际请求：{calls}"
    assert not [call for call in calls if "IncludeItemTypes=Movie" in call]


def test_movies_library_still_queries_movie_item_type(monkeypatch) -> None:
    """电影库行为不变，仍然查 Movie。"""
    calls: list[str] = []

    def fake_query(query: str, *args, **kwargs) -> dict[str, Any]:
        calls.append(query)
        return {"Items": []}

    client = _make_client()
    monkeypatch.setattr(client, "query", fake_query)

    client.get_user_library_watched("user", "user-id", "movies", "lib-1", "电影")

    assert [call for call in calls if "IncludeItemTypes=Movie" in call]
    assert not [call for call in calls if "IncludeItemTypes=Video" in call]
