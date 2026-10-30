# news-mcp-server プロジェクトレポート

調査日: 2026-10-30 / 対象コミット: `5896b83`(`main`)

## 1. このプロジェクトは何か

[News API](https://newsapi.org/)(newsapi.org)のニュース検索機能を、**MCP (Model Context Protocol) のツール**として公開する HTTP サーバーです。
Claude などの MCP クライアントから接続すると、LLM が「今日の日本のテクノロジーニュース」「特定キーワードの記事検索」などを直接実行できるようになります。

主な特徴:

- **クラウドデプロイ前提**: Render / Google Cloud Run で動かすことを想定(`PORT` 環境変数の自動取得、ヘルスチェック用エンドポイント、Docker イメージ)
- **Bearer トークン認証**: 公開 URL に置いても第三者に使われないよう、全リクエストに `Authorization: Bearer <AUTH_TOKEN>` を要求
- **2 種類のトランスポート**: 推奨の Streamable HTTP(`/mcp`)と、旧方式の SSE(`/sse` + `/messages/`)
- **安全なエラー処理**: News API のエラー(認証失敗・レート制限・タイムアウト等)を MCP のツールエラーに変換し、API キーやスタックトレースを外部に出さない

### 技術スタック

| 項目 | 内容 |
|---|---|
| 言語 | Python 3.12+ |
| パッケージ管理 | uv(`uv.lock` で依存を固定) |
| MCP SDK | `mcp` 2.x(`MCPServer` クラス) |
| Web / ASGI | Starlette + uvicorn |
| HTTP クライアント | httpx(非同期) |
| 設定 | pydantic-settings(環境変数 / `.env`) |
| 品質管理 | pytest + pytest-asyncio + respx、Ruff、mypy(strict) |

## 2. 提供される MCP ツール

どちらも読み取り専用ツール(`readOnlyHint=true`)です。

### `get_top_headlines` — トップ/速報ヘッドライン取得

News API の `/v2/top-headlines` を呼び出します。

| 引数 | 型 | 説明 |
|---|---|---|
| `country` | str | 国コード(ISO 3166-1、例: `us`, `jp`) |
| `category` | enum | `business` / `entertainment` / `general` / `health` / `science` / `sports` / `technology` |
| `sources` | str | ソース ID のカンマ区切り(例: `bbc-news,cnn`) |
| `q` | str | キーワード |
| `page_size` | int | 取得件数 1–100(既定 10) |
| `page` | int | ページ番号(既定 1) |

制約:
- `country` / `category` / `sources` / `q` のうち **最低 1 つは必須**
- `sources` は `country` / `category` と **併用不可**(News API の仕様)

### `search_everything` — 全記事検索

News API の `/v2/everything` を呼び出します。

| 引数 | 型 | 説明 |
|---|---|---|
| `q` | str(必須) | 検索語。AND/OR/NOT、`"完全一致"`、`+`/`-` 前置に対応 |
| `search_in` | str | 検索対象フィールド(`title,description,content` のカンマ区切り) |
| `sources` | str | ソース ID のカンマ区切り |
| `domains` / `exclude_domains` | str | 対象 / 除外ドメインのカンマ区切り |
| `from_date` / `to_date` | str | 期間(ISO 8601、例: `2026-10-01`) |
| `language` | str | 言語コード(ISO 639-1、例: `en`, `ja`) |
| `sort_by` | enum | `relevancy` / `popularity` / `publishedAt` |
| `page_size` | int | 取得件数 1–100(既定 10) |
| `page` | int | ページ番号(既定 1) |

### 戻り値(両ツール共通)

```json
{
  "total_results": 123,
  "articles": [
    {
      "title": "...",
      "source": "BBC News",
      "author": "...",
      "description": "...",
      "url": "https://...",
      "published_at": "2026-10-30T01:23:45Z",
      "content": "..."
    }
  ]
}
```

### エラー時の挙動

| 状況 | クライアントに返るメッセージ |
|---|---|
| News API が 401(API キー不正) | `News API authentication failed. The server's API key may be invalid.` |
| News API が 429(レート制限) | `News API rate limit exceeded. Please try again later.` |
| タイムアウト(10 秒) | `News API request timed out. Please try again later.` |
| その他の API エラー | `News API error: <News API のメッセージ>` |

サーバーログにはステータスコードとエラーコードのみ記録され、API キーは出力されません。

## 3. アーキテクチャ

```
MCP クライアント (Claude 等)
        │  Authorization: Bearer <AUTH_TOKEN>
        ▼
┌──────────────────────────────────────────────┐
│ Starlette アプリ (uvicorn)                    │
│  BearerAuthMiddleware  … /health 以外を認証    │
│  ├─ GET  /health        ヘルスチェック          │
│  ├─ POST /mcp           Streamable HTTP (推奨) │
│  ├─ GET  /sse           SSE ストリーム (旧方式) │
│  └─ POST /messages/     SSE 用メッセージ送信    │
│        │                                      │
│  MCPServer: get_top_headlines / search_everything
│        │                                      │
│  NewsApiClient (httpx, X-Api-Key ヘッダー)     │
└────────┼─────────────────────────────────────┘
         ▼
   https://newsapi.org/v2
```

### ソースコード構成

| ファイル | 役割 |
|---|---|
| [src/news_mcp_server/\_\_main\_\_.py](../src/news_mcp_server/__main__.py) | エントリポイント。設定を読み込み uvicorn を起動。設定エラー時は値を含まないメッセージで終了 |
| [src/news_mcp_server/config.py](../src/news_mcp_server/config.py) | 環境変数から設定を読み込む `Settings`(API キー類は `SecretStr`) |
| [src/news_mcp_server/server.py](../src/news_mcp_server/server.py) | MCP ツール定義、エラー変換、Starlette アプリ組み立て(`create_app`) |
| [src/news_mcp_server/client.py](../src/news_mcp_server/client.py) | News API 非同期クライアント、レスポンスモデル、例外クラス |
| [src/news_mcp_server/auth.py](../src/news_mcp_server/auth.py) | Bearer 認証 ASGI ミドルウェア(`hmac.compare_digest` で定数時間比較) |
| [Dockerfile](../Dockerfile) | マルチステージビルド(uv で依存解決 → 非 root ユーザーで実行) |
| [tests/](../tests/) | pytest テスト一式(News API 呼び出しは respx でモック) |

### 設計上のポイント

- **ステートレス**: Streamable HTTP は `stateless_http=True` + `json_response=True` で動作。どのインスタンスでもリクエストを処理でき、Cloud Run / Render のスケールアウトに対応します。
- **SSE の制約**: SSE のセッションはプロセスメモリ上に保持されるため、**SSE を使う場合はインスタンス数を 1 に固定**する必要があります。
- **プロキシ対応**: uvicorn を `proxy_headers=True` で起動し、ロードバランサ配下で正しいクライアント情報を扱えます。
- **API キーの送り方**: News API へは `X-Api-Key` ヘッダーで送信し、URL クエリには含めません(ログへの漏洩防止。テストで検証済み)。

## 4. 使い方

### 4.1 事前準備

1. [newsapi.org](https://newsapi.org/register) で API キーを取得
2. サーバーへのアクセス用に任意の推測困難なトークンを生成(例: `openssl rand -hex 32`)
3. [uv](https://docs.astral.sh/uv/) をインストール

### 4.2 環境変数

| 変数 | 必須 | 既定値 | 説明 |
|---|---|---|---|
| `NEWS_API_KEY` | ○ | – | News API の API キー |
| `AUTH_TOKEN` | ○ | – | クライアントが送る Bearer トークン |
| `PORT` | | `8000` | 待ち受けポート(Render / Cloud Run が自動設定) |
| `HOST` | | `0.0.0.0` | 待ち受けアドレス |

ローカルでは `.env.example` をコピーして `.env` を作れば自動で読み込まれます。

```bash
cp .env.example .env
# .env を編集して NEWS_API_KEY と AUTH_TOKEN を設定
```

### 4.3 ローカルで起動

```bash
uv sync
uv run news-mcp-server        # または: uv run python -m news_mcp_server
```

動作確認:

```bash
# ヘルスチェック(認証不要)
curl http://localhost:8000/health
# => {"status":"ok"}

# ツール一覧(要認証)
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# ツール呼び出し例
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_top_headlines","arguments":{"country":"jp","category":"technology","page_size":5}}}'
```

トークンなし・誤りの場合は `401 {"error":"unauthorized"}` が返ります。

### 4.4 Docker で起動

```bash
docker build -t news-mcp-server .
docker run --rm -p 8000:8000 \
  -e NEWS_API_KEY=xxxxx \
  -e AUTH_TOKEN=yyyyy \
  news-mcp-server
```

イメージにはテスト・`.env`・Git 情報などは含まれません(`.dockerignore` で除外)。

### 4.5 クラウドへのデプロイ

**Google Cloud Run**

```bash
gcloud run deploy news-mcp-server \
  --source . \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --set-env-vars NEWS_API_KEY=xxxxx,AUTH_TOKEN=yyyyy
```

- アプリ側で Bearer 認証を行うため `--allow-unauthenticated` で公開します。
- 本番では `--set-env-vars` の代わりに Secret Manager(`--set-secrets`)の利用を推奨します。
- SSE を使う場合は `--max-instances 1` を指定してください。

**Render**

1. 「New Web Service」でリポジトリを接続し、ランタイムに **Docker** を選択
2. Environment に `NEWS_API_KEY` と `AUTH_TOKEN` を設定(`PORT` は Render が自動設定)
3. Health Check Path に `/health` を指定

### 4.6 MCP クライアントからの接続

接続先 URL は `https://<デプロイ先ホスト>/mcp`、ヘッダーに `Authorization: Bearer <AUTH_TOKEN>` を指定します。

**Claude Code の例**

```bash
claude mcp add --transport http news https://<host>/mcp \
  --header "Authorization: Bearer <AUTH_TOKEN>"
```

Streamable HTTP に対応していないクライアントは、SSE エンドポイント `https://<host>/sse` を同じヘッダー付きで指定してください。

## 5. 開発

```bash
uv sync                    # 開発用依存も含めてインストール
uv run pytest              # テスト実行
uv run ruff format         # フォーマット
uv run ruff check --fix    # Lint
uv run mypy src            # 型チェック(strict)
```

- テストは計 47 件(調査時点ですべて成功)。News API へのリクエストはすべて respx でモックされ、実 API は呼びません。
- テスト範囲: News API クライアント(正常系・各種エラー・API キーがクエリに載らないこと)、MCP ツール(入力検証・エラー変換)、認証ミドルウェア、Streamable HTTP / SSE の両トランスポート、設定エラー時に秘密情報を漏らさないこと。
- 開発ルール(TDD、Conventional Commits 等)は [CLAUDE.md](../CLAUDE.md) を参照してください。

## 6. 現状の気になる点

- **README.md が空**: このレポートの「使い方」部分を README に転記することを推奨します。
- **`__init__.py` の `hello()`**: `uv init` のテンプレートが残ったもので、どこからも使われていません。
- **News API の利用制限**: 無料の Developer プランは本番利用不可・リクエスト数制限・記事の遅延などの制約があります。公開運用する場合は有料プランを確認してください。
