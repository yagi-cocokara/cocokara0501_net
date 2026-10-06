# 会社のGitHubへの引っ越し手順書

個人のGitHub（`yagi-cocokara`）にある倉庫の箱（リポジトリ）を、
**会社の倉庫（Organization）**へ引っ越すための手順です。

## かかる時間のめやす

| 作業 | 時間 |
|---|---|
| A. 会社の倉庫を作る | 約5分 |
| B. 箱を引っ越す | 1つの箱につき約2分 |
| C. Netlify（ホームページ公開）をつなぎ直す | 約10〜20分 |
| D. Claude をつなぎ直す | 約10分 |
| E. 確認 | 約10分 |
| **合計** | **約40分〜1時間** |

**おすすめ**：ホームページを見る人が少ない時間（夜や休日）に、一気に進めてください。
C が終わるまでの間、ホームページの**更新**が止まることがあります。
ただし、公開中のホームページが消えることはありません。

---

## 始める前に（準備）

- [ ] 会社の倉庫の名前を決める（英数字とハイフンのみ。例：`cocokara-inc`）
- [ ] 会社の倉庫の連絡用メールアドレスを決める（会社のアドレスがおすすめ）
- [ ] GitHub・Netlify・Claude に、それぞれログインできることを確認する
- [ ] 念のため、Mac の `タスク管理データ.json` を別の場所にコピーしておく
      （ガントチャートのデータは引っ越しの影響を受けませんが、念のため）

---

## A. 会社の倉庫（Organization）を作る　約5分

1. GitHub に `yagi-cocokara` でログインします。
2. 右上の自分のアイコン →「**Your organizations**」を押します。
3. 「**New organization**」を押します。
4. 「**Free**」（無料）の「Create a free organization」を選びます。
5. 次のように入力します。
   - Organization name：決めた名前（例：`cocokara-inc`）
   - Contact email：会社のメールアドレス
   - This organization belongs to：「**A business or institution**」（会社のもの）を選び、会社名を入力
6. 「Next」→ メンバー招待の画面は「**Skip this step**」で飛ばして大丈夫です（あとで招待できます）。

**合いかぎを会社の上の方にも渡す（おすすめ）**
- 会社の倉庫のページ →「People」→「Invite member」で招待し、役割を「**Owner**」にします。
- こうしておくと、担当者が変わっても倉庫に入れなくなる心配がありません。

---

## B. 箱（リポジトリ）を引っ越す　1つにつき約2分

引っ越す箱：`cocokara0501_net`（ほかの箱も、同じ手順で引っ越せます）

1. GitHub で `yagi-cocokara/cocokara0501_net` を開きます。
2. 上の「**Settings**」（歯車）を押します。
3. 一番下までスクロールし、赤い枠の「Danger Zone」の「**Transfer**」を押します。
   - 「Danger（危険）」と書いてありますが、引っ越しなので心配いりません。
4. 「Select one of my organizations」で、A で作った会社の倉庫を選びます。
5. 確認のため、箱の名前（`yagi-cocokara/cocokara0501_net`）を入力して「**I understand, transfer this repository**」を押します。

**引っ越し後のこと**
- 箱の中身・変更の履歴・下書きの棚（作業用ブランチ）は、そのまま引っ越します。
- 古い住所（`yagi-cocokara/cocokara0501_net`）にアクセスすると、新しい住所へ自動で案内されます。
- 鍵の有無（公開／非公開）も変わりません。

---

## C. Netlify（ホームページの公開）をつなぎ直す　約10〜20分

### C-1. まず、今のつながり方を確認する

1. Netlify にログインし、看護師募集サイトを開きます。
2. 左のメニュー「**Site configuration**」→「**Build & deploy**」→「**Continuous deployment**」を開きます。
3. 「Repository」の欄を見ます。
   - **`github.com/yagi-cocokara/cocokara0501_net` と出ている場合**
     → GitHub とつながっています。C-2 へ進んでください。
   - **「Manual deploys」など、GitHub の名前が出ていない場合**
     → GitHub とはつながっていません（ファイルを手で入れて公開している）。
       **C はやらなくて大丈夫です。** D へ進んでください。

### C-2. Netlify に会社の倉庫の合いかぎを渡す

1. 同じ画面の「Repository」の欄の「**Manage repository**」→「**Link to a different repository**」を押します。
2. 「**GitHub**」を選びます。
3. 倉庫を選ぶ画面で、会社の倉庫が出てこない場合は、
   一番下の「**Configure the Netlify app on GitHub**」を押します。
4. GitHub の画面に移ったら、会社の倉庫を選び、
   「Only select repositories」で `cocokara0501_net` を選んで「**Install**」（または「Save」）を押します。

### C-3. 新しい住所の箱を選び直す

1. Netlify の画面に戻り、会社の倉庫の `cocokara0501_net` を選びます。
2. 公開する棚（Branch to deploy）が「**main**」になっていることを確認します。
3. ほかの設定（Build command など）は、**今のまま変えずに**保存します。

---

## D. Claude をつなぎ直す　約10分

### D-1. Claude（職人さん）に会社の倉庫の合いかぎを渡す

1. https://github.com/apps/claude を開き、「**Configure**」（または「Install」）を押します。
2. 会社の倉庫を選びます。
3. 「Only select repositories」で `cocokara0501_net` を選び、「**Install**」（または「Save」）を押します。
4. 「権限の更新を承認してください」と出たら、「Review request」→「Accept new permissions」で承認します。

### D-2. 新しい Claude アカウントと GitHub をつなぐ

（会社のチームプランのアカウントに切り替えたあとに行います）

1. 新しいアカウントで Claude にログインします。
2. https://claude.ai/connect-github を開き、GitHub（`yagi-cocokara`）とつなぎます。
3. Claude Code で新しいセッションを始めるとき、会社の倉庫の `cocokara0501_net` を選びます。
4. 最初に「**HANDOFF.md を読んで、続きをお願いします**」と伝えます。

**チームプランの場合**：会社の管理者が、Claude と GitHub のつなぎ方をまとめて設定することがあります。
うまくつながらないときは、管理者に「Claude GitHub App を会社の GitHub 組織に入れてほしい」と伝えてください。

---

## E. 最後の確認　約10分

- [ ] ホームページが今までどおり表示される
- [ ] （C-2 をやった場合）Netlify の「Deploys」で、最新の公開が「Published」になっている
- [ ] Claude Code で小さな変更を頼み、「アップロードできた」と返ってくる
- [ ] ガントチャートのアプリが、今までどおり開ける（データは Mac の中なので影響なし）

## 困ったときは

- **Netlify に会社の倉庫が出てこない** → C-2 の「Configure the Netlify app on GitHub」で、会社の倉庫を許可したか確認。
- **Claude が「403」「アクセスできません」と言う** → D-1 で `cocokara0501_net` を選んだか、権限の承認をしたか確認。
- **元に戻したい** → 会社の倉庫の箱の「Settings」→「Transfer」で、`yagi-cocokara` に戻せます。
