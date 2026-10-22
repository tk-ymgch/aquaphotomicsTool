# Cloudflare Pagesへの配布

v1.6.1で移行した認証付きModule WorkerをPages advanced modeの`_worker.js`として引き続き配布します。v1.9.0ではUIの基調を維持し、試料別Aquagramの時系列・全画面探索を追加しました。aquap2pyは0.3.1です。設定schema1を維持し、旧設定の読込にも対応します。

## ビルドと検証

Node.js 22.18以降と既存のpnpm環境を使います。

```sh
pnpm install --frozen-lockfile
pnpm build:pages
node tests/pages-build.mjs
```

`build:pages`は通常の本番ビルド後に`scripts/build-pages.mjs`を実行します。出力先`pages-dist/`には次の2ファイルだけを置きます。

| ファイル | 内容 |
| --- | --- |
| `_worker.js` | `dist/server/index.js`とバイト単位で同一の認証付きWorker。全クライアント資産を内包 |
| `_routes.json` | schema version 1、`include: ["/*"]`、`exclude: []` |

HTML・JavaScript・CSS・Python・wheelを別の公開静的ファイルとして置きません。Workerが認証後に内包資産を返すため、`env.ASSETS.fetch()`による静的配信へのフォールバックはありません。Pagesの出力先に`.client-build/`や`public/`を指定しないでください。

`tests/pages-build.mjs`は、既存Workerとの完全一致、全クライアント資産の認証前拒否と認証後バイト一致、誤ったパスワード、ログイン、ログアウト、HEAD、秘密設定欠落時の503を、毎回生成する人工認証情報で確認します。

## 公開先の設定

PagesプロジェクトのProductionと、公開する場合はPreviewの双方へ、次の値を**暗号化されたSecrets**として設定します。値はソース、ビルド成果物、設定例、ログへ含めません。

| Secret名 | 形式 |
| --- | --- |
| `SITE_PASSWORD_HASH` | `pbkdf2:100000:<16-byte saltの小文字hex>:<32-byte SHA-256導出値の小文字hex>` |
| `SESSION_SIGNING_KEY` | 32-byteの乱数を小文字hexで表した64文字 |

共有パスワードはユーザーが指定した現在の値から新しいsaltでハッシュを生成し、公式Wrangler CLIの標準入力を使って設定します。変更時は署名鍵も新しい乱数へ更新し、再デプロイ後に新しいパスワードの受理と以前のパスワードの拒否を確認します。秘密値をファイル・ログへ保存しません。利用者は指定された現在のパスワードで再ログインします。認証Cookieの有効期間8時間、HttpOnly・Secure・SameSite=Strict、全応答の`private, no-store`は既存と共通です。両Secretsが正しく設定されない環境は503で停止します。

Secretsを設定した後、`pages-dist/`をWranglerの`pages deploy`でアップロードします。Pagesプロジェクト名とProduction branchは対象プロジェクトの値を明示し、別プロジェクトへ誤配布しないようにします。

```sh
wrangler pages deploy pages-dist --project-name <Pagesプロジェクト名> --branch <Production branch>
```

Direct Uploadはローカルで検証した成果物をそのまま公開する方法です。Direct Uploadで作ったPagesプロジェクトを後からGit integration方式に切り替えることはできず、自動Git連携へ変更する際は別のPagesプロジェクトが必要です。既存のSitesプロジェクトやGitHub mainの更新は、この配布コマンドには含まれません。

## 公開後の確認

Production URLでログイン画面、誤ったパスワードの拒否、指定された現在のパスワードでのログイン、サンプル読込、前処理・PCA・Aquagram・PLS、結果保存、ログアウトを確認します。ログアウト状態でPython・JS・wheelの直URLが401になることと、認証後の資産SHA-256がローカルビルドと一致することを確認します。公開先URL、deployment ID、検証結果はプロジェクトの引継ぎ記録へ保存します。

任意のローカルR/aquap2連携を使う場合は、`bridge/serve.py`の許可Originへ実際のProduction URLのOrigin（`https://<公開ホスト名>`）を明示してからbridgeを再起動します。既存のSites Originは維持し、ワイルドカードで許可範囲を広げません。通常のブラウザーPython解析にはbridgeは不要です。保存済み解析設定・結果ファイルは引き続き利用できます。

## 公式仕様

2026-10-22確認。

- [Pages advanced mode](https://developers.cloudflare.com/pages/functions/advanced-mode/)：`_worker.js`はModule Workerとして全リクエストを処理します。
- [Functions invocation routes](https://developers.cloudflare.com/pages/functions/routing/#functions-invocation-routes)：`_routes.json`のinclude/excludeを定義します。
- [Pages Secrets](https://developers.cloudflare.com/pages/functions/bindings/#secrets)：Secretsを暗号化して設定し、使用するdeploymentより前に準備します。
- [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)：Wranglerで事前ビルド済みディレクトリーを公開します。
