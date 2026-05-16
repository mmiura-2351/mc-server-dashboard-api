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

## 4. リリース手順

リリースは原則メンテナ (admin 権限保持者) が以下の手順で実施する。

1. **次バージョンを決定**
   - 直近 `[Unreleased]` セクションの変更内容を確認し SemVer ルールに照らしてバンプ種別を選ぶ
2. **リリース PR を作成**
   - ブランチ: `release/vX.Y.Z`
   - `pyproject.toml` の `version` を更新
   - `uv lock` を再生成
   - `CHANGELOG.md`: `[Unreleased]` を `[X.Y.Z] - YYYY-MM-DD` に rename、新しい `[Unreleased]` を追加
   - PR タイトル: `release: vX.Y.Z`
3. **PR レビュー → マージ**
   - CI green を確認し squash merge (リポジトリ既定)
4. **タグ作成・push**
   ```bash
   git checkout master
   git pull
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```
5. **GitHub Release を発行**
   ```bash
   gh release create vX.Y.Z \
       --title "vX.Y.Z" \
       --notes-file <(awk '/^## \[X\.Y\.Z\]/{flag=1;next} /^## \[/{flag=0} flag' CHANGELOG.md)
   ```
   または GitHub Web UI から `vX.Y.Z` タグを選択し、CHANGELOG 該当セクションを本文に貼り付けて発行

## 5. ホットフィックス

本番に出ているリリースの致命的バグに対しては、master からの通常フローではなく
タグから分岐したホットフィックス運用も可能。

```bash
git checkout -b hotfix/vX.Y.Z+1 vX.Y.Z
# 修正をコミット
# 上記 §4 の手順に沿ってリリース
git checkout master
git merge --no-ff hotfix/vX.Y.Z+1
```

## 6. スコープ外 (将来 Issue で扱う)

- `/version` エンドポイントの追加
- タグ push をトリガーとした GitHub Actions による Release 自動生成
- CHANGELOG 自動生成 (commit メッセージや PR ラベルからの生成)
