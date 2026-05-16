# Dependency Management Policy

このドキュメントは `mc-server-dashboard-api` の依存ライブラリ管理ポリシーを定める。Issue #150 (親) / #161 (B-1) で策定。

## 1. バージョン指定スタイル

`pyproject.toml` に直接記述する依存は、種別に応じて以下のスタイルで統一する。

| 種別 | 指定形式 | 例 |
|---|---|---|
| **直接依存 (アプリ実行時)** | `"name>=X.Y.Z,<NEXT_MAJOR"` | `"fastapi>=0.115.12,<1.0.0"`, `"sqlalchemy>=2.0.41,<3.0.0"` |
| **直接依存 (0.x.y のライブラリ)** | `"name>=X.Y.Z,<X.NEXT_MINOR"` | `"starlette>=0.47.2,<0.48.0"` |
| **開発依存 (lint/test/型/フック)** | `"name>=X.Y.Z"` | `"pytest>=8.4.1"`, `"ruff>=0.11.12"` |
| **間接依存 (推移的)** | `pyproject.toml` に書かない | `uv.lock` に固定される |

### 設計意図

- **直接依存はメジャー上限を付ける**: SemVer 前提でマイナー・パッチ更新を許容しつつ、互換破壊のあるメジャー更新は明示的な PR で扱う
- **0.x.y は破壊的変更がマイナー単位で来る**: SemVer 慣習に従い、`<X.NEXT_MINOR` で上限を切る
- **開発依存に上限は付けない**: 実行時挙動に影響せず、最新のツール改善 (高速化・新機能) を取り込みやすくする
- **間接依存は書かない**: `uv.lock` が真実源、`pyproject.toml` に重複して書くと二重管理になる

## 2. 例外: 完全固定 (`==`) を許容する条件

以下のいずれかに該当する場合のみ `==` での完全固定を許容する。

- セキュリティ要件で正確なバージョン固定が必須 (暗号系ライブラリ等)
- 既知の互換性問題で特定バージョン以外で動作不能
- 上流ライブラリの SemVer 違反でパッチ更新でも破壊が起こる実績がある

固定する場合は、`pyproject.toml` 内の該当行直前にコメントで理由と参照 (Issue/PR/Advisory) を記載する。

```toml
# Pinned: CVE-XXXX-YYYY mitigation requires exact version (Refs: #NNN)
"some-lib==1.2.3",
```

## 3. 依存配置の分類

| グループ | 配置 | 対象 |
|---|---|---|
| `[project].dependencies` | アプリ実行時依存のみ | fastapi, pydantic, sqlalchemy, uvicorn, passlib, python-jose, aiohttp, aiofiles, psutil 等 |
| `[dependency-groups].dev` | 開発・テスト・lint・型・フック | pytest, pytest-asyncio, pytest-xdist, httpx (TestClient用), ruff, mypy, pre-commit, coverage |

### 判定基準

- 「`uv sync` (本番想定) で抜けてもアプリが起動・動作するか」を基準にする
  - 抜けて困る → `dependencies`
  - 抜けても OK → `dev` group
- テストフレームワーク、lint、型チェッカ、TestClient (`httpx`)、フォーマッタは原則 dev group

## 4. ロックファイル (`uv.lock`) の運用

- **唯一の真実源**: 再現性の起点として `uv.lock` を扱う
- master ブランチへのコミット必須
- セットアップ:
  - 本番想定: `uv sync`
  - 開発: `uv sync --group dev`
- 更新方法:
  - パッチ・マイナー一括: `uv lock --upgrade`
  - 個別: `uv lock --upgrade-package <name>`

## 5. セキュリティ更新

| 種別 | 対応方針 |
|---|---|
| GitHub Security Advisory アラート | 受領後 **1 週間以内**にパッチ適用 PR を作成 |
| Dependabot security update PR | **1 営業日以内**にレビューしマージ判断 |
| 既知 CVE のある古いライブラリ | 段階的に置換候補を検討 (Issue #164 B-4 で扱う) |
| 緊急性が高い脆弱性 (RCE 等) | 通常リリースサイクルを待たず hotfix リリースを実施 |

セキュリティ対応は **`dependencies` ラベル + `security` ラベル**を付与する。

### 5.1 サプライチェーン cooldown ポリシー

リリース直後にメンテナアカウント乗っ取り・typosquatting・compromised release が発覚するケースに備え、**リリースから 7 日以内のバージョンは取り込まない**。発覚から修正・撤回までに数日かかるため、7 日のリスク窓を回避することで影響を最小化する。

| ツール | 設定箇所 | 挙動 |
|---|---|---|
| `uv` | `pyproject.toml` の `[tool.uv].exclude-newer = "7 days"` | `uv lock` / `uv lock --upgrade` / `uv add` の解決時に 7 日以内のリリースを除外 (`uv sync` はロック通りに動くため影響なし) |
| Dependabot | `.github/dependabot.yml` の `cooldown` | リリースから `default-days` (= 7)、メジャー更新は `semver-major-days` (= 14) 経過するまで PR を作成しない |

#### Override 手順 (緊急 CVE 対応時)

cooldown を bypass する必要がある場合は以下のいずれかで対応する。Override の理由 (CVE 番号・Advisory リンク) を PR 本文に明記すること。

- **uv (ローカル)**: 特定パッケージのみ cooldown を外して更新する。`--exclude-newer-package` は `PACKAGE=DATE` または `PACKAGE=false` の形式 (`=` 区切り) で指定する。

  ```bash
  # cooldown を完全に無効化して最新版を取り込む
  uv lock --upgrade-package <pkg> --exclude-newer-package <pkg>=false

  # あるいは特定日 (例: CVE Advisory 公開日) を上限に指定する
  uv lock --upgrade-package <pkg> --exclude-newer-package <pkg>=2026-05-15
  ```

- **Dependabot**: GitHub Security Advisory に紐づく **security update** は cooldown を自動で bypass するため、追加設定は不要。手動で取り込みたい場合はローカルで上記 `uv` コマンドを実行して PR を起票する。

## 6. Dependabot 運用

現状の `.github/dependabot.yml` 設定をポリシーとして明文化する。

| 項目 | 設定 |
|---|---|
| パッケージエコシステム | `pip` |
| スケジュール | weekly, Monday 21:00 UTC (Tokyo 月曜 06:00) |
| グルーピング | `production-dependencies` / `dev-dependencies` の 2 群 |
| 同時 open PR 上限 | 2 |
| コミット規約 | `chore(deps): ...` (scope 付き) |
| 自動付与ラベル | `dependencies`, `python` |
| cooldown | `default-days: 7` / `semver-major-days: 14` (§5.1 参照) |

### マージ方針

| 更新種別 | 対応 |
|---|---|
| パッチ更新 | 通常レビュー後 squash merge |
| マイナー更新 | 通常レビュー後 squash merge (CI グリーン必須) |
| メジャー更新 | Dependabot がグループから外して個別 PR を起こす想定。Issue #164 B-4 のフローで個別評価 |

## 7. メジャーバージョン更新

メジャー更新は破壊的変更を含む可能性が高いため、以下のルールで扱う。

1. **必ず単独 PR**: Dependabot のグループ更新には含めない
2. **migration guide を確認**: 上流のリリースノート・移行ガイドを PR 本文に引用
3. **破壊的変更がある場合**: 本プロジェクトの破壊的変更も伴う可能性があるため、Issue #176 (バージョン管理) のメジャー bump と歩調を合わせる
4. **検証**: 単体テスト・統合テストに加え、影響範囲のスモークテストを実施

## 8. 例外的な運用と参照

- **間接依存に脆弱性が出た場合**: 推移的依存は `uv.lock` でのみ管理しているため、必要に応じて `pyproject.toml` に一時的に直接依存として追加して上書きする (修正されたら削除)
- **本ポリシーで判断できない事例**: Issue を起票して議論し、結論を本ドキュメントに追記する

## 参照

- 親 Issue: [#150](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/150) (ライブラリアップデート方針の整備と一括更新)
- 本ドキュメント策定 Issue: [#161](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/161) (B-1)
- 関連: [#162](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/162) (B-2: 指定スタイル統一)、[#164](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/164) (B-4: メジャー更新の個別検証)
- 関連: [#194](https://github.com/mmiura-2351/mc-server-dashboard-api/issues/194) (cooldown ポリシーの強制)
