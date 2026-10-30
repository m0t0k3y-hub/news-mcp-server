# news-mcp-server

[News API](https://newsapi.org/) のニュース検索を **MCP (Model Context Protocol) ツール**として提供するリモート MCP サーバーです。
Claude などの MCP クライアントから接続すると、LLM が最新のヘッドラインや記事検索を直接実行できるようになります。

Render や Google Cloud Run へのデプロイを前提に設計されています。

## 特徴

- **2 つのニュースツール**: トップヘッドライン取得と全記事検索
- **Bearer トークン認証**: 公開 URL に置いても `AUTH_TOKEN` を知るクライアントだけが利用可能
- **Streamable HTTP + SSE**: 推奨の Streamable HTTP(`/mcp`)に加え、旧方式の SSE(`/sse`)にも対応
- **クラウド対応**: ステートレス動作、`PORT` 環境変数への追従、認証不要のヘルスチェック(`/health`)、非 root で動く軽量 Docker イメージ
- **安全なエラー処理**: News API のエラーをわかりやすいツールエラーに変換し、API キーやスタックトレースを外部に出しません

## 提供ツール

| ツール | 内容 | 主な引数 |
|---|---|---|
| `get_top_headlines` | 国・カテゴリ・ソース別のトップ/速報ヘッドライン | `country`, `category`, `sources`, `q`, `page_size`, `page` |
| `search_everything` | 15 万以上のニュースソース・ブログから記事を検索 | `q`(必須), `language`, `from_date`, `to_date`, `sort_by`, `domains` など |

どちらも、記事のタイトル・ソース・著者・概要・URL・公開日時・本文抜粋のリストを返します。
引数の詳細は [docs/project-report.md](docs/project-report.md#2-提供される-mcp-ツール) を参照してください。

## クイックスタート

### 必要なもの

- Python 3.12+ と [uv](https://docs.astral.sh/uv/)(または Docker)
- [News API キー](https://newsapi.org/register)
- 任意の認証トークン(例: `openssl rand -hex 32`)

### ローカルで起動

```bash
git clone https://github.com/m0t0k3y-hub/news-mcp-server.git
cd news-mcp-server

cp .env.example .env   # NEWS_API_KEY と AUTH_TOKEN を設定
uv sync
uv run news-mcp-server
```

### Docker で起動

```bash
docker build -t news-mcp-server .
docker run --rm -p 8000:8000 \
  -e NEWS_API_KEY=your_news_api_key \
  -e AUTH_TOKEN=your_auth_token \
  news-mcp-server
```

### 動作確認

```bash
curl http://localhost:8000/health
# => {"status":"ok"}

curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## 設定

| 環境変数 | 必須 | 既定値 | 説明 |
|---|---|---|---|
| `NEWS_API_KEY` | ✅ | – | News API の API キー |
| `AUTH_TOKEN` | ✅ | – | クライアントが `Authorization: Bearer` で送るトークン |
| `PORT` | | `8000` | 待ち受けポート(Render / Cloud Run が自動設定) |
| `HOST` | | `0.0.0.0` | 待ち受けアドレス |

## エンドポイント

| パス | メソッド | 認証 | 用途 |
|---|---|---|---|
| `/mcp` | POST | 必要 | MCP Streamable HTTP(推奨) |
| `/sse` | GET | 必要 | MCP SSE ストリーム(旧方式) |
| `/messages/` | POST | 必要 | SSE 用メッセージ送信 |
| `/health` | GET | 不要 | ヘルスチェック |

> SSE のセッションはプロセスメモリ上に保持されるため、SSE を使う場合はインスタンス数を 1 にしてください。Streamable HTTP はステートレスなのでスケールアウトできます。

## MCP クライアントから接続

接続先は `https://<your-host>/mcp`、ヘッダーに `Authorization: Bearer <AUTH_TOKEN>` を指定します。

**Claude Code**

```bash
claude mcp add --transport http news https://<your-host>/mcp \
  --header "Authorization: Bearer <AUTH_TOKEN>"
```

## デプロイ

- **Render**: [docs/deploy-render.md](docs/deploy-render.md) に手順書があります
- **Google Cloud Run**:

  ```bash
  gcloud run deploy news-mcp-server \
    --source . \
    --region asia-northeast1 \
    --allow-unauthenticated \
    --set-env-vars NEWS_API_KEY=xxxxx,AUTH_TOKEN=yyyyy
  ```

  本番では Secret Manager(`--set-secrets`)の利用を推奨します。

## 開発

```bash
uv sync                    # 開発用依存を含めてインストール
uv run pytest              # テスト(News API 呼び出しは respx でモック)
uv run ruff format         # フォーマット
uv run ruff check --fix    # Lint
uv run mypy src            # 型チェック(strict)
```

開発ルール(TDD、Conventional Commits など)は [CLAUDE.md](CLAUDE.md) を参照してください。

```
src/news_mcp_server/
├── __main__.py   # エントリポイント(設定読み込み・uvicorn 起動)
├── config.py     # 環境変数からの設定
├── server.py     # MCP ツール定義と HTTP アプリ
├── client.py     # News API 非同期クライアント
└── auth.py       # Bearer 認証ミドルウェア
```

## ドキュメント

- [プロジェクトレポート](docs/project-report.md) — 設計・ツール仕様・エラー処理の詳細
- [Render デプロイ手順書](docs/deploy-render.md)

## 注意事項

News API の無料 Developer プランは開発・テスト用途向けで、リクエスト数の上限などの制約があります。公開運用する場合は [News API の料金プラン](https://newsapi.org/pricing) を確認してください。
