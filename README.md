# Personal News RSS v2

無料で使える個人用ニュースRSS生成ツールです。OpenAI API・有料APIは不要です。

## カテゴリー
1. 国内重要ニュース
2. 浜松市・静岡県西部
3. IT・AI
4. ガジェット
5. ゲーム
6. J-HipHop・音楽
7. QOL・生活改善
8. 映画・動画配信（Prime Video / Netflix）
9. オリジナルドラマ（Prime Video / Netflix）

除外: 海外ニュース、一般経済、NISA・資産運用、新車など車そのもののニュース。
車載ガジェット（Android Auto / CarPlay / Ottocast等）は残します。

## 改良点
- 浜松市の検索フィードを追加
- Netflix / Prime Video公式サイトを優先する検索フィードを追加
- J-HipHop / 日本語ラップ / レゲエを追加
- QOL・生活改善を追加
- 車載ガジェット専用検索を追加
- RSS記事の元メディア名を表示
- 同一タイトルの重複除去
- 全体RSSに加えてカテゴリー別RSSを生成
- 朝 7:30 / 昼 12:00 / 夕 18:00 JST に自動更新

## GitHubでの使い方
1. GitHubで新しいリポジトリを作成
2. ZIPを解凍して中身をアップロード
3. Actions を有効化
4. Settings → Pages
5. Source: Deploy from a branch
6. Branch: main / Folder: /docs
7. Save

公開後:
`https://ユーザー名.github.io/リポジトリ名/feed.xml`

カテゴリー別:
- `feed-hamamatsu.xml`
- `feed-it-ai.xml`
- `feed-gadget.xml`
- `feed-game.xml`
- `feed-music.xml`
- `feed-qol.xml`
- `feed-streaming.xml`
- `feed-original-drama.xml`

## 無料運用について
このツール自体に有料APIはありません。GitHub ActionsとGitHub Pagesの無料利用範囲で運用する想定です。

## 注意
Google News検索RSSは公式に長期固定仕様として文書化されたAPIではないため、将来URL仕様が変わる可能性があります。
そのため検索条件はすべて config.json に分離してあり、変更しやすくしています。
