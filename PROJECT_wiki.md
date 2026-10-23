# PROJECT_wiki：JellyPlex-Watched

> 从 https://github.com/luigi311/JellyPlex-Watched 克隆，版本 8.5.3。
> 本文件记录项目结构、核心机制，以及对上游做的本地改动。

## 1. 项目是什么

在 Jellyfin / Emby / Plex 之间双向同步多个用户的「已观看」和「观看进度」。
纯本地运行，通过各服务器的 HTTP API 读写，不依赖任何中间服务。

- 语言/依赖管理：Python >= 3.12 + uv（`pyproject.toml` + `uv.lock`）
- 入口：`main.py`，逻辑在 `src/`
- 配置：复制 `sample.config.yaml` 为 `config.yaml`

## 2. 核心数据流

```
get_libraries()                 发现各服务器上的库（名称 -> 类型）
    ↓
combine_library_lists()         按名称/规则决定哪些库互相同步
    ↓
get_watched()                   拉取每个用户在每个库里的已观看/进度
    ↓
sync_inventory / sync_plan      比对两端差异，生成写入计划（含中继路径）
    ↓
update_watched()                把计划写回目标服务器
```

关键数据模型在 `src/watched.py`：

- `MediaIdentifiers`：条目身份（文件名 locations + imdb/tvdb/tmdb + 别名）
- `MediaItem`：一个条目 + 其观看状态
- `LibraryData`：**只有 `movies` 和 `series` 两个容器**（二分模型）
- `UserData`：某个用户在所有库的数据

## 3. 匹配机制（`src/watched.py:573` media_identifier_keys）

两个条目只要满足以下任一条件即视为同一个：

1. **文件名相同**——`("location", basename)`，来自 `src/functions.py:159`
   `filename_from_any_path()`，只取路径最后一段，**目录结构不参与匹配**，
   且能自动识别 Windows/UNC/Linux 两种路径写法。
2. **provider id 相同**——imdb / tvdb / tmdb 之一。

注意：文件名匹配**大小写敏感、扩展名必须一致**，未做归一化。

相关开关（`src/settings.py:709-710`，默认都开）：

- `generate_guids: bool = True`
- `generate_locations: bool = True`

## 4. 本次本地改动：支持家庭视频库（Home Videos）

上游只认 movie / tvshow，家庭视频库在第一步就被丢弃。已做如下改造。

### 4.1 Jellyfin / Emby 侧（`src/jellyfin_emby.py`）

新增模块级常量：

- `SUPPORTED_LIBRARY_TYPES = ("movies", "tvshows", "homevideos")`
- `ITEM_TYPE_TO_LIBRARY_TYPE = {"Movie": "movies", "Episode": "tvshows", "Video": "homevideos"}`

改动点：

1. `get_user_libraries()`：库类型白名单放行 `homevideos`；
   库未声明 `CollectionType` 时，抽样条目类型推断，新增 `Video -> homevideos`。
   照片（`Photo`）不在映射表里，因此**图文混排的库仍会被判定为 homevideos**（照片本身不会被当作视频拉取）。
2. `get_user_library_watched()`：`Literal` 增加 `homevideos`；电影库与家庭视频库
   共用扁平影片流程，只是查询的 `IncludeItemTypes` 分别为 `Movie` / `Video`。
3. `get_watched()`：放行 `homevideos`，并把库类型原样传给上一步（原来只传 movies/tvshows）。
4. `update_user_watched()`：写入前搜索条目时改为
   `IncludeItemTypes=Movie,Video`，这样「家庭视频库 <-> 电影库」跨类型互相同步也能命中。

### 4.2 Plex 侧（`src/plex.py`）：无需改动

已验证 plexapi 4.18.1 只有四种库类型：`movie` / `show` / `artist` / `photo`。
Plex 的「其他视频 / 家庭视频」库上报的 type 就是 `movie`，走原有电影分支即可；
拉取、匹配（`markWatched()`、guids、locations）全部通用。

### 4.3 配置（`sample.config.yaml`）

`whitelist_library_types` 增加 `"homevideos"`。
**这是必需项**：模板里的白名单会同时校验源库和目标库类型，不加这一项，
照抄模板的用户即使代码已支持也会被过滤掉。

### 4.4 列表型配置在环境变量里怎么写（Docker 场景）

配置源优先级（高 -> 低），见 `src/settings.py:1511`：

```
JPW_ 前缀环境变量  >  .env(JPW_ 前缀)  >  legacy 环境变量  >  config.yaml  >  secrets
```

`whitelist_library_types` 是列表，以下三种写法实测均可（已验证生效）：

| 写法 | 示例 |
| --- | --- |
| config.yaml | `whitelist_library_types:` 换行 `- "movie"` ... |
| legacy 环境变量（逗号分隔） | `WHITELIST_LIBRARY_TYPE=movie,show,movies,tvshows,homevideos` |
| JPW_ 前缀（JSON 数组） | `JPW_WHITELIST_LIBRARY_TYPES=["movie","show","homevideos"]` |

两个坑：

1. legacy 变量名是**单数** `WHITELIST_LIBRARY_TYPE`，不是 `..._TYPES`。
2. 环境变量会**覆盖** config.yaml 的同名配置，两边都写时以环境变量为准。

**最省事的做法是干脆不配白名单**：白名单为空时 `is_library_type_allowed()`
直接放行所有类型，家庭视频自动生效。只有照抄了 `sample.config.yaml`
（它默认带白名单）才需要补 `homevideos`。

### 4.5 CI / 镜像发布改为本仓库 GHCR（`.github/workflows/ci.yml`）

上游只往 `luigi311` 名下的 GHCR 和 DockerHub 推镜像，fork 后跑 CI 不会有任何产出。
已改为推送到 `ghcr.io/qian9008/jellyplex-watched`：

1. `docker` job 增加 `permissions: contents: read, packages: write`
   —— 默认 `GITHUB_TOKEN` 只有读权限，不加这段推送必然 403。
2. `docker/metadata-action` 的 `images` 只保留 GHCR，且镜像名写全小写。
   GHCR 不接受大写仓库名，`${{ github.repository }}`（含 `JellyPlex-Watched`）
   会导致 reference 非法，因此用 `github.repository_owner` + 小写包名。
3. 删除 DockerHub 登录步骤（没有对应 secrets，留着只会静默跳过）。
4. `Build Push` 的 `push` 条件改为只看 `steps.ghcr_login.outcome`。

触发与标签：push 到非 PR 事件即构建推送；`latest` 标签只在打 git tag 时生成
（`flavor: latest=false` + `type=raw,value=latest,enable=${{ startsWith(github.ref, 'refs/tags/') }}`），
普通 push 得到的是分支名 / sha 标签。`alpine` 是默认变体，拿不带后缀的标签。

构建平台已设为 `linux/amd64`（仅 x86_64）：arm64 在 amd64 runner 上要靠 QEMU
模拟，慢十倍以上。需要 arm64 时把 `Build Push` 步骤的 `platforms` 改回
`linux/amd64,linux/arm64` 即可，其余不用动。

### 4.6 日志输出适配中文环境

三处改动，解决中文库名/用户名在日志里不可读的问题：

1. `src/functions.py` 的 `formatter()`：`json.dumps` 增加 `ensure_ascii=False`。
   这是**最主要的一项**——之前中文会被转义成 `\u5bb6\u5ead...`，日志完全没法读。
2. `src/functions.py` 的 `configure_logger()`：日志文件 sink 增加
   `encoding="utf-8"`。loguru 默认按 locale 编码写文件，容器里 locale 多为
   C/POSIX，写中文会直接 `UnicodeEncodeError`。
3. `Dockerfile.alpine` / `Dockerfile.slim`：增加 `PYTHONUTF8=1` 与
   `PYTHONIOENCODING=utf-8`，保证控制台（`docker logs`）输出中文正常。

注意：`src/functions.py` 原本是 **CRLF/LF 混合行尾**，用编辑器整体重写会让
diff 变成整个文件、后续同步上游全是冲突。改动时必须保留原有行尾，
只替换目标片段（本次用了 `/tmp/patch_functions.py` 这类原子化脚本）。

### 4.7 测试（`test/test_home_videos.py`，新增 5 例）

覆盖：声明式 homevideos 库识别、无 CollectionType 时靠 Video 条目推断、
纯照片库仍被排除、家庭视频库查询用 Video、电影库仍用 Movie（防回归）。

全量测试：323 passed。

### 4.8 修复启动报错 `has duplicate alias`

现象（容器启动即退出）：

```
Startup error: configuration validation failed: configuration: Value error,
user_mappings[xxx] has duplicate alias (jellyfin-main, xxx).
```

成因：`src/settings.py` 的 `_validate_alias_ownership()` 规定，同一个
canonical 下不能出现两次相同的 `(server, 名称)`（名称按 `casefold` 比较）。
但 legacy `USER_MAPPING` 的迁移逻辑（`legacy_settings._build_legacy_mappings`）
会把一对名字的**左右两个都**注册到**每一台**服务器上；当左右名字相同时
（例如 `USER_MAPPING={"xxx": "xxx"}`），同一台服务器上就注册了两次，
于是迁移生成的 config.yaml 自己就过不了校验——属于上游 bug。

修复（两处）：

1. `src/settings.py`：`UserMapping` / `LibraryMapping` 增加 after 校验器，
   丢弃重复的 `(server, 名称)` 别名并打警告，不再直接拒绝配置。
   跨 canonical 抢占同一身份（两个 canonical 声明同一个 `(server, 名称)`）
   仍然报错，那是真冲突。
2. `src/legacy_settings.py`：`_build_legacy_mappings` 生成别名时按
   `(server, casefold(name))` 去重，迁移产出的 config.yaml 本身就是干净的。

配套测试 `test/test_alias_dedupe.py`（6 例）。全量测试：329 passed。

补充：如果两端用户名本来相同，**根本不需要写 user_mappings**——同步引擎会
按同名自动匹配，直接删掉这段配置即可。

## 5. 已知限制

- 家庭视频没有 provider id，只能靠文件名匹配，两端文件名必须逐字符一致
  （含大小写与扩展名）。同库内若存在同名不同内容的文件（如不同年份目录下的
  `IMG_1234.mp4`），会被误判为同一条目——当前未做目录/大小辅助判定。
- Jellyfin 的 `mixed`（电影+剧集混合）库仍不支持。
- 照片、音乐库始终排除。

## 6. 常用命令

```bash
uv sync                 # 安装依赖（含 dev 组）
uv run pytest test/ -q  # 跑测试
uv run python main.py   # 正式运行；加 --dry-run 可只看计划不写入
```
