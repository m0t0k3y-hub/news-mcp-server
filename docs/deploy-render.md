# Render デプロイ手順書

news-mcp-server を [Render](https://render.com/) の Web Service(Docker ランタイム)としてデプロイし、MCP クライアントから使えるようにするまでの手順です。

プロジェクト全体の概要は [project-report.md](project-report.md) を参照してください。

## 全体の流れ

1. 事前準備(News API キー・認証トークン・GitHub)
2. デプロイ対象のコードを GitHub に push
3. Render で Web Service を作成
4. 環境変数・ヘルスチェックを設定してデプロイ
5. 動作確認
6. MCP クライアントから接続

---

## 1. 事前準備

| 必要なもの | 入手方法 |
|---|---|
| Render アカウント | https://dashboard.render.com/ で GitHub アカウント連携でサインアップ |
| News API キー | https://newsapi.org/register で取得 |
| 認証トークン(`AUTH_TOKEN`) | 自分で生成する推測困難な文字列。例: `openssl rand -hex 32` |
| GitHub リポジトリ | `https://github.com/m0t0k3y-hub/news-mcp-server` |

> **注意**: `AUTH_TOKEN` は公開 URL への唯一のアクセス制御です。十分に長いランダム値を使い、リポジトリやチャットに貼らないでください。

## 2. デプロイ対象のコードを GitHub に push する

Render は GitHub 上のブランチからビルドします。ビルドには以下のファイルが **push 先のブランチに存在している** 必要があります。

- `Dockerfile`
- `pyproject.toml` / `uv.lock`(`uv sync --locked` で使用)
- `README.md`(`pyproject.toml` の `readme` として参照)
- `src/`

2026-10-30 時点で、これらはすべて `main`(`origin/main`)に含まれています。ローカルの変更がある場合は `main` に取り込んで push しておきます。

```bash
git switch main
git push origin main
```

feature ブランチを試験的にデプロイしたい場合は、そのブランチを push して手順 3 の「Branch」にブランチ名を指定します。

### (任意)ローカルで Docker ビルドを確認

Render 上でビルドに失敗すると原因の切り分けに時間がかかるため、事前にローカルで確認しておくと安心です。

```bash
docker build -t news-mcp-server .
docker run --rm -p 8000:8000 -e NEWS_API_KEY=xxxxx -e AUTH_TOKEN=yyyyy news-mcp-server
curl http://localhost:8000/health   # => {"status":"ok"}
```

## 3. Render で Web Service を作成

1. Render ダッシュボードで **New → Web Service** を選択
2. **Git Provider** で GitHub を選び、`news-mcp-server` リポジトリを接続
   - 初回は「Configure account」から Render GitHub App にリポジトリへのアクセス権を付与します
3. 以下のように設定します

| 項目 | 設定値 |
|---|---|
| Name | `news-mcp-server`(任意。URL の一部になります) |
| Language / Runtime | **Docker** |
| Branch | `main` |
| Region | 日本から使うなら **Singapore** が最も近い |
| Root Directory | 空欄(リポジトリ直下) |
| Dockerfile Path | `./Dockerfile`(既定のまま) |
| Instance Type | 試用なら **Free**、常用なら Starter 以上(後述) |

Docker ランタイムでは Build Command / Start Command の入力は不要です。起動コマンドは Dockerfile の `CMD ["python", "-m", "news_mcp_server"]` が使われます。

## 4. 環境変数とヘルスチェックの設定

### 環境変数

同じ作成画面の **Environment Variables**(作成後は サービス → **Environment**)で設定します。

| Key | Value | 備考 |
|---|---|---|
| `NEWS_API_KEY` | 取得した News API キー | 必須 |
| `AUTH_TOKEN` | 手順 1 で生成したトークン | 必須 |

- **`PORT` は設定不要です。** Render が自動で `PORT` を注入し、サーバーはその値で待ち受けます(未設定時の既定は 8000)。
- `HOST` も既定の `0.0.0.0` のままで構いません。
- どちらかの必須変数が欠けていると、起動時にログへ次のようなメッセージを出して終了します(値そのものは出力されません)。

  ```
  Invalid configuration from environment variables:
    NEWS_API_KEY: Field required
  ```

### ヘルスチェック

**Advanced → Health Check Path** に `/health` を設定します。

`/health` は認証不要で `{"status":"ok"}` を返すため、Render のヘルスチェックが Bearer 認証に阻まれることはありません。

### Auto-Deploy

既定では指定ブランチへの push ごとに自動で再デプロイされます。手動で反映したい場合は **Settings → Auto-Deploy** で無効にしてください。

### デプロイ実行

**Create Web Service**(または **Deploy Web Service**)を押すとビルドが始まります。**Logs** タブで以下を確認します。

1. Docker ビルドが完了する(依存インストール含め数分)
2. `Uvicorn running on http://0.0.0.0:<PORT>` が出力される
3. ステータスが **Live** になる

サービスの URL は `https://<Name>.onrender.com` の形式で、ダッシュボード上部に表示されます(Name が重複している場合はランダムな接尾辞が付きます)。

## 5. 動作確認

以下、`https://news-mcp-server.onrender.com` を実際の URL に、`$AUTH_TOKEN` を設定したトークンに置き換えてください。

```bash
URL=https://news-mcp-server.onrender.com

# 1) ヘルスチェック(認証不要)
curl $URL/health
# => {"status":"ok"}

# 2) 認証が効いていること(トークンなし → 401)
curl -i -X POST $URL/mcp
# => HTTP/2 401 ... {"error":"unauthorized"}

# 3) ツール一覧
curl -X POST $URL/mcp \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# 4) 実際に News API を呼ぶ
curl -X POST $URL/mcp \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_top_headlines","arguments":{"country":"us","page_size":3}}}'
```

4) で記事が返れば完了です。`News API authentication failed...` が返る場合は `NEWS_API_KEY` の値を見直してください。

## 6. MCP クライアントから接続

| 項目 | 値 |
|---|---|
| URL(推奨: Streamable HTTP) | `https://<Name>.onrender.com/mcp` |
| URL(旧方式: SSE) | `https://<Name>.onrender.com/sse` |
| ヘッダー | `Authorization: Bearer <AUTH_TOKEN>` |

**Claude Code の例**

```bash
claude mcp add --transport http news https://<Name>.onrender.com/mcp \
  --header "Authorization: Bearer <AUTH_TOKEN>"
```

追加後、`claude mcp list` で接続状態を確認できます。

---

## 運用上の注意

### Free インスタンスのスリープ

Free インスタンスは一定時間(約 15 分)リクエストがないと停止し、次のリクエストで再起動します。再起動には数十秒〜1 分程度かかるため、MCP クライアントの最初の接続がタイムアウトすることがあります。常用するなら Starter 以上の有料インスタンスを選んでください。

### SSE を使う場合はインスタンス数を 1 に

Streamable HTTP(`/mcp`)はステートレスなので、複数インスタンスにスケールしても問題ありません。一方、SSE(`/sse` + `/messages/`)のセッションは各インスタンスのメモリ上にあるため、**複数インスタンスにするとリクエストが別インスタンスに振られて失敗します**。SSE クライアントを使う場合は Scaling でインスタンス数を 1 に固定してください。

### トークンのローテーション

`AUTH_TOKEN` を変更するには Environment で値を更新して保存します。保存後に再デプロイされ、新しいトークンが有効になります(旧トークンは即時無効)。接続中のクライアント側の設定も合わせて更新してください。

### News API のプラン

News API の無料 Developer プランは開発・テスト用途向けで、リクエスト数の上限などの制約があり、本番利用は想定されていません。上限を超えるとツールは `News API rate limit exceeded...` を返します。公開運用する場合は News API の有料プランを検討してください。

## (任意)Blueprint(render.yaml)で設定をコード化する

ダッシュボードでの手動設定の代わりに、リポジトリ直下に `render.yaml` を置いて **New → Blueprint** から作成することもできます。設定をリポジトリで管理したい場合に便利です。

```yaml
services:
  - type: web
    name: news-mcp-server
    runtime: docker
    plan: free            # 常用するなら starter など
    region: singapore
    branch: main
    dockerfilePath: ./Dockerfile
    healthCheckPath: /health
    envVars:
      - key: NEWS_API_KEY
        sync: false       # 値は Blueprint 作成時にダッシュボードで入力
      - key: AUTH_TOKEN
        sync: false
```

`sync: false` を指定した変数は、Blueprint 作成時にダッシュボードで値の入力を求められます。秘密情報を `render.yaml` に直接書かないでください。

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| ビルドが `uv.lock` / `Dockerfile` が見つからず失敗 | 指定ブランチにファイルがない。手順 2 を確認 |
| ビルドが `uv sync --locked` で失敗 | `pyproject.toml` を変更して `uv.lock` を更新していない。ローカルで `uv lock` → コミット → push |
| ログに `Invalid configuration from environment variables` | `NEWS_API_KEY` / `AUTH_TOKEN` が未設定。Environment を確認 |
| デプロイが Health check で失敗 | Health Check Path が `/health` になっているか確認 |
| すべてのリクエストが 401 | `Authorization: Bearer <トークン>` の形式・値を確認(`Bearer` と半角スペースが必要) |
| ツールが `News API authentication failed` を返す | `NEWS_API_KEY` が誤っている |
| 最初の接続だけタイムアウトする | Free インスタンスのスリープ復帰待ち。再試行するか有料インスタンスに変更 |
| SSE 接続が途中で失敗する | 複数インスタンスで動作している。インスタンス数を 1 に |
