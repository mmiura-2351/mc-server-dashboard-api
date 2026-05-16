# リリース運用ガイド

本ドキュメントは `mc-server-dashboard-api` のバージョニング規約とリリース手順を定める。
親 Issue: #183 / ロードマップ: #188 (Phase 3)

## 1. バージョニング規約 (SemVer)

バージョンは [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) に準拠し、
`MAJOR.MINOR.PATCH` の三要素で表記する。

| 区分 | 意味 | 例 |
|---|---|---|
| MAJOR | 後方互換を破壊する変更 | `1.0.0` → `2.0.0` |
| MINOR | 後方互換のある機能追加 | `1.2.0` → `1.3.0` |
| PATCH | 後方互換のあるバグ修正 | `1.2.3` → `1.2.4` |

### 1.1 `0.x.y` 期間の扱い

SemVer 仕様どおり `0.x.y` 期間は公開 API が不安定として扱う。本プロジェクトでは以下の運用とする。

- **後方互換を破壊する変更**: MINOR を上げる (`0.1.0` → `0.2.0`)
- **機能追加・互換のあるバグ修正**: PATCH を上げる (`0.1.0` → `0.1.1`)
- `1.0.0` 到達のタイミングは別途決定する (API が安定し本番運用に耐えると判断したとき)

### 1.2 Pre-release

リリース候補は `vX.Y.Z-rc.N` の形式で発行する (例: `v0.2.0-rc.1`)。
その他の suffix (`-alpha.N`, `-beta.N`) は原則使用しない。

### 1.3 タグ命名規約

- リリースタグは `vX.Y.Z` (先頭 `v` を必須とする)
- pre-release: `vX.Y.Z-rc.N`
- ローカル検証用タグなど、公式リリース以外には `v` プレフィックスを付けない

## 2. バージョンの単一真実源

`pyproject.toml` の `[project].version` を単一の真実源とする。

- Python コードからの参照は `app.__version__` (内部で
  `importlib.metadata.version("mc-server-dashboard-api")` を呼び出す) を経由する
- FastAPI アプリは `FastAPI(version=__version__)` を渡し、OpenAPI スキーマに反映する
- README やドキュメント中にバージョン番号をハードコードしない

## 3. CHANGELOG 運用

形式は [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) に従う。

### 3.1 PR 作成時

- 機能追加・バグ修正・破壊的変更・依存更新など利用者影響のある変更は
  `CHANGELOG.md` の `[Unreleased]` セクションへ追記する
- 該当しない変更 (内部リファクタ、CI 設定、開発体験向上のみなど) は省略可

### 3.2 リリース時

- `[Unreleased]` を `[X.Y.Z] - YYYY-MM-DD` に rename し、新しい空の `[Unreleased]` を直上に追加
- 日付は UTC 基準でリリース PR をマージした日とする

## 4. リリース手順 (tagpr による自動化)

本リポジトリは [tagpr](https://github.com/Songmu/tagpr) によりバージョン bump・タグ付与・
GitHub Release 発行を自動化している (`.github/workflows/tagpr.yml` / `.tagpr`)。

### 4.1 通常リリースの流れ

1. **PR をマージする** (通常の開発フロー)
   - 利用者影響のある変更は `CHANGELOG.md` の `[Unreleased]` に追記しておく
   - 破壊的変更 / 機能追加の場合は PR にラベルを付与
     - `tagpr:major` — MAJOR bump
     - `tagpr:minor` — MINOR bump
     - ラベル無し — PATCH bump (既定)
2. **master への push を tagpr が検知** し、リリース PR (タイトル例: `Release for vX.Y.Z`) を自動作成・更新する
   - `pyproject.toml` の `version` を次バージョンに書き換え
   - `uv lock` を実行して lockfile を同期 (`.tagpr` の `command` 設定)
3. **リリース PR で CHANGELOG を整える** (メンテナ手動)
   - `[Unreleased]` を `[X.Y.Z] - YYYY-MM-DD` に rename し、新しい `[Unreleased]` を直上に追加
   - リリース PR ブランチに直接コミットして push
4. **リリース PR の内容を確認**
   - `pyproject.toml` の `version` 行のみが書き換わっていること
   - `uv.lock` が同期更新されていること
   - 上記以外の意図しない変更が混入していないこと
5. **リリース PR をマージ** (squash merge)
   - マージ後 tagpr が自動で `vX.Y.Z` タグ作成・push と GitHub Release 発行を行う

### 4.2 リリース PR には CI が走らないことに注意

GitHub の仕様上、`GITHUB_TOKEN` を用いて作成された PR (= tagpr が作成するリリース PR) は
他の workflow をトリガしない。すなわち **リリース PR には `ci.yaml` の lint / format / test が走らない**。

対策:

- **§4.1 の手順 4 で diff を必ず目視確認する** (`pyproject.toml` + `uv.lock` + CHANGELOG 以外の変更が無いことを確認)
- CI を回したい場合は、リリース PR のブランチに対して以下で手動起動できる:
  ```bash
  gh workflow run ci.yaml --ref <release-pr-branch-name>
  ```
- 恒久対策として PAT / GitHub App トークンへの切り替えを将来検討 (別 Issue で扱う)

### 4.3 リポジトリ設定 (一度きり)

tagpr が PR を作成できるよう、以下の設定を確認する。

- Settings → Actions → General → Workflow permissions:
  - **Allow GitHub Actions to create and approve pull requests** を ON

### 4.4 Dependabot PR の扱い

tagpr は Dependabot 作成 PR をデフォルトでバージョン bump 対象から除外する。
依存更新のみが master に積まれている期間はリリース PR が作られない (= 依存更新だけでは
新しいバージョンを切らない方針)。依存更新もリリースに含めたい場合は、利用者影響のある
通常 PR を 1 件マージするか、Dependabot PR マージ後に master へ意味のあるコミットを
別途積む運用とする (なお tagpr の patch bump はラベル無しが既定動作であり、明示ラベルは不要)。

## 5. 手動リリース手順 (フォールバック)

tagpr の停止時・初回リリース・例外対応時には以下の手動手順を用いる。

1. ブランチ `release/vX.Y.Z` を作成
2. `pyproject.toml` の `version` を更新、`uv lock` を再実行
3. `CHANGELOG.md`: `[Unreleased]` を `[X.Y.Z] - YYYY-MM-DD` に rename、新しい `[Unreleased]` を追加
4. PR を作成 (タイトル: `release: vX.Y.Z`)、レビュー後 squash merge
5. タグ作成・push:
   ```bash
   git checkout master && git pull
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```
6. GitHub Release 発行:
   ```bash
   gh release create vX.Y.Z --title "vX.Y.Z" \
       --notes-file <(awk '/^## \[X\.Y\.Z\]/{flag=1;next} /^## \[/{flag=0} flag' CHANGELOG.md)
   ```

## 6. ホットフィックス

本番に出ているリリースの致命的バグに対しては、master からの通常フローではなく
タグから分岐したホットフィックス運用も可能。

```bash
git checkout -b hotfix/vX.Y.Z+1 vX.Y.Z
# 修正をコミット
# 上記 §5 の手動手順に沿ってリリース (tagpr の自動化はホットフィックス用途を想定していない)
git checkout master
git merge --no-ff hotfix/vX.Y.Z+1
```

## 7. スコープ外 (将来 Issue で扱う)

- `/version` エンドポイントの追加
- CHANGELOG 自動生成 (tagpr の `changelog = true` 機能の利用、または PR ラベルからの生成)
